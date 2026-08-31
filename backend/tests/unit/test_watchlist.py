"""The watchlist.

A list of symbols with a price beside each. Almost all of the behaviour worth
testing is about the list itself — what happens to a duplicate, to a symbol
the screener does not recognise, and to the order — because a watchlist that
quietly loses or reorders a name is worse than no watchlist.
"""

from __future__ import annotations

import json

import pytest

from app.services.state import StateStore
from app.services.watchlist import COLUMNS, MAX_SYMBOLS, WatchlistService, _shape


def row(**overrides) -> list:
    """One TradingView row, in the column order the service selects."""
    values = {
        "name": "AAA",
        "description": "Alpha Inc.",
        "close": 10.0,
        "change": 2.5,
        "volume": 1_000_000.0,
        "relative_volume_10d_calc": 1.4,
        "market_cap_basic": 300_000_000.0,
        "premarket_change": 0.5,
        "earnings_release_next_date": None,
    }
    values.update(overrides)
    return [values[name] for name in COLUMNS]


async def _never(_query):
    raise AssertionError("the screener was called with quotes switched off")


def service(tmp_path, rows: list[list] | None = None, fail: bool = False):
    async def fetch(_query):
        if fail:
            raise RuntimeError("TradingView said no")
        return rows or []

    state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
    return WatchlistService(state, fetch=fetch)


class TestTheList:
    async def test_add_then_read_back(self, tmp_path):
        watchlist = service(tmp_path)
        assert await watchlist.add("AAPL") == ["AAPL"]
        assert watchlist.symbols() == ["AAPL"]

    async def test_symbols_are_upper_cased(self, tmp_path):
        watchlist = service(tmp_path)
        assert await watchlist.add(" tsla ") == ["TSLA"]

    async def test_adding_twice_does_not_duplicate(self, tmp_path):
        """Almost always a mis-click, and a list holding one name twice is
        worse than useless."""
        watchlist = service(tmp_path)
        await watchlist.add("AAPL")
        assert await watchlist.add("aapl") == ["AAPL"]

    async def test_order_is_the_order_things_were_added(self, tmp_path):
        watchlist = service(tmp_path)
        for symbol in ("ZM", "AAPL", "NVDA"):
            await watchlist.add(symbol)
        assert watchlist.symbols() == ["ZM", "AAPL", "NVDA"]

    async def test_remove_leaves_the_rest_in_order(self, tmp_path):
        watchlist = service(tmp_path)
        for symbol in ("ZM", "AAPL", "NVDA"):
            await watchlist.add(symbol)
        assert await watchlist.remove("AAPL") == ["ZM", "NVDA"]

    async def test_removing_something_absent_is_not_an_error(self, tmp_path):
        watchlist = service(tmp_path)
        await watchlist.add("AAPL")
        assert await watchlist.remove("TSLA") == ["AAPL"]

    async def test_blank_is_not_a_symbol(self, tmp_path):
        assert await service(tmp_path).add("   ") == []

    async def test_the_list_is_capped(self, tmp_path):
        watchlist = service(tmp_path)
        for index in range(MAX_SYMBOLS + 5):
            await watchlist.add(f"S{index}")
        assert len(watchlist.symbols()) == MAX_SYMBOLS

    async def test_it_survives_a_restart(self, tmp_path):
        await service(tmp_path).add("AAPL")
        assert service(tmp_path).symbols() == ["AAPL"]


class TestRows:
    async def test_empty_list_asks_nothing(self, tmp_path):
        calls = []

        async def fetch(query):
            calls.append(query)
            return []

        state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
        assert await WatchlistService(state, fetch=fetch).rows() == []
        assert calls == []

    async def test_a_row_carries_the_quote(self, tmp_path):
        watchlist = service(tmp_path, [row(name="AAA", close=12.5, change=3.0)])
        await watchlist.add("AAA")
        (entry,) = await watchlist.rows()
        assert entry["symbol"] == "AAA"
        assert entry["name"] == "Alpha Inc."
        assert (entry["close"], entry["change"]) == (12.5, 3.0)

    async def test_rows_follow_the_lists_order_not_the_screeners(self, tmp_path):
        """TradingView answers in its own order; the list's order is the
        user's, and it is the one on screen."""
        watchlist = service(tmp_path, [row(name="AAA"), row(name="BBB"), row(name="CCC")])
        for symbol in ("CCC", "AAA", "BBB"):
            await watchlist.add(symbol)
        assert [entry["symbol"] for entry in await watchlist.rows()] == ["CCC", "AAA", "BBB"]

    async def test_an_unknown_symbol_still_gets_a_row(self, tmp_path):
        """A delisted or mistyped ticker has to stay visible: it is still on
        the list, and dropping it silently leaves no way to remove it."""
        watchlist = service(tmp_path, [row(name="AAA")])
        await watchlist.add("AAA")
        await watchlist.add("ZZZZ")
        rows = await watchlist.rows()
        assert [entry["symbol"] for entry in rows] == ["AAA", "ZZZZ"]
        assert rows[1]["close"] is None

    async def test_a_nan_never_reaches_a_row(self, tmp_path):
        """Every screener cell arrives through pandas, and NaN is a float."""
        watchlist = service(tmp_path, [row(name="AAA", close=float("nan"))])
        await watchlist.add("AAA")
        (entry,) = await watchlist.rows()
        assert entry["close"] is None

    async def test_quotes_are_cached_between_reads(self, tmp_path):
        calls = []

        async def fetch(query):
            calls.append(query)
            return [row(name="AAA")]

        state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
        watchlist = WatchlistService(state, fetch=fetch)
        await watchlist.add("AAA")
        await watchlist.rows()
        await watchlist.rows()
        assert len(calls) == 1

    async def test_adding_a_symbol_invalidates_the_cache(self, tmp_path):
        """Otherwise the new name shows a blank row until the TTL expires."""
        calls = []

        async def fetch(query):
            calls.append(query)
            return [row(name="AAA"), row(name="BBB")]

        state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
        watchlist = WatchlistService(state, fetch=fetch)
        await watchlist.add("AAA")
        await watchlist.rows()
        await watchlist.add("BBB")
        rows = await watchlist.rows()
        assert len(calls) == 2
        assert rows[1]["close"] == 10.0


