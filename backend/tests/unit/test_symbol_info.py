"""The info strip numbers: session volumes, rotation, halt bands."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.clock import now_epoch
from app.domain.screener import SymbolStats
from app.domain.timeframes import Timeframe
from app.market.store import BarStore
from app.services.halts import HaltState
from app.services.symbol_info import SymbolInfoService, _tier2_band_percent
from app.services.tv import TVDataService
from tests.conftest import make_bar, make_minute_series, ny_epoch


def service_with(store: BarStore, stats: SymbolStats | None, **deps) -> SymbolInfoService:
    tv = TVDataService(fetch=lambda q: {"totalCount": 0, "data": []})
    if stats is not None:
        stats.fetched_at = now_epoch()
        tv._stats_cache[stats.symbol] = stats
    return SymbolInfoService(store, tv, **deps)


def stats_for(symbol: str = "RUN") -> SymbolStats:
    return SymbolStats(
        symbol=symbol,
        float_shares=5_000_000,
        market_cap=40_000_000,
        avg_vol_10d=2_000_000,
        description="Runner Inc",
    )


class FakeEdgar:
    """Just enough EDGAR for a dilution read to exist.

    One cover-page float figure, so the live shelf capacity has something to
    be a multiple *of*.
    """

    def __init__(self, reported_float: float = 9_000_000.0):
        self._facts = {
            "facts": {
                "dei": {
                    "EntityPublicFloat": {
                        "units": {
                            "USD": [
                                {
                                    "end": "2025-06-30",
                                    "val": reported_float,
                                    "form": "10-K",
                                    "filed": "2026-03-31",
                                }
                            ]
                        }
                    }
                }
            }
        }

    def peek_facts(self, symbol):
        return self._facts

    def peek_filings(self, symbol):
        return []


@pytest.fixture
def store() -> BarStore:
    return BarStore()


class TestBuild:
    def test_nothing_loaded_and_no_stats_is_none(self, store):
        service = service_with(store, None)
        assert service.build("RUN") is None

    def test_day_volume_sums_only_today(self, store):
        yesterday = make_minute_series(ny_epoch(2024, 3, 4, 9, 30), [10.0] * 5)
        today = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [11.0] * 3)
        store.replace("RUN", Timeframe.M1, yesterday + today)

        info = service_with(store, stats_for()).build("RUN")
        assert info is not None
        # make_minute_series bars carry volume=100 each.
        assert info["day_volume"] == pytest.approx(300)

    def test_premarket_volume_and_rotation(self, store):
        premarket = make_minute_series(ny_epoch(2024, 3, 5, 7, 0), [9.0] * 4)
        regular = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 6)
        store.replace("RUN", Timeframe.M1, premarket + regular)

        info = service_with(store, stats_for()).build("RUN")
        assert info["pm_volume"] == pytest.approx(400)
        assert info["day_volume"] == pytest.approx(1000)
        assert info["float_rotation"] == pytest.approx(1000 / 5_000_000)
        assert info["pm_float_rotation"] == pytest.approx(400 / 5_000_000)
        assert info["rel_vol"] == pytest.approx(1000 / 2_000_000)

    def test_prev_close_comes_from_the_last_prior_day(self, store):
        store.replace(
            "RUN",
            Timeframe.D1,
            [
                make_bar(ny_epoch(2024, 3, 1, 0, 0), 4.20),
                make_bar(ny_epoch(2024, 3, 4, 0, 0), 4.80),
            ],
        )
        store.replace("RUN", Timeframe.M1, make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [5.0]))

        # "Today" in this test is the present, so both daily bars are prior days.
        info = service_with(store, stats_for()).build("RUN")
        assert info["prev_close"] == pytest.approx(4.80)

    def test_stats_alone_still_produce_a_message(self, store):
        info = service_with(store, stats_for()).build("RUN")
        assert info is not None
        assert info["float_shares"] == pytest.approx(5_000_000)
        assert info["day_volume"] == 0.0
        assert info["float_rotation"] is None


class TestListingAge:
    DAY = 86_400

    def daily(self, store, first_days_ago: int) -> None:
        start = now_epoch() - first_days_ago * self.DAY
        bars = [make_bar(start + i * self.DAY, 10.0) for i in range(3)]
        store.replace("RUN", Timeframe.D1, bars)

    def test_a_young_history_reports_its_age(self, store):
        self.daily(store, 23)
        assert service_with(store, stats_for()).build("RUN")["listed_days"] == 23

    def test_an_old_history_reports_nothing(self, store):
        """Near the fetch window the age measures the fetch, not the listing."""
        self.daily(store, 500)
        assert service_with(store, stats_for()).build("RUN")["listed_days"] is None

    def test_no_daily_history_reports_nothing(self, store):
        assert service_with(store, stats_for()).build("RUN")["listed_days"] is None


class TestBorrow:
    def test_borrow_fields_ride_the_payload(self, store):
        service = service_with(store, stats_for(), borrow=lambda s: (2.9, 1_500_000.0))
        info = service.build("RUN")
        assert (info["shortable"], info["shortable_shares"]) == (2.9, 1_500_000.0)

    def test_without_a_lookup_the_fields_are_none(self, store):
        info = service_with(store, stats_for()).build("RUN")
        assert (info["shortable"], info["shortable_shares"]) == (None, None)

    def test_a_symbol_the_lookup_has_not_seen_is_none(self, store):
        service = service_with(store, stats_for(), borrow=lambda s: None)
        info = service.build("RUN")
        assert (info["shortable"], info["shortable_shares"]) == (None, None)


class TestHaltState:
    def test_defaults_to_calm_without_a_tracker(self, store):
        info = service_with(store, stats_for()).build("RUN")
        assert (info["halted"], info["halts_today"]) == (False, 0)
        assert info["halt_resumed_at"] is None

    def test_rides_the_tracker(self, store):
        state = HaltState(halted=True, count=3, halted_at=1_700_000_000.0, resumed_at=None)
        info = service_with(store, stats_for(), halts=lambda s: state).build("RUN")
        assert (info["halted"], info["halts_today"]) == (True, 3)
        assert info["halt_halted_at"] == 1_700_000_000

    def test_the_resume_time_rides_the_payload(self, store):
        """The reopen read is measured off this stamp, so it has to survive
        the trip: without it the strip can say a stock resumed but not when."""
        state = HaltState(
            halted=False, count=2, halted_at=1_700_000_000.0, resumed_at=1_700_000_300.0
        )
        info = service_with(store, stats_for(), halts=lambda s: state).build("RUN")
        assert info["halt_resumed_at"] == 1_700_000_300
        assert info["halted"] is False


class TestReverseSplit:
    class FakeSplits:
        def __init__(self, split):
            self._split = split

        def peek(self, symbol):
            return self._split

    def test_absent_without_a_service(self, store):
        info = service_with(store, stats_for()).build("RUN")
        assert info["reverse_split_ratio"] is None
        assert info["reverse_split_days"] is None

    def test_ratio_and_recency_ride_the_payload(self, store):
        from datetime import timedelta

        from app.domain.sessions import ny_date
        from app.services.corporate_actions import ReverseSplit

        split = ReverseSplit(ratio=12.0, ex_date=ny_date(now_epoch()) - timedelta(days=45))
        info = service_with(store, stats_for(), splits=self.FakeSplits(split)).build("RUN")
        assert info["reverse_split_ratio"] == pytest.approx(12.0)
        assert info["reverse_split_days"] == 45


class TestYahooFloat:
    class FakeYahoo:
        def peek_float(self, symbol):
            return 3_500_000.0

    def test_absent_without_a_provider(self, store):
        assert service_with(store, stats_for()).build("RUN")["yahoo_float"] is None

    def test_rides_the_payload(self, store):
        info = service_with(store, stats_for(), yahoo=self.FakeYahoo()).build("RUN")
        assert info["yahoo_float"] == pytest.approx(3_500_000)


class TestPullbackPayload:
    def test_no_leg_means_null_fields(self, store):
        flat = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 20)
        store.replace("RUN", Timeframe.M1, flat)
        info = service_with(store, stats_for()).build("RUN")
        assert info["pullback_depth_pct"] is None
        assert info["pullback_bars"] is None

    def test_a_measured_pullback_rides_the_payload(self, store):
        # A 10 -> 12 leg pulling back to 11.5. make_bar pads high/low by $1,
        # so the peak high is 13.0, the trough low 9.0: leg 4.0, given back
        # 13.0 - 11.5 = 1.5 -> 37.5%.
        closes = [10.0, 11.0, 12.0, 11.7, 11.5]
        store.replace("RUN", Timeframe.M1, make_minute_series(ny_epoch(2024, 3, 5, 9, 30), closes))
        info = service_with(store, stats_for()).build("RUN")
        assert info["pullback_depth_pct"] == pytest.approx(37.5)
        assert info["pullback_bars"] == 2
        assert info["pullback_leg_pct"] == pytest.approx(4.0 / 9.0 * 100.0)

    def test_the_leg_does_not_straddle_the_overnight_gap(self, store):
        # Yesterday closed at 20 after a run; today is flat at 10. The gap
        # down is not a "pullback" from yesterday's high.
        yesterday = make_minute_series(ny_epoch(2024, 3, 4, 15, 0), [18.0, 19.0, 20.0])
        today = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 10)
        store.replace("RUN", Timeframe.M1, yesterday + today)
        info = service_with(store, stats_for()).build("RUN")
        assert info["pullback_depth_pct"] is None


class TestHaltBands:
    def test_tier_percent_follows_the_prior_close(self):
        assert _tier2_band_percent(5.0) == pytest.approx(0.10)
        assert _tier2_band_percent(1.50) == pytest.approx(0.20)
        assert _tier2_band_percent(0.50) is None

    def test_bands_bracket_the_reference(self, store):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_ref"] == pytest.approx(10.0)
        assert info["halt_up"] == pytest.approx(11.0)
        assert info["halt_down"] == pytest.approx(9.0)

    def test_sub_dollar_uses_fifteen_cent_bands(self, store):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [0.60] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 0.55)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_up"] == pytest.approx(0.75)
        assert info["halt_down"] == pytest.approx(0.45)

    def test_without_a_prev_close_no_bands(self, store):
        store.replace("RUN", Timeframe.M1, make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [5.0]))
        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_up"] is None
        assert info["halt_band_pct"] is None
        assert info["halt_band_cents"] is None

    def test_the_tier_width_ships_with_the_levels(self, store):
        """Two prices and two percentages do not say how much room the name
        has for the session; the tier does, and it is fixed by last night's
        close rather than by anything happening now."""
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_band_pct"] == pytest.approx(10.0)
        assert info["halt_band_cents"] is None

    def test_a_two_ninety_close_gets_the_wide_band(self, store):
        """Twenty cents of last night's close is the difference between a 10%
        band and a 20% one, all day."""
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [4.0] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 2.90)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_band_pct"] == pytest.approx(20.0)

    def test_the_cent_band_reports_cents_not_a_percentage(self, store):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [0.60] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 0.55)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_band_pct"] is None
        assert info["halt_band_cents"] == pytest.approx(15.0)


class TestLiveShelfCapacity:
    """The baby-shelf ceiling, priced at the run rather than at the cover page.

    Two bases have to agree here. The daily store is strictly historical —
    today's candle is folded in only on read — so a 60-day high taken from it
    alone would miss the very spike that moves the number.
    """

    TODAY = date(2026, 3, 5)

    def test_the_window_stops_at_sixty_calendar_days(self):
        ancient = make_bar(ny_epoch(2025, 11, 1, 0, 0), 500.0)  # ~124 days back
        recent = make_bar(ny_epoch(2026, 2, 20, 0, 0), 9.0)
        high = SymbolInfoService._lookback_high([ancient, recent], [], self.TODAY)
        # make_bar pads the high a dollar above the close.
        assert high == pytest.approx(10.0)

    def test_todays_spike_counts(self):
        """The run is the whole point: a stock that quadrupled this morning
        has quadrupled what its issuer may sell, before any filing exists."""
        history = [make_bar(ny_epoch(2026, 2, 20, 0, 0), 2.0)]  # high 3.0
        today = make_minute_series(ny_epoch(2026, 3, 5, 9, 30), [4.0, 11.0, 9.0])
        assert SymbolInfoService._lookback_high(history, today, self.TODAY) == pytest.approx(12.0)

    def test_no_prices_at_all_is_no_answer(self):
        assert SymbolInfoService._lookback_high([], [], self.TODAY) is None

    def test_the_read_carries_a_capacity_priced_off_the_tape(self, store):
        """5M float shares against a $12 high is $60M of float — still under
        the $75M line, so a third of it is the twelve-month ceiling."""
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2026, 2, 20, 0, 0), 2.0)])
        store.replace(
            "RUN", Timeframe.M1, make_minute_series(ny_epoch(2026, 3, 5, 9, 30), [11.0])
        )
        service = service_with(store, stats_for(), edgar=FakeEdgar())
        shelf = service.dilution("RUN").live_shelf

        assert shelf.price == pytest.approx(12.0)
        assert shelf.public_float == pytest.approx(60_000_000)
        assert shelf.capped is True
        assert shelf.capacity == pytest.approx(20_000_000)
        # Against the $9M on the last cover page.
        assert shelf.multiple == pytest.approx(60 / 9)

    def test_a_bigger_run_lifts_the_cap_entirely(self, store):
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2026, 2, 20, 0, 0), 2.0)])
        store.replace(
            "RUN", Timeframe.M1, make_minute_series(ny_epoch(2026, 3, 5, 9, 30), [20.0])
        )
        service = service_with(store, stats_for(), edgar=FakeEdgar())
        shelf = service.dilution("RUN").live_shelf

        assert shelf.capped is False
        assert shelf.capacity is None

    def test_the_memo_does_not_freeze_it_at_the_old_price(self, store):
        """The filings are cached against their own identity; the price is
        not. A shelf capacity stuck at whatever the stock was worth when the
        documents last changed would be worse than none."""
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2026, 2, 20, 0, 0), 2.0)])
        store.replace(
            "RUN", Timeframe.M1, make_minute_series(ny_epoch(2026, 3, 5, 9, 30), [5.0])
        )
        service = service_with(store, stats_for(), edgar=FakeEdgar())
        first = service.dilution("RUN").live_shelf.public_float

        store.replace(
            "RUN", Timeframe.M1, make_minute_series(ny_epoch(2026, 3, 5, 9, 30), [5.0, 30.0])
        )
        second = service.dilution("RUN").live_shelf.public_float
        assert second > first
