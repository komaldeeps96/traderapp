"""The mid-session filing alert.

A shelf takedown priced into a spike you are long is the most expensive
surprise in this style of trading. What matters here is that the alert fires
for the filings that mean supply, stays quiet for the ones that do not, and
never fires for what was already on file when the chart was opened.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.domain.filings import Filing, FilingKind
from app.services.filing_watch import FilingWatchService


def filing(form: str, accession: str, kind: FilingKind) -> Filing:
    return Filing(
        form=form,
        kind=kind,
        note="",
        filed=date(2026, 8, 28),
        accepted=None,
        accession=accession,
        items=(),
        url="",
    )


TAKEDOWN = filing("424B5", "acc-424", FilingKind.DILUTION)
LATE = filing("NT 10-Q", "acc-nt", FilingKind.DISTRESS)
INSIDER = filing("4", "acc-4", FilingKind.OWNERSHIP)
QUARTERLY = filing("10-Q", "acc-10q", FilingKind.PERIODIC)


class FakeEdgar:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls: list[str] = []

    async def refresh_filings(self, symbol: str):
        self.calls.append(symbol)
        return list(self.rows)


@pytest.fixture
def alerts():
    return []


def watcher(edgar, alerts):
    service = FilingWatchService(edgar)

    async def handler(symbol: str, row: Filing) -> None:
        alerts.append((symbol, row.form))

    service.on_alert(handler)
    return service


class TestBaseline:
    async def test_the_first_poll_never_alerts(self, alerts):
        """Everything on file when a chart opens is already history — opening
        a company that raised last week must not fire an alarm about it."""
        service = watcher(FakeEdgar([TAKEDOWN, LATE]), alerts)
        await service._poll("CELU")
        assert alerts == []

    async def test_an_unchanged_trail_stays_quiet(self, alerts):
        service = watcher(FakeEdgar([TAKEDOWN]), alerts)
        await service._poll("CELU")
        await service._poll("CELU")
        assert alerts == []

    async def test_an_empty_trail_does_not_set_a_baseline(self, alerts):
        """A failed fetch returns nothing; treating that as "no filings exist"
        would alert on the whole trail once EDGAR answered again."""
        edgar = FakeEdgar([])
        service = watcher(edgar, alerts)
        await service._poll("CELU")

        edgar.rows = [TAKEDOWN]
        await service._poll("CELU")
        assert alerts == []


class TestAlerts:
    async def test_a_new_takedown_alerts(self, alerts):
        edgar = FakeEdgar([LATE])
        service = watcher(edgar, alerts)
        await service._poll("CELU")

        edgar.rows = [TAKEDOWN, LATE]
        await service._poll("CELU")
        assert alerts == [("CELU", "424B5")]

    async def test_a_new_distress_filing_alerts(self, alerts):
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        await service._poll("CELU")

        edgar.rows = [LATE, QUARTERLY]
        await service._poll("CELU")
        assert alerts == [("CELU", "NT 10-Q")]

    async def test_routine_filings_never_alert(self, alerts):
        """An insider's tax withholding is a row in the panel, not an alarm —
        waking a trader for one trains them to ignore the real thing."""
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        await service._poll("CELU")

        edgar.rows = [INSIDER, QUARTERLY]
        await service._poll("CELU")
        assert alerts == []

    async def test_the_same_filing_only_alerts_once(self, alerts):
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        await service._poll("CELU")

        edgar.rows = [TAKEDOWN, QUARTERLY]
        await service._poll("CELU")
        await service._poll("CELU")
        assert alerts == [("CELU", "424B5")]

    async def test_switching_away_and_back_does_not_replay(self, alerts):
        edgar = FakeEdgar([TAKEDOWN])
        service = watcher(edgar, alerts)
        await service._poll("CELU")
        await service._poll("AAPL")
        await service._poll("CELU")
        assert alerts == []

    async def test_each_symbol_keeps_its_own_baseline(self, alerts):
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        await service._poll("CELU")
        await service._poll("AAPL")

        edgar.rows = [TAKEDOWN, QUARTERLY]
        await service._poll("AAPL")
        assert alerts == [("AAPL", "424B5")]


class TestPollLoop:
    """The loop itself, not just the poll it calls.

    Driven with a very short interval rather than a fake clock: the thing
    worth proving is that a failing poll does not kill the loop and that
    cancellation still gets through, both of which are about real await
    points.
    """

    async def test_polls_the_watched_symbol_on_the_interval(self, alerts):
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        service._poll_seconds = 0.01
        service.watch("CELU")

        await service.start()
        await asyncio.sleep(0.05)
        await service.stop()

        assert edgar.calls and set(edgar.calls) == {"CELU"}

    async def test_it_polls_nothing_until_a_symbol_is_watched(self, alerts):
        edgar = FakeEdgar([QUARTERLY])
        service = watcher(edgar, alerts)
        service._poll_seconds = 0.01

        await service.start()
        await asyncio.sleep(0.05)
        await service.stop()

        assert edgar.calls == []

    async def test_a_failing_poll_does_not_kill_the_loop(self, alerts):
        """EDGAR having a bad minute must not silently end the watch for the
        rest of the session."""
        edgar = FakeEdgar([QUARTERLY])
        calls = {"n": 0}

        async def refresh(symbol):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("503 from EDGAR")
            return [QUARTERLY]

        edgar.refresh_filings = refresh
        service = watcher(edgar, alerts)
        service._poll_seconds = 0.01
        service.watch("CELU")

        await service.start()
        await asyncio.sleep(0.06)
        await service.stop()

        assert calls["n"] >= 2

    async def test_stop_is_idempotent(self, alerts):
        service = watcher(FakeEdgar(), alerts)
        service._poll_seconds = 0.01
        await service.start()
        await service.stop()
        await service.stop()

    async def test_start_twice_runs_one_loop(self, alerts):
        service = watcher(FakeEdgar(), alerts)
        await service.start()
        first = service._task
        await service.start()
        assert service._task is first
        await service.stop()


class TestLifecycle:
    async def test_start_without_edgar_is_a_no_op(self):
        service = FilingWatchService(None)
        await service.start()
        await service.stop()

    async def test_stop_is_safe_before_start(self):
        await FilingWatchService(FakeEdgar()).stop()

    async def test_watch_selects_the_symbol(self):
        service = FilingWatchService(FakeEdgar())
        service.watch("CELU")
        assert service._symbol == "CELU"
