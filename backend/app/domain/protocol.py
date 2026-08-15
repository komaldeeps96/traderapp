"""The WebSocket wire protocol.

Inbound client commands are Pydantic models because they are untrusted — a
symbol ends up inside an upstream API request, so it is validated against a
strict pattern before it goes anywhere.

Outbound messages are built as plain dicts. A snapshot carries thousands of
bars and is rebuilt per subscription, so routing it through model validation
on every send buys nothing. The shapes are declared as TypedDicts and mirrored
in ``frontend/src/types/protocol.ts``; ``tests/unit/test_protocol.py`` locks
them down.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from .bars import Bar
from .quotes import Quote
from .sessions import is_extended_hours
from .timeframes import Timeframe

# Long enough for real tickers (BRK.B, GOOGL) without being an open field.
SYMBOL_PATTERN = r"^[A-Z][A-Z0-9.\-]{0,9}$"

# Hard cap: each row costs a live IBKR market-data line, and fifteen is
# already more than the workflow reads — the top handful is the trade.
MAX_SCANNER_ROWS = 15

# Every extra timeframe is another resample and another indicator pass per
# broadcast tick. The UI asks for two; the cap is only there so a malformed
# client cannot ask for a hundred.
MAX_EXTRA_TIMEFRAMES = 4


class DataSource(str, Enum):
    IBKR = "ibkr"
    ALPACA = "alpaca"
    NONE = "none"


# ── inbound: client → server ───────────────────────────────────────────


class _Command(BaseModel):
    model_config = {"extra": "forbid"}


class SubscribeCommand(_Command):
    action: Literal["subscribe"]
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    timeframe: str = Timeframe.M1.value
    # Additional timeframes on the same symbol, for the mini charts beside the
    # main one. The primary is what the session remembers and what a "no data"
    # error reports on; these are extra views, and asking for none is normal.
    extra_timeframes: list[str] = Field(default_factory=list, max_length=MAX_EXTRA_TIMEFRAMES)

    @field_validator("symbol", mode="before")
    @classmethod
    def _normalise_symbol(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("timeframe")
    @classmethod
    def _known_timeframe(cls, value: str) -> str:
        return Timeframe.parse(value).value

    @field_validator("extra_timeframes")
    @classmethod
    def _known_extra_timeframes(cls, value: list[str]) -> list[str]:
        return [Timeframe.parse(entry).value for entry in value]

    @property
    def parsed_timeframe(self) -> Timeframe:
        return Timeframe.parse(self.timeframe)

    @property
    def parsed_extra_timeframes(self) -> tuple[Timeframe, ...]:
        """The extras, deduplicated, with the primary removed.

        The primary is already subscribed; a client whose main chart sits on a
        timeframe one of its minis also wants should not be charged for it
        twice.
        """
        primary = self.parsed_timeframe
        seen: dict[Timeframe, None] = {}
        for entry in self.extra_timeframes:
            timeframe = Timeframe.parse(entry)
            if timeframe is not primary:
                seen[timeframe] = None
        return tuple(seen)


class UnsubscribeCommand(_Command):
    action: Literal["unsubscribe"]


# A numeric filter that can be set, left alone (omitted), or switched off
# entirely with the literal string "clear".
Clearable = float | Literal["clear"] | None


class ConfigureScannerCommand(_Command):
    action: Literal["scanner.configure"]
    scan_code: str | None = Field(default=None, max_length=40)
    above_price: float | None = Field(default=None, ge=0, le=1_000_000)
    below_price: float | None = Field(default=None, ge=0, le=1_000_000)
    above_volume: int | None = Field(default=None, ge=0)
    market_cap_above: Clearable = None
    market_cap_below: Clearable = None
    change_perc_above: Clearable = None
    number_of_rows: int | None = Field(default=None, ge=1, le=MAX_SCANNER_ROWS)


class StopScannerCommand(_Command):
    action: Literal["scanner.stop"]


class PingCommand(_Command):
    action: Literal["ping"]


ClientCommand = Annotated[
    SubscribeCommand
    | UnsubscribeCommand
    | ConfigureScannerCommand
    | StopScannerCommand
    | PingCommand,
    Field(discriminator="action"),
]


class ClientCommandEnvelope(BaseModel):
    """Wrapper that lets a raw payload be validated against the union."""

    command: ClientCommand


def parse_command(payload: object) -> ClientCommand:
    """Validate an arbitrary decoded JSON payload as a client command."""
    return ClientCommandEnvelope(command=payload).command  # type: ignore[arg-type]


# ── outbound: server → client ──────────────────────────────────────────


class WireBar(TypedDict, total=False):
    t: int  # epoch seconds, period open
    o: float
    h: float
    l: float  # noqa: E741 — the wire field name, matching o/h/l/c/v
    c: float
    v: float
    n: float  # trade count
    x: int  # present and 1 only for extended-hours bars


SeriesPoint = tuple[int, float]


class Snapshot(TypedDict):
    type: Literal["snapshot"]
    symbol: str
    timeframe: str
    bars: list[WireBar]
    series: dict[str, list[SeriesPoint]]
    source: str
    delayed: bool
    generated_at: int


class BarUpdate(TypedDict):
    type: Literal["bar"]
    symbol: str
    timeframe: str
    bar: WireBar
    series: dict[str, float]


# Functional syntax because "as" — the ask size — is a Python keyword.
QuoteMessage = TypedDict(
    "QuoteMessage",
    {
        "type": str,  # always "quote"
        "symbol": str,
        "bid": float,
        "ask": float,
        "bs": float,  # bid size, shares
        "as": float,  # ask size, shares
        "t": int,
    },
)


class StatusMessage(TypedDict):
    type: Literal["status"]
    source: str
    delayed: bool
    ibkr_connected: bool
    alpaca_available: bool
    message: str | None


class ApiUsageMessage(TypedDict):
    """Request-budget usage for each upstream, for the toolbar meters."""

    type: Literal["api"]
    alpaca: dict
    ibkr: dict


class ScannerMessage(TypedDict):
    type: Literal["scanner"]
    rows: list[dict]
    config: dict
    running: bool


class RegimeMessage(TypedDict):
    type: Literal["regime"]
    regime: dict
    running: bool
    error: str | None


class ErrorMessage(TypedDict):
    type: Literal["error"]
    code: str
    message: str


def encode_bar(bar: Bar, *, intraday: bool) -> WireBar:
    """Serialise a bar, tagging extended-hours periods for the chart tint.

    Daily bars span a whole session and are never tagged.
    """
    wire: WireBar = {
        "t": bar.time,
        "o": round(bar.open, 6),
        "h": round(bar.high, 6),
        "l": round(bar.low, 6),
        "c": round(bar.close, 6),
        "v": bar.volume,
        "n": bar.trades,
    }
    if intraday and is_extended_hours(bar.time):
        wire["x"] = 1
    return wire


def encode_bars(bars: list[Bar], *, intraday: bool) -> list[WireBar]:
    return [encode_bar(bar, intraday=intraday) for bar in bars]


def snapshot_message(
    *,
    symbol: str,
    timeframe: Timeframe,
    bars: list[Bar],
    series: dict[str, list[SeriesPoint]],
    source: DataSource,
    delayed: bool,
    generated_at: int,
) -> Snapshot:
    return {
        "type": "snapshot",
        "symbol": symbol,
        "timeframe": timeframe.value,
        "bars": encode_bars(bars, intraday=timeframe.is_intraday),
        "series": series,
        "source": source.value,
        "delayed": delayed,
        "generated_at": generated_at,
    }


def bar_message(
    *,
    symbol: str,
    timeframe: Timeframe,
    bar: Bar,
    series: dict[str, float],
) -> BarUpdate:
    return {
        "type": "bar",
        "symbol": symbol,
        "timeframe": timeframe.value,
        "bar": encode_bar(bar, intraday=timeframe.is_intraday),
        "series": series,
    }


def status_message(
    *,
    source: DataSource,
    delayed: bool,
    ibkr_connected: bool,
    alpaca_available: bool,
    message: str | None = None,
) -> StatusMessage:
    return {
        "type": "status",
        "source": source.value,
        "delayed": delayed,
        "ibkr_connected": ibkr_connected,
        "alpaca_available": alpaca_available,
        "message": message,
    }


def scanner_message(*, rows: list[dict], config: dict, running: bool) -> ScannerMessage:
    return {"type": "scanner", "rows": rows, "config": config, "running": running}


def quote_message(symbol: str, quote: Quote) -> QuoteMessage:
    return {"type": "quote", "symbol": symbol, **quote.to_wire()}  # type: ignore[typeddict-item]


def api_usage_message(snapshot: dict) -> ApiUsageMessage:
    return {"type": "api", "alpaca": snapshot["alpaca"], "ibkr": snapshot["ibkr"]}


def regime_message(*, regime: dict, running: bool, error: str | None) -> RegimeMessage:
    return {"type": "regime", "regime": regime, "running": running, "error": error}


def error_message(code: str, message: str) -> ErrorMessage:
    return {"type": "error", "code": code, "message": message}
