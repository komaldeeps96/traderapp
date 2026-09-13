"""Shutdown reaches the news summary's readings in flight."""

from __future__ import annotations

import asyncio

from app.core.settings import NewsAISettings
from app.services.news_ai import NewsAIService


async def test_stopping_cancels_every_reading_in_flight():
    service = NewsAIService(NewsAISettings(enabled=False), news=None)
    readings = [asyncio.create_task(asyncio.sleep(30)) for _ in range(2)]
    service._running = {"WETO": readings[0], "FNGR": readings[1]}

    await service.stop()
    assert all(reading.cancelled() for reading in readings)


async def test_stopping_with_nothing_running_is_quiet():
    await NewsAIService(NewsAISettings(enabled=False), news=None).stop()
