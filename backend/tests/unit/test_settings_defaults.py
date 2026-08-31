"""The shipped scanner filters.

These are trading decisions, not incidental values — each was set against a
live scan and would revert silently. The subscription plumbing is covered in
test_ibkr_provider; this pins what the app actually asks for.
"""

from __future__ import annotations

from app.core.settings import ScannerSettings
from app.domain.scanner import DEFAULT_SCANNER_ROWS, SCANNER_TIERS


class TestScannerDefaults:
    def test_market_cap_bands_partition_with_no_overlap(self):
        """A $1-20 band let Coupang, SoFi and Grab through on the live scan:
        a large cap with a low share price is still a large cap — so each
        tier's band, not price, is the size gate. Each tier's floor is the
        previous tier's ceiling, so the four scanners never surface the same
        name at a boundary."""
        bands = [(t["market_cap_above"], t["market_cap_below"]) for t in SCANNER_TIERS]
        assert bands == [
            (1_000_000, 2_000_000_000),
            (2_000_000_000, 10_000_000_000),
            (10_000_000_000, 200_000_000_000),
            (200_000_000_000, None),
        ]

    def test_every_tier_runs_at_the_same_depth(self):
        """Four panels stacked in one column share their height with the key
        levels underneath, so none of them gets to be the deep one."""
        rows = {str(tier["id"]): tier["rows"] for tier in SCANNER_TIERS}
        assert set(rows.values()) == {DEFAULT_SCANNER_ROWS}

    def test_the_row_count_is_not_a_settings_knob(self):
        """It belongs to the tier, beside the band — one source of truth."""
        assert not hasattr(ScannerSettings(), "number_of_rows")

    def test_price_has_a_ceiling_and_no_floor(self):
        settings = ScannerSettings()
        assert settings.below_price == 50.0
        assert settings.above_price is None

    def test_the_tape_must_be_moving(self):
        """Trades per minute, not cumulative volume. Volume is what a name has
        already done today; by the time a runner has it, it is often over.

        Two hundred admits a name in the first minutes of a move, before the
        rate has built — which is the part worth catching."""
        assert ScannerSettings().above_trade_rate == 200

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
