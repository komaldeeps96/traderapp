"""Shared test fixtures.

The application is exercised for real — real services, real routing, real
WebSocket — with only the upstream HTTP and socket boundaries stubbed. Nothing
test-shaped is injected into the app itself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import NY_TZ
from app.domain.bars import Bar

# ── time helpers ───────────────────────────────────────────────────────


def ny_epoch(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Epoch seconds for a New York wall-clock moment."""
    return int(datetime(year, month, day, hour, minute, tzinfo=NY_TZ).timestamp())


def utc_dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ── bar builders ───────────────────────────────────────────────────────


def make_bar(time: int, close: float, *, volume: float = 100.0, trades: float = 5.0) -> Bar:
    """A bar with a small, predictable range around ``close``."""
    return Bar(
        time=time,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=volume,
        trades=trades,
    )


def make_minute_series(start_epoch: int, closes: list[float]) -> list[Bar]:
    return [make_bar(start_epoch + i * 60, close) for i, close in enumerate(closes)]


def make_daily_series(start: datetime, closes: list[float]) -> list[Bar]:
    """Consecutive weekday daily bars starting at ``start``."""
    bars: list[Bar] = []
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(make_bar(int(day.timestamp()), close))
        day += timedelta(days=1)
    return bars


# ── Alpaca wire fixtures ───────────────────────────────────────────────


def alpaca_bar(moment: datetime, close: float, *, volume: float = 1000.0) -> dict:
    """One bar in Alpaca's REST/stream shape."""
    return {
        "t": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "o": close - 0.5,
        "h": close + 1.0,
        "l": close - 1.0,
        "c": close,
        "v": volume,
        "n": 25,
        "vw": close,
    }


def alpaca_bars_response(symbol: str, bars: list[dict], next_token: str | None = None) -> dict:
    return {"bars": {symbol: bars}, "next_page_token": next_token}


def minute_bars_for(symbol: str, start: datetime, count: int, base: float = 100.0) -> dict:
    """A run of consecutive minute bars with a gentle deterministic drift."""
    return alpaca_bars_response(
        symbol,
        [
            alpaca_bar(start + timedelta(minutes=i), base + (i % 17) * 0.1)
            for i in range(count)
        ],
    )


def trades_for(symbol: str, start: datetime, count: int, base: float = 100.0) -> dict:
    """A run of trades two seconds apart, in Alpaca's REST shape."""
    return {
        "trades": {
            symbol: [
                {
                    "t": (start + timedelta(seconds=2 * i)).astimezone(UTC).strftime(
                        "%Y-%m-%dT%H:%M:%S.%fZ"
                    ),
                    "p": base + (i % 13) * 0.05,
                    "s": 100 + (i % 5) * 10,
                }
                for i in range(count)
            ]
        },
        "next_page_token": None,
    }


def daily_bars_for(symbol: str, end: datetime, count: int, base: float = 95.0) -> dict:
    """``count`` weekday daily bars ending the day before ``end``."""
    entries: list[dict] = []
    day = end - timedelta(days=1)
    made = 0
    while made < count:
        if day.weekday() < 5:
            entries.append(alpaca_bar(day.replace(hour=5, minute=0), base + made * 0.25))
            made += 1
        day -= timedelta(days=1)
    entries.reverse()
    return alpaca_bars_response(symbol, entries)


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def minute_bars() -> list[Bar]:
    """A trading day from 09:30, 60 one-minute bars."""
    return make_minute_series(
        ny_epoch(2024, 3, 5, 9, 30), [100.0 + i * 0.1 for i in range(60)]
    )


@pytest.fixture
def daily_bars() -> list[Bar]:
    """40 consecutive weekday daily bars ending 2024-03-04."""
    return make_daily_series(
        datetime(2024, 1, 8, tzinfo=NY_TZ), [90.0 + i * 0.5 for i in range(40)]
    )


@pytest.fixture(autouse=True)
def _no_lingering_tasks():
    """Fail loudly if a test leaks a background task."""
    yield
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        return
    if loop.is_closed():
        return
