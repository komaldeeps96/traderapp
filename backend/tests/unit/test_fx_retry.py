"""A rate the endpoint refused is asked for again — after a while, not at once.

Held as None for the session, one 429 during a burst left those periods
unconverted until a restart; asked again every time, the same burst would pay
the retry delay on every line of every statement.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import fx as fx_module
from app.services.fx import FAILURE_RETRY_SECONDS, FxService
from tests.unit.test_fx_cache import Recording

DAY = date(2025, 12, 31)
YEAR = (date(2025, 1, 1), date(2025, 12, 31))


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch):
    monkeypatch.setattr(fx_module, "RETRY_DELAY_SECONDS", 0)


async def test_a_refused_closing_rate_is_not_asked_for_again_at_once():
    network, clock = Recording(rate=None), Clock()
    service = FxService(client=network, clock=clock)
    assert await service.closing_rate("CAD", DAY) is None
    asked = network.calls
    assert await service.closing_rate("CAD", DAY) is None
    assert network.calls == asked


async def test_a_refused_closing_rate_is_asked_for_again_later():
    network, clock = Recording(rate=None), Clock()
    service = FxService(client=network, clock=clock)
    await service.closing_rate("CAD", DAY)

    network.rate = 0.75
    clock.now += FAILURE_RETRY_SECONDS + 1
    assert await service.closing_rate("CAD", DAY) == 0.75


async def test_a_refused_average_is_asked_for_again_later():
    network, clock = Recording(rate=None), Clock()
    service = FxService(client=network, clock=clock)
    assert await service.average_rate("CAD", *YEAR) is None

    network.rate = 0.74
    clock.now += FAILURE_RETRY_SECONDS + 1
    assert await service.average_rate("CAD", *YEAR) == pytest.approx(0.74)


async def test_a_refusal_is_never_written_to_the_cache_file(tmp_path):
    path = tmp_path / "fx.json"
    service = FxService(client=Recording(rate=None), cache_path=path, clock=Clock())
    await service.closing_rate("CAD", DAY)
    await service.close()
    assert not path.exists() or "CAD" not in path.read_text()
