"""Pure indicator maths.

Every function takes plain numbers and returns plain numbers, with ``None``
where a value is not yet defined. No dataframes, no global state, no clock —
so each one is directly unit-testable.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

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

    Recursing straight from the first sample instead makes early values track
    price almost exactly and drift for hundreds of bars.
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

    Not configurable per user: the point of the indicator is that everyone sees
    the same crossovers.
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

    Resets on the New York date, not the UTC date: UTC midnight falls inside the
    US after-hours session and would split one day's VWAP in two.

    Anchored at 04:00 rather than NY midnight so the line is the one every other
    participant watches — VWAP earns its place through polarity, which only
    holds if it is the same quantity. Trades outside the session are excluded
    and carry no value of their own.

    Computed from the charted bars alone, never seeded from another timeframe:
    the minute base counts odd-lot volume and the 10-second bars do not, so a
    seed would be inflated and drift as minutes are overwritten by the resample.
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

    Unlike the daily key levels in ``levels.py`` these *move* as the day trades:
    a "retest of the high of day" is meaningless against a frozen value. The
    pre-market high is drawn separately and stays settled.
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

    The moment is what stops these repainting: the regular-session open does not
    exist at 09:00, so drawing it across the pre-market would show a line nobody
    could have traded against.
    """

    value: Number = None
    known_from: float | None = None


@dataclass(frozen=True, slots=True)
class SessionLevels:
    """Prices anchored to session boundaries rather than to a daily bar.

    Built from the minute base rather than the displayed timeframe: the
    after-hours high belongs to the *previous* session, which the 10-second
    window does not reach.
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

    Broadcast across the whole day, not just the pre-market bars: it is a level
    referenced all session, so it must be present on the 14:00 bar too.
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
    repeat the same number ~960 times per level per day. The endpoints of each
    run draw an identical horizontal line.
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
# The live update loop needs each indicator's *current* value only, once a
# second per subscribed chart. Building whole arrays to read the last element
# costs milliseconds rather than microseconds, so these compute just the tail.


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


# ── windowed relative volume ──────────────────────────────────────────

# Two days whose first bars sit further apart than this are not measuring
# the same window: the older one was truncated by the history fetch, and
# comparing a 4am-anchored day against a noon-anchored one manufactures a
# relative-volume signal out of the fetch boundary.
_WRVOL_START_SLACK_SECONDS = 600

# New York day bucketing as pure arithmetic: the tape prints 4:00-20:00 ET,
# and any fixed offset between 4 and 5 hours buckets every such timestamp
# identically under both EST and EDT. Mirrors the frontend's session lib.
_NY_OFFSET_SECONDS = 16_200

# How far back the denominator reaches, matching the 50-day baseline the
# screener's relative volume uses. Only the first handful of those sessions
# are covered by the minute base (history.intraday_days is 5, deliberately:
# one Alpaca request per ticker switch); the rest are projected off the daily
# base, which is already loaded years deep for the same symbol.
_WRVOL_LOOKBACK_SESSIONS = 50


def _arith_day(epoch: float) -> int:
    return int((epoch - _NY_OFFSET_SECONDS) // 86_400)


def _daily_bar_day(epoch: float) -> int:
    """The arithmetic day index of a daily bar.

    Daily bars anchor to New York *midnight* (``market/resample.py``), outside
    the 04:00-20:00 window the offset arithmetic is valid over: under EDT it
    lands on the previous day. Nudging by twelve hours puts the stamp at New
    York noon, unambiguously mid-session under either offset.
    """
    return _arith_day(epoch + 43_200)


@dataclass(slots=True)
class _VolumeDay:
    day: int
    first_tod: float
    tods: list[float]
    cums: list[float]


def _volume_days(minute_bars: Sequence[Bar]) -> list[_VolumeDay]:
    """Cumulative volume per bar, grouped by New York day."""
    days: list[_VolumeDay] = []
    current: _VolumeDay | None = None
    total = 0.0
    for bar in minute_bars:
        day = int((bar.time - _NY_OFFSET_SECONDS) // 86_400)
        tod = (bar.time - _NY_OFFSET_SECONDS) % 86_400
        if current is None or day != current.day:
            total = 0.0
            current = _VolumeDay(day=day, first_tod=tod, tods=[], cums=[])
            days.append(current)
        total += bar.volume
        current.tods.append(tod)
        current.cums.append(total)
    return days


def _cum_at_or_before(day: _VolumeDay, tod: float) -> float | None:
    """The day's cumulative volume at the last minute at or before ``tod``."""
    index = bisect_right(day.tods, tod) - 1
    return day.cums[index] if index >= 0 else None


