"""The companies the audit checks, and why each one is in the list.

Breadth is the point. A parser that works on Apple and nothing else is a
parser that works on one filing style, and the ways these differ — taxonomy,
currency, fiscal calendar, industry vocabulary — are exactly the ways it
breaks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Subject:
    symbol: str
    tier: str
    sector: str
    country: str
    # The currency the filings are in; the audit asserts we detect it.
    currency: str
    note: str
    # True where the SEC itself has no annual statements to compare against,
    # so an empty result is the correct one. Never set this to quieten a
    # failure — the audit still asserts the emptiness is real.
    no_annual_filings: bool = False


UNIVERSE: tuple[Subject, ...] = (
    # ── mega caps: the well-behaved case, and the baseline ──────────────
    Subject("AAPL", "mega", "technology", "US", "USD", "September year end"),
    Subject("MSFT", "mega", "technology", "US", "USD", "June year end"),
    Subject("NVDA", "mega", "semiconductors", "US", "USD", "January year end"),
    # ── large caps across sectors: different statement vocabularies ─────
    Subject("JPM", "large", "banking", "US", "USD", "no gross profit; 931 concepts"),
    # The ticker moved to a successor registrant in July 2026 —
    # "ExxonMobil Holdings Corp", CIK 2115436 — after a holding-company
    # reorganisation. It has filed one 10-Q and no annual report, and EDGAR
    # publishes no machine-readable link back to CIK 34088, where the history
    # lives. An empty statement is the honest answer until it files a 10-K.
    Subject(
        "XOM",
        "large",
        "energy",
        "US",
        "USD",
        "successor registrant; no annual filings yet",
        no_annual_filings=True,
    ),
    Subject("JNJ", "large", "healthcare", "US", "USD", ""),
    Subject("WMT", "large", "retail", "US", "USD", "January year end, calls it FY2026"),
    Subject("KO", "large", "beverages", "US", "USD", ""),
    Subject("T", "large", "telecom", "US", "USD", ""),
    Subject("BA", "large", "aerospace", "US", "USD", "sustained losses"),
    # ── mid and small: thinner filings, more gaps ───────────────────────
    Subject("CROX", "mid", "footwear", "US", "USD", ""),
    Subject("ELF", "mid", "cosmetics", "US", "USD", "March year end"),
    Subject("PANW", "mid", "software", "US", "USD", "July year end"),
    Subject("CELU", "small", "biotech", "US", "USD", "loss-making micro cap"),
    # ── foreign private issuers: the taxonomy and currency cases ────────
    Subject("SNDL", "small", "cannabis", "CA", "CAD", "40-F, IFRS, reports in CAD"),
    Subject("CGC", "small", "cannabis", "CA", "CAD", "switched IFRS to US GAAP"),
    Subject("TLRY", "small", "cannabis", "CA", "USD", "Canadian but files 10-K in USD"),
    Subject("BABA", "mega", "e-commerce", "CN", "CNY", "20-F, IFRS, March year end"),
    Subject("NVO", "mega", "pharma", "DK", "DKK", "20-F, IFRS, reports in kroner"),
    Subject("SHOP", "large", "software", "CA", "USD", "Canadian, files US GAAP"),
)

BY_SYMBOL = {subject.symbol: subject for subject in UNIVERSE}
