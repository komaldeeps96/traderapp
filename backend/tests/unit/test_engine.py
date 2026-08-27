"""The indicator engine.

The most valuable test here is that the cheap `latest()` path — used once a
second per chart — agrees with the full `compute()` path. If those ever
diverge, the number in the sidebar stops matching the line on the chart.
"""

from __future__ import annotations

import pytest

from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine, latest_values
from app.indicators.levels import DailyLevelIndex
from app.indicators.spec import IndicatorSpec
from tests.conftest import make_minute_series, ny_epoch

ALL_INTRADAY = {"1m": {"enabled": True}, "5m": {"enabled": True}}


def spec(**overrides) -> IndicatorSpec:
    base = {
        "id": "ema9",
        "type": "ema",
        "label": "EMA 9",
        "span": 9,
        "timeframes": ALL_INTRADAY,
    }
    base.update(overrides)
    return IndicatorSpec.model_validate(base)


@pytest.fixture
def bars():
    return make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [100.0 + (i % 11) * 0.4 for i in range(90)])


@pytest.fixture
def level_index(daily_bars):
    engine = IndicatorEngine(_full_specs())
    return DailyLevelIndex(daily_bars, engine.all_level_keys())


def _full_specs() -> list[IndicatorSpec]:
    return [
        spec(),
        spec(id="ema20", label="EMA 20", span=20),
        spec(id="vwap", type="vwap", label="VWAP", span=None),
        spec(id="macd", type="macd", label="MACD", span=None),
        spec(id="pm_high", type="premarket", label="PM High", span=None, bound="high"),
        spec(id="prev_day_close", type="daily_level", label="PDC", span=None, level="prev_day_close"),
        spec(id="d_sma20", type="daily_level", label="1D SMA 20", span=None, level="sma:20"),
        spec(id="volume", type="volume", label="Volume", span=None),
    ]


class TestWrvolSpec:
    def wrvol_spec(self):
        return spec(id="wrvol", type="wrvol", label="Windowed RVOL", span=None)

    def test_series_ride_the_minute_base(self, bars):
        engine = IndicatorEngine([self.wrvol_spec()])
        # Two synthetic sessions of minute bars, a day apart.
        day = 86_400
        minutes = bars
        shifted = [
            type(b)(
                time=b.time + day,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                trades=b.trades,
            )
            for b in bars
        ]
        series = engine.compute(shifted, Timeframe.M1, minute_bars=minutes + shifted)
        assert "wrvol" in series
        # Same volumes at the same time of day: the ratio is one.
        assert series["wrvol"][-1][1] == pytest.approx(1.0)

        latest = engine.latest(shifted, Timeframe.M1, minute_bars=minutes + shifted)
        assert latest["wrvol"] == pytest.approx(1.0)

    def test_without_the_minute_base_it_stays_silent(self, bars):
        engine = IndicatorEngine([self.wrvol_spec()])
        assert "wrvol" not in engine.compute(bars, Timeframe.M1)
        assert "wrvol" not in engine.latest(bars, Timeframe.M1)

    def test_readout_only_is_declared_to_the_client(self):
        assert self.wrvol_spec().to_client()["readout_only"] is True
        assert spec().to_client()["readout_only"] is False


