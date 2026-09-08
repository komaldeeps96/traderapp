"""Time and sales: the aggressor inference, the ring buffer, and the wire.

The classification is the part worth testing hard. Nothing on either feed says
whether a print was a buy or a sell — every green row on this window is this
module's opinion, formed by comparing the print against the book that was
standing — so the boundaries between the five verdicts are the feature.
"""

from __future__ import annotations

import pytest

from app.domain.protocol import tape_message
from app.domain.quotes import Quote
from app.domain.tape import Aggressor, classify
from app.market.bar_builder import Trade
from app.services.quotes import QuoteService
from app.services.tape import TapeService


def book(bid: float = 2.50, ask: float = 2.52) -> Quote:
    return Quote(bid=bid, ask=ask, bid_size=500, ask_size=900, time=1_700_000_000.0)


async def service(bid: float = 2.50, ask: float = 2.52, **kwargs) -> TapeService:
    quotes = QuoteService()
    await quotes.handle_quote("RUN", book(bid, ask))
    return TapeService(quotes, **kwargs)


def trade(price: float, size: float = 100, **kwargs) -> Trade:
    return Trade(time=1_700_000_000.25, price=price, size=size, **kwargs)


class TestClassify:
    def test_at_the_ask_is_a_lift(self):
        assert classify(2.52, book()) is Aggressor.ASK

    def test_through_the_ask_is_a_sweep(self):
        assert classify(2.53, book()) is Aggressor.ABOVE_ASK

    def test_at_the_bid_is_a_hit(self):
        assert classify(2.50, book()) is Aggressor.BID

    def test_under_the_bid_is_a_sweep_the_other_way(self):
        assert classify(2.49, book()) is Aggressor.BELOW_BID

    def test_inside_the_spread_takes_neither_side(self):
        assert classify(2.51, book()) is Aggressor.MID

    def test_a_sub_penny_improvement_is_still_inside(self):
        """Price improvement lands a hair off the quote, not on it."""
        assert classify(2.5199, book()) is Aggressor.MID
        assert classify(2.5001, book()) is Aggressor.MID

    def test_one_tick_through_is_a_sweep_not_a_lift(self):
        """The tolerance absorbs float error and nothing wider.

        A band wide enough to call a penny through the offer "at the ask"
        would erase the distinction the two greens exist to draw.
        """
        assert classify(2.5201, book()) is Aggressor.ABOVE_ASK
        assert classify(2.4999, book()) is Aggressor.BELOW_BID

    def test_a_price_reconstructed_by_arithmetic_still_lands_on_the_quote(self):
        """0.1 + 0.2 is not 0.3, and a tape must not care."""
        assert classify(0.1 + 0.2, book(0.29, 0.3)) is Aggressor.ASK

    def test_no_quote_yet_means_no_verdict(self):
        assert classify(2.52, None) is Aggressor.UNKNOWN

    def test_a_crossed_book_means_no_verdict(self):
        crossed = Quote(bid=2.60, ask=2.50, bid_size=1, ask_size=1, time=0)
        assert classify(2.55, crossed) is Aggressor.UNKNOWN


