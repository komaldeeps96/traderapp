"""What the watchlist can actually quote, against the live screener.

Marked `audit` and excluded from the default run: it leaves the machine.

It exists because reusing the screeners' universe filter here was wrong in a
way no unit test could have caught — every symbol still produced a row, and
every one of those rows was empty. The panel looked like it worked. Only
asking the real source about real symbols shows which of them answer.

The three classes below are the ones that were blank, each named with why:
a secondary US listing, a depositary receipt, and an ETF.
"""

from __future__ import annotations

import pytest

from app.services.watchlist import WatchlistService

pytestmark = pytest.mark.audit


class Stub:
    """The state store, reduced to the one thing the service reads."""

    def __init__(self, symbols: list[str]):
        self._symbols = symbols

    def watchlist(self) -> list[str]:
        return list(self._symbols)


# Symbol, and what it is a case of. A name here is a claim that this class of
# instrument is watchable, not that this particular company matters.
SUBJECTS = [
    ("AAPL", "US common stock, primary listing — the easy case"),
    ("CGC", "US listing whose primary listing is the TSX; is_primary is False"),
    ("BABA", "depositary receipt; TradingView types it `dr`, not `stock`"),
    ("TSM", "depositary receipt, and one of the largest companies listed"),
    ("SPY", "ETF; the client library's default filter excludes these outright"),
    ("QQQ", "ETF, and the one most likely to be on a US day trader's list"),
    ("GOOGL", "second share class; is_primary belongs to GOOG"),
    ("BRK.B", "second share class, and a symbol carrying a dot"),
    ("FGI", "nano cap — the tier this terminal was built for"),
    ("T", "large cap, NYSE"),
]


@pytest.fixture(scope="module")
def quoted() -> dict[str, dict]:
    """One request for every subject, exactly as the panel would make it."""
    import asyncio

    symbols = [symbol for symbol, _ in SUBJECTS]
    service = WatchlistService(Stub(symbols))
    rows = asyncio.run(service.rows())
    return {row["symbol"]: row for row in rows}


class TestEverySymbolIsQuoted:
    @pytest.mark.parametrize(("symbol", "why"), SUBJECTS, ids=[s for s, _ in SUBJECTS])
    def test_it_has_a_price(self, symbol, why, quoted):
        row = quoted[symbol]
        assert row["close"] is not None, f"{symbol} came back blank — {why}"
        assert row["close"] > 0
        assert row["name"], f"{symbol} has a price but no company name"

    def test_the_list_order_is_preserved(self, quoted):
        assert list(quoted) == [symbol for symbol, _ in SUBJECTS]


class TestWhatIsAllowedToBeMissing:
    def test_a_fund_may_report_no_market_cap(self, quoted):
        """An ETF has assets under management, not a market cap. A blank
        there is the source being right, and must not blank the row."""
        assert quoted["SPY"]["market_cap"] is None
        assert quoted["SPY"]["close"] is not None

    def test_a_fund_may_report_no_earnings_date(self, quoted):
        assert quoted["SPY"]["next_earnings"] is None

    def test_a_symbol_that_does_not_exist_still_gets_a_row(self):
        """It is on the list, and this panel is the only place to remove it."""
        import asyncio

        rows = asyncio.run(WatchlistService(Stub(["ZZZZ"])).rows())
        assert [row["symbol"] for row in rows] == ["ZZZZ"]
        assert rows[0]["close"] is None
