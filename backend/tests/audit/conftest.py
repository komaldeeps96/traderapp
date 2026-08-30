"""Shared machinery for the audit: our numbers, and the auditors'.

Everything here reaches the network, which is why the whole directory sits
behind the `audit` marker and is excluded from `pytest tests` by default.

The two auditors are chosen for what they disagree about. **yfinance** reports
in the filer's own currency and names it, so it checks the parse itself —
whether we read the right concept, in the right period, before any conversion.
**TradingView** normalises to USD, so it checks the conversion. A number that
satisfies both has been read correctly and restated correctly, and those are
different claims.
"""

from __future__ import annotations

import asyncio
import json
import math
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("yfinance", reason="install the audit extra: pip install -e '.[audit]'")

import yfinance as yf

from app.providers.edgar import EdgarProvider
from app.services.financials import build_statements, convert_to_usd
from app.services.fx import FxService

warnings.filterwarnings("ignore")

USER_AGENT = "traderapp-audit/1.0 (komaldeeps96@gmail.com)"

# Fiscal period ends are reported to the day by the SEC and rounded to month
# end by others, so two dates within a fortnight are the same period.
PERIOD_TOLERANCE_DAYS = 20

# A restatement, a rounding convention or a slightly different concept choice
# moves a figure by a fraction of a percent. Anything past this is a bug.
NATIVE_TOLERANCE = 0.01
# Across a currency boundary the auditors' own FX conventions differ from
# ours, so the same figure is allowed more room.
CONVERTED_TOLERANCE = 0.04

_CACHE = Path(__file__).parent / ".cache"


def relative_difference(ours: float, theirs: float) -> float:
    if theirs == 0:
        return 0.0 if ours == 0 else 1.0
    return abs(ours - theirs) / abs(theirs)


@dataclass(frozen=True, slots=True)
class Reading:
    """One figure, from one source, for one period."""

    period_end: date
    value: float


def nearest(readings: dict[date, float], target: date) -> float | None:
    """The reading for the same fiscal period, matched by date proximity."""
    best: tuple[int, float] | None = None
    for when, value in readings.items():
        gap = abs((when - target).days)
        if gap <= PERIOD_TOLERANCE_DAYS and (best is None or gap < best[0]):
            best = (gap, value)
    return best[1] if best else None


@pytest.fixture(scope="session")
def edgar_facts():
    """`companyfacts` per symbol, fetched once and cached on disk.

    The audit is run deliberately and often twice in a row while a
    disagreement is chased down; re-downloading a megabyte of XBRL each time
    is rude to the SEC and slow for the person waiting.
    """
    _CACHE.mkdir(exist_ok=True)
    loaded: dict[str, dict | None] = {}

    def load(symbol: str) -> dict | None:
        if symbol in loaded:
            return loaded[symbol]
        cached = _CACHE / f"{symbol}.json"
        if cached.exists():
            loaded[symbol] = json.loads(cached.read_text())
            return loaded[symbol]

        async def fetch():
            provider = EdgarProvider(user_agent=USER_AGENT)
            try:
                await provider.prefetch(symbol)
                return provider.peek_facts(symbol)
            finally:
                await provider.close()

        facts = asyncio.run(fetch())
        if facts:
            cached.write_text(json.dumps(facts))
        loaded[symbol] = facts
        return facts

    return load


@pytest.fixture(scope="session")
def our_statements(edgar_facts):
    """What the terminal itself would show, native and converted."""
    built: dict[tuple[str, bool], dict] = {}

    def load(symbol: str, converted: bool = False) -> dict:
        key = (symbol, converted)
        if key not in built:
            native = build_statements(edgar_facts(symbol), annual=True, limit=6)
            if converted:

                async def run():
                    fx = FxService()
                    try:
                        return await convert_to_usd(
                            build_statements(edgar_facts(symbol), annual=True, limit=6), fx
                        )
                    finally:
                        await fx.close()

                built[key] = asyncio.run(run())
            else:
                built[key] = native
        return built[key]

    return load


@pytest.fixture(scope="session")
def yahoo():
    """yfinance's annual statements, keyed by period end, in native currency."""
    cache: dict[str, dict] = {}

    def load(symbol: str) -> dict:
        if symbol not in cache:
            ticker = yf.Ticker(symbol)
            frames = {}
            for name, frame in (
                ("income", ticker.income_stmt),
                ("balance", ticker.balance_sheet),
                ("cash", ticker.cashflow),
            ):
                rows: dict[str, dict[date, float]] = {}
                if frame is not None and not frame.empty:
                    for label in frame.index:
                        series: dict[date, float] = {}
                        for column in frame.columns:
                            value = frame.loc[label, column]
                            if isinstance(value, (int, float)) and math.isfinite(value):
                                series[column.date()] = float(value)
                        if series:
                            rows[str(label)] = series
                frames[name] = rows
            info = {}
            try:
                info = ticker.info or {}
            except Exception:
                info = {}
            cache[symbol] = {"frames": frames, "currency": info.get("financialCurrency")}
        return cache[symbol]

    return load


def our_line(statements: dict, key: str) -> dict[date, float]:
    """One of our lines, keyed by period end."""
    for statement in statements.get("statements", []):
        for line in statement["lines"]:
            if line["key"] == key:
                return {
                    date.fromisoformat(period["end"]): value
                    for period, value in zip(statements["periods"], line["values"], strict=True)
                    if value is not None
                }
    return {}


def their_line(yahoo_data: dict, frame: str, *labels: str) -> dict[date, float]:
    """The auditor's equivalent, taking whichever label it uses."""
    rows = yahoo_data["frames"].get(frame, {})
    for label in labels:
        if label in rows:
            return rows[label]
    return {}
