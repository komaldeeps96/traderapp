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

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = BACKEND_ROOT / "config"

# Loopback, the three RFC 1918 ranges and Bonjour names.
HOME_NETWORK = (
    r"localhost"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|[A-Za-z0-9-]+\.local"
)

AlpacaFeed = Literal["sip", "iex", "delayed_sip", "otc"]


class _Section(BaseModel):
    # A misspelt or retired key fails at startup, rather than being dropped in
    # silence with its default left in force.
    model_config = ConfigDict(extra="forbid")


class AlpacaSettings(_Section):
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
    # The same walk for the 10s window's prior sessions. Twelve pages is 120k
    # trades — a whole previous session for a small-cap runner, the closing hours
    # for a mega cap, which is the part that has to join up with today.
    max_prior_session_pages: int = Field(default=12, ge=1, le=200)

    @property
    def enabled(self) -> bool:
        return bool(self.key_id and self.secret_key)

    @property
    def is_delayed(self) -> bool:
        return self.feed == "delayed_sip"


class IBKRSettings(_Section):
    """Interactive Brokers TWS / Gateway connection."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7496
    client_id: int = 1
    # How long to wait for TWS before giving up and falling back to Alpaca.
    connect_timeout_seconds: float = Field(default=6.0, gt=0)
    # Cap on reconnect backoff once TWS has gone away.
    max_reconnect_delay_seconds: float = Field(default=30.0, gt=0)


class TradingSettings(_Section):
    """Order entry through IBKR. See docs/order-entry.md.

    A second TWS connection on its own client id; the data client is
    ``readonly=True`` and pacing-limited. ``enabled`` is False here and in every
    test settings object — off, nothing reaches ``placeOrder``.

    TWS's **Read-Only API** checkbox (Global Configuration → API → Settings)
    enforces read-only; ``ib_async``'s ``readonly`` only skips the client's own
    open-order fetch.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    # The same TWS the data client uses. 7496 live, 7497 paper, 4001/4002 the
    # gateway equivalents; ``is_paper`` reads the port so the panel can say
    # which one it is rather than the user having to remember.
    port: int = 7496
    # The data client is 1.
    client_id: int = 2
    # Blank means the single managed account, which is the usual case.
    account: str = ""
    connect_timeout_seconds: float = Field(default=6.0, gt=0)
    max_reconnect_delay_seconds: float = Field(default=30.0, gt=0)

    # How far through the book a marketable limit is priced — a *cap*, not a
    # price. Larger of the two parts wins: five cents is 12 bps on a $40 name and
    # 12.5% on a $0.40 one, and at 15 bps they cross at $33.33.
    offset_cents: float = Field(default=5.0, gt=0)
    offset_bps: float = Field(default=15.0, ge=0)

    # The buy buttons, in dollars, and the sell buttons as fractions of the
    # position. Order is display order, left to right.
    buy_dollars: list[float] = Field(default_factory=lambda: [10.0, 25.0, 50.0])
    sell_fractions: list[float] = Field(default_factory=lambda: [0.25, 0.5, 1.0])
    # A quote that has not moved in this long is a feed that stopped, not a quiet book.
    max_quote_age_seconds: float = Field(default=15.0, gt=0)
    # Held plus bought, at the limit. The per-order cap alone bounds nothing:
    # enough clicks build any size.
    max_position_dollars: float = Field(default=300.0, gt=0)

    # DAY over IOC: both essentially always fill at these sizes, but DAY's
    # failure is a resting order that shows in the working count, while IOC's is
    # a sell that silently cancelled and left a position believed closed.
    tif: Literal["DAY", "IOC", "GTC"] = "DAY"

    # Not optional for this workflow. Small-cap momentum runs pre-market, and
    # without this a limit order simply sits unfilled until 09:30. It is also
    # why these are limit orders: TWS refuses market orders outside RTH.
    outside_rth: bool = True

    # Hard server-side ceiling on one order's notional, checked before TWS. A
    # hair above the largest button, so no arithmetic fault can exceed the order
    # clicked. Raising the buttons means raising this, in the same file.
    max_order_dollars: float = Field(default=60.0, gt=0)

    # A second order on the same side of the same symbol inside this window is
    # refused as a double-click. A deliberate second order waits a beat.
    repeat_guard_seconds: float = Field(default=1.0, ge=0)

    # Buys and sells are accepted only from this machine. The terminal is served
    # to the LAN so a phone can watch; cancel-all is allowed from anywhere.
    allow_remote: bool = False

    @property
    def is_paper(self) -> bool:
        """True for the paper ports. 7496/4001 are the live ones."""
        return self.port in (7497, 4002)

    @field_validator("buy_dollars")
    @classmethod
    def _positive_dollars(cls, value: list[float]) -> list[float]:
        if not value or any(amount <= 0 for amount in value):
            raise ValueError("buy_dollars must be a non-empty list of positive amounts")
        return value

    @field_validator("sell_fractions")
    @classmethod
    def _valid_fractions(cls, value: list[float]) -> list[float]:
        if not value or any(not 0 < fraction <= 1 for fraction in value):
            raise ValueError("sell_fractions must be a non-empty list within (0, 1]")
        return value


