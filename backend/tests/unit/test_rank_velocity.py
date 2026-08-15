"""Rank velocity: places gained over a rolling window."""

from __future__ import annotations

from app.services.rank_velocity import RankTracker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def tracker(window: float = 30.0) -> tuple[RankTracker, FakeClock]:
    clock = FakeClock()
    return RankTracker(window, clock=clock), clock


class TestWarmUp:
    def test_the_first_observation_claims_nothing(self):
        ranks, _ = tracker()
        result = ranks.observe(["AAA", "BBB"])
        assert result.deltas == {} and result.entered == frozenset()

    def test_nothing_is_reported_until_the_window_has_passed(self):
        """A delta over four seconds is not a delta over thirty."""
        ranks, clock = tracker(window=30.0)
        ranks.observe(["AAA", "BBB"])
        clock.advance(4)
        assert ranks.observe(["BBB", "AAA"]).deltas == {}


class TestDeltas:
    def test_climbing_the_list_is_positive(self):
        ranks, clock = tracker(window=10.0)
        ranks.observe(["AAA", "BBB", "CCC"])
        clock.advance(11)
        result = ranks.observe(["CCC", "AAA", "BBB"])
        # CCC went from index 2 to index 0 — up two places.
        assert result.deltas["CCC"] == 2
        assert result.deltas["AAA"] == -1
        assert result.deltas["BBB"] == -1

    def test_a_row_that_has_not_moved_is_omitted(self):
        ranks, clock = tracker(window=10.0)
        ranks.observe(["AAA", "BBB"])
        clock.advance(11)
        assert ranks.observe(["AAA", "BBB"]).deltas == {}

    def test_a_newcomer_is_reported_as_entered_not_as_a_jump(self):
        """Entering the visible list is the signal; a number would invent one."""
        ranks, clock = tracker(window=10.0)
        ranks.observe(["AAA", "BBB"])
        clock.advance(11)
        result = ranks.observe(["CCC", "AAA", "BBB"])
        assert result.entered == frozenset({"CCC"})
        assert "CCC" not in result.deltas

    def test_a_name_that_left_and_returned_counts_as_entered(self):
        ranks, clock = tracker(window=10.0)
        ranks.observe(["AAA", "BBB"])
        clock.advance(11)
        ranks.observe(["BBB"])
        clock.advance(11)
        assert ranks.observe(["AAA", "BBB"]).entered == frozenset({"AAA"})


class TestWindowing:
    def test_the_baseline_spans_the_full_window_not_the_emit_interval(self):
        """The bug this guards: evicting every expired snapshot.

        That would leave the youngest survivor as the baseline, silently
        shrinking the window to the 3-second emit interval and turning a
        climb measurement into jitter.
        """
        ranks, clock = tracker(window=30.0)
        ranks.observe(["AAA", "BBB", "CCC"])  # t=0, AAA at 0
        for _ in range(20):  # 60s of 3-second emissions, AAA drifting down
            clock.advance(3)
            ranks.observe(["BBB", "CCC", "AAA"])
        # Against 30s ago AAA is already last, so no movement is reported —
        # not the single place it moved in the very first step.
        assert ranks.observe(["BBB", "CCC", "AAA"]).deltas == {}

    def test_measures_against_a_window_ago_not_the_previous_call(self):
        ranks, clock = tracker(window=30.0)
        ranks.observe(["AAA", "BBB"])  # baseline: AAA 0
        clock.advance(31)
        ranks.observe(["BBB", "AAA"])  # AAA 1
        clock.advance(1)
        # Only one second later: the baseline is still the t=0 snapshot,
        # so AAA is still reported as down one — the move has not aged out.
        assert ranks.observe(["BBB", "AAA"]).deltas == {"AAA": -1, "BBB": 1}


class TestReset:
    def test_reset_drops_the_history(self):
        ranks, clock = tracker(window=10.0)
        ranks.observe(["AAA", "BBB"])
        clock.advance(11)
        ranks.reset()
        assert ranks.observe(["BBB", "AAA"]).deltas == {}
