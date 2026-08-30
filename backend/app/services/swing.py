"""Swing screens, run against TradingView.

The four market-cap scanners are a day-trading instrument: they rank by trade
rate and rotation, and they answer "what is moving *now*". A swing setup is a
different question — "what has been working, and is it at a place worth
buying" — and it is answered from daily structure rather than from the tape.

Two consequences shape this file.

**These do not need IBKR.** The day scanners are dark whenever TWS is not
running, which is most of the time outside a session. A swing screen is a
daily-bar question, so it answers from TradingView and works with nothing
else connected.

**The interesting filters cannot be sent.** TradingView's query language
compares a column against a *number*, not against another column, so "within
10% of the 52-week high" and "sitting on the 50-day" cannot be expressed in
the request. The coarse terms go to the server, and the proximity tests run
here on the rows that come back — which is also why each screen asks for more
rows than it shows.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from tradingview_screener import Query, col

from ..core.clock import now_epoch
from ..domain.screener import finite
from .tv import _common_stock_terms

logger = logging.getLogger(__name__)

# A swing setup does not change second to second, and every run is a request
# to TradingView; a minute-old screen is as good as a fresh one.
SWING_TTL_SECONDS = 60.0

# Fetched before refining, since the proximity tests happen here. Wide enough
# that a strict screen still fills, small enough to stay one request.
FETCH_LIMIT = 300

COLUMNS = [
    "name",
    "description",
    "close",
    "change",
    "relative_volume_10d_calc",
    "market_cap_basic",
    "average_volume_10d_calc",
    "Perf.W",
    "Perf.1M",
    "Perf.3M",
    "SMA50",
    "SMA200",
    "price_52_week_high",
    "ADR",
    "sector",
    # A setup that reports in three days is a different proposition; the
    # column rides the same request, so carrying it is free.
    "earnings_release_next_date",
]


@dataclass(frozen=True, slots=True)
class SwingScreen:
    id: str
    label: str
    note: str
    order_by: str
    ascending: bool = False
    # Coarse, sent to TradingView.
    require_uptrend: bool = False
    require_above_200: bool = False
    # Fine, applied to the returned rows.
    max_off_high: float | None = None
    min_off_high: float | None = None
    min_rvol: float | None = None
    near_sma50: float | None = None


SCREENS: tuple[SwingScreen, ...] = (
    SwingScreen(
        id="trend",
        label="Trend continuation",
        note="Above a rising 50 and 200, within 10% of the 52-week high, ranked by three-month strength.",
        order_by="Perf.3M",
        require_uptrend=True,
        max_off_high=10.0,
    ),
    SwingScreen(
        id="breakout",
        label="Breakout",
        note="At the 52-week high on expanding volume — the day the base ends.",
        order_by="relative_volume_10d_calc",
        require_uptrend=True,
        max_off_high=2.0,
        min_rvol=1.5,
    ),
    SwingScreen(
        id="pullback",
        label="Pullback to the 50",
        note="Still above the 200, 5 to 25% off the high, and back at the 50-day.",
        order_by="Perf.3M",
        require_above_200=True,
        min_off_high=5.0,
        max_off_high=25.0,
        near_sma50=4.0,
    ),
    SwingScreen(
        id="momentum",
        label="Momentum leaders",
        note="The strongest month in the market, above the 50-day.",
        order_by="Perf.1M",
    ),
)

SCREENS_BY_ID = {screen.id: screen for screen in SCREENS}


@dataclass(frozen=True, slots=True)
class SwingConfig:
    """What the user can tune. Deliberately few: a screen is a setup, not a
    filter builder, and the two numbers that change with account size are the
    ones that matter."""

    min_market_cap: float = 2_000_000_000.0
    min_avg_volume: float = 1_000_000.0
    rows: int = 15

    def to_dict(self) -> dict:
        return {
            "min_market_cap": self.min_market_cap,
            "min_avg_volume": self.min_avg_volume,
            "rows": self.rows,
        }


DEFAULT_CONFIG = SwingConfig()


def _percent_off_high(close: float | None, high: float | None) -> float | None:
    if close is None or high is None or high <= 0:
        return None
    return (close / high - 1.0) * 100.0


def _distance_to_sma(close: float | None, sma: float | None) -> float | None:
    if close is None or sma is None or sma <= 0:
        return None
    return abs(close / sma - 1.0) * 100.0


def _passes(screen: SwingScreen, row: dict) -> bool:
    # Re-checked here rather than trusted from `_shape`, because this is the
    # function whose failure is silent: every comparison against NaN is False,
    # so a row carrying one passes each test *by failing it*.
    off_high = finite(row.get("off_high"))
    # `off_high` is negative below the high, so "within 10%" is >= -10.
    if screen.max_off_high is not None and (off_high is None or off_high < -screen.max_off_high):
        return False
    if screen.min_off_high is not None and (off_high is None or off_high > -screen.min_off_high):
        return False
    if screen.min_rvol is not None:
        rvol = finite(row.get("rvol"))
        if rvol is None or rvol < screen.min_rvol:
            return False
    if screen.near_sma50 is not None:
        distance = finite(row.get("distance_to_sma50"))
        if distance is None or distance > screen.near_sma50:
            return False
    return True


class SwingService:
    def __init__(self, fetch=None):
        self._fetch = fetch
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._config = DEFAULT_CONFIG
        self._note: str | None = None

    @property
    def config(self) -> SwingConfig:
        return self._config

    @property
    def note(self) -> str | None:
        """Set only when TradingView itself failed, so an empty screen can say
        so rather than reading as "nothing qualifies today"."""
        return self._note

    def adopt_config(self, config: dict | None) -> None:
        if not isinstance(config, dict):
            return
        current = self._config.to_dict()
        for key, value in config.items():
            if key in current and isinstance(value, (int, float)) and value >= 0:
                current[key] = value
        self._config = SwingConfig(
            min_market_cap=float(current["min_market_cap"]),
            min_avg_volume=float(current["min_avg_volume"]),
            rows=max(1, min(int(current["rows"]), 50)),
        )
        self._cache.clear()

    def configure(self, **changes) -> SwingConfig:
        self.adopt_config({key: value for key, value in changes.items() if value is not None})
        return self._config

    def peek(self, screen_id: str) -> list[dict] | None:
        cached = self._cache.get(screen_id)
        if cached is None or now_epoch() - cached[0] >= SWING_TTL_SECONDS:
            return None
        return cached[1]

    async def rows(self, screen_id: str) -> list[dict]:
        screen = SCREENS_BY_ID.get(screen_id)
        if screen is None:
            return []
        fresh = self.peek(screen_id)
        if fresh is not None:
            return fresh

        try:
            rows = await self._run(screen)
        except Exception as exc:
            logger.warning("Swing screen %s failed: %s", screen_id, exc)
            self._note = "TradingView did not answer; the screen is stale."
            return self._cache.get(screen_id, (0.0, []))[1]

        self._note = None
        self._cache[screen_id] = (now_epoch(), rows)
        return rows

    async def _run(self, screen: SwingScreen) -> list[dict]:
        query = self._query(screen)
        if self._fetch is not None:
            payload = await self._fetch(query)
        else:
            payload = await asyncio.to_thread(_scan, query)
        refined = [row for row in _shape(payload) if _passes(screen, row)]
        return refined[: self._config.rows]

    def _query(self, screen: SwingScreen) -> Query:
        terms = [
            *_common_stock_terms(),
            col("market_cap_basic") >= self._config.min_market_cap,
            col("average_volume_10d_calc") >= self._config.min_avg_volume,
        ]
        if screen.require_uptrend:
            terms += [col("close") > col("SMA50"), col("SMA50") > col("SMA200")]
        elif screen.require_above_200:
            terms.append(col("close") > col("SMA200"))
        else:
            terms.append(col("close") > col("SMA50"))
        return (
            Query()
            .select(*COLUMNS)
            .where(*terms)
            .order_by(screen.order_by, ascending=screen.ascending)
            .limit(FETCH_LIMIT)
        )


def _scan(query: Query) -> list[list]:
    _, frame = query.get_scanner_data()
    return frame[COLUMNS].values.tolist() if not frame.empty else []


def _shape(payload) -> list[dict]:
    """Raw rows into the shape the table draws, with the derived fields."""
    index = {name: position for position, name in enumerate(COLUMNS)}

    def number(row, name):
        return finite(row[index[name]])

    def text(row, name):
        value = row[index[name]]
        return value if isinstance(value, str) else ""

    out: list[dict] = []
    for row in payload:
        close = number(row, "close")
        row_out = {
            "symbol": text(row, "name"),
            "name": text(row, "description"),
            "sector": text(row, "sector"),
            "close": close,
            "change": number(row, "change"),
            "rvol": number(row, "relative_volume_10d_calc"),
            "market_cap": number(row, "market_cap_basic"),
            "avg_volume": number(row, "average_volume_10d_calc"),
            "perf_week": number(row, "Perf.W"),
            "perf_month": number(row, "Perf.1M"),
            "perf_quarter": number(row, "Perf.3M"),
            "adr": number(row, "ADR"),
            "off_high": _percent_off_high(close, number(row, "price_52_week_high")),
            "distance_to_sma50": _distance_to_sma(close, number(row, "SMA50")),
            "next_earnings": number(row, "earnings_release_next_date"),
        }
        if row_out["symbol"]:
            out.append(row_out)
    return out
