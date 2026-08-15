"""The shipped scanner filters.

These are trading decisions, not incidental values — each was set against a
live scan and would revert silently. The subscription plumbing is covered in
test_ibkr_provider; this pins what the app actually asks for.
"""

from __future__ import annotations

from app.core.settings import ScannerSettings


class TestScannerDefaults:
    def test_market_cap_is_the_size_gate_not_price(self):
        """A $1-20 band let Coupang, SoFi and Grab through on the live scan:
        a large cap with a low share price is still a large cap."""
        settings = ScannerSettings()
        assert settings.market_cap_above == 1_000_000
        assert settings.market_cap_below == 2_000_000_000

    def test_price_has_a_ceiling_and_no_floor(self):
        settings = ScannerSettings()
        assert settings.below_price == 50.0
        assert settings.above_price is None

    def test_no_volume_floor(self):
        assert ScannerSettings().above_volume is None

    def test_only_names_up_on_the_day(self):
        assert ScannerSettings().change_perc_above == 10.0

    def test_fund_products_are_excluded(self):
        """`instrument: STK` alone admits ETFs — a 2x leveraged one topped the
        trade-rate scan on pure derivative churn."""
        assert set(ScannerSettings().exclude_stock_types) == {"ETF", "ETN", "CEF", "ETMF"}

    def test_adrs_are_kept(self):
        """`inc:CORP` would have dropped them, and small-cap runners are
        often ADRs — TAL Education was filtered out by it in testing."""
        assert "ADR" not in ScannerSettings().exclude_stock_types
