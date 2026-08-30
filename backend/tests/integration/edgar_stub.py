"""A stand-in for SEC EDGAR, shaped like the real documents.

The figures are Celularity's, taken from the live ``companyfacts`` and
``submissions`` documents during the research that produced this feature — a
company with a 25.8M warrant overhang against 28.9M shares, five months of
cash, and a filing trail full of offerings. Using real numbers means the
assertions read like the panel they are testing.
"""

from __future__ import annotations

import httpx

CIK = 1752828

TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": CIK, "ticker": "CELU", "title": "Celularity Inc"},
}

_FILINGS = [
    # form, filingDate, accession, primaryDocument, items, acceptanceDateTime
    ("NT 10-Q", "2026-08-14", "0001493152-26-038318", "nt.htm", "", "2026-08-14T16:05:12.000Z"),
    ("8-K", "2026-07-29", "0001493152-26-036000", "f8k.htm", "3.01", "2026-07-29T21:01:00.000Z"),
    ("25-NSE", "2026-07-22", "0001354457-26-000719", "", "", "2026-07-22T12:00:00.000Z"),
    ("424B3", "2026-01-08", "0001493152-26-000878", "p.htm", "", "2026-01-08T14:30:00.000Z"),
    ("S-1", "2025-12-31", "0001493152-25-029802", "s1.htm", "", "2025-12-31T15:00:00.000Z"),
    ("8-K", "2026-06-30", "0001493152-26-030000", "f8k.htm", "1.01", "2026-06-30T20:00:00.000Z"),
    ("10-K", "2026-04-30", "0001493152-26-020000", "10k.htm", "", "2026-04-30T21:00:00.000Z"),
    ("4", "2026-06-23", "0001493152-26-029000", "f4.xml", "", "2026-06-23T22:00:00.000Z"),
]

SUBMISSIONS = {
    "name": "Celularity Inc",
    "sic": "2834",
    "sicDescription": "Pharmaceutical Preparations",
    "exchanges": ["Nasdaq"],
    "website": "",
    "stateOfIncorporationDescription": "Delaware",
    "fiscalYearEnd": "1231",
    "filings": {
        "recent": {
            "form": [row[0] for row in _FILINGS],
            "filingDate": [row[1] for row in _FILINGS],
            "accessionNumber": [row[2] for row in _FILINGS],
            "primaryDocument": [row[3] for row in _FILINGS],
            "items": [row[4] for row in _FILINGS],
            "acceptanceDateTime": [row[5] for row in _FILINGS],
        }
    },
}


def _instant(end: str, val: float, form: str = "10-K", filed: str = "2026-04-30") -> dict:
    return {"end": end, "val": val, "form": form, "filed": filed}


def _span(start: str, end: str, val: float, form: str = "10-K", filed: str = "2026-04-30") -> dict:
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def _concept(taxonomy: str, name: str, unit: str, entries: list[dict]) -> tuple[str, str, dict]:
    return taxonomy, name, {"units": {unit: entries}}


_CONCEPTS = [
    _concept(
        "dei",
        "EntityCommonStockSharesOutstanding",
        "shares",
        [_instant("2025-04-06", 23_949_229), _instant("2026-04-28", 28_945_961)],
    ),
    _concept("us-gaap", "CommonStockSharesIssued", "shares", [_instant("2025-12-31", 28_837_787)]),
    _concept(
        "us-gaap", "CommonStockSharesAuthorized", "shares", [_instant("2025-12-31", 730_000_000)]
    ),
    _concept(
        "us-gaap",
        "ClassOfWarrantOrRightOutstanding",
        "shares",
        [_instant("2024-12-31", 11_221_557), _instant("2025-12-31", 25_774_577)],
    ),
    _concept(
        "us-gaap",
        "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1",
        "USD/shares",
        [_instant("2024-11-25", 3.0)],
    ),
    _concept(
        "us-gaap", "PreferredStockSharesOutstanding", "shares", [_instant("2025-12-31", 1_732_084)]
    ),
    _concept("us-gaap", "ConvertibleNotesPayable", "USD", [_instant("2025-12-31", 922_000)]),
    _concept(
        "us-gaap",
        "CashAndCashEquivalentsAtCarryingValue",
        "USD",
        [_instant("2025-12-31", 6_175_000)],
    ),
    _concept(
        "us-gaap",
        "NetCashProvidedByUsedInOperatingActivities",
        "USD",
        [_span("2025-01-01", "2025-12-31", -13_254_000)],
    ),
    _concept("dei", "EntityPublicFloat", "USD", [_instant("2025-06-30", 28_400_000)]),
    # Enough of an income statement and balance sheet for the financials
    # endpoint to have something to shape. Two years so a series is visible,
    # and the revenue concept changes name between them, which is the ASC 606
    # break every real filer of that vintage has.
    _concept(
        "us-gaap",
        "Revenues",
        "USD",
        [_span("2024-01-01", "2024-12-31", 48_100_000, filed="2025-03-20")],
    ),
    _concept(
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "USD",
        [_span("2025-01-01", "2025-12-31", 26_400_000)],
    ),
    _concept(
        "us-gaap",
        "NetIncomeLoss",
        "USD",
        [
            _span("2024-01-01", "2024-12-31", -32_700_000, filed="2025-03-20"),
            _span("2025-01-01", "2025-12-31", -21_500_000),
        ],
    ),
    _concept(
        "us-gaap",
        "Assets",
        "USD",
        [
            _instant("2024-12-31", 61_300_000, filed="2025-03-20"),
            _instant("2025-12-31", 42_800_000),
        ],
    ),
]


def _company_facts() -> dict:
    facts: dict = {}
    for taxonomy, name, body in _CONCEPTS:
        facts.setdefault(taxonomy, {})[name] = body
    return {"cik": CIK, "entityName": "Celularity Inc.", "facts": facts}


COMPANY_FACTS = _company_facts()


def edgar_transport(*, fail: bool = False) -> httpx.MockTransport:
    """Serve the three EDGAR documents; ``fail`` makes every one 503."""

    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503)
        url = str(request.url)
        if "company_tickers" in url:
            return httpx.Response(200, json=TICKERS)
        if "submissions" in url:
            return httpx.Response(200, json=SUBMISSIONS)
        if "companyfacts" in url:
            return httpx.Response(200, json=COMPANY_FACTS)
        return httpx.Response(404)

    return httpx.MockTransport(handler)
