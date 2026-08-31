"""Application settings.

Resolution order (highest priority first):

1. explicit constructor arguments (used by tests)
2. environment variables, e.g. ``TRADERAPP_ALPACA__KEY_ID``
3. ``.env``
4. ``config/settings.yaml``
5. field defaults

Nested settings use a double underscore, so ``alpaca.key_id`` is set with
``TRADERAPP_ALPACA__KEY_ID``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = BACKEND_ROOT / "config"

AlpacaFeed = Literal["sip", "iex", "delayed_sip", "otc"]


class AlpacaSettings(BaseModel):
    """Alpaca market data credentials and endpoints.

    ``feed`` selects the data entitlement:

    - ``iex``         free real-time, IEX exchange only
    - ``delayed_sip`` free full-market tape, delayed 15 minutes
    - ``sip``         paid full-market tape, real time
    """

    key_id: str = ""
    secret_key: str = ""
    feed: AlpacaFeed = "iex"
    # Live Benzinga headlines over their news socket. Separate from ``feed``,
    # which governs the price tape only: news is a different product and is
    # not delayed. Off in tests, where nothing may leave the machine.
    news_stream: bool = True
    data_url: str = "https://data.alpaca.markets"
    stream_url: str = "wss://stream.data.alpaca.markets"
    # Alpaca caps a single bars request at 10k rows.
    page_limit: int = Field(default=10_000, ge=1, le=10_000)
    timeout_seconds: float = Field(default=20.0, gt=0)
    # Rebuilding 10s bars walks the raw trade tape newest-first; a runaway
    # ticker prints millions of trades a day, so the walk is capped in pages
    # of ``page_limit`` and keeps the most recent window when it truncates.
    max_trade_pages: int = Field(default=40, ge=1, le=200)

    @property
    def enabled(self) -> bool:
        return bool(self.key_id and self.secret_key)

    @property
    def is_delayed(self) -> bool:
        return self.feed == "delayed_sip"


class IBKRSettings(BaseModel):
    """Interactive Brokers TWS / Gateway connection."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7496
    client_id: int = 1
    # How long to wait for TWS before giving up and falling back to Alpaca.
    connect_timeout_seconds: float = Field(default=6.0, gt=0)
    # Cap on reconnect backoff once TWS has gone away.
    max_reconnect_delay_seconds: float = Field(default=30.0, gt=0)


class HistorySettings(BaseModel):
    """How much history to load for each base timeframe."""

    intraday_days: int = Field(default=5, ge=1, le=30)
    # Alpaca serves the daily base in one request capped at ``page_limit``
    # rows, so a wider window costs nothing until it stops filling the page.
    # Forty years is where ~252 sessions a year meets that 10k cap; the
    # weekly and monthly levels drawn off this series get the full record
    # instead of whatever three years happened to contain.
    daily_years: int = Field(default=40, ge=1, le=50)
    max_bars_in_memory: int = Field(default=20_000, ge=100)
    # IBKR is only asked for the most recent slice; Alpaca covers the rest.
    # (The 10-second window is not configured here: it always runs from the
    # previous session's 16:00 close, split IBKR-recent / Alpaca-earlier.)
    ibkr_recent_seconds: int = Field(default=3600, ge=60)


class EdgarSettings(BaseModel):
    """SEC EDGAR — the fundamentals and filings source.

    No key and no account, but SEC does require a User-Agent that identifies
    the caller and carries a contact address, and blocks the ones that do
    not. Set a real address here before running this against production
    EDGAR; the default is deliberately obviously unset.
    """

    enabled: bool = True
    user_agent: str = "traderapp/1.0 (contact: set edgar.user_agent in settings)"
    # How often the filing trail of the focused symbol is re-read, looking for
    # an offering that landed mid-session. Well inside SEC's rate limit at one
    # symbol; the XBRL facts are not re-fetched on this cadence.
    filing_poll_seconds: float = Field(default=60.0, ge=15.0)


class RegimeSettings(BaseModel):
    """The TradingView market-regime poll.

    The filter fields that used to live here belonged to a screener panel
    that no longer exists; only the switch and the cadence are read now.
    """

    enabled: bool = True
    refresh_seconds: float = Field(default=15.0, ge=5.0)


# The stock types IBKR's scanner knows about, from its own scanner-parameters
# document (the STKTYPE filter's combo values).
STOCK_TYPES = frozenset({"CORP", "ADR", "ETF", "ETN", "REIT", "CEF", "ETMF"})


