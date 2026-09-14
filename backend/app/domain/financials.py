"""Financial statements, built from EDGAR ``companyfacts``.

Three traps shape this module:

**``fy`` and ``fp`` describe the filing, not the fact.** A 10-K restates prior
years as comparatives, so Apple's FY2016 revenue carries ``fy: 2018``. A fact's
period is ``start``–``end`` and nothing else.

**Cumulative facts share the shape of quarterly ones.** A 10-Q reports the
quarter *and* the year to date, so one concept carries 3-, 6-, 9- and 12-month
durations in a single list. Only the duration in days separates them.

**Concepts fragment mid-history.** ASC 606 stopped Apple's ``Revenues`` in 2018
and continued it under ``RevenueFromContractWithCustomerExcludingAssessedTax``,
so the chains below are merged period by period, earlier entries winning.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from ..core.clock import parse_iso_date
from .companyfacts import concept_units
from .financial_lines import (
    BALANCE_SHEET,
    CASH_FLOW,
    INCOME_STATEMENT,
    MONEY,
    PER_SHARE,
    SHARES,
    STATEMENTS,
    Chain,
)

# A duration this long is a year, this short is a quarter, and anything
# between the two is a year-to-date cumulative that must not enter a series.
ANNUAL_DAYS = (340, 400)
QUARTER_DAYS = (80, 100)

# Fiscal calendars are counted in weeks, so a "quarter to end-April" can close
# on 3 May and a fiscal year on 27 September. Reading the month off the end
# date directly puts those in the wrong quarter, so it is read a fortnight
# earlier, which lands every drifting close back inside its own month.
_MONTH_ANCHOR = timedelta(days=15)


USD_CODE = "USD"

# Currencies whose symbol is a dollar sign. The statement header states the
# ISO code, so this only decides what the cells are prefixed with.
_DOLLARS = frozenset({"USD", "CAD", "AUD", "NZD", "HKD", "SGD"})

# Concepts probed to find out what a company reports in. Cheap and reliable:
# every filer states its total assets.
_CURRENCY_PROBES: Chain = (
    ("us-gaap", "Assets"),
    ("ifrs-full", "Assets"),
    ("us-gaap", "Revenues"),
    ("ifrs-full", "Revenue"),
)


def reporting_currency(facts: dict | None) -> str:
    """The currency a company states its statements in.

    Read rather than assumed: dividing a USD market cap by CAD earnings gives a
    P/E wrong by the exchange rate that looks entirely reasonable.
    """
    tally: dict[str, int] = {}
    for taxonomy, concept in _CURRENCY_PROBES:
        for unit, entries in concept_units(facts, taxonomy, concept).items():
            if len(unit) == 3 and unit.isalpha() and unit.isupper():
                tally[unit] = tally.get(unit, 0) + len(entries or ())
    if not tally:
        return "USD"
    # USD wins a tie: a filer reporting in both is reporting to US investors.
    return max(tally, key=lambda unit: (tally[unit], unit == "USD"))


def currency_symbol(currency: str) -> str:
    if currency in _DOLLARS:
        return "$"
    return {"EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "CHF": "CHF ", "ILS": "\u20aa"}.get(
        currency, f"{currency} "
    )


def unit_key(kind: str, currency: str) -> str:
    """The `units` key in companyfacts for one kind of line."""
    if kind == PER_SHARE:
        return f"{currency}/shares"
    if kind == SHARES:
        return "shares"
    return currency


@dataclass(frozen=True, slots=True)
class Fact:
    """One reported number, reduced to the period it actually covers."""

    end: date
    start: date | None
    value: float
    form: str
    filed: date | None

    @property
    def days(self) -> int | None:
        return (self.end - self.start).days if self.start else None


def _facts_for(facts: dict | None, taxonomy: str, concept: str, unit: str) -> list[Fact]:
    """Every fact reported for one concept, in one unit.

    The unit is named rather than merged: EPS is quoted in USD/shares and share
    counts in shares, so merging mixes 0.97 with 15 billion in one line.
    """
    entries = concept_units(facts, taxonomy, concept).get(unit)
    if not isinstance(entries, list):
        return []

    out: list[Fact] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        end = parse_iso_date(entry.get("end"))
        value = entry.get("val")
        if end is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        out.append(
            Fact(
                end=end,
                start=parse_iso_date(entry.get("start")),
                value=float(value),
                form=str(entry.get("form") or ""),
                filed=parse_iso_date(entry.get("filed")),
            )
        )
    return out


def _covers(fact: Fact, instant: bool, annual: bool) -> bool:
    """Whether a fact is the period this series is built from.

    An instant series wants facts with no ``start``. A duration series wants
    only the exact span asked for — hence a range test rather than "has a
    start", since a 10-Q also carries year-to-date cumulatives.
    """
    if instant:
        return fact.start is None
    if fact.days is None:
        return False
    low, high = ANNUAL_DAYS if annual else QUARTER_DAYS
    return low <= fact.days <= high


def _anchor_date(end: date) -> date:
    return end - _MONTH_ANCHOR


def _anchor_month(end: date) -> int:
    return _anchor_date(end).month


def fiscal_year_of(end: date) -> int:
    """The year a fiscal year *ending* on ``end`` is named for.

    The calendar year it closes in — a convention, not a fact. Companies with a
    January year-end disagree with each other, and the ``fy`` field is the
    filing's own focus and contradicts itself. So the label is a convention and
    the *end date* is the fact; every period carries its end alongside it.
    """
    # The anchored date, not the raw one. A 52/53-week filer can close its year
    # on 3 January, and `end.year` would call that the next year, putting two
    # identically-labelled columns in the table.
    return _anchor_date(end).year


def _period_key(end: date, annual: bool, year_end_month: int | None) -> str:
    if annual:
        return f"FY{fiscal_year_of(end)}"
    if year_end_month is None:
        return end.isoformat()

    anchor = _anchor_date(end)
    month = anchor.month
    # A quarter belongs to the fiscal year closing *after* it. Day 28 so the
    # fortnight anchor cannot push this sentinel into the previous month, and so
    # into the previous fiscal year label. The anchored year, as fiscal_year_of
    # uses: a quarter closing 3 January belongs to the year just ended.
    year = anchor.year if month <= year_end_month else anchor.year + 1
    year_end = date(year, year_end_month, 28)
    # Counted forward from the month the fiscal year closes, so Apple's
    # December quarter is Q1 — the company's own numbering, not the calendar's.
    quarter = ((month - year_end_month - 1) % 12) // 3 + 1
    return f"FY{fiscal_year_of(year_end)} Q{quarter}"


def _pick(facts: list[Fact], instant: bool, annual: bool) -> dict[date, Fact]:
    """One fact per period end, preferring the most recently filed.

    Every later filing repeats the quarter as a comparative, restated where the
    company revised it. The newest statement of a period is the one to believe.
    """
    best: dict[date, Fact] = {}
    for fact in facts:
        if not _covers(fact, instant, annual):
            continue
        held = best.get(fact.end)
        if held is None or (fact.filed or date.min) > (held.filed or date.min):
            best[fact.end] = fact
    return best


def _derive_quarters(facts: list[Fact]) -> dict[date, Fact]:
    """The quarters a company never reported on their own.

    Two holes come from how the forms work. A 10-Q states cash flow year *to
    date*, so a three-month cash flow fact often does not exist; and no 10-Q is
    filed for Q4, which the 10-K covers.

    Both fall out of one arithmetic: within a fiscal year the cumulatives share
    a ``start``, so consecutive differences are the quarters and the year minus
    nine months is the fourth.
    """
    by_start: dict[date, dict[date, Fact]] = {}
    for fact in facts:
        if fact.start is None or fact.days is None or fact.days < QUARTER_DAYS[0]:
            continue
        held = by_start.setdefault(fact.start, {}).get(fact.end)
        if held is None or (fact.filed or date.min) > (held.filed or date.min):
            by_start[fact.start][fact.end] = fact

    out: dict[date, Fact] = {}
    for group in by_start.values():
        previous: Fact | None = None
        for end in sorted(group):
            fact = group[end]
            if previous is None:
                if QUARTER_DAYS[0] <= (fact.days or 0) <= QUARTER_DAYS[1]:
                    out[end] = fact
            elif QUARTER_DAYS[0] <= (end - previous.end).days <= QUARTER_DAYS[1]:
                out[end] = replace(fact, value=fact.value - previous.value, start=previous.end)
            previous = fact
    return out


def _derive_total_liabilities(lines: list[dict]) -> None:
    """Fill a total-liabilities line the filer never tagged.

    Some filers report the components and `LiabilitiesAndStockholdersEquity`
    but not the `Liabilities` subtotal. The sheet still states the number, as
    the remainder once everything with a claim after creditors is removed.

    Only filled where genuinely absent, and the arithmetic is named in the
    line's concepts so a derived figure is never passed off as a tag.
    """
    by_key = {line["key"]: line for line in lines}
    target = by_key.get("total_liabilities")
    assets = by_key.get("total_assets")
    equity = by_key.get("equity")
    if assets is None or equity is None:
        return

    # Gap-filling, not all-or-nothing: a filer can tag `Liabilities` for early
    # years and stop, leaving the line present but empty where it matters.
    # Whether minority interests are already inside the equity figure depends on
    # which concept answered; subtracting them again understates liabilities by
    # exactly that amount.
    equity_includes_minorities = bool(
        set(equity["concepts"])
        & {
            "Equity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        }
    )
    subtract = (
        ["temporary_equity"]
        if equity_includes_minorities
        else [
            "noncontrolling_interest",
            "temporary_equity",
        ]
    )

    derived: dict[date, Fact] = {}
    existing = target["_values"] if target is not None else {}
    for end, asset_fact in assets["_values"].items():
        if end in existing:
            continue
        equity_fact = equity["_values"].get(end)
        if equity_fact is None:
            continue
        residual = asset_fact.value - equity_fact.value
        for key in subtract:
            other = by_key.get(key)
            found = other["_values"].get(end) if other else None
            if found is not None:
                residual -= found.value
        derived[end] = replace(asset_fact, value=residual)

    if not derived:
        return
    if target is None:
        spec = next(s for s in BALANCE_SHEET if s.key == "total_liabilities")
        target = {
            "statement": "balance",
            "instant": True,
            "kind": spec.unit,
            "key": spec.key,
            "label": spec.label,
            "unit": assets.get("unit", spec.unit),
            "concepts": [],
            "_values": {},
        }
        lines.append(target)
    target["_values"] = {**existing, **derived}
    target["concepts"] = [
        *target["concepts"],
        "derived: assets less equity and minority interests",
    ]


# Flows whose annual filings date the fiscal year. Revenue first; a filer with
# none, such as a pre-revenue biotech, still reports its loss and its burn.
_YEAR_END_LINES = ("revenue", "net_income", "operating_cash_flow")


def _year_end_month(facts: dict | None, currency: str) -> int | None:
    """The month the fiscal year closes, read off the annual filings."""
    specs = {spec.key: spec for spec in (*INCOME_STATEMENT, *CASH_FLOW)}
    concepts = [concept for key in _YEAR_END_LINES for concept in specs[key].concepts]
    for taxonomy, concept in concepts:
        rows = _facts_for(facts, taxonomy, concept, unit_key(MONEY, currency))
        annual = _pick(rows, instant=False, annual=True)
        if annual:
            return _anchor_month(max(annual))
    return None


def build_statements(facts: dict | None, annual: bool, limit: int = 8) -> dict:
    """Every statement line, over the most recent ``limit`` periods.

    Chains are merged period by period rather than resolved to one concept: a
    company that changed concepts mid-history reports each half under a
    different name, so picking one name returns half a series.
    """
    currency = reporting_currency(facts)
    year_end_month = None if annual else _year_end_month(facts, currency)

    lines: list[dict] = []
    ends: set[date] = set()
    for statement_key, statement_label, specs in STATEMENTS:
        for spec in specs:
            merged: dict[date, Fact] = {}
            used: list[str] = []
            for taxonomy, concept in spec.concepts:
                reported = _facts_for(facts, taxonomy, concept, unit_key(spec.unit, currency))
                found = _pick(reported, instant=spec.instant, annual=annual)
                if not annual and not spec.instant and spec.additive:
                    # What the company stated wins; the arithmetic only fills
                    # the quarters no form ever carried.
                    found = {**_derive_quarters(reported), **found}
                if not found:
                    continue
                if merged and not spec.merge_chain:
                    # One definition for the whole row, not the best-covered
                    # patchwork of several.
                    continue
                # Earlier in the chain wins: the first name is the one the
                # company reports today, and a later name only fills the
                # stretch of history the first one does not reach.
                new = {end: fact for end, fact in found.items() if end not in merged}
                if new:
                    merged.update(new)
                    used.append(concept)
            if not merged:
                continue
            # Only durations set the axis. A balance sheet is filed at every
            # quarter end, so letting instants in would put three extra
            # columns between one annual close and the next, each holding a
            # balance and nothing else.
            if not spec.instant:
                ends.update(merged)
            lines.append(
                {
                    "statement": statement_key,
                    "instant": spec.instant,
                    "kind": spec.unit,
                    "statement_label": statement_label,
                    "key": spec.key,
                    "label": spec.label,
                    "unit": unit_key(spec.unit, currency),
                    "concepts": used,
                    "_values": merged,
                }
            )

    _derive_total_liabilities(lines)

    periods = sorted(ends, reverse=True)[:limit]
    keys = [_period_key(end, annual, year_end_month) for end in periods]
    # The window each period covers, taken from whichever duration fact set
    # the axis. Conversion needs it: a flow goes at the average rate across
    # the period, and the average needs both ends.
    starts = {
        end: fact.start
        for line in lines
        if not line["instant"]
        for end, fact in line["_values"].items()
        if fact.start is not None
    }

    return {
        # Stated rather than assumed: a foreign private issuer reports in its
        # own currency, and a figure with no currency beside it is a number
        # that cannot be compared to anything.
        "currency": currency,
        "symbol_prefix": currency_symbol(currency),
        "periods": [
            {
                "key": key,
                "end": end.isoformat(),
                "start": starts[end].isoformat() if starts.get(end) else None,
                "fiscal_year": fiscal_year_of(end),
            }
            for key, end in zip(keys, periods, strict=True)
        ],
        "statements": [
            {
                "key": statement_key,
                "label": statement_label,
                "lines": [
                    {
                        "key": line["key"],
                        "label": line["label"],
                        "unit": line["unit"],
                        "kind": line["kind"],
                        "instant": line["instant"],
                        "concepts": line["concepts"],
                        "values": [
                            (
                                round(fact.value, 4)
                                if (fact := line["_values"].get(end)) is not None
                                else None
                            )
                            for end in periods
                        ],
                    }
                    for line in lines
                    if line["statement"] == statement_key
                ],
            }
            for statement_key, statement_label, _ in STATEMENTS
            if any(line["statement"] == statement_key for line in lines)
        ],
    }


async def convert_to_usd(built: dict, fx) -> dict:
    """Restate a statement set in dollars.

    Separate from `build_statements`, and async, because it reaches the network:
    the builder stays pure and this is the only part that can fail.

    Each period converts at its own rate, not today's — a single current rate
    would push this year's exchange move back through ten years of history and
    call it growth. Two rates per period, since IAS 21 puts flows at the average
    across the period and balances at the closing rate on the sheet date.

    A period whose rate cannot be fetched is blanked and named in
    ``unconverted_periods`` rather than mixed into a dollar column. With no rate
    for any period (a currency the source does not carry), the table stays in
    the filer's own currency.
    """
    native = built.get("currency", USD_CODE)
    if native == USD_CODE:
        built["native_currency"] = USD_CODE
        built["converted"] = False
        return built

    closing: dict[str, float | None] = {}
    average: dict[str, float | None] = {}
    for period in built.get("periods", []):
        end = parse_iso_date(period.get("end"))
        start = parse_iso_date(period.get("start"))
        if end is None:
            continue
        closing[period["key"]] = await fx.closing_rate(native, end)
        average[period["key"]] = (
            await fx.average_rate(native, start, end)
            if start is not None
            else closing[period["key"]]
        )
        period["fx_closing"] = closing[period["key"]]
        period["fx_average"] = average[period["key"]]

    keys = [period["key"] for period in built.get("periods", [])]
    unconverted = [key for key in keys if closing.get(key) is None or average.get(key) is None]
    if keys and len(unconverted) == len(keys):
        built["native_currency"] = native
        built["converted"] = False
        built["unconverted_periods"] = unconverted
        return built

    for statement in built.get("statements", []):
        for line in statement.get("lines", []):
            if line.get("kind") == SHARES:
                continue
            rates = closing if line.get("instant") else average
            line["values"] = [
                None if value is None or rates.get(key) is None else round(value * rates[key], 4)
                for key, value in zip(keys, line["values"], strict=True)
            ]
            line["unit"] = unit_key(line.get("kind", MONEY), USD_CODE)

    built["native_currency"] = native
    built["currency"] = USD_CODE
    built["symbol_prefix"] = currency_symbol(USD_CODE)
    built["converted"] = True
    # Named rather than counted: a column silently missing from a converted
    # table is the one thing worse than an unconverted one.
    built["unconverted_periods"] = unconverted
    return built


# A search returns rows, not a statement, and a company can report nine
# hundred concepts. This is what one screenful of them costs.
MAX_CONCEPT_ROWS = 60


def _humanise(concept: str) -> str:
    """`RetainedEarningsAccumulatedDeficit` -> `Retained earnings accumulated deficit`."""
    words: list[str] = []
    current = ""
    for character in concept:
        if character.isupper() and current and not current.isupper():
            words.append(current)
            current = character
        else:
            current += character
    if current:
        words.append(current)
    joined = " ".join(words).replace("  ", " ").strip()
    return joined[:1].upper() + joined[1:].lower() if joined else concept


def search_concepts(
    facts: dict | None,
    annual: bool,
    query: str,
    limit: int = 8,
    max_rows: int = MAX_CONCEPT_ROWS,
) -> dict:
    """Every concept a company reports, not just the ones drawn on a statement.

    A curated statement is roughly a tenth of what a filer tags (Apple 503
    concepts, JP Morgan 931); the rest is where a specific question is answered.

    The period axis is the statement's own, not one derived from whatever
    matched: search results include instants filed at every quarter end, which
    would set duplicate columns. It also puts a number found here in the same
    column as the statement line above it.

    Ranked by how much history each concept has.
    """
    currency = reporting_currency(facts)
    needle = query.strip().lower()
    empty = {"currency": currency, "query": query, "total": 0, "periods": [], "rows": []}
    if not isinstance(facts, dict) or not needle:
        return empty

    statements = build_statements(facts, annual=annual, limit=limit)
    periods = statements["periods"]
    if not periods:
        return empty
    ends = [date.fromisoformat(period["end"]) for period in periods]

    matches: list[dict] = []
    for taxonomy, concepts in (facts.get("facts") or {}).items():
        if not isinstance(concepts, dict):
            continue
        for concept, node in concepts.items():
            if needle not in concept.lower():
                continue
            for unit in (node or {}).get("units") or {}:
                rows = _facts_for(facts, taxonomy, concept, unit)
                # A concept is an instant or a duration, never both; the facts
                # say which, and the answer decides how it is picked.
                instant = all(row.start is None for row in rows) if rows else False
                found = _pick(rows, instant=instant, annual=annual)
                hits = sum(1 for end in ends if end in found)
                if not hits:
                    continue
                matches.append(
                    {
                        "key": f"{taxonomy}:{concept}:{unit}",
                        "label": _humanise(concept),
                        "concept": concept,
                        "taxonomy": taxonomy,
                        "unit": unit,
                        "hits": hits,
                        "values": [
                            round(found[end].value, 4) if end in found else None for end in ends
                        ],
                    }
                )

    # Most-populated first: a row with a value in every column is the one
    # worth reading, and a search for "tax" returns a hundred and twenty.
    matches.sort(key=lambda row: (-row["hits"], row["concept"]))

    return {
        "currency": currency,
        "query": query,
        "total": len(matches),
        "periods": periods,
        "rows": [
            {key: row[key] for key in ("key", "label", "concept", "taxonomy", "unit", "values")}
            for row in matches[:max_rows]
        ],
    }