class TestRecording:
    async def test_a_print_is_classified_against_the_standing_book(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.52))
        row = tape.recent("RUN")[0]
        assert row.side is Aggressor.ASK
        assert row.price == pytest.approx(2.52)
        assert row.size == 100

    async def test_the_book_that_counts_is_the_one_standing_at_the_time(self):
        """A quote update between two prints re-frames the second."""
        quotes = QuoteService()
        await quotes.handle_quote("RUN", book(2.50, 2.52))
        tape = TapeService(quotes)

        await tape.handle_trade("RUN", trade(2.52))
        await quotes.handle_quote("RUN", book(2.55, 2.57))
        await tape.handle_trade("RUN", trade(2.52))

        assert [row.side for row in tape.recent("RUN")] == [
            Aggressor.ASK,
            Aggressor.BELOW_BID,
        ]

    async def test_sequences_are_strictly_increasing_per_symbol(self):
        tape = await service()
        for _ in range(3):
            await tape.handle_trade("RUN", trade(2.51))
        assert [row.seq for row in tape.recent("RUN")] == [1, 2, 3]
        assert tape.revision("RUN") == 3

    async def test_symbols_keep_their_own_sequence(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51))
        await tape.handle_trade("AEMD", trade(2.51))
        assert tape.revision("RUN") == 1
        assert tape.revision("AEMD") == 1

    async def test_an_empty_print_is_not_a_row(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51, size=0))
        await tape.handle_trade("RUN", trade(0.0, size=100))
        assert tape.recent("RUN") == []

    async def test_a_late_report_stays_on_the_tape_and_is_marked(self):
        """It is real volume at a stale price: shown, flagged, filterable."""
        tape = await service()
        await tape.handle_trade("RUN", trade(2.20, price_forming=False, conditions=("Z",)))
        row = tape.recent("RUN")[0]
        assert row.price_forming is False
        assert row.conditions == ("Z",)

    async def test_the_venue_is_carried_through_untranslated(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51, exchange="D"))
        assert tape.recent("RUN")[0].exchange == "D"

    async def test_a_symbol_nobody_has_quoted_still_records(self):
        """The tape fills from the first print — there is no history to wait on."""
        tape = TapeService(QuoteService())
        await tape.handle_trade("RUN", trade(2.51))
        assert tape.recent("RUN")[0].side is Aggressor.UNKNOWN


class TestBounds:
    async def test_the_buffer_keeps_the_newest_rows(self):
        tape = await service(buffer=3)
        for price in (2.50, 2.51, 2.52, 2.53):
            await tape.handle_trade("RUN", trade(price))
        assert [row.seq for row in tape.recent("RUN")] == [2, 3, 4]

    async def test_the_oldest_symbol_is_evicted_first(self):
        tape = await service(max_symbols=2)
        await tape.handle_trade("AAA", trade(2.51))
        await tape.handle_trade("BBB", trade(2.51))
        await tape.handle_trade("CCC", trade(2.51))
        assert tape.recent("AAA") == []
        assert tape.recent("BBB") and tape.recent("CCC")

    async def test_printing_again_saves_a_symbol_from_eviction(self):
        tape = await service(max_symbols=2)
        await tape.handle_trade("AAA", trade(2.51))
        await tape.handle_trade("BBB", trade(2.51))
        await tape.handle_trade("AAA", trade(2.51))
        await tape.handle_trade("CCC", trade(2.51))
        assert tape.recent("BBB") == []
        assert tape.recent("AAA") and tape.recent("CCC")

    async def test_drop_forgets_the_symbol(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51))
        tape.drop("RUN")
        assert tape.recent("RUN") == []
        assert tape.revision("RUN") == 0


class TestSince:
    async def test_returns_only_what_is_new_oldest_first(self):
        tape = await service()
        for _ in range(5):
            await tape.handle_trade("RUN", trade(2.51))
        assert [row.seq for row in tape.since("RUN", 3)] == [4, 5]

    async def test_nothing_new_is_an_empty_list(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51))
        assert tape.since("RUN", 1) == []
        assert tape.since("UNKNOWN", 0) == []

    async def test_a_cursor_older_than_the_buffer_gets_what_survives(self):
        """Rows that scrolled off are gone; the client is not told twice."""
        tape = await service(buffer=2)
        for _ in range(5):
            await tape.handle_trade("RUN", trade(2.51))
        assert [row.seq for row in tape.since("RUN", 0)] == [4, 5]


class TestWireShape:
    async def test_a_batch_carries_the_short_keys(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.5199, size=250, exchange="Q"))
        message = tape_message("RUN", tape.recent("RUN"))

        assert message["type"] == "tape"
        assert message["symbol"] == "RUN"
        assert message["reset"] is False
        row = message["prints"][0]
        assert row["q"] == 1
        assert row["p"] == pytest.approx(2.5199)
        assert row["s"] == 250
        assert row["a"] == "mid"
        assert row["x"] == "Q"

    async def test_time_is_milliseconds(self):
        """Second resolution loses the ordering inside a burst."""
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51))
        assert tape_message("RUN", tape.recent("RUN"))["prints"][0]["t"] == 1_700_000_000_250

    async def test_the_quiet_fields_are_omitted_when_empty(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.51))
        row = tape_message("RUN", tape.recent("RUN"))["prints"][0]
        assert "x" not in row
        assert "c" not in row
        assert "f" not in row

    async def test_an_irregular_print_is_flagged(self):
        tape = await service()
        await tape.handle_trade("RUN", trade(2.20, price_forming=False, conditions=("W",)))
        row = tape_message("RUN", tape.recent("RUN"))["prints"][0]
        assert row["f"] == 0
        assert row["c"] == ["W"]

    async def test_reset_marks_a_replacement(self):
        assert tape_message("RUN", [], reset=True) == {
            "type": "tape",
            "symbol": "RUN",
            "reset": True,
            "prints": [],
        }