class TestWhenTradingViewIsDown:
    async def test_rows_still_appear_and_a_note_says_why(self, tmp_path):
        watchlist = service(tmp_path, fail=True)
        await watchlist.add("AAA")
        rows = await watchlist.rows()
        assert [entry["symbol"] for entry in rows] == ["AAA"]
        assert rows[0]["close"] is None
        assert watchlist.note is not None

    async def test_the_note_clears_once_it_answers_again(self, tmp_path):
        state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
        answers = [RuntimeError("down"), [row(name="AAA")]]

        async def fetch(_query):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        watchlist = WatchlistService(state, fetch=fetch)
        await watchlist.add("AAA")
        await watchlist.rows()
        assert watchlist.note is not None
        watchlist._quotes = None
        await watchlist.rows()
        assert watchlist.note is None


class TestTheUniverse:
    """What a watchlist is allowed to contain.

    The screeners keep to primary listings of US common stock, because they
    have to decide what deserves a place in a ranked list nobody asked for.
    A watchlist has no such question: somebody typed the symbol. Reusing the
    screener filter here blanked Canopy Growth (primary listing is the TSX),
    every ADR (Alibaba is typed `dr`) and every ETF.
    """

    @staticmethod
    def _body(symbols: list[str]) -> dict:
        from tradingview_screener import Query, col

        from app.services.watchlist import ANY_INSTRUMENT, COLUMNS, EXCHANGES

        query = (
            Query()
            .select(*COLUMNS)
            .where(col("exchange").isin(EXCHANGES), col("name").isin(symbols))
        )
        query.set_property("filter2", ANY_INSTRUMENT)
        return query.query

    def test_it_does_not_ask_for_a_primary_listing(self):
        assert "is_primary" not in json.dumps(self._body(["CGC"]))

    def test_it_admits_more_than_common_stock(self):
        kinds = {
            operand["expression"]["right"]
            for operand in self._body(["BABA"])["filter2"]["operands"]
        }
        assert kinds == {"stock", "dr", "fund"}

    def test_it_still_asks_only_for_us_listings(self):
        """The chart beside this panel can only draw a US listing."""
        assert "NASDAQ" in json.dumps(self._body(["AAPL"]))

    def test_a_fund_without_a_market_cap_is_still_a_row(self):
        """An ETF reports no market cap; that is not a reason to hide it."""
        shaped = _shape([row(name="SPY", market_cap_basic=float("nan"))])
        assert shaped["SPY"]["market_cap"] is None
        assert shaped["SPY"]["name"] == "Alpha Inc."


class TestWithTheScreenerSwitchedOff:
    """The list is the feature; the prices are what it can reach.

    A desk with no outbound access — or a test run, where nothing may leave
    the machine — still gets the names, their order and their persistence.
    """

    def _offline(self, tmp_path):
        state = StateStore(tmp_path / "state.yaml", "AAPL", "10s")
        return WatchlistService(state, fetch=_never, quotes_enabled=False)

    async def test_the_names_are_still_there(self, tmp_path):
        watchlist = self._offline(tmp_path)
        await watchlist.add("AAPL")
        await watchlist.add("TSLA")
        assert [entry["symbol"] for entry in await watchlist.rows()] == ["AAPL", "TSLA"]

    async def test_it_asks_nothing_of_the_network(self, tmp_path):
        watchlist = self._offline(tmp_path)
        await watchlist.add("AAPL")
        await watchlist.rows()  # `_never` raises if it is called

    async def test_the_empty_prices_are_explained(self, tmp_path):
        watchlist = self._offline(tmp_path)
        await watchlist.add("AAPL")
        rows = await watchlist.rows()
        assert rows[0]["close"] is None
        assert watchlist.note is not None


class TestShape:
    def test_a_row_without_a_symbol_is_dropped(self):
        assert _shape([row(name=None)]) == {}

    @pytest.mark.parametrize("value", [None, "", 3])
    def test_a_missing_description_becomes_empty_not_none(self, value):
        """It is rendered straight into a cell; None would read as "None"."""
        assert _shape([row(description=value)])["AAA"]["name"] == ""
