"""Which trade prints are allowed to shape a bar.

The tape carries prints that report volume but must not move price:
average-price blocks, late reports, prior-reference prices, derivatively-priced
crosses, odd lots. Folding those into OHLC grows phantom wicks and lurches the
session VWAP.

Follows the CTA/UTP participation rules the SIPs use to build the official
high/low/last (CTS Pillar Output Specification, UTP Binary Output Spec, TDDS
2.1), with one divergence for odd lots at ``_ODD_LOT``:

- ``SKIP``        administrative reprints whose volume is on the tape
                  elsewhere, plus odd lots;
- ``VOLUME_ONLY`` real volume whose price is not a market price *now*;
- everything else is price-forming.

The specification filters *per field*, not per trade (``G`` is barred from
high/low but may set open and close); a single flag collapses that. ``T``,
ordinary extended hours, stays price-forming — every pre-open print on a
gapper carries it. ``U`` is its out-of-sequence flavour, treated like ``Z``.
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

# Divergence from the specification, for consistency with the bars this app is
# built on. The SIP rule bars an odd lot from price but counts it in volume, as
# Alpaca's bars do; IBKR quotes volume net of odd lots everywhere, and its 10s
# bars are our baseline. Following the SIP would put the Alpaca failover on a
# different convention from the chart it fills in — worth ~21-26% of shares on a
# small-cap gapper.
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
