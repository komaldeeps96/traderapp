"""The halt state machine: transition counting and the day boundary."""

from __future__ import annotations

from datetime import date

from app.services import halts as halts_module
from app.services.halts import HaltTracker


class TestMark:
    def test_unknown_symbol_reads_as_calm(self):
        assert HaltTracker().status("FGI") == (False, 0)

    def test_a_halt_counts_once(self):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        assert tracker.status("FGI") == (True, 1)

    def test_a_repeated_halt_report_does_not_count_again(self):
        """Two sources report the same halt; the transition is one."""
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        tracker.mark("FGI", True)
        assert tracker.status("FGI") == (True, 1)

    def test_halt_resume_halt_counts_twice(self):
        tracker = HaltTracker()
        for state in (True, False, True):
            tracker.mark("FGI", state)
        assert tracker.status("FGI") == (True, 2)

    def test_a_resume_alone_counts_nothing(self):
        tracker = HaltTracker()
        tracker.mark("FGI", False)
        assert tracker.status("FGI") == (False, 0)

    def test_symbols_are_independent(self):
        tracker = HaltTracker()
        tracker.mark("FGI", True)
        assert tracker.status("OTHR") == (False, 0)


class TestDayReset:
    def test_the_count_resets_on_a_new_ny_day(self, monkeypatch):
        tracker = HaltTracker()
        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 18))
        tracker.mark("FGI", True)
        tracker.mark("FGI", False)
        assert tracker.status("FGI") == (False, 1)

        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 19))
        assert tracker.status("FGI") == (False, 0)

    def test_a_halt_standing_overnight_survives_as_one(self, monkeypatch):
        """Still halted at the new open: not calm, and it counts as today's first."""
        tracker = HaltTracker()
        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 18))
        tracker.mark("FGI", True)

        monkeypatch.setattr(halts_module, "ny_date", lambda _: date(2026, 8, 19))
        assert tracker.status("FGI") == (True, 1)
