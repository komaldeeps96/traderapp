"""Insider transactions, read for what they mean rather than what they are.

A Form 4 is filed for every share an insider touches, and most of what it
records is payroll. Grants, option exercises and shares withheld to cover the
tax on a vest are compensation mechanics: they move the share count and say
nothing about what the insider thinks. Naive trackers count all of it, which
is why "insider selling" headlines are usually a vest.

Two things carry information, and this module exists to separate them from
the rest:

**An open-market purchase.** An insider paying their own cash for stock at
the market price, under the same disclosure rules as everyone else.

**A discretionary sale.** A sale *not* made under a 10b5-1 plan. Plan sales
are scheduled months ahead and are as automatic as a payroll deduction; the
form says which is which, so there is no reason to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Intent(str, Enum):
    """What a transaction says, if anything."""

    # Cash out of pocket, at the market. The one that carries conviction.
    BUY = "buy"
    # Stock sold at the market. What it means depends on whether it was
    # scheduled, which `planned` answers.
    SELL = "sell"
    # Grants, vests, exercises, tax withholding: how the person is paid.
    COMPENSATION = "compensation"
    # Gifts, conversions, transfers between forms of ownership.
    OTHER = "other"


# Table 1 transaction codes. The note is what the code means to a reader, not
# what the SEC calls it.
CODES: dict[str, tuple[Intent, str]] = {
    "P": (Intent.BUY, "open-market purchase"),
    "S": (Intent.SELL, "open-market sale"),
    "A": (Intent.COMPENSATION, "grant or award"),
    "M": (Intent.COMPENSATION, "option exercise"),
    "F": (Intent.COMPENSATION, "shares withheld for tax"),
    "X": (Intent.COMPENSATION, "in-the-money option exercised"),
    "C": (Intent.OTHER, "conversion of a derivative"),
    "G": (Intent.OTHER, "gift"),
    "D": (Intent.OTHER, "disposition to the issuer"),
    "I": (Intent.OTHER, "discretionary transaction"),
    "J": (Intent.OTHER, "other acquisition or disposal"),
    "V": (Intent.OTHER, "voluntary early report"),
}

UNKNOWN_CODE = (Intent.OTHER, "unrecognised code")


def classify(code: str) -> tuple[Intent, str]:
    return CODES.get(code.strip().upper(), UNKNOWN_CODE)


@dataclass(frozen=True, slots=True)
class InsiderTrade:
    """One line of one Form 4."""

    filed: date
    traded: date
    owner: str
    role: str
    code: str
    intent: Intent
    note: str
    shares: float | None
    price: float | None
    # Shares held afterwards — the denominator that turns a sale into either
    # a trim or an exit.
    shares_after: float | None
    acquired: bool
    # Sold under a plan adopted months earlier, so not a decision made today.
    planned: bool
    url: str

    @property
    def value(self) -> float | None:
        if self.shares is None or self.price is None:
            return None
        return self.shares * self.price

    def to_dict(self) -> dict:
        return {
            "filed": self.filed.isoformat(),
            "traded": self.traded.isoformat(),
            "owner": self.owner,
            "role": self.role,
            "code": self.code,
            "intent": self.intent.value,
            "note": self.note,
            "shares": self.shares,
            "price": self.price,
            "shares_after": self.shares_after,
            "acquired": self.acquired,
            "planned": self.planned,
            "value": self.value,
            "url": self.url,
        }
