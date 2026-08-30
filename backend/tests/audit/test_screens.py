"""The screens, checked against their own promises.

A screen has no external truth to be measured against — it is our own
definition. What it does have is a claim printed on screen, and the rows had
better satisfy it: a panel headed "within 10% of the 52-week high" that
returns something 40% below is worse than an empty panel, because it is
believed.

This is the audit the swing screens most need. Their proximity filters run
locally, on rows fetched with coarser terms, because TradingView compares a
column against a number and never against another column. That local step is
where a sign error hides, and a sign error inverts a setup: the pullback
screen quietly becomes a second breakout screen.
"""

from __future__ import annotations

import pytest

from app.services.swing import SCREENS, SwingService, _passes

pytestmark = pytest.mark.audit

SCREEN_PARAMS = [pytest.param(screen, id=screen.id) for screen in SCREENS]


@pytest.fixture(scope="session")
def live_screens():
    """Each screen run once against the real TradingView universe."""
    import asyncio

    service = SwingService()
    rows: dict[str, list[dict]] = {}

    def load(screen_id: str) -> list[dict]:
        if screen_id not in rows:
            rows[screen_id] = asyncio.run(service.rows(screen_id))
        return rows[screen_id]

    return load


class TestRowsKeepTheScreensPromise:
    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_every_row_satisfies_the_stated_filter(self, screen, live_screens):
        rows = live_screens(screen.id)
        if not rows:
            pytest.skip(f"{screen.id} returned nothing; a real market state")
        failures = [
            f"{row['symbol']}: off_high={row.get('off_high')} rvol={row.get('rvol')} "
            f"sma50_gap={row.get('distance_to_sma50')}"
            for row in rows
            if not _passes(screen, row)
        ]
        assert not failures, f"{screen.id} returned rows it excludes:\n  " + "\n  ".join(failures)

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_proximity_to_the_high_is_respected(self, screen, live_screens):
        """The filter the panel's own sentence is written around."""
        if screen.max_off_high is None:
            pytest.skip(f"{screen.id} sets no ceiling on distance from the high")
        for row in live_screens(screen.id):
            off_high = row["off_high"]
            assert off_high is not None, f"{row['symbol']} has no distance from its high"
            assert -screen.max_off_high <= off_high <= 0.0, (
                f"{row['symbol']} is {off_high:.1f}% from its high, outside "
                f"the {screen.max_off_high:.0f}% the screen promises"
            )

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_a_pullback_really_has_pulled_back(self, screen, live_screens):
        """The one a sign error inverts.

        `off_high` is negative below the high, so "at least 5% off" is
        `<= -5`. Get the sign wrong and the screen returns breakouts under a
        pullback heading.
        """
        if screen.min_off_high is None:
            pytest.skip(f"{screen.id} is not a pullback screen")
        for row in live_screens(screen.id):
            assert row["off_high"] <= -screen.min_off_high, (
                f"{row['symbol']} is only {row['off_high']:.1f}% off its high, "
                f"which is not a {screen.min_off_high:.0f}% pullback"
            )

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_volume_expansion_is_real_where_it_is_claimed(self, screen, live_screens):
        if screen.min_rvol is None:
            pytest.skip(f"{screen.id} makes no claim about volume")
        for row in live_screens(screen.id):
            assert row["rvol"] is not None and row["rvol"] >= screen.min_rvol, (
                f"{row['symbol']} at {row['rvol']}x is below the "
                f"{screen.min_rvol}x the screen promises"
            )


class TestRowsAreUsable:
    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_the_shared_filters_are_honoured(self, screen, live_screens):
        """Market cap and liquidity are the two numbers the user sets."""
        import asyncio

        service = SwingService()
        config = service.config
        for row in asyncio.run(service.rows(screen.id)):
            assert row["market_cap"] is None or row["market_cap"] >= config.min_market_cap
            assert row["avg_volume"] is None or row["avg_volume"] >= config.min_avg_volume

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_a_row_carries_what_the_table_draws(self, screen, live_screens):
        rows = live_screens(screen.id)
        if not rows:
            pytest.skip(f"{screen.id} returned nothing")
        for row in rows:
            assert row["symbol"], "a row with no symbol cannot be clicked"
            assert row["close"] is not None and row["close"] > 0

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_no_row_appears_twice(self, screen, live_screens):
        symbols = [row["symbol"] for row in live_screens(screen.id)]
        assert len(symbols) == len(set(symbols)), f"{screen.id} repeats a symbol"

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_the_row_cap_is_honoured(self, screen, live_screens):
        import asyncio

        service = SwingService()
        assert len(asyncio.run(service.rows(screen.id))) <= service.config.rows


class TestDerivedFieldsAreConsistent:
    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_the_distance_from_the_high_is_never_positive(self, screen, live_screens):
        """A stock cannot trade above its own 52-week high.

        If one appears to, the high and the close came from different rows.
        """
        for row in live_screens(screen.id):
            if row["off_high"] is not None:
                assert row["off_high"] <= 0.01, (
                    f"{row['symbol']} is {row['off_high']:.2f}% *above* its high"
                )

    @pytest.mark.parametrize("screen", SCREEN_PARAMS)
    def test_earnings_dates_are_not_in_the_past(self, screen, live_screens):
        """The column says "next"; a date behind us is a stale row."""
        from app.core.clock import now_epoch

        # Generous: the field updates after the release, not at the bell.
        cutoff = now_epoch() - 100 * 86_400
        for row in live_screens(screen.id):
            when = row.get("next_earnings")
            if when is not None:
                assert when >= cutoff, f"{row['symbol']} reports a date long past"
