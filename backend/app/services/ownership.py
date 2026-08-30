"""What insiders have actually done, from the Form 4 trail.

The filing list gives the forms; the numbers are inside each one, so this
fetches the ownership XML per filing. That is the only read in the terminal
priced per *filing* rather than per company, which is why it is capped and
cached hard: a serial filer can have hundreds, and the SEC allowance is
shared with everything else.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from xml.etree import ElementTree

from ..core.clock import now_epoch
from ..domain.filings import Filing
from ..domain.ownership import InsiderTrade, Intent, classify

logger = logging.getLogger(__name__)

# Form 4s are read newest-first and stop here. Deep history is a research
# question, not a trading one, and every extra filing is another request.
MAX_FILINGS = 24

# The window the summary speaks for. A quarter is long enough to show a
# pattern and short enough that it is still about this position.
WINDOW_DAYS = 90

OWNERSHIP_TTL_SECONDS = 900.0

# The rendered document sits under an XSL directory; the raw XML is its
# sibling. `primaryDocument` points at the rendered one.
_XSL_PREFIX = "xsl"


def raw_document_url(url: str) -> str:
    """The machine-readable sibling of a rendered ownership form."""
    head, _, tail = url.rpartition("/")
    if not head:
        return url
    parent, _, folder = head.rpartition("/")
    if folder.startswith(_XSL_PREFIX):
        return f"{parent}/{tail}"
    return url


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _number(node, path: str) -> float | None:
    raw = _text(node, path)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _flag(node, path: str) -> bool:
    return _text(node, path).lower() in {"1", "true"}


def _role(owner) -> str:
    """Director, officer, ten-percent holder — in that order of interest."""
    relationship = owner.find("reportingOwnerRelationship")
    if relationship is None:
        return ""
    parts: list[str] = []
    title = _text(relationship, "officerTitle")
    if _flag(relationship, "isOfficer"):
        parts.append(title or "officer")
    if _flag(relationship, "isDirector"):
        parts.append("director")
    if _flag(relationship, "isTenPercentOwner"):
        parts.append("10% owner")
    return ", ".join(parts)


def parse_form4(xml: str, filed: date, url: str) -> list[InsiderTrade]:
    """Every Table 1 line of one Form 4.

    Derivative transactions are deliberately skipped: an option grant and its
    later exercise would otherwise each land as a row, double-counting one
    piece of compensation.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        logger.debug("Unparseable ownership document: %s", url)
        return []

    owner_node = root.find("reportingOwner")
    owner = _text(owner_node, "reportingOwnerId/rptOwnerName") if owner_node is not None else ""
    role = _role(owner_node) if owner_node is not None else ""
    planned = _flag(root, "aff10b5One")
    period = _text(root, "periodOfReport")

    trades: list[InsiderTrade] = []
    for node in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(node, "transactionCoding/transactionCode")
        if not code:
            continue
        intent, note = classify(code)
        traded_raw = _text(node, "transactionDate/value") or period
        try:
            traded = date.fromisoformat(traded_raw)
        except ValueError:
            traded = filed
        acquired = (
            _text(node, "transactionAmounts/transactionAcquiredDisposedCode/value").upper() == "A"
        )
        trades.append(
            InsiderTrade(
                filed=filed,
                traded=traded,
                owner=owner,
                role=role,
                code=code.upper(),
                intent=intent,
                note=note,
                shares=_number(node, "transactionAmounts/transactionShares/value"),
                price=_number(node, "transactionAmounts/transactionPricePerShare/value"),
                shares_after=_number(
                    node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
                ),
                acquired=acquired,
                # A plan only excuses a sale; a purchase under one is still
                # cash out of pocket.
                planned=planned and intent is Intent.SELL,
                url=url,
            )
        )
    return trades


def summarise(trades: list[InsiderTrade], today: date, window: int = WINDOW_DAYS) -> dict:
    """The read: open-market conviction, with the payroll set aside.

    Compensation is counted but kept out of the net, because a vest and a
    purchase are not the same act and adding them produces a number that
    means nothing.
    """
    cutoff = today - timedelta(days=window)
    recent = [trade for trade in trades if trade.traded >= cutoff]

    def total(intent: Intent, planned: bool | None = None) -> dict:
        rows = [
            trade
            for trade in recent
            if trade.intent is intent and (planned is None or trade.planned is planned)
        ]
        return {
            "count": len(rows),
            "shares": sum(trade.shares or 0.0 for trade in rows),
            "value": sum(trade.value or 0.0 for trade in rows),
            "people": len({trade.owner for trade in rows if trade.owner}),
        }

    buys = total(Intent.BUY)
    discretionary = total(Intent.SELL, planned=False)
    scheduled = total(Intent.SELL, planned=True)

    return {
        "window_days": window,
        "buys": buys,
        "discretionary_sells": discretionary,
        "planned_sells": scheduled,
        "compensation": total(Intent.COMPENSATION),
        # Open market only, and only what was decided rather than scheduled.
        "net_value": buys["value"] - discretionary["value"],
        "verdict": _verdict(buys, discretionary),
    }


def _verdict(buys: dict, sells: dict) -> str:
    if buys["count"] == 0 and sells["count"] == 0:
        return "No open-market insider activity in the window."
    if buys["count"] and not sells["count"]:
        people = buys["people"]
        who = "an insider" if people == 1 else f"{people} insiders"
        return f"{who} bought at the market and none sold."
    if sells["count"] and not buys["count"]:
        return "Open-market selling only, none of it under a plan."
    return "Insiders on both sides of the market."


class OwnershipService:
    def __init__(self, edgar):
        self._edgar = edgar
        self._cache: dict[str, tuple[float, list[InsiderTrade]]] = {}

    def peek(self, symbol: str) -> list[InsiderTrade] | None:
        cached = self._cache.get(symbol)
        if cached is None or now_epoch() - cached[0] >= OWNERSHIP_TTL_SECONDS:
            return None
        return cached[1]

    async def trades(self, symbol: str, filings: list[Filing]) -> list[InsiderTrade]:
        fresh = self.peek(symbol)
        if fresh is not None:
            return fresh

        forms = [filing for filing in filings if filing.form in {"4", "4/A"}][:MAX_FILINGS]
        if not forms:
            self._cache[symbol] = (now_epoch(), [])
            return []

        documents = await asyncio.gather(
            *(self._edgar.fetch_document(raw_document_url(filing.url)) for filing in forms),
            return_exceptions=True,
        )

        trades: list[InsiderTrade] = []
        for filing, document in zip(forms, documents, strict=True):
            if not isinstance(document, str):
                continue
            trades.extend(parse_form4(document, filing.filed, filing.url))

        trades.sort(key=lambda trade: (trade.traded, trade.filed), reverse=True)
        self._cache[symbol] = (now_epoch(), trades)
        return trades

    def drop(self, symbol: str) -> None:
        self._cache.pop(symbol, None)
