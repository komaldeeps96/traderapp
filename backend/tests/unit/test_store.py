"""Bar storage."""

from __future__ import annotations

import pytest

from app.domain.bars import Bar, merge_bars
from app.domain.timeframes import Timeframe
from app.market.store import BarStore
from tests.conftest import make_bar


@pytest.fixture
def store() -> BarStore:
    return BarStore(max_bars=100)


class TestReads:
    def test_unknown_symbol_is_empty(self, store):
        assert store.get("NOPE", Timeframe.M1) == []

    def test_has_is_false_until_written(self, store):
        assert store.has("AAPL", Timeframe.M1) is False

    def test_replace_then_read(self, store):
        bars = [make_bar(60, 1.0), make_bar(120, 2.0)]
        store.replace("AAPL", Timeframe.M1, bars)
        assert len(store.get("AAPL", Timeframe.M1)) == 2

    def test_replace_sorts_by_time(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(120, 2.0), make_bar(60, 1.0)])
        assert [b.time for b in store.get("AAPL", Timeframe.M1)] == [60, 120]

    def test_timeframes_are_independent(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        assert store.get("AAPL", Timeframe.D1) == []

    def test_symbols_are_independent(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        assert store.get("TSLA", Timeframe.M1) == []


class TestUpsert:
    def test_appends_a_newer_bar(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        assert store.upsert("AAPL", Timeframe.M1, make_bar(120, 2.0)) is True
        assert len(store.get("AAPL", Timeframe.M1)) == 2

    def test_replaces_the_newest_bar_in_place(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        assert store.upsert("AAPL", Timeframe.M1, make_bar(60, 9.0)) is False
        bars = store.get("AAPL", Timeframe.M1)
        assert len(bars) == 1 and bars[0].close == pytest.approx(9.0)

    def test_replaces_an_older_bar_without_reordering(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0), make_bar(120, 2.0)])
        store.upsert("AAPL", Timeframe.M1, make_bar(60, 7.0))
        bars = store.get("AAPL", Timeframe.M1)
        assert [b.time for b in bars] == [60, 120]
        assert bars[0].close == pytest.approx(7.0)

    def test_inserts_a_late_bar_in_order(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0), make_bar(180, 3.0)])
        assert store.upsert("AAPL", Timeframe.M1, make_bar(120, 2.0)) is True
        assert [b.time for b in store.get("AAPL", Timeframe.M1)] == [60, 120, 180]

    def test_works_on_an_empty_symbol(self, store):
        assert store.upsert("NEW", Timeframe.M1, make_bar(60, 1.0)) is True

    def test_trims_to_the_cap(self):
        store = BarStore(max_bars=10)
        for i in range(25):
            store.upsert("AAPL", Timeframe.M1, make_bar(60 * (i + 1), float(i)))
        bars = store.get("AAPL", Timeframe.M1)
        assert len(bars) == 10
        assert bars[-1].close == pytest.approx(24.0)


class TestMerge:
    def test_incoming_wins_on_a_shared_timestamp(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        store.merge("AAPL", Timeframe.M1, [make_bar(60, 5.0)])
        bars = store.get("AAPL", Timeframe.M1)
        assert len(bars) == 1 and bars[0].close == pytest.approx(5.0)

    def test_keeps_bars_only_one_side_has(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        store.merge("AAPL", Timeframe.M1, [make_bar(120, 2.0)])
        assert [b.time for b in store.get("AAPL", Timeframe.M1)] == [60, 120]

    def test_merging_into_nothing_just_stores(self, store):
        store.merge("AAPL", Timeframe.M1, [make_bar(120, 2.0), make_bar(60, 1.0)])
        assert [b.time for b in store.get("AAPL", Timeframe.M1)] == [60, 120]


class TestClear:
    def test_clear_removes_one_symbol(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        store.replace("TSLA", Timeframe.M1, [make_bar(60, 1.0)])
        store.clear("AAPL")
        assert store.get("AAPL", Timeframe.M1) == []
        assert len(store.get("TSLA", Timeframe.M1)) == 1

    def test_clear_all_empties_everything(self, store):
        store.replace("AAPL", Timeframe.M1, [make_bar(60, 1.0)])
        store.clear_all()
        assert store.symbols == []


class TestMergeBars:
    def test_primary_replaces_rather_than_sums(self):
        """A shared minute must not double-count volume."""
        primary = [Bar(time=60, open=1, high=2, low=0, close=1, volume=500)]
        secondary = [Bar(time=60, open=9, high=9, low=9, close=9, volume=900)]
        merged = merge_bars(primary, secondary)
        assert len(merged) == 1
        assert merged[0].volume == pytest.approx(500)
        assert merged[0].close == pytest.approx(1)

    def test_union_is_sorted(self):
        merged = merge_bars([make_bar(180, 3.0)], [make_bar(60, 1.0), make_bar(120, 2.0)])
        assert [b.time for b in merged] == [60, 120, 180]

    def test_handles_empty_sides(self):
        assert merge_bars([], []) == []
        assert len(merge_bars([make_bar(60, 1.0)], [])) == 1
        assert len(merge_bars([], [make_bar(60, 1.0)])) == 1


class TestBarHelpers:
    def test_merged_with_folds_two_bars(self):
        first = Bar(time=60, open=10, high=12, low=9, close=11, volume=100, trades=5)
        second = Bar(time=60, open=11, high=15, low=8, close=14, volume=50, trades=3)
        folded = first.merged_with(second)
        assert (folded.open, folded.high, folded.low, folded.close) == (10, 15, 8, 14)
        assert folded.volume == pytest.approx(150)
        assert folded.trades == pytest.approx(8)

    def test_wire_round_trip(self):
        bar = Bar(time=60, open=1.5, high=2.5, low=0.5, close=2.0, volume=10, trades=2)
        assert Bar.from_wire(bar.to_wire()) == bar
