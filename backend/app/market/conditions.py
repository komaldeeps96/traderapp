"""Which trade prints are allowed to shape a bar.

The consolidated tape carries prints that report volume but must not move
price: average-price blocks, late (out-of-sequence) reports, prior-reference
prices, derivatively-priced crosses, odd lots. Folding those into OHLC is
exactly how a chart grows phantom wicks and a session VWAP lurches — one
five-million-share average-price print at a stale price does both at once.

The classification follows the CTA/UTP participation rules the SIPs
themselves use when building the official high/low/last — the CTS Pillar
Output Specification, the UTP Binary Output Spec and TDDS 2.1, which Alpaca
documents following as well — with one deliberate divergence for odd lots,
explained at ``_ODD_LOT``:

- ``SKIP``        dropped outright: administrative reprints whose volume is
                  already on the tape elsewhere, plus odd lots, which IBKR
                  also omits from both price and volume;
- ``VOLUME_ONLY`` real volume whose price is not a market price *now*;
- everything else is a price-forming trade.

One caveat this module cannot express: the specification filters *per field*,
not per trade — ``G`` for instance is barred from high/low but allowed to set
open and close. A single flag collapses that distinction. It has not bitten
yet because none of the affected codes has appeared in this cohort.

``T`` — the ordinary extended-hours condition — stays price-forming on
purpose: the pre-market session is half the point of this terminal, and on a
small-cap gapper every pre-open print carries it, so excluding it would leave
04:00–09:30 blank. ``U`` is the *out-of-sequence* extended-hours flavour and
is treated like its regular-session twin ``Z``: a late report should not plant
a wick at a stale price during the session we actually trade.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class TradeKind(Enum):
    PRICE_FORMING = "price_forming"
    VOLUME_ONLY = "volume_only"
    SKIP = "skip"


# Market-center official open/close and corrected-close reprints: their size
# double-counts auction volume already printed. These are the only three the
# SIP specification itself bars from volume.
_SKIP = frozenset({"M", "Q", "9"})

# A deliberate divergence from the specification, for consistency with the
# bars this app is built on.
#
# The SIP rule is that an odd lot is barred from price but still counts in
# volume, and that is what Alpaca's published bars do. IBKR does not: its
# historical bars, its 5-second bars and its ``Last`` tick stream all quote
# volume net of odd lots, as does TWS. Those historical 10s bars are our
# baseline — the minute base is resampled from them — so following the SIP
# here would put the Alpaca failover on a different convention from the
# chart it is filling in, and move reported volume by a quarter mid-session.
#
# On a small-cap gapper odd lots run ~73% of prints and ~21-26% of shares, so
# the two conventions are not close. One convention, matched to the baseline,
# is worth more than conformance here.
_ODD_LOT = frozenset({"I"})

# Counted in volume, excluded from open/high/low/close:
#   C cash sale · G bunched sold · H price variation · N next day ·
#   P prior reference price · R seller ·
#   U extended hours, sold out of sequence · V contingent trade ·
#   W average price · Z sold out of sequence ·
#   4 derivatively priced · 7 qualified contingent trade
#
# Odd lots are absent from this set on purpose — see _ODD_LOT above.
_VOLUME_ONLY = frozenset({"C", "G", "H", "N", "P", "R", "U", "V", "W", "Z", "4", "7"})


def classify_conditions(conditions: Iterable[str] | None) -> TradeKind:
    """Classify a print by its SIP sale conditions."""
    if not conditions:
        return TradeKind.PRICE_FORMING
    flags = {str(code).strip() for code in conditions}
    if flags & _SKIP or flags & _ODD_LOT:
        return TradeKind.SKIP
    if flags & _VOLUME_ONLY:
        return TradeKind.VOLUME_ONLY
    return TradeKind.PRICE_FORMING
