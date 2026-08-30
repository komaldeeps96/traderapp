"""SEC EDGAR: the filing trail and the XBRL facts behind it.

This is the fundamentals backbone, because IBKR is not one. Every
``reqFundamentalData`` report type on this account answers error 10358
("Fundamentals data is not allowed"), the ratio and dividend generic ticks
stay silent, and Wall Street Horizon answers 10276 — probed against live TWS,
see ``tmp/ibkr-fundamentals/probe_fundamentals.py``. EDGAR needs no key, no
account and no entitlement, and it is the only free source that carries what
this workflow actually needs: warrants outstanding, cash against burn, shares
authorised versus issued, public float, and the offering trail.

Three endpoints, three cache lifetimes:

    company_tickers.json    ticker -> CIK. Changes when a company lists or
                            renames; a day is generous.
    submissions/CIK…json    the filing trail. Short-lived, because a 424B5
                            landing mid-session is the thing worth knowing.
    companyfacts/CIK…json   every XBRL fact ever reported. Quarterly data —
                            half a day is still fresher than the source.

SEC asks for a declared User-Agent carrying a contact address and rate-limits
at ten requests a second; both are honoured here, the second through the same
``ProviderBudget`` the market-data upstreams use, so EDGAR shows up in the
toolbar meters beside them.

Like ``yahoo.py``, nothing here raises into a caller. Every failure degrades
to ``None`` and the panel renders without that field rather than not at all.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from ..core.clock import now_epoch
from ..domain.filings import Filing, classify, filing_url
from ..services.api_budget import ProviderBudget

logger = logging.getLogger(__name__)

TICKER_MAP_TTL_SECONDS = 24 * 3600.0
FILINGS_TTL_SECONDS = 300.0
FACTS_TTL_SECONDS = 12 * 3600.0
# A failed lookup is retried sooner than a good one, but not per broadcast.
MISS_TTL_SECONDS = 900.0

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# SEC blocks requests without a contact address in the User-Agent. This is the
# fallback; ``edgar.user_agent`` in settings is where a real one belongs.
DEFAULT_USER_AGENT = "traderapp/1.0 (contact: set edgar.user_agent in settings)"

# What to say when the ticker map could not be fetched.
#
# This exact failure is easy to hit and used to be invisible: www.sec.gov —
# which serves the ticker map — answers 403 to a User-Agent without a real
# contact address, while data.sec.gov answers 200 to the same one. Without a
# CIK nothing else can be requested, so the panel filled with nulls and told
# the user the company files nothing, which was a lie about a configuration
# problem.
UNAVAILABLE_NOTE = (
    "SEC refused the request. Set edgar.user_agent in settings.yaml to a "
    "string carrying a real contact address, e.g. "
    '"traderapp/1.0 (you@example.com)".'
)

# The submissions document carries up to a thousand recent filings. Keeping
# them all costs nothing and lets the dilution service count offerings over a
# trailing year without a second request.
MAX_FILINGS = 1000


@dataclass(frozen=True)
class CompanyProfile:
    """Who the filer is, from the submissions document's header."""

    cik: int
    name: str
    sic: str
    sic_description: str
    exchanges: tuple[str, ...]
    website: str
    state_of_incorporation: str
    fiscal_year_end: str

    def to_dict(self) -> dict:
        return {
            "cik": self.cik,
            "name": self.name,
            "sic": self.sic,
            "sic_description": self.sic_description,
            "exchanges": list(self.exchanges),
            "website": self.website,
            "state_of_incorporation": self.state_of_incorporation,
            "fiscal_year_end": self.fiscal_year_end,
        }


