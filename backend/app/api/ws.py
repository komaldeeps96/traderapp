"""The WebSocket endpoint.

One connection owns one chart subscription. Everything a client sends is
validated against the command union before it reaches a service, and any
rejection comes back as an ``error`` message rather than closing the socket —
a mistyped symbol should not cost the user their connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..domain.protocol import (
    ConfigureScannerCommand,
    StopScannerCommand,
    SubscribeCommand,
    error_message,
    parse_command,
    quote_message,
)
from ..services.connection import ClientConnection
from ..services.container import AppContainer, get_container

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket) -> None:
    container: AppContainer = get_container()
    await websocket.accept()

    connection = ClientConnection(websocket)
    await container.hub.register(connection)

    # Opening frames: what the data source is doing, whatever each scanner
    # tier and regime already have, and the request-budget meters — so a
    # client joining mid-session is not staring at nothing.
    connection.send(container.status_payload())
    for scanner_id in container.scanners:
        connection.send(container.scanner_payload(scanner_id))
    connection.send(container.regime_payload())
    connection.send(container.api_payload())

    try:
        while True:
            raw = await websocket.receive_text()
            await _dispatch(container, connection, raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("client %s failed", connection.id)
    finally:
        await container.hub.unregister(connection)


async def _dispatch(container: AppContainer, connection: ClientConnection, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except ValueError:
        connection.send(error_message("bad_json", "Message was not valid JSON."))
        return

    try:
        command = parse_command(payload)
    except ValidationError as exc:
        connection.send(error_message("bad_command", _explain(exc)))
        return

    action = command.action

    if action == "ping":
        connection.send({"type": "pong"})

    elif action == "subscribe":
        await _subscribe(container, connection, command)

    elif action == "unsubscribe":
        await container.hub.unsubscribe(connection)

    elif action == "scanner.configure":
        await _configure_scanner(container, connection, command)

    elif action == "scanner.stop":
        await _stop_scanner(container, connection, command)


_pending_prefetches: set[asyncio.Task] = set()


def _prefetch_stats(container: AppContainer, symbol: str) -> None:
    """Warm the reference stats without holding up the snapshot.

    When they land, the symbol is touched so the next broadcast tick carries
    an info strip with the float and market cap filled in.
    """

    async def run() -> None:
        with contextlib.suppress(Exception):
            await container.symbol_info.prefetch(symbol)
            container.market_data.touch(symbol)

    task = asyncio.create_task(run())
    _pending_prefetches.add(task)
    task.add_done_callback(_pending_prefetches.discard)


async def _subscribe(
    container: AppContainer, connection: ClientConnection, command: SubscribeCommand
) -> None:
    symbol = command.symbol
    timeframe = command.parsed_timeframe

    # TradingView reference stats ride the regime switch: with it off — as
    # in the test suites — nothing here may leave the machine.
    if container.settings.regime.enabled:
        _prefetch_stats(container, symbol)
    snapshots = await container.hub.subscribe(
        connection, symbol, timeframe, command.parsed_extra_timeframes
    )
    if not snapshots:
        # Either nothing came back for the symbol, or the client already moved
        # on. Only the first case is worth reporting.
        if connection.subscription == (symbol, timeframe):
            connection.send(
                error_message(
                    "no_data",
                    f"No market data available for {symbol}. "
                    "Check the ticker, or that a data provider is connected.",
                )
            )
        return

    # Primary first, then the mini charts.
    for snapshot in snapshots:
        connection.send(snapshot)
    # The freshest quote rides along so the spread readout never opens blank.
    quote = container.quotes.get(symbol)
    if quote is not None:
        connection.send(quote_message(symbol, quote))
    await container.state.save(symbol, timeframe.value)


async def _configure_scanner(
    container: AppContainer, connection: ClientConnection, command: ConfigureScannerCommand
) -> None:
    scanner = container.scanners.get(command.scanner_id)
    if scanner is None:
        connection.send(error_message("scanner", f"Unknown scanner {command.scanner_id!r}."))
        return

    ok, message = await scanner.configure(
        scan_code=command.scan_code,
        above_price=command.above_price,
        below_price=command.below_price,
        above_volume=command.above_volume,
        market_cap_above=command.market_cap_above,
        market_cap_below=command.market_cap_below,
        change_perc_above=command.change_perc_above,
    )
    if not ok and message:
        connection.send(error_message("scanner", message))
    else:
        # The filters applied; remember them so the next startup opens with
        # the scan the user actually uses, not the YAML defaults.
        await container.state.save_scanner(command.scanner_id, scanner.state.config.to_dict())
    connection.send(container.scanner_payload(command.scanner_id))


async def _stop_scanner(
    container: AppContainer, connection: ClientConnection, command: StopScannerCommand
) -> None:
    scanner = container.scanners.get(command.scanner_id)
    if scanner is None:
        connection.send(error_message("scanner", f"Unknown scanner {command.scanner_id!r}."))
        return
    await scanner.stop()


def _explain(exc: ValidationError) -> str:
    """Turn a validation error into one readable sentence for the client."""
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"] if part != "command")
    detail = first.get("msg", "is invalid")
    return f"{location or 'message'}: {detail}"
