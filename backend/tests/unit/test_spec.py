"""Indicator config validation.

A typo in the YAML must fail at startup with a precise message rather than
silently drawing nothing.
"""

from __future__ import annotations

import pytest
import yaml

from app.core.settings import CONFIG_DIR
from app.domain.timeframes import Timeframe
from app.indicators.spec import (
    IndicatorConfigError,
    IndicatorSpec,
    Pane,
    load_indicator_specs,
)


def write_config(tmp_path, indicators: list[dict]):
    path = tmp_path / "indicators.yaml"
    path.write_text(yaml.safe_dump({"indicators": indicators}))
    return path


VALID_EMA = {
    "id": "ema9",
    "type": "ema",
    "label": "EMA 9",
    "span": 9,
    "timeframes": {"1m": {"enabled": True}},
}


class TestShippedConfig:
    """The config the app actually runs on."""

    def test_loads(self):
        assert load_indicator_specs(CONFIG_DIR / "indicators.yaml")

    def test_ids_are_unique(self):
        specs = load_indicator_specs(CONFIG_DIR / "indicators.yaml")
        ids = [s.id for s in specs]
        assert len(ids) == len(set(ids))

    def test_every_key_level_is_on_for_intraday(self):
        """Momentum levels are the setup; they must default to visible."""
        specs = load_indicator_specs(CONFIG_DIR / "indicators.yaml")
        levels = [s for s in specs if s.group in ("key_levels", "daily_ma")]
        assert levels
        for level in levels:
            option = level.option_for(Timeframe.M1)
            assert option is not None and option.enabled, level.id

    def test_every_key_level_is_directly_labelled(self):
        """A level's identity must never rest on colour alone.

        There are ~20 of them drawn in one identical neutral line, so the
        axis tag is the only thing telling them apart. A sub-pane indicator
        (MACD) is identified by its own pane instead.

        The moving averages and VWAP are exempt: they track price, so their
        tags cluster around the last trade — over the levels being read — and
        the three MA hues were picked for colour-vision separation precisely
        so they can carry identity on their own.
        """
        specs = load_indicator_specs(CONFIG_DIR / "indicators.yaml")
        for indicator in specs:
            if indicator.draws_series and indicator.group == "key_levels":
                assert indicator.last_value, indicator.id

    def test_every_key_level_looks_the_same(self):
        """One solid neutral line, no exceptions.

        They used to be tiered by weight and dash pattern, which made a
        handful conspicuously unlike the rest for a distinction the eye had
        to be taught — and most of it was overwritten each frame by the
        confluence pass anyway. What a level is worth is shown by the band
        colouring, not by its configured style.
        """
        specs = load_indicator_specs(CONFIG_DIR / "indicators.yaml")
        levels = [s for s in specs if s.group == "key_levels"]
        assert levels
        assert {s.line_style.value for s in levels} == {"solid"}
        assert len({(s.color, s.color_dark) for s in levels}) == 1

    def test_the_price_axis_is_not_crowded_by_lines_that_track_price(self):
        specs = load_indicator_specs(CONFIG_DIR / "indicators.yaml")
        floating = {s.id for s in specs if s.group in ("moving_averages", "session")}
        assert floating
        labelled = {s.id for s in specs if s.last_value}
        assert floating - labelled == floating - {"ema50"}

    def test_premarket_levels_are_present(self):
        ids = {s.id for s in load_indicator_specs(CONFIG_DIR / "indicators.yaml")}
        assert {"pm_high", "pm_low", "prev_day_close"} <= ids


class TestValidation:
    def test_accepts_a_well_formed_indicator(self, tmp_path):
        assert len(load_indicator_specs(write_config(tmp_path, [VALID_EMA]))) == 1

    def test_rejects_a_duplicate_id(self, tmp_path):
        with pytest.raises(IndicatorConfigError, match="duplicate"):
            load_indicator_specs(write_config(tmp_path, [VALID_EMA, dict(VALID_EMA)]))

    def test_rejects_an_ema_without_a_span(self, tmp_path):
        broken = {k: v for k, v in VALID_EMA.items() if k != "span"}
        with pytest.raises(IndicatorConfigError, match="span"):
            load_indicator_specs(write_config(tmp_path, [broken]))

    def test_rejects_a_premarket_without_a_bound(self, tmp_path):
        broken = {**VALID_EMA, "type": "premarket", "span": None}
        with pytest.raises(IndicatorConfigError, match="bound"):
            load_indicator_specs(write_config(tmp_path, [broken]))

    def test_rejects_an_unknown_level(self, tmp_path):
        broken = {**VALID_EMA, "type": "daily_level", "span": None, "level": "prev_decade_high"}
        with pytest.raises(IndicatorConfigError):
            load_indicator_specs(write_config(tmp_path, [broken]))

    def test_rejects_an_unknown_timeframe(self, tmp_path):
        broken = {**VALID_EMA, "timeframes": {"3s": {"enabled": True}}}
        with pytest.raises(IndicatorConfigError):
            load_indicator_specs(write_config(tmp_path, [broken]))

    def test_rejects_a_bad_colour(self, tmp_path):
        with pytest.raises(IndicatorConfigError):
            load_indicator_specs(write_config(tmp_path, [{**VALID_EMA, "color": "red"}]))

    def test_rejects_an_unknown_field(self, tmp_path):
        with pytest.raises(IndicatorConfigError):
            load_indicator_specs(write_config(tmp_path, [{**VALID_EMA, "colour": "#ffffff"}]))

    def test_rejects_a_missing_file(self, tmp_path):
        with pytest.raises(IndicatorConfigError, match="not found"):
            load_indicator_specs(tmp_path / "absent.yaml")

    def test_rejects_a_file_without_an_indicator_list(self, tmp_path):
        path = tmp_path / "indicators.yaml"
        path.write_text(yaml.safe_dump({"nope": []}))
        with pytest.raises(IndicatorConfigError, match="indicators"):
            load_indicator_specs(path)

    def test_error_names_the_offending_entry(self, tmp_path):
        broken = {k: v for k, v in VALID_EMA.items() if k != "span"}
        with pytest.raises(IndicatorConfigError, match=r"indicators\[1\]"):
            load_indicator_specs(write_config(tmp_path, [VALID_EMA, broken]))


class TestDerivedProperties:
    def test_volume_goes_to_its_own_pane(self):
        volume = IndicatorSpec.model_validate({**VALID_EMA, "type": "volume", "span": None})
        assert volume.pane is Pane.VOLUME

    def test_macd_goes_to_its_own_pane(self):
        macd = IndicatorSpec.model_validate({**VALID_EMA, "type": "macd", "span": None})
        assert macd.pane is Pane.MACD

    def test_lines_go_to_the_price_pane(self):
        assert IndicatorSpec.model_validate(VALID_EMA).pane is Pane.PRICE

    def test_panes_do_not_draw_series(self):
        volume = IndicatorSpec.model_validate({**VALID_EMA, "type": "volume", "span": None})
        assert volume.draws_series is False

    def test_applies_to_reads_the_timeframe_map(self):
        indicator = IndicatorSpec.model_validate(VALID_EMA)
        assert indicator.applies_to(Timeframe.M1)
        assert not indicator.applies_to(Timeframe.D1)

    def test_client_payload_carries_both_theme_colours(self):
        indicator = IndicatorSpec.model_validate({**VALID_EMA, "color": "#123456"})
        payload = indicator.to_client()
        assert payload["color"] == "#123456"
        assert payload["color_dark"] == "#123456"