class HistorySettings(_Section):
    """How much history to load for each base timeframe."""

    intraday_days: int = Field(default=5, ge=1, le=30)
    # Alpaca serves the daily base in one request capped at ``page_limit`` rows,
    # so a wider window costs nothing until it stops filling the page. Forty
    # years is where ~252 sessions a year meets that 10k cap.
    daily_years: int = Field(default=40, ge=1, le=50)
    max_bars_in_memory: int = Field(default=20_000, ge=100)
    # IBKR is only asked for the most recent slice; Alpaca covers the rest.
    ibkr_recent_seconds: int = Field(default=3600, ge=60)
    # How many *earlier* sessions the 10-second window reaches back over, walked
    # off Alpaca's trade tape; IBKR serves the last twelve hours natively
    # (app/providers/router.py). One session is enough for EMA 600 on a liquid
    # name; raise it for a thin one. Each is one more tape walk per switch.
    tensec_prior_sessions: int = Field(default=1, ge=0, le=5)


class EdgarSettings(_Section):
    """SEC EDGAR — fundamentals and filings.

    No key, but SEC requires a User-Agent identifying the caller with a contact
    address and blocks the ones without. The default is obviously unset.
    """

    enabled: bool = True
    user_agent: str = "traderapp/1.0 (contact: set edgar.user_agent in settings)"
    # How often the filing trail of the focused symbol is re-read, looking for
    # an offering that landed mid-session. Well inside SEC's rate limit at one
    # symbol; the XBRL facts are not re-fetched on this cadence.
    filing_poll_seconds: float = Field(default=60.0, ge=15.0)


class RegimeSettings(_Section):
    """The TradingView market-regime poll — switch and cadence only."""

    enabled: bool = True
    refresh_seconds: float = Field(default=15.0, ge=5.0)


# The stock types IBKR's scanner knows about, from its own scanner-parameters
# document (the STKTYPE filter's combo values).
STOCK_TYPES = frozenset({"CORP", "ADR", "ETF", "ETN", "REIT", "CEF", "ETMF"})


class NewsAISettings(_Section):
    """The news panel's summary line — the ``claude`` CLI as a child process.

    Run in print mode with no tools and no session; see ``services/news_ai.py``.
    ``enabled`` is on — with the CLI absent the panel says so in one line. Off in
    every test settings object: it spawns a process that reaches Anthropic.
    """

    enabled: bool = True
    # Resolved on PATH, then in the usual install directories. A value
    # carrying a separator is taken as a path and used as given.
    command: str = "claude"
    # Sonnet reads a press release as well as anything and costs about a
    # cent a day per symbol. An alias ('sonnet', 'opus') or a full model id.
    model: str = "sonnet"
    # A reading is one API turn behind a process launch. Measured at 5-12s;
    # this is the ceiling before the panel gives up and says so.
    timeout_seconds: float = Field(default=90.0, gt=0)
    # A hard per-reading ceiling handed to the CLI. One costs ~$0.01, so this
    # only ever bites on something that has gone wrong.
    max_budget_usd: float = Field(default=0.25, gt=0)
    # How long a brief stands before new headlines start another reading. A busy
    # pre-market delivers a headline a minute and each would launch a process;
    # refresh overrides this.
    min_interval_seconds: float = Field(default=120.0, ge=0)


