"""The halt state machine: transition counting, times, and the day boundary."""

from __future__ import annotations

from datetime import date

import pytest

from app.services import halts as halts_module
from app.services.halts import HaltTracker


@pytest.fixture
def clock(monkeypatch):
    """A movable server clock, so transition times are assertable."""
    state = {"now": 1_700_000_000.0}

    def advance(seconds: float) -> None:
        state["now"] += seconds

    monkeypatch.setattr(halts_module, "now_epoch", lambda: state["now"])
    advance.at = lambda: state["now"]  # type: ignore[attr-defined]
    return advance


class TestMark:
    def test_unknown_symbol_reads_as_calm(self):
        state = HaltTracker().status("FGI")
        assert (state.halted, state.count) == (False, 0)
        assert (state.halted_at, state.resumed_at) == (None, None)

    def test_a_halt_counts_once(self):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (True, 1)

    def test_a_repeated_halt_report_does_not_count_again(self):
        """Two sources report the same halt; the transition is one."""
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        tracker.mark("FGI", True)
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (True, 1)

    def test_halt_resume_halt_counts_twice(self):
        tracker = HaltTracker()
        for halted in (True, False, True):
            tracker.mark("FGI", halted)
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (True, 2)

    def test_a_resume_alone_counts_nothing(self):
        tracker = HaltTracker()
        tracker.mark("FGI", False)
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (False, 0)
        assert state.resumed_at is None

    def test_symbols_are_independent(self):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        assert tracker.status("OTHR").count == 0


class TestTransitionTimes:
    def test_the_halt_is_stamped(self, clock):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        assert tracker.status("FGI").halted_at == pytest.approx(1_700_000_000.0)

    def test_the_resume_is_stamped(self, clock):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        clock(300)
        tracker.mark("FGI", False)

        state = tracker.status("FGI")
        assert state.resumed_at == pytest.approx(1_700_000_300.0)
        # The halt that ended keeps its own stamp: the pair is what says how
        # long the stock was frozen.
        assert state.halted_at == pytest.approx(1_700_000_000.0)

    def test_a_repeated_report_does_not_restamp(self, clock):
        """Both feeds report the same halt seconds apart; the reopen clock
        must measure the tape, not the second provider's latency."""
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        clock(300)
        tracker.mark("FGI", False)
        clock(5)
        tracker.mark("FGI", False)

        assert tracker.status("FGI").resumed_at == pytest.approx(1_700_000_300.0)

    def test_a_second_halt_replaces_the_first_stamp(self, clock):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        clock(300)
        tracker.mark("FGI", False)
        clock(120)
        tracker.mark("FGI", True)

        state = tracker.status("FGI")
        assert state.count == 2
        assert state.halted_at == pytest.approx(1_700_000_420.0)
        # The previous resume stands until this halt ends — the strip reads
        # "halted" from the flag, not from a missing resume time.
        assert state.resumed_at == pytest.approx(1_700_000_300.0)


class TestDayReset:
    def test_the_count_resets_on_a_new_ny_day(self, monkeypatch):
        tracker = HaltTracker()
        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 18))
        tracker.mark("FGI", True)
        tracker.mark("FGI", False)
        assert tracker.status("FGI").count == 1

        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 19))
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (False, 0)

    def test_yesterdays_resume_does_not_read_as_this_mornings(self, monkeypatch):
        """A terminal left open overnight must not open the session claiming
        the stock reopened moments ago."""
        tracker = HaltTracker()
        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 18))
        tracker.mark("FGI", True)
        tracker.mark("FGI", False)

        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 19))
        state = tracker.status("FGI")
        assert state.resumed_at is None
        assert state.halted_at is None

    def test_a_halt_standing_overnight_survives_as_one(self, monkeypatch):
        """Still halted at the new open: not calm, and it counts as today's first."""
        tracker = HaltTracker()
        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 18))
        tracker.mark("FGI", True)

        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 19))
        state = tracker.status("FGI")
        assert (state.halted, state.count) == (True, 1)
        # The halt is still running, so its start time is still the truth.
        assert state.halted_at is not None