class EdgarProvider:
    def __init__(
        self,
        budget: ProviderBudget | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self._budget = budget
        self._transport = transport
        self._user_agent = user_agent
        self._client: httpx.AsyncClient | None = None
        # ticker -> CIK, fetched once and reused for every symbol.
        self._tickers: dict[str, int] | None = None
        self._tickers_at = 0.0
        # True once a ticker-map fetch has failed and none has ever
        # succeeded — the difference between "unknown symbol" and "SEC would
        # not talk to us", which the panel has to be able to tell apart.
        self._map_failed = False
        self._profiles: dict[str, tuple[float, CompanyProfile | None]] = {}
        self._filings: dict[str, tuple[float, list[Filing]]] = {}
        self._facts: dict[str, tuple[float, dict | None]] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── reads without touching the network ─────────────────────────────

    def peek_profile(self, symbol: str) -> CompanyProfile | None:
        cached = self._profiles.get(symbol)
        return cached[1] if cached is not None else None

    def peek_filings(self, symbol: str) -> list[Filing]:
        cached = self._filings.get(symbol)
        return cached[1] if cached is not None else []

    def note(self) -> str | None:
        """Why the panel is empty, when the reason is not the company."""
        return UNAVAILABLE_NOTE if self._map_failed else None

    def peek_facts(self, symbol: str) -> dict | None:
        """The raw ``companyfacts`` payload; ``dilution.py`` does the maths."""
        cached = self._facts.get(symbol)
        return cached[1] if cached is not None else None

    # ── warming ────────────────────────────────────────────────────────

    async def prefetch(self, symbol: str) -> None:
        """Warm the profile, the filing trail and the XBRL facts.

        Called from the symbol-info prefetch loop at subscribe time, so the
        dock is already populated by the time a tab is clicked.
        """
        if self._fresh(self._filings, symbol, FILINGS_TTL_SECONDS) and self._fresh(
            self._facts, symbol, FACTS_TTL_SECONDS
        ):
            return
        async with self._lock:
            cik = await self._cik(symbol)
            if cik is None:
                self._profiles[symbol] = (now_epoch(), None)
                self._facts[symbol] = (now_epoch(), None)
                return
            await self._load_submissions(symbol, cik)
            await self._load_facts(symbol, cik)

    async def refresh_filings(self, symbol: str) -> list[Filing]:
        """Re-read only the filing trail, ignoring its cache.

        The live-alert poll uses this: facts move quarterly and must not be
        re-fetched every minute, but a new 424B5 is exactly what is being
        watched for.
        """
        async with self._lock:
            cik = await self._cik(symbol)
            if cik is None:
                return []
            await self._load_submissions(symbol, cik)
        return self.peek_filings(symbol)

    # ── fetching ───────────────────────────────────────────────────────

    async def _cik(self, symbol: str) -> int | None:
        if self._tickers is None or now_epoch() - self._tickers_at > TICKER_MAP_TTL_SECONDS:
            payload = await self._get_json(_TICKERS_URL)
            parsed = _parse_ticker_map(payload)
            if parsed:
                self._tickers = parsed
                self._tickers_at = now_epoch()
                self._map_failed = False
            elif self._tickers is None:
                # Only a first failure is fatal; a refresh that fails keeps
                # serving the map already held.
                self._map_failed = True
        if self._tickers is None:
            return None
        return self._tickers.get(symbol.upper())

    async def _load_submissions(self, symbol: str, cik: int) -> None:
        payload = await self._get_json(_SUBMISSIONS_URL.format(cik=cik))
        if payload is None:
            # Keep whatever the last good read produced; a transient 503 must
            # not empty a populated panel.
            self._filings.setdefault(symbol, (now_epoch(), []))
            self._profiles.setdefault(symbol, (now_epoch(), None))
            return
        self._profiles[symbol] = (now_epoch(), _parse_profile(payload, cik))
        self._filings[symbol] = (now_epoch(), _parse_filings(payload, cik))

    async def _load_facts(self, symbol: str, cik: int) -> None:
        if self._fresh(self._facts, symbol, FACTS_TTL_SECONDS):
            return
        payload = await self._get_json(_FACTS_URL.format(cik=cik))
        # A company with no XBRL history 404s. That is a real answer — a
        # brand-new listing — and is cached as a miss rather than retried.
        self._facts[symbol] = (now_epoch(), payload)

    async def fetch_document(self, url: str) -> str | None:
        """One filing document, as text.

        Separate from `_get_json` because the ownership forms are XML, and
        because this is the one read that is *per filing* rather than per
        company — it goes through the same budget so a company with a long
        Form 4 trail cannot spend the whole allowance at once.
        """
        try:
            if self._budget is not None:
                await self._budget.acquire()
            response = await self._ensure_client().get(url)
            if response.status_code != 200:
                logger.debug("EDGAR %s for %s", response.status_code, url)
                return None
            return response.text
        except Exception:
            logger.debug("EDGAR document request failed: %s", url, exc_info=True)
            return None

    async def _get_json(self, url: str) -> dict | None:
        try:
            if self._budget is not None:
                await self._budget.acquire()
            response = await self._ensure_client().get(url)
            if response.status_code != 200:
                logger.debug("EDGAR %s for %s", response.status_code, url)
                return None
            return response.json()
        except Exception:
            logger.debug("EDGAR request failed: %s", url, exc_info=True)
            return None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=20.0,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    @staticmethod
    def _fresh(cache: dict[str, tuple[float, object]], symbol: str, ttl: float) -> bool:
        cached = cache.get(symbol)
        if cached is None:
            return False
        age = now_epoch() - cached[0]
        return age < (ttl if cached[1] else MISS_TTL_SECONDS)


# ── parsing ────────────────────────────────────────────────────────────


def _parse_ticker_map(payload: object) -> dict[str, int]:
    """``{"0": {"cik_str": 320193, "ticker": "AAPL", ...}, …}`` -> lookup."""
    if not isinstance(payload, dict):
        return {}
    mapping: dict[str, int] = {}
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        ticker = entry.get("ticker")
        cik = entry.get("cik_str")
        if isinstance(ticker, str) and isinstance(cik, int):
            mapping[ticker.upper()] = cik
    return mapping


def _parse_profile(payload: dict, cik: int) -> CompanyProfile | None:
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        return None
    exchanges = payload.get("exchanges")
    return CompanyProfile(
        cik=cik,
        name=name,
        sic=str(payload.get("sic") or ""),
        sic_description=str(payload.get("sicDescription") or ""),
        exchanges=tuple(str(item) for item in exchanges) if isinstance(exchanges, list) else (),
        website=str(payload.get("website") or ""),
        state_of_incorporation=str(payload.get("stateOfIncorporationDescription") or ""),
        fiscal_year_end=str(payload.get("fiscalYearEnd") or ""),
    )


def _parse_filings(payload: dict, cik: int) -> list[Filing]:
    """The ``filings.recent`` column store, transposed into rows.

    EDGAR ships parallel arrays rather than records, and a truncated one is
    possible; zipping to the shortest keeps a malformed document from
    producing rows with fields borrowed from their neighbours.
    """
    recent = (payload.get("filings") or {}).get("recent")
    if not isinstance(recent, dict):
        return []

    columns = ("form", "filingDate", "accessionNumber", "primaryDocument", "items", "acceptanceDateTime")
    values = [recent.get(name) for name in columns]
    if not all(isinstance(column, list) for column in values):
        return []
    forms, dates, accessions, documents, items, accepted = values

    rows: list[Filing] = []
    for index in range(min(len(column) for column in values)):
        if index >= MAX_FILINGS:
            break
        filed = _parse_date(dates[index])
        form = str(forms[index] or "")
        if filed is None or not form:
            continue
        raw_items = str(items[index] or "")
        kind, note = classify(form, raw_items)
        accession = str(accessions[index] or "")
        rows.append(
            Filing(
                form=form,
                kind=kind,
                note=note,
                filed=filed,
                accepted=_parse_accepted(accepted[index]),
                accession=accession,
                items=tuple(part.strip() for part in raw_items.split(",") if part.strip()),
                url=filing_url(cik, accession, str(documents[index] or "")),
            )
        )
    return rows


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_accepted(value: object) -> int | None:
    """``2026-08-14T16:05:12.000Z`` -> epoch seconds.

    EDGAR stamps acceptance in Eastern time without an offset in some older
    rows and with a trailing ``Z`` in current ones; only the latter is
    trusted, since guessing a zone on a timestamp used to decide whether a
    filing landed inside the session would be worse than omitting it.
    """
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.replace(tzinfo=UTC).timestamp())
