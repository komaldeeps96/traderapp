"""Market scanner domain types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Curated subset of IBKR scan codes relevant to momentum trading. The full
# reqScannerParameters() list is mostly bonds/options/futures scans.
# TOP_TRADE_RATE leads: it ranks by IBKR's own trades-per-minute measure,
# which is exactly the attention read this scanner exists for — the per-row
# tape windows then carry the numbers IBKR's rank-only rows do not.
SCAN_CODES: tuple[dict[str, str], ...] = (
    {"code": "TOP_TRADE_RATE", "label": "Top Trade Rate"},
    {"code": "TOP_TRADE_COUNT", "label": "Top Trade Count"},
    {"code": "TOP_PERC_GAIN", "label": "Top % Gainers"},
    {"code": "TOP_PERC_LOSE", "label": "Top % Losers"},
    {"code": "MOST_ACTIVE", "label": "Most Active"},
    {"code": "HOT_BY_VOLUME", "label": "Hot by Volume"},
    {"code": "TOP_VOLUME_RATE", "label": "Top Volume Rate"},
    {"code": "HALTED", "label": "Halted"},
)

VALID_SCAN_CODES = frozenset(entry["code"] for entry in SCAN_CODES)


@dataclass(slots=True)
class ScannerConfig:
    scan_code: str
    above_price: float | None = None
    below_price: float | None = None
    above_volume: int | None = None
    # Dollars. IBKR filters on these natively via the scanner subscription.
    market_cap_above: float | None = None
    market_cap_below: float | None = None
    # Percent change on the day; applied as a subscription filter and again
    # to the returned rows, because IBKR filter support varies by scan code.
    change_perc_above: float | None = None
    number_of_rows: int = 15

    def to_dict(self) -> dict:
        return asdict(self)

    def merged(self, **overrides: object) -> "ScannerConfig":
        """Apply the overrides that were supplied.

        ``None`` means "leave unchanged"; the sentinel ``"clear"`` relaxes a
        bound entirely so a filter can be switched off from the client.
        """
        data = self.to_dict()
        for key, value in overrides.items():
            if value is None:
                continue
            data[key] = None if value == "clear" else value
        return ScannerConfig(**data)  # type: ignore[arg-type]


@dataclass(slots=True)
class ScannerRow:
    rank: int
    symbol: str
    exchange: str = ""
    price: float | None = None
    pct_change: float | None = None
    volume: float | None = None
    # Sliding-window activity, maintained from raw trade prints rather than
    # IBKR's own opaque rate ticks.
    trades_1m: int = 0
    trades_5m: int = 0
    dollar_vol_1m: float = 0.0
    dollar_vol_5m: float = 0.0
    trades_day: float | None = None
    dollar_vol_day: float | None = None
    # Places gained over the rank-velocity window; positive is upward.
    # ``None`` while the window is still filling, or for a row that was not
    # on the list a window ago — ``entered`` distinguishes the two.
    rank_delta: int | None = None
    entered: bool = False
    # Reference numbers from TradingView, filled from its cache so the 3s
    # emission never waits on the network. None until the first fetch lands.
    float_shares: float | None = None
    market_cap: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ScannerState:
    config: ScannerConfig
    rows: list[ScannerRow] = field(default_factory=list)
    running: bool = False