class ScannerSettings(BaseModel):
    """Defaults for the IBKR market scanner."""

    enabled: bool = True
    scan_code: str = "TOP_TRADE_RATE"

    # Capitalisation does the size filtering, so price and volume are left
    # open: a floor on either only discards names the market-cap band has
    # already qualified. The ceiling stays because the workflow does not
    # trade above it.
    above_price: float | None = None
    below_price: float | None = 50.0
    # Trades per minute. Five hundred is a tape that is actually being
    # worked; below it a name is drifting, however much volume it has already
    # accumulated today.
    above_trade_rate: int | None = 500

    # How many rows a panel shows is not settable here: it belongs to the
    # market-cap tier, beside the band, in app/domain/scanner.py's
    # SCANNER_TIERS, where every tier now runs at the same depth.

    # Market cap is no longer a single band here — the four scanner tiers
    # (app/domain/scanner.py, SCANNER_TIERS) each carry their own band, e.g.
    # the small-cap tier's $1M floor drops sub-$1M shells that can top a
    # print-rate ranking on a few thousand dollars of churn, and its $2B
    # ceiling is the real small-cap gate: without one the trade-rate scan
    # fills with large caps that merely have a low share price (Coupang,
    # SoFi and Grab all cleared a $1-20 band in testing). Price is not a
    # proxy for size.

    # Up 10%+ on the day — the same gate the TradingView screen uses, so the
    # two panels answer about the same universe. Applied as a subscription
    # filter and again to the rows, since scan codes honour it inconsistently.
    change_perc_above: float | None = 10.0

    # How far back rank velocity looks.
    #
    # Well inside IBKR's ranking push, measured at ~33s: the delta therefore
    # reports reordering driven by the tape within one membership generation,
    # rather than the wholesale churn a push brings. Rows that arrive with a
    # push show as ``entered`` instead, which is the honest description.
    #
    # At the 3s emit interval the baseline lands ~2 emissions back, so this
    # reads immediate jostling rather than a sustained climb.
    rank_window_seconds: float = Field(default=5.0, gt=0)

    # STK.US.MAJOR is Listed/NASDAQ. Per-exchange codes exist and combine as a
    # comma-separated list — "STK.NYSE,STK.AMEX,STK.ARCA,STK.NASDAQ" is MAJOR
    # minus BATS, which lists almost no operating companies. STK.US adds
    # OTCMarkets, STK.US.MINOR is OTC alone.
    location_code: str = "STK.US.MAJOR"
    instrument: str = "STK"
    min_refresh_seconds: float = Field(default=3.0, gt=0)

    # ``instrument: STK`` still admits every stock-shaped product, so a
    # leveraged ETF like SNXX ("TRADR 2X LONG SNDK DAILY ETF") can top a
    # trade-rate scan on pure derivative churn. Excluding the fund family
    # leaves operating companies.
    #
    # Excluded rather than restricted to CORP on purpose: ``inc:CORP`` also
    # drops ADRs, and plenty of small-cap runners are ADRs — TAL Education
    # was filtered out by it in testing.
    exclude_stock_types: list[str] = Field(default_factory=lambda: ["ETF", "ETN", "CEF", "ETMF"])

    @field_validator("exclude_stock_types")
    @classmethod
    def _known_stock_types(cls, value: list[str]) -> list[str]:
        """Reject unknown codes loudly.

        IBKR ignores a malformed stock-type filter in silence — the scan just
        keeps returning ETFs — so a typo here has to fail at startup rather
        than at the moment it matters.
        """
        unknown = [code for code in value if code.upper() not in STOCK_TYPES]
        if unknown:
            raise ValueError(f"unknown stock type(s) {unknown}; valid: {sorted(STOCK_TYPES)}")
        return [code.upper() for code in value]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADERAPP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        yaml_file=str(CONFIG_DIR / "settings.yaml"),
        extra="ignore",
    )

    app_name: str = "TraderApp"
    log_level: str = "INFO"
    # Browsers enforce CORS on the REST calls; the WebSocket is exempt.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )

    default_symbol: str = "AAPL"
    default_timeframe: str = "10s"

    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    ibkr: IBKRSettings = Field(default_factory=IBKRSettings)
    history: HistorySettings = Field(default_factory=HistorySettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    regime: RegimeSettings = Field(default_factory=RegimeSettings)
    edgar: EdgarSettings = Field(default_factory=EdgarSettings)

    indicators_file: Path = CONFIG_DIR / "indicators.yaml"
    state_file: Path = CONFIG_DIR / "state.yaml"
    # Exchange rates for periods that have already closed, which never
    # change. Kept out of state.yaml because it is a cache, not a setting:
    # deleting it costs one refetch and nothing else.
    fx_cache_file: Path = CONFIG_DIR / "fx-rates.json"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # YAML sits last so real environment variables always win over a
        # checked-out config file.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
