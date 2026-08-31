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

# What a tier shows when it does not ask for more. Four concurrent scanners
# is a lot of screen and a lot of IBKR market-data lines, so depth is spent
# where it earns its keep rather than raised across the board.
DEFAULT_SCANNER_ROWS = 5

# The four market-cap bands the terminal runs concurrently, one IBKR
# scanner subscription each. Bands partition cleanly with no overlap: large
# cap's ceiling is mega cap's floor. The size gate does the real filtering —
# price and volume stay open on each tier so a low share price or a quiet
# day doesn't discard a name the market cap has already qualified.
#
# ``rows`` is the depth of the panel, and it is a property of the tier rather
# than of the client for the same reason the band is: a state file written
# before a depth changed must not pin the panel back to the old number.
#
# Every tier shows five. Small cap ran at ten for a while, being the tier this
# terminal exists for, but four panels stacked in one 320px column share their
# height with the key levels underneath, and the depth was spent on names
# nobody scrolled to.
SCANNER_TIERS: tuple[dict[str, object], ...] = (
    {
        "id": "small_cap",
        "label": "Small Cap",
        "market_cap_above": 1_000_000,
        "market_cap_below": 2_000_000_000,
        "rows": DEFAULT_SCANNER_ROWS,
    },
    {
        "id": "mid_cap",
        "label": "Mid Cap",
        "market_cap_above": 2_000_000_000,
        "market_cap_below": 10_000_000_000,
        "rows": DEFAULT_SCANNER_ROWS,
    },
    {
        "id": "large_cap",
        "label": "Large Cap",
        "market_cap_above": 10_000_000_000,
        "market_cap_below": 200_000_000_000,
        "rows": DEFAULT_SCANNER_ROWS,
    },
    {
        "id": "mega_cap",
        "label": "Mega Cap",
        "market_cap_above": 200_000_000_000,
        "market_cap_below": None,
        "rows": DEFAULT_SCANNER_ROWS,
    },
)

SCANNER_TIER_IDS = frozenset(str(tier["id"]) for tier in SCANNER_TIERS)
SCANNER_TIER_BY_ID = {str(tier["id"]): tier for tier in SCANNER_TIERS}


@dataclass(slots=True)
class ScannerConfig:
    scan_code: str
    above_price: float | None = None
    below_price: float | None = None
    # Trades per minute, IBKR's own ``tradeRateAbove``. This replaced a
    # cumulative-volume floor, which asks the wrong question for this
    # workflow: volume is what a name has already done today, and by the time
    # a runner has the volume it is often over. Trade rate is what the tape is
    # doing *now*, which is the thing being scanned for.
    #
    # Verified against a live TWS: on one small-cap scan, no filter and >=100
    # both returned ten rows, >=500 returned two, and >=5000 returned none.
    above_trade_rate: int | None = None
    # Dollars. IBKR filters on these natively via the scanner subscription.
    market_cap_above: float | None = None
    market_cap_below: float | None = None
    # Percent change on the day; applied as a subscription filter and again
    # to the returned rows, because IBKR filter support varies by scan code.
    change_perc_above: float | None = None
    # Set from the tier, never from the client or the state file — see
    # ScannerService.
    number_of_rows: int = DEFAULT_SCANNER_ROWS

    def to_dict(self) -> dict:
        return asdict(self)

    def merged(self, **overrides: object) -> ScannerConfig:
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
