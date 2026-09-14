"""The socket protocol is written twice: ``domain/protocol.py`` and
``frontend/src/types/protocol.ts``. A field renamed on one side only is a value
the terminal silently stops showing, so both are held to one set of names."""

from __future__ import annotations

import re
import typing
from pathlib import Path

from app.core.clock import now_epoch
from app.core.settings import TradingSettings
from app.domain import protocol
from app.domain.news import Catalyst, Headline
from app.domain.scanner import ScannerRow
from app.domain.screener import SymbolStats
from app.market.store import BarStore
from app.providers.ibkr_broker import IBKRBroker
from app.services.quotes import QuoteService
from app.services.symbol_info import SymbolInfoService
from app.services.trading import TradingService
from app.services.tv import TVDataService
from tests.unit.test_ibkr_broker import FakeTrade

PROTOCOL_TS = Path(__file__).resolve().parents[3] / "frontend/src/types/protocol.ts"

# Built as plain dicts on the server; `info` is checked against its builder.
UNTYPED = {"info", "pong"}


def _typescript() -> str:
    text = re.sub(r"/\*.*?\*/", "", PROTOCOL_TS.read_text(), flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _union(source: str, name: str) -> str:
    match = re.search(rf"^export type {name} =(.*?);\n\n", source, flags=re.S | re.M)
    assert match, f"{name} is not in protocol.ts"
    return match.group(1)


def _tag(pattern: str, body: str) -> str:
    match = re.search(pattern, body)
    assert match, body
    return match.group(1)


def ts_messages() -> dict[str, set[str]]:
    """``ServerMessage`` members' top-level fields, keyed by ``type``."""
    source = _typescript()
    bodies = dict(
        re.findall(r"^export interface (\w+)[^{]*\{(.*?)^\}", source, flags=re.S | re.M)
    )
    messages = {}
    for name in re.findall(r"\|\s*(\w+)", _union(source, "ServerMessage")):
        body = bodies[name]
        messages[_tag(r'\n  type: "(\w+)";', body)] = set(
            re.findall(r"^  (\w+)\??:", body, flags=re.M)
        )
    return messages


def ts_commands() -> dict[str, set[str]]:
    """``ClientCommand`` members' fields, keyed by ``action``."""
    members = re.findall(r"\{(.*?)\}", _union(_typescript(), "ClientCommand"), flags=re.S)
    return {
        _tag(r'action: "([\w.]+)"', body): set(re.findall(r"(\w+)\??:", body))
        for body in members
    }


def py_messages() -> dict[str, set[str]]:
    messages = {}
    for value in vars(protocol).values():
        if typing.is_typeddict(value):
            hints = typing.get_type_hints(value)
            if "type" in hints:
                (kind,) = typing.get_args(hints["type"])
                messages[kind] = set(hints)
    return messages


def py_commands() -> dict[str, set[str]]:
    union, _ = typing.get_args(protocol.ClientCommand)
    return {
        typing.get_args(model.model_fields["action"].annotation)[0]: set(model.model_fields)
        for model in typing.get_args(union)
    }


def test_both_sides_declare_the_same_server_messages():
    assert set(ts_messages()) == set(py_messages()) | UNTYPED


def test_server_messages_carry_the_same_fields():
    ts = ts_messages()
    py = py_messages()
    assert {kind: ts[kind] for kind in py} == py


def test_the_info_frame_carries_what_the_client_reads():
    tv = TVDataService(fetch=lambda q: {"totalCount": 0, "data": []})
    stats = SymbolStats(symbol="RUN", float_shares=5_000_000, market_cap=40_000_000)
    stats.fetched_at = now_epoch()
    tv._stats_cache["RUN"] = stats

    payload = SymbolInfoService(BarStore(), tv).build("RUN")

    assert payload is not None
    assert set(payload) == ts_messages()["info"]


def test_commands_carry_the_same_fields():
    assert ts_commands() == py_commands()


# ── nested payloads ────────────────────────────────────────────────────
# Plain dicts on the server, so each is held to the code that builds it.


def ts_interface(name: str) -> set[str]:
    match = re.search(rf"^export interface {name}\b[^{{]*\{{(.*?)^\}}", _typescript(), flags=re.S | re.M)
    assert match, f"{name} is not in protocol.ts"
    return set(re.findall(r"^  (\w+)\??:", match.group(1), flags=re.M))


def test_the_trading_state_matches():
    settings = TradingSettings()
    state = TradingService(IBKRBroker(settings), QuoteService(), settings).state()
    assert set(state) == ts_interface("TradingState")


def test_a_position_row_matches():
    broker = IBKRBroker(TradingSettings())
    broker._positions = {"AAPL": 5}
    assert set(broker.positions()[0]) == ts_interface("PositionRow")


def test_an_order_row_matches():
    wire = IBKRBroker(TradingSettings())._order_wire(FakeTrade("AAPL", "BUY", 1))
    assert set(wire) == ts_interface("OrderRow")


def test_a_scanner_row_matches():
    assert set(ScannerRow(rank=1, symbol="AAPL").to_dict()) == ts_interface("ScannerRow")


def test_a_headline_matches():
    row = Headline("a1", "BZ", 0, "Headline", next(iter(Catalyst))).to_dict()
    assert set(row) == ts_interface("Headline")

