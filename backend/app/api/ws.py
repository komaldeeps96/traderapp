"""The WebSocket endpoint.

One connection owns one chart subscription. Everything a client sends is
validated against the command union before it reaches a service, and a
rejection or a failure comes back as an ``error`` message rather than closing
the socket.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..domain.protocol import (
    BuyCommand,
    CancelAllCommand,
    ClientCommand,
    ConfigureScannerCommand,
    SellCommand,
    SetIndicatorVisibilityCommand,
    StopScannerCommand,
    SubscribeCommand,
    WatchlistAddCommand,
    WatchlistRemoveCommand,
    error_message,
    parse_command,
    quote_message,
)
from ..services.connection import ClientConnection
from ..services.container import AppContainer, get_container
from .origin import origin_allowed

logger = logging.getLogger(__name__)

# RFC 6455: a handshake refused on policy.
POLICY_VIOLATION = 1008

REMOTE_REFUSAL = "Orders are accepted only from this machine (trading.allow_remote is off)."
DISARMED_REFUSAL = "This window has not armed the order strip; press ARM first."


async def websocket_endpoint(websocket: WebSocket) -> None:
    container: AppContainer = get_container()
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, websocket.headers.get("host"), container.settings):
        logger.warning("Refused a WebSocket from %s", origin)
        await websocket.close(code=POLICY_VIOLATION)
        return
    await websocket.accept()

    connection = ClientConnection(websocket)
    loads: set[asyncio.Task] = set()
    try:
        await container.hub.register(connection)
        await _send_opening_frames(container, connection)
        while True:
            command = _parse(connection, await websocket.receive_text())
            if command is None:
                continue
            if command.action in ("subscribe", "unsubscribe"):
                for load in loads:
                    load.cancel()
            if command.action == "subscribe":
                # A history load can take seconds. Off the receive loop, so a
                # sell or a cancel sent meanwhile is read at once, not after it.
                load = asyncio.create_task(_run(container, connection, command))
                loads.add(load)
                load.add_done_callback(loads.discard)
            else:
                await _run(container, connection, command)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("client %s failed", connection.id)
    finally:
        for load in loads:
            load.cancel()
        await asyncio.gather(*loads, return_exceptions=True)
        await container.hub.unregister(connection)


async def _send_opening_frames(container: AppContainer, connection: ClientConnection) -> None:
    """What the data source is doing, whatever each scanner tier and regime
    already have, and the request-budget meters — so a client joining
    mid-session is not staring at nothing."""
    connection.send(container.fanout.status_payload())
    for scanner_id in container.scanners:
        connection.send(container.fanout.scanner_payload(scanner_id))
    connection.send(container.fanout.regime_payload())
    connection.send(container.fanout.api_payload())
    # Sent even with trading off, so the strip can say so rather than render
    # as a live panel that silently does nothing.
    connection.send(container.fanout.trading_payload())
    # Last, and only if there is one: the fetch reaches TradingView, and
    # nothing above it should wait on the network.
    if container.watchlist.symbols():
        connection.send(await container.fanout.watchlist_payload())


def _parse(connection: ClientConnection, raw: str) -> ClientCommand | None:
    """The command in ``raw``, or None after telling the client why not."""
    try:
        payload = json.loads(raw)
    except ValueError:
        connection.send(error_message("bad_json", "Message was not valid JSON."))
        return None
    try:
        return parse_command(payload)
    except ValidationError as exc:
        action = payload.get("action") if isinstance(payload, dict) else None
        connection.send(
            error_message(
                "bad_command", _explain(exc), action=action if isinstance(action, str) else None
            )
        )
        return None


async def _run(container: AppContainer, connection: ClientConnection, command) -> None:
    try:
        await _handle(container, connection, command)
    except Exception:
        logger.exception("%s failed for client %s", command.action, connection.id)
        connection.send(
            error_message(
                "server", f"The server failed on {command.action}.", action=command.action
            )
        )


async def _handle(container: AppContainer, connection: ClientConnection, command) -> None:
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

    elif action == "indicators.visibility":
        await _save_indicator_visibility(container, command)

    elif action in ("watchlist.add", "watchlist.remove"):
        await _edit_watchlist(container, command)

    elif action == "trade.arm":
        connection.armed = command.armed

    elif action in ("trade.buy", "trade.sell", "trade.cancel_all"):
        await _trade(container, connection, command)


async def _trade(
    container: AppContainer,
    connection: ClientConnection,
    command: BuyCommand | SellCommand | CancelAllCommand,
) -> None:
    """Place or cancel, then tell everyone what the account looks like.

    The command carries a dollar amount or a fraction, never a share count —
    ``_Command`` forbids extra fields. Sizing happens in TradingService against
    the freshest quote and IBKR's own position.

    A refusal comes back as an ``error`` on the asking connection *and* leaves a
    note on the broadcast state: an order that silently did not go is the
    failure this panel exists to remove.
    """
    places = command.action != "trade.cancel_all"
    if places and container.trading.enabled and not (
        connection.is_local or container.settings.trading.allow_remote
    ):
        connection.send(error_message("trade", REMOTE_REFUSAL, action=command.action))
        return
    if places and container.trading.enabled and not connection.armed:
        connection.send(error_message("trade", DISARMED_REFUSAL, action=command.action))
        return

    if command.action == "trade.buy":
        result = await container.trading.buy(command.symbol, command.dollars)
    elif command.action == "trade.sell":
        result = await container.trading.sell(command.symbol, command.fraction)
    else:
        result = await container.trading.cancel_all()

    if not result.get("ok"):
        message = str(result.get("message") or "Order refused.")
        connection.send(error_message("trade", message, action=command.action))
    container.hub.broadcast(container.fanout.trading_payload())


async def _edit_watchlist(
    container: AppContainer, command: WatchlistAddCommand | WatchlistRemoveCommand
) -> None:
    """Add or drop one symbol, then tell every client the whole list.

    The list lives in one file, not per connection, so a name added on one
    window appears on the others.
    """
    if command.action == "watchlist.add":
        await container.watchlist.add(command.symbol)
    else:
        await container.watchlist.remove(command.symbol)
    container.hub.broadcast(await container.fanout.watchlist_payload())


_pending_prefetches: set[asyncio.Task] = set()


def _prefetch_stats(container: AppContainer, symbol: str) -> None:
    """Warm the reference stats without holding up the snapshot.

    When they land, the symbol is touched so the next broadcast tick carries
    an info strip with the float and market cap filled in.
    """

    async def run() -> None:
        # Two separate attempts: an IBKR news timeout must not cost the
        # reference stats their touch, and vice versa.
        try:
            await container.symbol_info.prefetch(symbol)
            container.market_data.touch(symbol)
        except Exception:
            logger.warning("Reference stats prefetch failed for %s", symbol, exc_info=True)
        try:
            await container.news.prefetch(symbol)
        except Exception:
            logger.warning("News prefetch failed for %s", symbol, exc_info=True)
        # The watcher follows whichever chart is open; the baseline is taken
        # on its first poll, so opening a company that raised last week does
        # not fire an alarm about it.
        container.filing_watch.watch(symbol)

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
                    action="subscribe",
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


async def _save_indicator_visibility(
    container: AppContainer, command: SetIndicatorVisibilityCommand
) -> None:
    """Persist one timeframe's indicator toggles, as deltas.

    The client sends the whole picture; only what differs from the config is
    written, so a changed default in `indicators.yaml` reaches charts the user
    never touched.

    Ids the config no longer defines are dropped here, where the specs are, so a
    removed indicator cannot be resurrected by a stale saved value.
    """
    timeframe = command.parsed_timeframe
    defaults = {
        spec.id: option.enabled
        for spec in container.specs
        if (option := spec.option_for(timeframe)) is not None
    }
    overrides = {
        name: visible
        for name, visible in command.visible.items()
        if name in defaults and defaults[name] != visible
    }
    await container.state.save_indicators(timeframe.value, overrides)


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
        above_trade_rate=command.above_trade_rate,
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
    connection.send(container.fanout.scanner_payload(command.scanner_id))


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
