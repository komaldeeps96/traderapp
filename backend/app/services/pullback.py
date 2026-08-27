"""The first-pullback read: depth, volume contraction, freshness.

The playbook's entry is not the breakout — it is the first orderly pullback
after one. What makes a pullback orderly is concrete enough to measure:

- it holds the top half of the leg (a retrace past 50% says the buyers who
  drove the leg are gone, past ~78.6% says the leg failed);
- volume dries up while it forms (heavy volume on the way down is not a
  pullback, it is distribution);
- it is fresh (a "pullback" ten minutes old is a downtrend with a story).

This module turns those into numbers from the day's 1-minute bars. Nothing
here decides healthy/failed — the raw measurements ride the info payload
and the frontend applies the thresholds, where they are unit-tested against
what the trader actually sees.

Leg detection is deliberately simple: the peak is the highest high of the
trailing window, the trough the lowest low before it in the same window.
Swing-labeling algorithms were not attempted — every parameter they add is
a parameter this display would have to explain. The two constants below are
the entire tuning surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.bars import Bar

# The window that defines "the current leg". An hour of minute bars: long
# enough to hold any leg worth pulling back from, short enough that the
# morning's first run does not shadow the afternoon's.
LOOKBACK_BARS = 60

# A leg smaller than this fraction of price is chop, not a leg; measuring
# a "pullback" inside it would manufacture signal from noise.
MIN_LEG_PERCENT = 3.0


@dataclass(slots=True)
class Pullback:
    """One measured pullback. All fields are raw; thresholds live client-side."""

    # How much of the leg has been given back, 0-100+. 38 means price sits
    # 38% of the way back down from the peak toward the trough.
    depth_percent: float
    # Mean pullback-bar volume over mean rally-bar volume. Below ~0.5 is the
    # drying-up the setup wants; None when the rally printed no volume.
    volume_ratio: float | None
    # Minutes since the peak. Small is fresh; double digits is a downtrend.
    bars_since_high: int
    # The leg itself, as a percentage of the trough price — how much there
    # is to pull back from.
    leg_percent: float


def measure(bars: list[Bar]) -> Pullback | None:
    """Measure the active pullback, or None when there is nothing to measure.

    None is the common answer, and each way of reaching it is a statement:
    no leg (chop), no pullback yet (price is at the highs), or a leg fully
    retraced (whatever that is now, it is not a pullback).
    """
    window = bars[-LOOKBACK_BARS:]
    if len(window) < 3:
        return None

    # Peak: highest high; on equal highs the LATEST wins, because
    # bars_since_high reports the freshness of the most recent test.
    peak_idx = max(range(len(window)), key=lambda i: (window[i].high, i))
    peak = window[peak_idx].high

    # Trough: lowest low up to and including the peak bar.
    trough_idx = min(range(peak_idx + 1), key=lambda i: (window[i].low, -i))
    trough = window[trough_idx].low

    leg = peak - trough
    if trough <= 0 or leg <= 0:
        return None
    leg_percent = leg / trough * 100.0
    if leg_percent < MIN_LEG_PERCENT:
        return None

    bars_since = len(window) - 1 - peak_idx
    if bars_since == 0:
        return None  # price is making the high now; nothing has pulled back

    last = window[-1].close
    depth_percent = (peak - last) / leg * 100.0
    if depth_percent > 100.0:
        return None  # below the trough: the leg is gone, not pulling back

    rally = window[trough_idx : peak_idx + 1]
    pullback = window[peak_idx + 1 :]
    rally_volume = sum(bar.volume for bar in rally) / len(rally)
    pullback_volume = sum(bar.volume for bar in pullback) / len(pullback)
    ratio = (pullback_volume / rally_volume) if rally_volume > 0 else None

    return Pullback(
        depth_percent=depth_percent,
        volume_ratio=ratio,
        bars_since_high=bars_since,
        leg_percent=leg_percent,
    )
