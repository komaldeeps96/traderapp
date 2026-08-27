"""The state file: last chart, last scanner filters, and their coexistence."""

from __future__ import annotations

from app.services.state import StateStore


def store(tmp_path, **kwargs):
    return StateStore(tmp_path / "state.yaml", "AAPL", "10s", **kwargs)


class TestChartState:
    async def test_round_trips_symbol_and_timeframe(self, tmp_path):
        first = store(tmp_path)
        await first.save("FGI", "1m")
        assert (store(tmp_path).symbol, store(tmp_path).timeframe) == ("FGI", "1m")

    def test_defaults_before_any_save(self, tmp_path):
        assert (store(tmp_path).symbol, store(tmp_path).timeframe) == ("AAPL", "10s")

    def test_a_corrupt_file_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "state.yaml").write_text("[not: a: mapping")
        assert store(tmp_path).symbol == "AAPL"


class TestScannerState:
    async def test_round_trips_the_filters(self, tmp_path):
        await store(tmp_path).save_scanner(
            "small_cap", {"scan_code": "TOP_PERC_GAIN", "above_price": 2.0}
        )
        assert store(tmp_path).scanner_config("small_cap") == {
            "scan_code": "TOP_PERC_GAIN",
            "above_price": 2.0,
        }

    def test_absent_before_any_save(self, tmp_path):
        assert store(tmp_path).scanner_config("small_cap") is None

    async def test_each_tier_persists_independently(self, tmp_path):
        """Four scanners share one file and must not clobber each other."""
        first = store(tmp_path)
        await first.save_scanner("small_cap", {"scan_code": "TOP_TRADE_RATE"})
        await first.save_scanner("mid_cap", {"scan_code": "TOP_PERC_GAIN"})
        reloaded = store(tmp_path)
        assert reloaded.scanner_config("small_cap") == {"scan_code": "TOP_TRADE_RATE"}
        assert reloaded.scanner_config("mid_cap") == {"scan_code": "TOP_PERC_GAIN"}
        assert reloaded.scanner_config("large_cap") is None

    async def test_a_chart_save_preserves_the_scanners_section(self, tmp_path):
        """The two writers share one file and must not clobber each other."""
        first = store(tmp_path)
        await first.save_scanner("small_cap", {"scan_code": "TOP_TRADE_RATE"})
        await first.save("FGI", "1m")
        reloaded = store(tmp_path)
        assert reloaded.symbol == "FGI"
        assert reloaded.scanner_config("small_cap") == {"scan_code": "TOP_TRADE_RATE"}

    async def test_a_scanner_save_preserves_the_chart(self, tmp_path):
        first = store(tmp_path)
        await first.save("FGI", "1m")
        await first.save_scanner("small_cap", {"scan_code": "TOP_TRADE_RATE"})
        assert store(tmp_path).symbol == "FGI"

    def test_a_non_dict_scanners_section_is_ignored(self, tmp_path):
        (tmp_path / "state.yaml").write_text("symbol: FGI\nscanners: nonsense\n")
        assert store(tmp_path).scanner_config("small_cap") is None

    def test_a_malformed_entry_within_scanners_is_dropped_not_the_rest(self, tmp_path):
        (tmp_path / "state.yaml").write_text(
            "scanners:\n  small_cap: nonsense\n  mid_cap:\n    scan_code: TOP_TRADE_RATE\n"
        )
        loaded = store(tmp_path)
        assert loaded.scanner_config("small_cap") is None
        assert loaded.scanner_config("mid_cap") == {"scan_code": "TOP_TRADE_RATE"}
