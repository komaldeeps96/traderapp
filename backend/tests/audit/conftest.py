"""Shared machinery for the audit: our bars, fetched as the terminal fetches them.

Everything here reaches the network, so the directory sits behind the `audit`
marker and is excluded from `pytest tests` by default.
"""

from __future__ import annotations

import asyncio
import warnings
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("yfinance", reason="install the audit extra: pip install -e '.[audit]'")

warnings.filterwarnings("ignore")


def relative_difference(ours: float, theirs: float) -> float:
    if theirs == 0:
        return 0.0 if ours == 0 else 1.0
    return abs(ours - theirs) / abs(theirs)


@pytest.fixture(scope="session")
def daily_bars():
    """Daily bars per symbol, over the window the terminal itself loads.

    The chart half has no published truth — nobody else computes a moving
    average over *our* bars — so what is checked is that our bars agree with
    everyone else's and our arithmetic lands where theirs does.

    The window is taken from the app's own setting rather than picked here: an
    exponential average never fully forgets its seed, so over three years a
    200-day EMA is still 0.27% from where it settles, which looks like an
    arithmetic error and is not one.
    """
    from app.core.settings import get_settings
    from app.domain.timeframes import Timeframe
    from app.providers.alpaca import AlpacaProvider

    loaded: dict[str, list] = {}

    def load(symbol: str) -> list:
        if symbol in loaded:
            return loaded[symbol]

        async def fetch():
            settings = get_settings()
            provider = AlpacaProvider(settings.alpaca)
            await provider.start()
            try:
                end = datetime.now(UTC)
                start = end - timedelta(days=365 * settings.history.daily_years)
                return await provider.fetch_bars(symbol, Timeframe.D1, start, end)
            finally:
                await provider.stop()

        loaded[symbol] = asyncio.run(fetch())
        return loaded[symbol]

    return load


@pytest.fixture(scope="session")
def minute_bars():
    """A few days of one-minute bars, for the session levels.

    Kept to the handful of symbols that need it: a week of minutes is a
    thousand times the rows a daily series is, and the session levels are the
    same code for every symbol.
    """
    from app.core.settings import get_settings
    from app.domain.timeframes import Timeframe
    from app.providers.alpaca import AlpacaProvider

    loaded: dict[str, list] = {}

    def load(symbol: str) -> list:
        if symbol not in loaded:

            async def fetch():
                provider = AlpacaProvider(get_settings().alpaca)
                await provider.start()
                try:
                    end = datetime.now(UTC)
                    return await provider.fetch_bars(
                        symbol, Timeframe.M1, end - timedelta(days=5), end
                    )
                finally:
                    await provider.stop()

            loaded[symbol] = asyncio.run(fetch())
        return loaded[symbol]

    return load
