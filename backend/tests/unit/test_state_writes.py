"""The state file is written whole or not at all.

It holds the watchlist, every scanner tier's filters and the indicator
toggles; a truncated file loads as nothing and all of it is silently lost.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.state import StateStore


def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.yaml", "AAPL", "10s")


async def test_a_write_that_dies_halfway_leaves_the_last_good_file(tmp_path, monkeypatch):
    first = store(tmp_path)
    await first.save_watchlist(["AAPL", "TSLA"])

    real_write = Path.write_text

    def dies_halfway(self, text, *args, **kwargs):
        real_write(self, text[: len(text) // 2], *args, **kwargs)
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", dies_halfway)
    await first.save_watchlist(["NVDA"])
    monkeypatch.undo()

    assert store(tmp_path).watchlist() == ["AAPL", "TSLA"]


async def test_saves_landing_together_end_on_the_latest(tmp_path):
    state = store(tmp_path)
    await asyncio.gather(*(state.save(f"S{index}", "1m") for index in range(20)))
    assert store(tmp_path).symbol == "S19"


async def test_no_temporary_file_is_left_behind(tmp_path):
    await store(tmp_path).save("FGI", "1m")
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.yaml"]