class ScannerSettings(_Section):
    """Defaults for the IBKR market scanner."""

    enabled: bool = True
    scan_code: str = "TOP_TRADE_RATE"

    # Capitalisation does the size filtering, so price and volume floors are
    # left open — either would only discard names the market-cap band has
    # already qualified. The ceiling stays: the workflow does not trade above it.
    above_price: float | None = None
    below_price: float | None = 50.0
    # Trades per minute. Two hundred excludes most of the tape while still
    # admitting a small cap in the first minutes of a move. A first-run seed
    # only: once config/state.yaml exists it owns this, so changing it here does
    # nothing on a machine that has run the terminal — press Apply in the panel.
    above_trade_rate: int | None = 200

    # Row count is not settable here: it belongs to the market-cap tier, beside
    # the band, in app/domain/scanner.py's SCANNER_TIERS.

    # The four scanner tiers (app/domain/scanner.py, SCANNER_TIERS) each carry
    # their own band. The floor drops sub-$1M shells that can top a print-rate
    # ranking on a few thousand dollars of churn; the ceiling is the real
    # small-cap gate, since price is not a proxy for size.

    # Up 10%+ on the day — the same gate the TradingView screen uses, so the
    # two panels answer about the same universe. Applied as a subscription
    # filter and again to the rows, since scan codes honour it inconsistently.
    change_perc_above: float | None = 10.0

    # How far back rank velocity looks. Inside IBKR's ~33s ranking push, so the
    # delta reports tape-driven reordering within one membership generation
    # rather than the churn a push brings; rows arriving with a push show as
    # ``entered``. At the 3s emit interval the baseline lands ~2 emissions back.
    rank_window_seconds: float = Field(default=5.0, gt=0)

    # STK.US.MAJOR is Listed/NASDAQ. Per-exchange codes exist and combine as a
    # comma-separated list — "STK.NYSE,STK.AMEX,STK.ARCA,STK.NASDAQ" is MAJOR
    # minus BATS, which lists almost no operating companies. STK.US adds
    # OTCMarkets, STK.US.MINOR is OTC alone.
    location_code: str = "STK.US.MAJOR"
    instrument: str = "STK"
    min_refresh_seconds: float = Field(default=3.0, gt=0)

    # ``instrument: STK`` admits every stock-shaped product, so a leveraged ETF
    # can top a trade-rate scan on derivative churn; excluding the fund family
    # leaves operating companies. Excluded rather than restricted to CORP
    # because ``inc:CORP`` also drops ADRs, and small-cap runners are often ADRs.
    exclude_stock_types: list[str] = Field(default_factory=lambda: ["ETF", "ETN", "CEF", "ETMF"])

    @field_validator("exclude_stock_types")
    @classmethod
    def _known_stock_types(cls, value: list[str]) -> list[str]:
        """Reject unknown codes loudly.

        IBKR ignores a malformed stock-type filter in silence — the scan keeps
        returning ETFs — so a typo has to fail at startup.
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
        extra="forbid",
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
    # The same two ports reached from another device on the home WiFi: the phone
    # loads the dev server on :3000 and calls the API on :8000, a different
    # origin. Held to the three RFC 1918 ranges, loopback and Bonjour names, on
    # the dev and preview ports only — browsers reject "*" alongside
    # allow_credentials. Empty binds the terminal back to this laptop:
    #
    #     TRADERAPP_CORS_ORIGIN_REGEX= make backend
    cors_origin_regex: str = r"^http://(" + HOME_NETWORK + r"):(3000|4173)$"
    # The Host a browser sends is the name it dialled, so a DNS name rebound onto
    # this machine arrives under its own name and passes a same-origin check.
    allowed_host_regex: str = r"^(" + HOME_NETWORK + r"|\[::1\])(:\d+)?$"

    default_symbol: str = "AAPL"
    default_timeframe: str = "10s"

    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    ibkr: IBKRSettings = Field(default_factory=IBKRSettings)
    history: HistorySettings = Field(default_factory=HistorySettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    regime: RegimeSettings = Field(default_factory=RegimeSettings)
    edgar: EdgarSettings = Field(default_factory=EdgarSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)
    news_ai: NewsAISettings = Field(default_factory=NewsAISettings)

    indicators_file: Path = CONFIG_DIR / "indicators.yaml"
    state_file: Path = CONFIG_DIR / "state.yaml"
    # Exchange rates for periods that have already closed, which never change.
    # A cache, not a setting: deleting it costs one refetch.
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
            YamlConfigSettingsSource(settings_cls, yaml_file=settings_file()),
        )


def settings_file() -> Path:
    """The YAML settings file. ``TRADERAPP_SETTINGS_FILE`` points elsewhere, which
    is how a test server keeps this machine's own settings out of a run."""
    return Path(os.environ.get("TRADERAPP_SETTINGS_FILE") or CONFIG_DIR / "settings.yaml")


@lru_cache
def get_settings() -> Settings:
    return Settings()
