"""A scan that was running when TWS dropped starts again when it returns.

The provider side — forgetting its scans on the drop so nothing re-emits them —
is in test_ibkr_lines.py; this is the service's half of the same contract.
"""

from __future__ import annotations

from app.core.settings import ScannerSettings
from app.services.scanner import ScannerService


class FlakyIBKR:
    def __init__(self) -> None:
        self.is_available = True
        self.handler = None
        self.starts = 0

    def on_scanner(self, scanner_id, handler) -> None:
        self.handler = handler

    async def start_scanner(self, scanner_id, config) -> bool:
        self.starts += 1
        return True

    async def stop_scanner(self, scanner_id) -> None:
        return None


async def test_a_scan_running_when_tws_dropped_restarts_when_it_returns() -> None:
    ibkr = FlakyIBKR()
    scanner = ScannerService(ibkr, "small_cap", ScannerSettings(), None)
    assert await scanner.start()

    ibkr.is_available = False
    await scanner.refresh_availability()
    assert scanner.state.running is False

    ibkr.is_available = True
    await scanner.refresh_availability()
    assert ibkr.starts == 2
    assert scanner.state.running is True


async def test_a_scan_that_stayed_up_is_not_restarted() -> None:
    ibkr = FlakyIBKR()
    scanner = ScannerService(ibkr, "small_cap", ScannerSettings(), None)
    await scanner.start()
    await scanner.refresh_availability()
    assert ibkr.starts == 1