class FakeMarket:
    """Enough MarketDataService for the broadcaster's chart half to do nothing."""

    def revision(self, symbol: str) -> int:
        return 0

    def build_update(self, symbol: str, timeframe) -> None:
        return None

    def is_loaded(self, symbol: str) -> bool:
        return False


class FakeHub:
    def __init__(self, pairs):
        self._pairs = pairs
        self.sent: list[tuple[str, dict]] = []

    def pairs(self):
        return self._pairs

    def send_to_pair(self, symbol, timeframe, message):  # pragma: no cover - unused
        self.sent.append((symbol, message))

    def send_to_symbol(self, symbol, message):
        self.sent.append((symbol, message))

    def broadcast(self, message):  # pragma: no cover - unused
        pass


class TestBroadcast:
    """Coalescing, the shared cursor, and the overlap it deliberately allows."""

    @staticmethod
    def _make(tape: TapeService):
        from app.domain.timeframes import Timeframe
        from app.services.broadcaster import ChartBroadcaster

        hub = FakeHub({("RUN", Timeframe.S10)})
        return hub, ChartBroadcaster(hub, FakeMarket(), tape=tape)

    def _tapes(self, hub) -> list[dict]:
        return [message for _, message in hub.sent if message["type"] == "tape"]

    async def test_a_tick_carries_every_print_since_the_last_one(self):
        tape = await service()
        hub, broadcaster = self._make(tape)
        for _ in range(3):
            await tape.handle_trade("RUN", trade(2.51))

        broadcaster.tick()
        assert [row["q"] for row in self._tapes(hub)[0]["prints"]] == [1, 2, 3]

        await tape.handle_trade("RUN", trade(2.51))
        broadcaster.tick()
        assert [row["q"] for row in self._tapes(hub)[1]["prints"]] == [4]

    async def test_a_quiet_tape_costs_no_frame(self):
        tape = await service()
        hub, broadcaster = self._make(tape)
        await tape.handle_trade("RUN", trade(2.51))
        broadcaster.tick()
        assert broadcaster.tick() == 0
        assert len(self._tapes(hub)) == 1

    async def test_a_symbol_that_never_printed_costs_no_frame(self):
        tape = await service()
        _, broadcaster = self._make(tape)
        assert broadcaster.tick() == 0

    async def test_a_burst_is_capped_at_the_newest_rows(self):
        """A halt resuming must not queue a thousand rows nobody will read."""
        from app.services.broadcaster import MAX_PRINTS_PER_TICK

        tape = await service(buffer=MAX_PRINTS_PER_TICK + 50)
        hub, broadcaster = self._make(tape)
        for _ in range(MAX_PRINTS_PER_TICK + 20):
            await tape.handle_trade("RUN", trade(2.51))

        broadcaster.tick()
        prints = self._tapes(hub)[0]["prints"]
        assert len(prints) == MAX_PRINTS_PER_TICK
        assert prints[-1]["q"] == MAX_PRINTS_PER_TICK + 20

    async def test_a_restarted_sequence_is_sent_as_a_replacement(self):
        """Eviction rewinds the sequence; an append would interleave two tapes."""
        tape = await service()
        hub, broadcaster = self._make(tape)
        for _ in range(3):
            await tape.handle_trade("RUN", trade(2.51))
        broadcaster.tick()

        tape.drop("RUN")
        await tape.handle_trade("RUN", trade(2.60))
        broadcaster.tick()

        latest = self._tapes(hub)[-1]
        assert latest["reset"] is True
        assert [row["q"] for row in latest["prints"]] == [1]