def windowed_rvol(
    bars: Sequence[Bar],
    minute_bars: Sequence[Bar],
    daily_bars: Sequence[Bar] = (),
) -> list[Number]:
    """Time-matched relative volume, stamped onto each chart bar.

    Today's cumulative volume from the 04:00 open through the bar, over a
    typical day's cumulative at the same time of day — "is this pace hot for
    10:15am". Today's leg reads off the 1-minute base, so on a 10-second chart
    the value steps once a minute.

    The denominator has two sources:

    * The minute base gives the *exact* cumulative for the five sessions it
      covers; a wider 1-minute fetch would cost several Alpaca pages per switch.
    * The daily base, already loaded years deep, gives the *level* of every
      session back to ``_WRVOL_LOOKBACK_SESSIONS``, projected onto this time of
      day by the median shape measured where both bases exist.

    That split follows what varies: between sessions total volume moves by
    orders of magnitude while the shape of the curve barely does. Projection is
    skipped when no day carries both bases, leaving nothing to calibrate against.

    Reduced by **median**, not mean — one prior session that ran 50x would
    poison a mean denominator and halve every reading for days.

    ``None`` wherever a comparison does not exist: the oldest day in history, a
    bar whose day the minute base has not covered, or no full prior session.
    """
    days = _volume_days(minute_bars)
    by_day = {entry.day: index for index, entry in enumerate(days)}
    daily_volume = {
        _daily_bar_day(bar.time): bar.volume for bar in daily_bars if bar.volume > 0
    }

    # Per-day setup: which prior sessions the minute base can answer for
    # directly, and which daily bars are left to project from.
    context: dict[int, tuple[list[_VolumeDay], list[float]]] = {}

    def prior_context(day_index: int) -> tuple[list[_VolumeDay], list[float]]:
        cached = context.get(day_index)
        if cached is not None:
            return cached
        today = days[day_index]
        direct = [
            prior
            for prior in days[:day_index]
            if abs(prior.first_tod - today.first_tod) <= _WRVOL_START_SLACK_SECONDS
        ]
        covered = {prior.day for prior in direct}
        # Most recent sessions first, so the window is the latest 50 rather
        # than the oldest 50 of a forty-year daily history.
        volumes = [
            volume
            for day, volume in sorted(daily_volume.items(), reverse=True)
            if day < today.day and day not in covered
        ][:_WRVOL_LOOKBACK_SESSIONS]
        context[day_index] = (direct, volumes)
        return context[day_index]

    # Memoised per (day, minute): on a 10-second chart six consecutive bars
    # share one lookup, and each lookup walks up to fifty sessions.
    denominators: dict[tuple[int, int], float | None] = {}

    def denominator(day_index: int, tod: float) -> float | None:
        key = (day_index, int(tod // 60))
        if key in denominators:
            return denominators[key]

        direct_days, volumes = prior_context(day_index)
        estimates: list[float] = []
        shapes: list[float] = []
        for prior in direct_days:
            at = _cum_at_or_before(prior, tod)
            if at is None:
                continue
            estimates.append(at)
            whole = daily_volume.get(prior.day)
            if whole:
                shapes.append(at / whole)

        if shapes:
            shape = median(shapes)
            estimates.extend(volume * shape for volume in volumes)

        value = median(estimates) if estimates else None
        denominators[key] = value if value else None
        return denominators[key]

    out: list[Number] = []
    for bar in bars:
        day = _arith_day(bar.time)
        tod = (bar.time - _NY_OFFSET_SECONDS) % 86_400
        day_index = by_day.get(day)
        if day_index is None or day_index == 0:
            out.append(None)
            continue
        cum = _cum_at_or_before(days[day_index], tod)
        base = denominator(day_index, tod)
        out.append(cum / base if cum is not None and base is not None else None)
    return out


def windowed_rvol_last(
    bars: Sequence[Bar],
    minute_bars: Sequence[Bar],
    daily_bars: Sequence[Bar] = (),
) -> Number:
    """Just the latest bar's value — the once-a-second path."""
    if not bars:
        return None
    values = windowed_rvol(bars[-1:], minute_bars, daily_bars)
    return values[-1] if values else None
