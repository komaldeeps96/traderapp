"""Pure indicator maths.

Every function takes plain numbers and returns plain numbers, with ``None``
where a value is not yet defined. No dataframes, no global state, no clock —
so each one is directly unit-testable.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.bars import Bar
from ..domain.sessions import Session, ny_date, session_of

Number = float | None


def sma(values: Sequence[float], window: int) -> list[Number]:
    """Simple moving average. Undefined until ``window`` samples exist."""
    out: list[Number] = [None] * len(values)
    if window <= 0 or len(values) < window:
        return out

    running = float(sum(values[:window]))
    out[window - 1] = running / window
    for i in range(window, len(values)):
        running += values[i] - values[i - window]
        out[i] = running / window
    return out


def ema(values: Sequence[float], span: int) -> list[Number]:
    """Exponential moving average, seeded with an SMA of the first ``span``
    samples — the convention TradingView's ``ta.ema`` uses.

    Seeding matters: recursing straight from the first sample makes the early
    values track price almost exactly and drift for hundreds of bars.
    """
    out: list[Number] = [None] * len(values)
    if span <= 0 or len(values) < span:
        return out

    alpha = 2.0 / (span + 1.0)
    prev = float(sum(values[:span])) / span
    out[span - 1] = prev
    for i in range(span, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> tuple[list[Number], list[Number], list[Number]]:
    """MACD line, signal line, histogram — platform-default 12/26/9 on close.

    The settings are deliberately not configurable per user: the whole point
    of the indicator here is that everyone sees the same crossovers, so it is
    computed exactly the way charting platforms default to.
    """
    fast_line = ema(values, fast)
    slow_line = ema(values, slow)

    macd_line: list[Number] = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_line, slow_line, strict=True)
    ]

    defined = [v for v in macd_line if v is not None]
    signal_defined = ema(defined, signal_span)
    signal_line: list[Number] = [None] * len(values)
    cursor = 0
    for i, value in enumerate(macd_line):
        if value is None:
            continue
        signal_line[i] = signal_defined[cursor]
        cursor += 1

    histogram: list[Number] = [
        m - s if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line, strict=True)
    ]
    return macd_line, signal_line, histogram


def rolling_max(values: Sequence[float], window: int) -> list[Number]:
    """Rolling maximum over a trailing window, via a monotonic deque."""
    out: list[Number] = [None] * len(values)
    if window <= 0:
        return out

    candidates: deque[int] = deque()
    for i, value in enumerate(values):
        while candidates and values[candidates[-1]] <= value:
            candidates.pop()
        candidates.append(i)
        if candidates[0] <= i - window:
            candidates.popleft()
        if i >= window - 1:
            out[i] = values[candidates[0]]
    return out


def rolling_min(values: Sequence[float], window: int) -> list[Number]:
    out: list[Number] = [None] * len(values)
    if window <= 0:
        return out

    candidates: deque[int] = deque()
    for i, value in enumerate(values):
        while candidates and values[candidates[-1]] >= value:
            candidates.pop()
        candidates.append(i)
        if candidates[0] <= i - window:
            candidates.popleft()
        if i >= window - 1:
            out[i] = values[candidates[0]]
    return out


def typical_price(bar: Bar) -> float:
    return (bar.high + bar.low + bar.close) / 3.0


def session_vwap(bars: Sequence[Bar]) -> list[Number]:
    """Volume-weighted average price, anchored to the 04:00-20:00 NY session.

    Resetting on the New York date rather than the UTC date matters: UTC
    midnight falls in the middle of the US after-hours session, which would
    split a single trading day's VWAP in two.

    Anchoring at 04:00 rather than NY midnight matters just as much, and for
    a different reason. VWAP earns its place through *polarity* — price above
    it is bullish, below it bearish — and that only works if our line is the
    same line every other participant is watching. A print at 02:00 folded
    into the average makes it a different quantity wearing the same name.
    Trades outside the session are therefore excluded rather than seeding it,
    and carry no value of their own.

    Computed from the charted bars alone, never seeded from another
    timeframe. Seeding was tried, from the minute base, and produced a
    staircase: the minute store is Alpaca's, which counts odd-lot volume,
    while the 10-second bars are IBKR's, which do not — so the seed was
    inflated, and it drifted as the minute bars were progressively
    overwritten by the 10-second resample. The 12-hour 10s window reaches
    04:00 through the session that matters, which is what makes this safe.
    """
    out: list[Number] = [None] * len(bars)
    current_date = None
    cum_pv = 0.0
    cum_vol = 0.0

    for i, bar in enumerate(bars):
        if session_of(bar.time) is Session.CLOSED:
            continue

        bar_date = ny_date(bar.time)
        if bar_date != current_date:
            current_date = bar_date
            cum_pv = 0.0
            cum_vol = 0.0

        cum_pv += typical_price(bar) * bar.volume
        cum_vol += bar.volume
        out[i] = cum_pv / cum_vol if cum_vol > 0 else None
    return out


def session_bounds(bars: Sequence[Bar]) -> tuple[list[Number], list[Number]]:
    """Running high and low of the session so far, 04:00-20:00 NY.

    Unlike the daily key levels in ``levels.py`` these *move* as the day
    trades, and that is the point. The high of day is the momentum scanner's
    own premise, the level the crowd converges on, and the usual profit
    target — a "retest of the high of day" is meaningless against a value
    frozen at yesterday's close. The pre-market high is drawn separately and
    stays settled; this one tracks the tape.
    """
    highs: list[Number] = [None] * len(bars)
    lows: list[Number] = [None] * len(bars)
    current_date = None
    hod: float | None = None
    lod: float | None = None

    for i, bar in enumerate(bars):
        if session_of(bar.time) is Session.CLOSED:
            continue

        bar_date = ny_date(bar.time)
        if bar_date != current_date:
            current_date = bar_date
            hod = lod = None

        hod = bar.high if hod is None else max(hod, bar.high)
        lod = bar.low if lod is None else min(lod, bar.low)
        highs[i] = hod
        lows[i] = lod
    return highs, lows


@dataclass(frozen=True, slots=True)
class SessionLevel:
    """A single price for the day, and the moment it became knowable.

    The second half is what stops these repainting. The regular-session open
    is not a level at 09:00 — it does not exist yet — so drawing it across
    the pre-market would show a line nobody could have traded against.
    """

    value: Number = None
    known_from: float | None = None


@dataclass(frozen=True, slots=True)
class SessionLevels:
    """Prices anchored to session boundaries rather than to a daily bar.

    Built from the minute base rather than the displayed timeframe: the
    after-hours high belongs to the *previous* session, twenty hours back,
    which the 10-second window does not reach.
    """

    pm_open: SessionLevel = SessionLevel()
    rth_open: SessionLevel = SessionLevel()
    ah_high: SessionLevel = SessionLevel()
    ah_low: SessionLevel = SessionLevel()

    def get(self, name: str) -> SessionLevel:
        return getattr(self, name, SessionLevel())


EMPTY_SESSION_LEVELS = SessionLevels()

SESSION_LEVEL_KINDS = frozenset({"pm_open", "rth_open", "ah_high", "ah_low"})


def session_levels(bars: Sequence[Bar], day) -> SessionLevels:
    """Session-boundary prices for ``day``, from a multi-day bar series."""
    first_pm: Bar | None = None
    first_rth: Bar | None = None
    previous_ah: list[Bar] = []
    previous_day = None

    for bar in bars:
        bar_day = ny_date(bar.time)
        session = session_of(bar.time)
        if bar_day == day:
            if session is Session.PREMARKET and first_pm is None:
                first_pm = bar
            elif session is Session.REGULAR and first_rth is None:
                first_rth = bar
        elif bar_day < day and session is Session.AFTERHOURS:
            # Keep only the newest prior after-hours session.
            if previous_day != bar_day:
                previous_day, previous_ah = bar_day, []
            previous_ah.append(bar)

    # Yesterday's after-hours is settled before today opens, so it is known
    # from the first moment of the day rather than from any print in it.
    ah_from = min((b.time for b in bars if ny_date(b.time) == day), default=None)
    return SessionLevels(
        pm_open=SessionLevel(first_pm.open, first_pm.time) if first_pm else SessionLevel(),
        rth_open=SessionLevel(first_rth.open, first_rth.time) if first_rth else SessionLevel(),
        ah_high=SessionLevel(max((b.high for b in previous_ah), default=None), ah_from)
        if previous_ah
        else SessionLevel(),
        ah_low=SessionLevel(min((b.low for b in previous_ah), default=None), ah_from)
        if previous_ah
        else SessionLevel(),
    )


def session_level_series(bars: Sequence[Bar], level: SessionLevel) -> list[Number]:
    """Broadcast one session price across the bars that could know it."""
    if level.value is None or level.known_from is None:
        return [None] * len(bars)
    return [level.value if bar.time >= level.known_from else None for bar in bars]


def premarket_bounds(bars: Sequence[Bar]) -> tuple[list[Number], list[Number]]:
    """Pre-market high and low for each bar's day.

    The settled value is broadcast across the *whole* day, not just the
    pre-market bars — it is a level traders reference all session, so it has
    to be present on the 14:00 bar too.
    """
    highs: dict[object, float] = {}
    lows: dict[object, float] = {}

    for bar in bars:
        if session_of(bar.time) is not Session.PREMARKET:
            continue
        day = ny_date(bar.time)
        highs[day] = max(highs.get(day, bar.high), bar.high)
        lows[day] = min(lows.get(day, bar.low), bar.low)

    high_out: list[Number] = []
    low_out: list[Number] = []
    for bar in bars:
        day = ny_date(bar.time)
        high_out.append(highs.get(day))
        low_out.append(lows.get(day))
    return high_out, low_out


def compress_steps(points: Sequence[tuple[int, Number]]) -> list[tuple[int, float]]:
    """Collapse runs of equal values to just their first and last point.

    Daily levels hold one value for a whole session, so a 1-minute chart would
    otherwise repeat the same number ~960 times per level per day. Keeping the
    endpoints of each run draws an identical horizontal line from a fraction
    of the points.
    """
    out: list[tuple[int, float]] = []
    run_start: int | None = None
    run_last: int = 0
    run_value: float = 0.0

    def close_run() -> None:
        if run_start is not None and run_last != run_start:
            out.append((run_last, run_value))

    for time, value in points:
        if value is None:
            close_run()
            run_start = None
            continue

        if run_start is not None and value == run_value:
            run_last = time
            continue

        close_run()
        out.append((time, value))
        run_start = time
        run_last = time
        run_value = value

    close_run()
    return out


def to_series(
    bars: Sequence[Bar], values: Sequence[Number]
) -> list[tuple[int, float]]:
    """Zip bar times with computed values, dropping undefined entries."""
    return [
        (bar.time, value)
        for bar, value in zip(bars, values, strict=True)
        if value is not None
    ]


# ── single-value variants ──────────────────────────────────────────────
#
# The live update loop only needs each indicator's *current* value, once a
# second per subscribed chart. Building whole arrays to read the last element
# is the difference between a few microseconds and a few milliseconds per
# indicator, so these compute just the tail.


def sma_last(values: Sequence[float], window: int) -> Number:
    if window <= 0 or len(values) < window:
        return None
    return float(sum(values[-window:])) / window


def ema_last(values: Sequence[float], span: int) -> Number:
    """Same recurrence as :func:`ema`, without allocating the full series."""
    if span <= 0 or len(values) < span:
        return None
    alpha = 2.0 / (span + 1.0)
    current = float(sum(values[:span])) / span
    for i in range(span, len(values)):
        current = alpha * values[i] + (1.0 - alpha) * current
    return current


def macd_last(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> tuple[Number, Number, Number]:
    """Current (macd, signal, histogram).

    The signal line's seed depends on the early MACD values, so this walks
    the full series; a bounded tail would drift from what :func:`macd` draws.
    """
    macd_line, signal_line, histogram = macd(values, fast, slow, signal_span)
    if not macd_line:
        return None, None, None
    return macd_line[-1], signal_line[-1], histogram[-1]


def _same_day_tail(bars: Sequence[Bar]) -> list[Bar]:
    """The trailing run of bars sharing the last bar's New York date."""
    if not bars:
        return []
    day = ny_date(bars[-1].time)
    tail: list[Bar] = []
    for bar in reversed(bars):
        if ny_date(bar.time) != day:
            break
        tail.append(bar)
    tail.reverse()
    return tail


def session_vwap_last(bars: Sequence[Bar]) -> Number:
    cum_pv = cum_vol = 0.0
    for bar in _same_day_tail(bars):
        if session_of(bar.time) is Session.CLOSED:
            continue
        cum_pv += typical_price(bar) * bar.volume
        cum_vol += bar.volume
    return cum_pv / cum_vol if cum_vol > 0 else None


def session_bounds_last(bars: Sequence[Bar]) -> tuple[Number, Number]:
    high: Number = None
    low: Number = None
    for bar in _same_day_tail(bars):
        if session_of(bar.time) is Session.CLOSED:
            continue
        high = bar.high if high is None else max(high, bar.high)
        low = bar.low if low is None else min(low, bar.low)
    return high, low


def premarket_bounds_last(bars: Sequence[Bar]) -> tuple[Number, Number]:
    high: Number = None
    low: Number = None
    for bar in _same_day_tail(bars):
        if session_of(bar.time) is not Session.PREMARKET:
            continue
        high = bar.high if high is None else max(high, bar.high)
        low = bar.low if low is None else min(low, bar.low)
    return high, low
