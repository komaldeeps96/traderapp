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


class TestIndicatorState:
    """Which indicators are on, per timeframe.

    The levels wanted on a 1-minute chart are rarely the ones wanted on a
    daily, so this is stored per timeframe rather than once.
    """

    async def test_round_trips_per_timeframe(self, tmp_path):
        first = store(tmp_path)
        await first.save_indicators("1m", {"ema9": False})
        await first.save_indicators("1d", {"prev_day_high": True})
        assert store(tmp_path).indicator_overrides() == {
            "1m": {"ema9": False},
            "1d": {"prev_day_high": True},
        }

    def test_empty_before_any_save(self, tmp_path):
        assert store(tmp_path).indicator_overrides() == {}

    async def test_an_empty_map_clears_the_timeframe(self, tmp_path):
        """Back to the defaults means no section, not an empty one."""
        first = store(tmp_path)
        await first.save_indicators("1m", {"ema9": False})
        await first.save_indicators("1m", {})
        assert store(tmp_path).indicator_overrides() == {}

    async def test_survives_a_chart_save(self, tmp_path):
        """One file, several sections; a chart save must not drop the rest."""
        first = store(tmp_path)
        await first.save_indicators("1d", {"ema9": False})
        await first.save("TSLA", "1d")
        await first.save_scanner("small_cap", {"scan_code": "TOP_PERC_GAIN"})
        reopened = store(tmp_path)
        assert reopened.indicator_overrides() == {"1d": {"ema9": False}}
        assert reopened.symbol == "TSLA"
        assert reopened.scanner_config("small_cap") == {"scan_code": "TOP_PERC_GAIN"}

    def test_a_hand_edited_file_cannot_poison_it(self, tmp_path):
        """Anything that is not timeframe -> {id: bool} is dropped."""
        (tmp_path / "state.yaml").write_text(
            "indicators:\n"
            "  1m:\n"
            "    ema9: false\n"
            "    ema20: 'yes'\n"      # not a bool
            "  1d: not-a-mapping\n"
            "  7: {}\n"               # not a timeframe string
        )
        assert store(tmp_path).indicator_overrides() == {"1m": {"ema9": False}}

    async def test_callers_cannot_mutate_the_cache(self, tmp_path):
        first = store(tmp_path)
        await first.save_indicators("1m", {"ema9": False})
        first.indicator_overrides()["1m"]["ema9"] = True
        assert first.indicator_overrides() == {"1m": {"ema9": False}}


class TestWatchlist:
    """A plain list of symbols, in the order they were added."""

    async def test_round_trips(self, tmp_path):
        await store(tmp_path).save_watchlist(["AAPL", "TSLA"])
        assert store(tmp_path).watchlist() == ["AAPL", "TSLA"]

    def test_empty_before_anything_is_watched(self, tmp_path):
        assert store(tmp_path).watchlist() == []

    async def test_order_is_the_users_and_is_kept(self, tmp_path):
        """Not sorted: the order things were added in is information."""
        await store(tmp_path).save_watchlist(["ZM", "AAPL", "NVDA"])
        assert store(tmp_path).watchlist() == ["ZM", "AAPL", "NVDA"]

    async def test_survives_a_chart_save(self, tmp_path):
        first = store(tmp_path)
        await first.save_watchlist(["AAPL"])
        await first.save("TSLA", "1m")
        reopened = store(tmp_path)
        assert reopened.watchlist() == ["AAPL"]
        assert reopened.symbol == "TSLA"

    def test_a_hand_edited_file_cannot_poison_it(self, tmp_path):
        (tmp_path / "state.yaml").write_text(
            "watchlist:\n  - aapl\n  - 7\n  - ''\n  - ' tsla '\n"
        )
        assert store(tmp_path).watchlist() == ["AAPL", "TSLA"]

    async def test_callers_cannot_mutate_the_cache(self, tmp_path):
        first = store(tmp_path)
        await first.save_watchlist(["AAPL"])
        first.watchlist().append("TSLA")
        assert first.watchlist() == ["AAPL"]
