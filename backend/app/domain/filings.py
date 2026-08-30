"""SEC filing forms, read for what they mean to a momentum trade.

A small cap's filing trail is its dilution history written down. The forms
that matter are not the ones an investor reads — nobody is trading a 10-K
here — but the ones that register, price or announce new stock:

    S-1 / S-3      shares registered for sale; the shelf being built
    EFFECT         that registration went effective — the shelf is now live
    424B*          a prospectus; 424B5 is the takedown, the actual sale
    8-K item 3.02  unregistered equity sold, no registration needed

and the ones that say the company is in trouble, which is where the supply
usually comes from next:

    NT 10-Q/K      the periodic report is late
    25-NSE         the exchange has moved to delist
    8-K item 3.01  notice of failure to satisfy a listing rule
    8-K item 4.02  previously issued financials can no longer be relied on

Everything else is classified so it can be pushed below a fold rather than
dropped: an insider Form 4 is not a catalyst, but it is worth a row.

Forms are matched exactly. EDGAR's ``form`` field is a controlled vocabulary,
so a prefix match would put ``S-1`` and ``S-1MEF`` in one bucket while also
catching ``SC 13D`` with a sloppy pattern; the explicit table is both safer
and self-documenting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class FilingKind(str, Enum):
    """Why a filing is on screen."""

    DILUTION = "dilution"
    DISTRESS = "distress"
    PERIODIC = "periodic"
    OWNERSHIP = "ownership"
    ROUTINE = "routine"


# Forms that register, price or record a sale of stock. The note is what the
# form means at the tape, not what the SEC calls it.
DILUTION_FORMS: dict[str, str] = {
    "S-1": "registering new shares for sale",
    "S-1/A": "amended share registration",
    "S-1MEF": "extra shares added to a pending registration",
    "S-3": "shelf registration — capacity to sell later",
    "S-3/A": "amended shelf registration",
    "S-3ASR": "automatic shelf — effective on filing",
    "S-3MEF": "extra shares added to a shelf",
    "POS AM": "post-effective amendment to a registration",
    "EFFECT": "registration went effective — the shelf is live",
    "424B1": "prospectus — offering priced",
    "424B2": "prospectus supplement — offering priced",
    "424B3": "prospectus supplement",
    "424B4": "prospectus — offering priced",
    "424B5": "shelf takedown — shares being sold now",
    "424B7": "prospectus supplement — selling shareholders",
    "424B8": "prospectus supplement",
    "S-8": "employee stock plan registered",
    "S-8 POS": "amended employee stock plan registration",
}

# Forms that say the company is late, delinquent or on its way off the
# exchange. Distress is a dilution leading indicator.
DISTRESS_FORMS: dict[str, str] = {
    "NT 10-Q": "quarterly report filed late",
    "NT 10-K": "annual report filed late",
    "NT 20-F": "annual report filed late",
    # Worded for what the form actually says. It removes *a class of
    # securities*, which for an issuer with listed debt is routinely a matured
    # note — Apple files one most years. The company-level signal is 8-K item
    # 3.01, and only that one escalates the dilution verdict.
    "25": "a security class removed from listing",
    "25-NSE": "a security class removed from listing (by the exchange)",
    "15-12B": "deregistering — reporting obligations ending",
    "15-12G": "deregistering — reporting obligations ending",
}

PERIODIC_FORMS: dict[str, str] = {
    "10-K": "annual report",
    "10-K/A": "amended annual report",
    "10-Q": "quarterly report",
    "10-Q/A": "amended quarterly report",
    "20-F": "annual report (foreign issuer)",
    "40-F": "annual report (Canadian issuer)",
    "6-K": "interim report (foreign issuer)",
}

OWNERSHIP_FORMS: dict[str, str] = {
    "3": "insider's initial holdings",
    "4": "insider bought or sold",
    "5": "insider annual statement",
    "SC 13D": "5%+ holder, activist intent",
    "SC 13D/A": "5%+ activist holding changed",
    "SC 13G": "5%+ passive holder",
    "SC 13G/A": "5%+ passive holding changed",
    "SC TO-T": "third-party tender offer",
    "SC 14D9": "response to a tender offer",
}

# 8-K is one form carrying a dozen unrelated announcements; only the item
# number says which. These are the ones that move a small cap.
EIGHT_K_ITEMS: dict[str, tuple[FilingKind, str]] = {
    "1.01": (FilingKind.DILUTION, "material agreement signed — often a purchase or ATM deal"),
    "1.02": (FilingKind.ROUTINE, "material agreement terminated"),
    "1.03": (FilingKind.DISTRESS, "bankruptcy or receivership"),
    "2.02": (FilingKind.ROUTINE, "results announced"),
    "2.04": (FilingKind.DISTRESS, "debt accelerated by a triggering event"),
    "3.01": (FilingKind.DISTRESS, "listing rule not satisfied — delisting notice"),
    "3.02": (FilingKind.DILUTION, "unregistered equity sold"),
    "3.03": (FilingKind.DILUTION, "shareholder rights modified"),
    "4.01": (FilingKind.ROUTINE, "auditor changed"),
    "4.02": (FilingKind.DISTRESS, "past financials can no longer be relied on"),
    "5.02": (FilingKind.ROUTINE, "director or officer change"),
    "5.03": (FilingKind.ROUTINE, "charter or fiscal year changed"),
    "7.01": (FilingKind.ROUTINE, "regulation FD disclosure"),
    "8.01": (FilingKind.ROUTINE, "other events"),
}

_EIGHT_K_FORMS = frozenset({"8-K", "8-K/A", "6-K"})

# The subset of the dilution forms that represents a company actually selling
# stock, for counting offering cadence. S-8 registers an employee plan and
# EFFECT only flips a switch on a registration already counted at its filing,
# so neither is an offering in the sense a trader means it.
OFFERING_FORMS = frozenset(
    {
        "S-1",
        "S-1/A",
        "S-1MEF",
        "S-3",
        "S-3/A",
        "S-3ASR",
        "S-3MEF",
        "424B1",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
        "424B7",
        "424B8",
    }
)

# 8-K items that are themselves a sale of stock, counted alongside the forms.
OFFERING_ITEMS = frozenset({"3.02"})


def classify(form: str, items: str = "") -> tuple[FilingKind, str]:
    """The kind and the trader-facing note for one filing.

    ``items`` is EDGAR's comma-separated 8-K item list. An 8-K is only as
    interesting as its items, so a filing carrying both a routine and a
    dilution item is reported as the dilution one — the reason it is worth
    looking at is the worst thing in it, not the first.
    """
    if form in _EIGHT_K_FORMS:
        return _classify_eight_k(form, items)
    for table, kind in (
        (DILUTION_FORMS, FilingKind.DILUTION),
        (DISTRESS_FORMS, FilingKind.DISTRESS),
        (PERIODIC_FORMS, FilingKind.PERIODIC),
        (OWNERSHIP_FORMS, FilingKind.OWNERSHIP),
    ):
        note = table.get(form)
        if note is not None:
            return kind, note
    return FilingKind.ROUTINE, ""


# Worst-first, so a filing is described by its most consequential item.
_ITEM_PRIORITY = (FilingKind.DISTRESS, FilingKind.DILUTION, FilingKind.ROUTINE)


def _classify_eight_k(form: str, items: str) -> tuple[FilingKind, str]:
    parsed = [item.strip() for item in items.split(",") if item.strip()]
    known = [EIGHT_K_ITEMS[item] for item in parsed if item in EIGHT_K_ITEMS]
    if not known:
        return FilingKind.ROUTINE, "current report" if form != "6-K" else "interim report"
    for kind in _ITEM_PRIORITY:
        for candidate_kind, note in known:
            if candidate_kind is kind:
                return kind, note
    return FilingKind.ROUTINE, ""


@dataclass(frozen=True)
class Filing:
    """One row of the filing trail."""

    form: str
    kind: FilingKind
    note: str
    filed: date
    # Acceptance is when EDGAR took it, not the filing date it is stamped
    # with — a 424B5 accepted at 16:05 is the one that matters, and only
    # this field can say so.
    accepted: int | None
    accession: str
    items: tuple[str, ...]
    url: str

    def to_dict(self) -> dict:
        return {
            "form": self.form,
            "kind": self.kind.value,
            "note": self.note,
            "filed": self.filed.isoformat(),
            "accepted": self.accepted,
            "accession": self.accession,
            "items": list(self.items),
            "url": self.url,
        }


def filing_url(cik: int, accession: str, primary_document: str) -> str:
    """Link to the document itself, or to the filing index without one."""
    stem = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{stem}"
    if primary_document:
        return f"{base}/{primary_document}"
    return f"{base}/{accession}-index.htm"
