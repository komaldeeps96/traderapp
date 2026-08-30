"""How much stock can hit the tape, how soon, and does the company need money.

This is what "fundamentals" means for a sub-$300M name held for minutes. A
P/E ratio never stopped a trade; a shelf takedown priced at a discount into
the spike you are long has stopped plenty. Everything computed here answers
one of three questions:

    SUPPLY      warrants, preferred, converts and unissued authorised shares
                — the stock that exists but is not yet on the tape
    NEED        cash against burn — how long before they must sell
    HABIT       the offering trail and the share count over a year — whether
                they have done it before, because they will do it again

Two rules govern the maths.

Every figure carries the date it was reported for. XBRL is quarterly and
arrives late; a company delinquent on its 10-Q may have its most recent cash
figure be three quarters old, and *that is itself the signal*. A number
rendered without its as-of date is a lie with a timestamp missing, so
``Dated`` is the only way a value leaves this module.

Nothing is assumed that is not reported. Preferred stock is counted and shown
but deliberately excluded from the fully-diluted share count: conversion
ratios are set per series in the charter and are not in the XBRL facts, so
folding it in at 1:1 would invent a number. The honest fully-diluted figure
is common plus warrants, with preferred and converts reported beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum

from ..domain.filings import OFFERING_FORMS, OFFERING_ITEMS, Filing

# Form S-3 General Instruction I.B.6 — the "baby shelf" rule. Below this
# public float a company may sell no more than a third of that float in any
# rolling twelve months. It is the hardest bound on how much a small cap can
# dilute you, and one XBRL field computes it.
BABY_SHELF_FLOAT = 75_000_000.0
BABY_SHELF_FRACTION = 1.0 / 3.0

# ...but the float in that XBRL field is measured once a year, on the cover of
# the 10-K. The rule re-measures on the *date of every sale*, against a share
# price taken from a 60-day look-back — and the guidance points at the highest
# price in that window rather than the last one.
#
# Which turns the cap inside out. A stock that triples has just tripled the
# dollars its issuer may sell, and if the run carries float through $75M the
# cap stops applying at all until the next measurement date. The spike is not
# merely an opportunity to dilute into; it is the legal precondition for
# diluting at that size. A read that prices the cap off last year's cover page
# understates it on exactly the names where it matters.
SHELF_LOOKBACK_DAYS = 60

# The two halves of that story, as the verdict tells it. Which one stands is
# decided by the tape, in ``DilutionRead.with_live_shelf``.
BABY_SHELF_REASON = "baby shelf limits apply"
UNCAPPED_REASON = "the run has carried float past $75M — the baby-shelf cap no longer applies"

# Windows, in days, for picking a reported flow out of the fact history.
_ANNUAL_MIN_DAYS = 330
_ANNUAL_MAX_DAYS = 400
# Shorter than a quarter is a stub period and annualises into nonsense.
_MIN_FLOW_DAYS = 80

_YEAR_DAYS = 365

# 8-K item 3.01 — "notice of failure to satisfy a continued listing rule". The
# only unambiguous, company-level delisting signal in the submissions index:
# Form 25 says *a class of securities* is being removed, which for an issuer
# with listed debt is routinely a matured note rather than its common stock.
LISTING_DEFICIENCY_ITEM = "3.01"

# Thresholds. Chosen for small caps, where a 10% warrant overhang is ordinary
# and a 25% one is the trade.
_OVERHANG_WATCH = 0.10
_OVERHANG_HEAVY = 0.25
_RUNWAY_URGENT_MONTHS = 6.0
_RUNWAY_SHORT_MONTHS = 12.0
_RUNWAY_WATCH_MONTHS = 18.0
_GROWTH_HEAVY = 0.25
_GROWTH_SERIAL = 0.20


class DilutionTone(str, Enum):
    """The verdict, in the idiom the frontend already uses for spread,
    pullback and borrow: a word beside the numbers, never instead of them."""

    CLEAN = "clean"
    WATCH = "watch"
    HEAVY = "heavy"
    SERIAL = "serial"


@dataclass(frozen=True)
class Dated:
    """A reported value and the period end it was reported for."""

    value: float
    as_of: date
    form: str

    def stale_days(self, today: date | None = None) -> int:
        return ((today or _today()) - self.as_of).days

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "as_of": self.as_of.isoformat(),
            "form": self.form,
            "stale_days": self.stale_days(),
        }


@dataclass(frozen=True)
class DilutionRead:
    # ── supply ─────────────────────────────────────────────────────────
    shares_outstanding: Dated | None
    shares_issued: Dated | None
    shares_authorized: Dated | None
    warrants: Dated | None
    warrant_strike: Dated | None
    preferred: Dated | None
    convertible_notes: Dated | None
    # ── need ───────────────────────────────────────────────────────────
    cash: Dated | None
    annual_operating_cash_flow: Dated | None
    public_float: Dated | None
    # ── derived ────────────────────────────────────────────────────────
    warrant_overhang: float | None
    fully_diluted: float | None
    fully_diluted_ratio: float | None
    authorized_headroom: float | None
    runway_months: float | None
    baby_shelf: bool | None
    baby_shelf_capacity: float | None
    share_growth_12m: float | None
    offerings_12m: int
    delinquent: bool
    listing_deficiency: bool
    delisting_filed: bool
    tone: DilutionTone
    reasons: tuple[str, ...]
    # Priced off the tape rather than off the filings, so it is attached by
    # the caller that has the tape — see ``with_live_shelf``.
    live_shelf: ShelfCapacity | None = None

    def with_live_shelf(self, shelf: ShelfCapacity | None) -> DilutionRead:
        """The same read, carrying a shelf capacity priced off the tape.

        Kept off ``measure`` on purpose: everything that function returns is
        a property of the filings, and this one moves with the stock.

        One reason is rewritten here rather than in ``measure``, because only
        here is it knowable. The verdict is built from the last cover page,
        so on a name whose run has carried float through $75M it would go on
        asserting that the cap applies while the panel beside it says the cap
        is gone. Uncapped is the worse fact of the two, and it should read
        that way.
        """
        if shelf is None or shelf.capped:
            return replace(self, live_shelf=shelf)
        reasons = tuple(reason for reason in self.reasons if BABY_SHELF_REASON not in reason)
        return replace(self, live_shelf=shelf, reasons=(*reasons, UNCAPPED_REASON))

    def to_dict(self) -> dict:
        def dated(value: Dated | None) -> dict | None:
            return value.to_dict() if value is not None else None

        return {
            "shares_outstanding": dated(self.shares_outstanding),
            "shares_issued": dated(self.shares_issued),
            "shares_authorized": dated(self.shares_authorized),
            "warrants": dated(self.warrants),
            "warrant_strike": dated(self.warrant_strike),
            "preferred": dated(self.preferred),
            "convertible_notes": dated(self.convertible_notes),
            "cash": dated(self.cash),
            "annual_operating_cash_flow": dated(self.annual_operating_cash_flow),
            "public_float": dated(self.public_float),
            "warrant_overhang": self.warrant_overhang,
            "fully_diluted": self.fully_diluted,
            "fully_diluted_ratio": self.fully_diluted_ratio,
            "authorized_headroom": self.authorized_headroom,
            "runway_months": self.runway_months,
            "baby_shelf": self.baby_shelf,
            "baby_shelf_capacity": self.baby_shelf_capacity,
            "share_growth_12m": self.share_growth_12m,
            "offerings_12m": self.offerings_12m,
            "delinquent": self.delinquent,
            "listing_deficiency": self.listing_deficiency,
            "delisting_filed": self.delisting_filed,
            "tone": self.tone.value,
            "reasons": list(self.reasons),
            "live_shelf": self.live_shelf.to_dict() if self.live_shelf else None,
        }


# The XBRL concepts each read comes from, best source first. A small filer
# often reports only the second or third of these, so the list is a fallback
# chain rather than a choice.
_SHARES_OUTSTANDING = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
)
_SHARES_ISSUED = (("us-gaap", "CommonStockSharesIssued"),)
_SHARES_AUTHORIZED = (("us-gaap", "CommonStockSharesAuthorized"),)
_WARRANTS = (
    ("us-gaap", "ClassOfWarrantOrRightOutstanding"),
    ("us-gaap", "ClassOfWarrantOrRightNumberOfSecuritiesCalledByWarrantsOrRights"),
)
_WARRANT_STRIKE = (
    ("us-gaap", "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1"),
)
_PREFERRED = (("us-gaap", "PreferredStockSharesOutstanding"),)
_CONVERTIBLE = (
    ("us-gaap", "ConvertibleNotesPayable"),
    ("us-gaap", "ConvertibleNotesPayableCurrent"),
    ("us-gaap", "ConvertibleNotesPayableNoncurrent"),
)
_CASH = (
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
)
_OPERATING_CASH_FLOW = (
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
)
_PUBLIC_FLOAT = (("dei", "EntityPublicFloat"),)


@dataclass(frozen=True, slots=True)
class ShelfCapacity:
    """What an effective S-3 permits, measured at today's prices.

    Says nothing about whether a shelf exists — that is the filing trail's
    job. This is the ceiling *if* one does, which is the number that decides
    how much of a run can be sold into.
    """

    price: float
    """The 60-day high the measurement runs against."""
    public_float: float
    """Float shares at that price."""
    capped: bool
    """The one-third limit still binds."""
    capacity: float | None
    """Dollars sellable in a rolling twelve months; ``None`` once uncapped."""
    multiple: float | None
    """Live float over the float on the last cover page. ``None`` without one."""

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "public_float": self.public_float,
            "capped": self.capped,
            "capacity": self.capacity,
            "multiple": self.multiple,
        }


def shelf_capacity(
    float_shares: float | None,
    lookback_high: float | None,
    reported_float: float | None = None,
) -> ShelfCapacity | None:
    """Baby-shelf capacity at the price the rule would actually use.

    ``lookback_high`` is the highest price of the last ``SHELF_LOOKBACK_DAYS``
    calendar days; ``reported_float`` is the dollar figure off the last 10-K
    cover, for contrast. ``None`` whenever the float share count or the price
    is missing — a capacity computed from half its inputs is worse than none.
    """
    if not float_shares or not lookback_high or float_shares <= 0 or lookback_high <= 0:
        return None
    live = float_shares * lookback_high
    capped = live < BABY_SHELF_FLOAT
    return ShelfCapacity(
        price=lookback_high,
        public_float=live,
        capped=capped,
        capacity=live * BABY_SHELF_FRACTION if capped else None,
        multiple=(live / reported_float) if reported_float and reported_float > 0 else None,
    )


def measure(
    facts: dict | None,
    filings: list[Filing] | None = None,
    today: date | None = None,
) -> DilutionRead | None:
    """Read the dilution picture, or ``None`` with nothing to read it from.

    ``facts`` is EDGAR's raw ``companyfacts`` payload.

    Nothing here depends on the tape. Whether the warrants are in the money is
    the one read that does, and it belongs to the frontend: the strike is
    carried on the read, the price changes every tick, and recomputing this
    whole thing per tick to answer one comparison would be absurd.
    """
    filings = filings or []
    if not facts and not filings:
        return None
    today = today or _today()

    shares_outstanding = _latest_instant(facts, _SHARES_OUTSTANDING)
    shares_issued = _latest_instant(facts, _SHARES_ISSUED)
    shares_authorized = _latest_instant(facts, _SHARES_AUTHORIZED)
    warrants = _latest_instant(facts, _WARRANTS)
    warrant_strike = _latest_instant(facts, _WARRANT_STRIKE)
    preferred = _latest_instant(facts, _PREFERRED)
    convertible = _latest_instant(facts, _CONVERTIBLE)
    cash = _latest_instant(facts, _CASH)
    public_float = _latest_instant(facts, _PUBLIC_FLOAT)
    operating_flow = _annual_flow(facts, _OPERATING_CASH_FLOW)

    base_shares = shares_outstanding.value if shares_outstanding else None
    overhang = (
        warrants.value / base_shares
        if warrants and base_shares and base_shares > 0
        else None
    )
    fully_diluted = (
        base_shares + warrants.value if warrants and base_shares is not None else None
    )
    fully_diluted_ratio = (
        fully_diluted / base_shares if fully_diluted and base_shares else None
    )
    headroom = (
        shares_authorized.value - shares_issued.value
        if shares_authorized and shares_issued
        else None
    )
    runway = _runway_months(cash, operating_flow)
    on_baby_shelf = public_float.value < BABY_SHELF_FLOAT if public_float else None
    capacity = (
        public_float.value * BABY_SHELF_FRACTION
        if public_float and on_baby_shelf
        else None
    )
    growth = _share_growth(facts)
    offerings = _count_offerings(filings, today)
    delinquent = _has_form(filings, {"NT 10-Q", "NT 10-K", "NT 20-F"}, today)
    listing_deficiency = _has_item(filings, LISTING_DEFICIENCY_ITEM, today)
    delisting_filed = _has_form(filings, {"25", "25-NSE"}, today)

    tone, reasons = _verdict(
        overhang=overhang,
        runway=runway,
        growth=growth,
        offerings=offerings,
        on_baby_shelf=on_baby_shelf,
        delinquent=delinquent,
        listing_deficiency=listing_deficiency,
        delisting_filed=delisting_filed,
    )

    return DilutionRead(
        shares_outstanding=shares_outstanding,
        shares_issued=shares_issued,
        shares_authorized=shares_authorized,
        warrants=warrants,
        warrant_strike=warrant_strike,
        preferred=preferred,
        convertible_notes=convertible,
        cash=cash,
        annual_operating_cash_flow=operating_flow,
        public_float=public_float,
        warrant_overhang=overhang,
        fully_diluted=fully_diluted,
        fully_diluted_ratio=fully_diluted_ratio,
        authorized_headroom=headroom,
        runway_months=runway,
        baby_shelf=on_baby_shelf,
        baby_shelf_capacity=capacity,
        share_growth_12m=growth,
        offerings_12m=offerings,
        delinquent=delinquent,
        listing_deficiency=listing_deficiency,
        delisting_filed=delisting_filed,
        tone=tone,
        reasons=reasons,
    )


# ── fact selection ─────────────────────────────────────────────────────


def _facts_for(facts: dict | None, taxonomy: str, concept: str) -> list[dict]:
    if not isinstance(facts, dict):
        return []
    concepts = (facts.get("facts") or {}).get(taxonomy) or {}
    units = (concepts.get(concept) or {}).get("units") or {}
    rows: list[dict] = []
    for entries in units.values():
        if isinstance(entries, list):
            rows.extend(entry for entry in entries if isinstance(entry, dict))
    return rows


def _latest_instant(
    facts: dict | None, concepts: tuple[tuple[str, str], ...]
) -> Dated | None:
    """The most recently reported point value.

    Instant facts (a balance, a share count) carry an ``end`` and no
    ``start``. The same period is often restated by a later filing, so ties on
    ``end`` are broken by ``filed`` — the newer statement of the same quarter
    is the one to believe.
    """
    for taxonomy, concept in concepts:
        best: tuple[str, str, dict] | None = None
        for entry in _facts_for(facts, taxonomy, concept):
            if entry.get("start") is not None:
                continue
            end = entry.get("end")
            value = entry.get("val")
            if not isinstance(end, str) or not isinstance(value, (int, float)):
                continue
            key = (end, str(entry.get("filed") or ""))
            if best is None or key > (best[0], best[1]):
                best = (end, key[1], entry)
        if best is not None:
            parsed = _to_date(best[0])
            if parsed is not None:
                return Dated(
                    value=float(best[2]["val"]),
                    as_of=parsed,
                    form=str(best[2].get("form") or ""),
                )
    return None


def _annual_flow(
    facts: dict | None, concepts: tuple[tuple[str, str], ...]
) -> Dated | None:
    """A twelve-month flow, annualising a shorter one when that is all there is.

    Cash-flow facts are cumulative from the fiscal year start, so the year's
    figure appears as one ``start``-to-``end`` span rather than four quarters
    to be summed — summing the reported periods would count Q1 four times.
    A full-year span is preferred; failing that the longest year-to-date span
    is scaled up, which is an estimate and is only ever used for the runway.
    """
    for taxonomy, concept in concepts:
        spans: list[tuple[date, date, dict]] = []
        for entry in _facts_for(facts, taxonomy, concept):
            start = _to_date(entry.get("start"))
            end = _to_date(entry.get("end"))
            value = entry.get("val")
            if start is None or end is None or not isinstance(value, (int, float)):
                continue
            spans.append((start, end, entry))
        if not spans:
            continue

        annual = [
            span
            for span in spans
            if _ANNUAL_MIN_DAYS <= (span[1] - span[0]).days <= _ANNUAL_MAX_DAYS
        ]
        if annual:
            _, end, entry = max(annual, key=lambda span: (span[1], span[2].get("filed") or ""))
            return Dated(float(entry["val"]), end, str(entry.get("form") or ""))

        partial = [span for span in spans if (span[1] - span[0]).days >= _MIN_FLOW_DAYS]
        if partial:
            start, end, entry = max(
                partial, key=lambda span: (span[1], span[2].get("filed") or "")
            )
            days = (end - start).days
            scaled = float(entry["val"]) * _YEAR_DAYS / days
            return Dated(scaled, end, str(entry.get("form") or ""))
    return None


def _share_growth(facts: dict | None) -> float | None:
    """Change in the reported share count over the trailing year.

    The window ends at the newest report rather than at today, so this reads
    "growth over the year up to the last filing" — with a delinquent filer,
    anchoring on today would silently stretch the window to whatever the gap
    happens to be. A company public for less than a year has nothing to
    compare against and reports ``None`` rather than a rate off a stub.
    """
    points: list[tuple[date, float]] = []
    for taxonomy, concept in _SHARES_OUTSTANDING:
        for entry in _facts_for(facts, taxonomy, concept):
            if entry.get("start") is not None:
                continue
            end = _to_date(entry.get("end"))
            value = entry.get("val")
            if end is None or not isinstance(value, (int, float)) or value <= 0:
                continue
            points.append((end, float(value)))
        if points:
            break
    if len(points) < 2:
        return None

    points.sort()
    latest_date, latest = points[-1]
    cutoff = latest_date.replace(year=latest_date.year - 1)
    earlier = [point for point in points if point[0] <= cutoff]
    if not earlier:
        return None
    _, base = earlier[-1]
    if base <= 0:
        return None
    return (latest - base) / base


def _runway_months(cash: Dated | None, flow: Dated | None) -> float | None:
    """Months of cash at the reported burn.

    Only a negative operating flow is a burn; a cash-generative company has
    no runway problem and reports ``None`` rather than an infinity.
    """
    if cash is None or flow is None or flow.value >= 0 or cash.value <= 0:
        return None
    monthly = -flow.value / 12.0
    if monthly <= 0:
        return None
    return cash.value / monthly


def _count_offerings(filings: list[Filing], today: date) -> int:
    cutoff = today.replace(year=today.year - 1)
    return sum(
        1
        for filing in filings
        if filing.filed >= cutoff
        and (
            filing.form in OFFERING_FORMS
            or bool(OFFERING_ITEMS.intersection(filing.items))
        )
    )


def _has_form(filings: list[Filing], forms: set[str], today: date) -> bool:
    cutoff = today.replace(year=today.year - 1)
    return any(
        filing.form in forms and filing.filed >= cutoff for filing in filings
    )


def _has_item(filings: list[Filing], item: str, today: date) -> bool:
    cutoff = today.replace(year=today.year - 1)
    return any(item in filing.items and filing.filed >= cutoff for filing in filings)


# ── the verdict ────────────────────────────────────────────────────────


def _verdict(
    *,
    overhang: float | None,
    runway: float | None,
    growth: float | None,
    offerings: int,
    on_baby_shelf: bool | None,
    delinquent: bool,
    listing_deficiency: bool,
    delisting_filed: bool,
) -> tuple[DilutionTone, tuple[str, ...]]:
    """Tone plus the plain-language reasons behind it.

    The reasons are the point. A grade a trader has to trust is worth less
    than three facts they can check, so every tone above ``clean`` ships the
    sentences that produced it.
    """
    reasons = _reasons(
        overhang=overhang,
        runway=runway,
        growth=growth,
        offerings=offerings,
        on_baby_shelf=on_baby_shelf,
        delinquent=delinquent,
        listing_deficiency=listing_deficiency,
        delisting_filed=delisting_filed,
    )

    serial = (
        offerings >= 3
        or (offerings >= 2 and growth is not None and growth >= _GROWTH_SERIAL)
        or (offerings >= 1 and (listing_deficiency or delinquent))
    )
    heavy = (
        (overhang is not None and overhang >= _OVERHANG_HEAVY)
        or (runway is not None and runway < _RUNWAY_URGENT_MONTHS)
        or (growth is not None and growth >= _GROWTH_HEAVY)
        or (offerings >= 1 and runway is not None and runway < _RUNWAY_SHORT_MONTHS)
        or listing_deficiency
    )
    watch = bool(reasons)

    if serial:
        return DilutionTone.SERIAL, reasons
    if heavy:
        return DilutionTone.HEAVY, reasons
    if watch:
        return DilutionTone.WATCH, reasons
    return DilutionTone.CLEAN, ()


def _reasons(
    *,
    overhang: float | None,
    runway: float | None,
    growth: float | None,
    offerings: int,
    on_baby_shelf: bool | None,
    delinquent: bool,
    listing_deficiency: bool,
    delisting_filed: bool,
) -> tuple[str, ...]:
    """The sentences a trader can check, worst-supply-first."""
    reasons: list[str] = []
    if overhang is not None and overhang >= _OVERHANG_WATCH:
        reasons.append(f"warrants {overhang:.0%} of shares outstanding")
    if runway is not None and runway < _RUNWAY_WATCH_MONTHS:
        reasons.append(f"{runway:.1f} months of cash at current burn")
    if growth is not None and growth >= _GROWTH_SERIAL:
        reasons.append(f"share count up {growth:.0%} in a year")
    if offerings:
        reasons.append(f"{offerings} offering filing{'s' if offerings > 1 else ''} in 12 months")
    if on_baby_shelf:
        reasons.append(f"public float under $75M — {BABY_SHELF_REASON}")
    if delinquent:
        reasons.append("late on a periodic report")
    if listing_deficiency:
        reasons.append("notified of a listing rule failure")
    # A bare Form 25 is only mentioned once something else corroborates it.
    # On its own it is usually a matured note being removed — Apple files one
    # most years — and reporting that as a delisting risk would be wrong.
    if delisting_filed and (listing_deficiency or delinquent):
        reasons.append("a security class filed for delisting")
    return tuple(reasons)


# ── helpers ────────────────────────────────────────────────────────────


def _to_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _today() -> date:
    return datetime.now(UTC).date()