class TestCompute:
    def test_produces_a_series_per_active_indicator(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, level_index=level_index)
        assert {"ema9", "ema20", "vwap"} <= set(series)

    def test_omits_volume_which_is_read_off_the_bar(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        assert "volume" not in engine.compute(bars, Timeframe.M1, level_index=level_index)

    def test_skips_indicators_not_configured_for_the_timeframe(self, bars):
        engine = IndicatorEngine([spec(timeframes={"1d": {"enabled": True}})])
        assert engine.compute(bars, Timeframe.M1) == {}

    def test_skips_vwap_on_a_daily_chart(self, bars):
        engine = IndicatorEngine(
            [spec(id="vwap", type="vwap", label="VWAP", span=None, timeframes={"1d": {"enabled": True}})]
        )
        assert "vwap" not in engine.compute(bars, Timeframe.D1)

    def test_is_empty_without_bars(self, level_index):
        engine = IndicatorEngine(_full_specs())
        assert engine.compute([], Timeframe.M1, level_index=level_index) == {}

    def test_key_levels_need_daily_data(self, bars):
        engine = IndicatorEngine(_full_specs())
        assert "prev_day_close" not in engine.compute(bars, Timeframe.M1)

    def test_key_levels_appear_with_daily_data(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, level_index=level_index)
        assert "d_sma20" in series

    def test_series_points_are_time_ordered(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        for points in engine.compute(bars, Timeframe.M1, level_index=level_index).values():
            times = [t for t, _ in points]
            assert times == sorted(times)

    def test_level_series_is_compressed_not_one_point_per_bar(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, level_index=level_index)
        # One value for the whole day collapses to its two endpoints.
        assert len(series["d_sma20"]) < len(bars)

    def test_ema_starts_only_once_its_span_has_filled(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, level_index=level_index)
        assert series["ema9"][0][0] == bars[8].time

    def test_builds_its_own_level_index_from_daily_bars(self, bars, daily_bars):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, daily_bars=daily_bars)
        assert "prev_day_close" in series

    def test_macd_emits_all_three_series(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        series = engine.compute(bars, Timeframe.M1, level_index=level_index)
        assert {"macd", "macd_signal", "macd_hist"} <= set(series)
        # Histogram is the gap between the two lines at matching times.
        signal = dict(series["macd_signal"])
        macd_line = dict(series["macd"])
        for time, hist in series["macd_hist"]:
            assert hist == pytest.approx(macd_line[time] - signal[time])

    def test_ema_span_override_changes_the_series(self, bars, level_index):
        """The 10s chart runs ema9 at span 54 — the override must be honoured."""
        overridden = spec(
            timeframes={"1m": {"enabled": True, "span": 20}},
        )
        plain20 = spec(id="ema20", label="EMA 20", span=20)
        engine = IndicatorEngine([overridden, plain20])
        series = engine.compute(bars, Timeframe.M1)
        assert series["ema9"] == series["ema20"]


class TestLatestMatchesCompute:
    """The fast path and the full path must never disagree."""

    def test_every_indicator_agrees(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        full = latest_values(engine.compute(bars, Timeframe.M1, level_index=level_index))
        fast = engine.latest(bars, Timeframe.M1, level_index)

        assert set(fast) == set(full)
        for key, value in fast.items():
            assert value == pytest.approx(full[key]), key

    def test_agrees_on_a_resampled_timeframe(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        full = latest_values(engine.compute(bars, Timeframe.M5, level_index=level_index))
        fast = engine.latest(bars, Timeframe.M5, level_index)
        for key, value in fast.items():
            assert value == pytest.approx(full[key]), key

    def test_agrees_after_the_newest_bar_changes(self, bars, level_index):
        engine = IndicatorEngine(_full_specs())
        bars[-1].close += 5.0
        full = latest_values(engine.compute(bars, Timeframe.M1, level_index=level_index))
        fast = engine.latest(bars, Timeframe.M1, level_index)
        for key, value in fast.items():
            assert value == pytest.approx(full[key]), key

    def test_is_empty_without_bars(self, level_index):
        engine = IndicatorEngine(_full_specs())
        assert engine.latest([], Timeframe.M1, level_index) == {}


class TestSpecLookups:
    def test_for_timeframe_filters(self):
        engine = IndicatorEngine([spec(), spec(id="daily_only", timeframes={"1d": {"enabled": True}})])
        assert [s.id for s in engine.for_timeframe(Timeframe.M1)] == ["ema9"]

    def test_all_level_keys_collects_every_level(self):
        engine = IndicatorEngine(_full_specs())
        assert len(engine.all_level_keys()) == 2

    def test_span_override_per_timeframe(self):
        indicator = IndicatorSpec.model_validate(
            {
                "id": "ema_slow",
                "type": "ema",
                "label": "EMA slow",
                "span": 45,
                "timeframes": {"1m": {"enabled": True}, "1d": {"enabled": True, "span": 50}},
            }
        )
        assert indicator.span_for(Timeframe.M1) == 45
        assert indicator.span_for(Timeframe.D1) == 50
