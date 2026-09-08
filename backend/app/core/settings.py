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
    # The same walk for the *prior* sessions of the 10s window, which is
    # off-screen background history rather than the chart's live edge. Twelve
    # pages is 120k trades: measured, that is the whole previous session for
    # a small-cap runner (WETO's 09-02 tape was 6.4 pages) and the closing
    # hours of it for a mega cap, which is the part that has to join up with
    # today. Names liquid enough to truncate here already carry far more than
    # a slow EMA needs inside the on-screen window.
    max_prior_session_pages: int = Field(default=12, ge=1, le=200)

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


class TradingSettings(BaseModel):
    """Order entry through IBKR — the one part of this app that spends money.

    A second TWS connection, on its own client id, because the data client is
    ``readonly=True`` and runs four scanner subscriptions, tick-by-tick
    streams and pacing-limited history through a reconnect loop. Order flow
    does not belong on it, and IBKR allows 32 concurrent API clients.

    ``enabled`` is False here and False in every test settings object, the
    same way ``alpaca.news_stream`` is: with it off the broker never connects
    and nothing can reach ``placeOrder``.

    One thing this file cannot control: TWS's own **Read-Only API** checkbox
    (Global Configuration → API → Settings). That is what actually enforces
    read-only — ``ib_async``'s ``readonly`` argument only skips the client's
    own open-order fetch — so with the box ticked every order is rejected
    whatever is set here. See docs/order-entry.md.
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

    # How far through the book a marketable limit is priced. The offset is a
    # *cap*, not a price: a limit fills at the best available price, so five
    # cents through the offer still fills at the offer when there is size
    # there, and the slack is only spent when the book moves between the
    # click and the arrival.
    #
    # Two parts, larger wins. Five cents is 12 bps on a $40 name and 12.5% on
    # a $0.40 one, so a flat figure is the wrong shape at one end or the
    # other. At 15 bps the two cross at $33.33.
    offset_cents: float = Field(default=5.0, gt=0)
    offset_bps: float = Field(default=15.0, ge=0)

    # The buy buttons, in dollars, and the sell buttons as fractions of the
    # position. Order is display order, left to right.
    buy_dollars: list[float] = Field(default_factory=lambda: [10.0, 25.0, 50.0])
    sell_fractions: list[float] = Field(default_factory=lambda: [0.25, 0.5, 1.0])

    # DAY over IOC deliberately. At these sizes a marketable limit essentially
    # always fills, so the difference is a tail either way — but DAY's failure
    # is a resting order that shows in the working count and can be cancelled,
    # while IOC's is a sell that silently cancelled and left a position the
    # trader believes is closed.
    tif: Literal["DAY", "IOC", "GTC"] = "DAY"

    # Not optional for this workflow. Small-cap momentum runs pre-market, and
    # without this a limit order simply sits unfilled until 09:30. It is also
    # why these are limit orders: TWS refuses market orders outside RTH.
    outside_rth: bool = True

    # A hard server-side ceiling on one order's notional, checked before
    # anything reaches TWS. Sixty is a hair above the largest button, so no
    # arithmetic fault anywhere in the stack can produce an order larger than
    # the one that was clicked. Raising the buttons means raising this, on
    # purpose, in the same file.
    max_order_dollars: float = Field(default=60.0, gt=0)

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


class TapeSettings(BaseModel):
    """Time and sales — the print-by-print window beside the chart.

    Nothing here reaches a bar or an indicator; the tape is a separate reader
    on the same trade stream (app/services/tape.py). Cost is a ring buffer per
    symbol and one extra WebSocket message per second per watched symbol, so
    there is no switch to turn it off — a tape that is not there is a window
    showing nothing, which is worse than one showing a slow name printing
    twice a minute.
    """

    # Rows held per symbol, server side. The client keeps its own, smaller
    # list; this is the depth a fresh subscribe is handed.
    buffer: int = Field(default=600, ge=50, le=5_000)
    # Symbols keeping a tape at once, evicted least-recently-printed.
    max_symbols: int = Field(default=16, ge=1, le=64)


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
    ibkr_recent_seconds: int = Field(default=3600, ge=60)
    # How many *earlier* sessions the 10-second window reaches back over,
    # walked off Alpaca's trade tape in the background pass. IBKR serves the
    # last twelve hours natively (app/providers/router.py); this is what sits
    # behind them.
    #
    # One is enough for the slowest line on the 10s chart. EMA 600 is one
    # hundred minutes of bars and draws nothing at all until it has 600 of
    # them: measured at midday, twelve hours held 1,078 for SPWR and 1,741
    # for WETO, so the line began most of the way across the chart — and
    # first thing in the morning it does not begin at all. Adding the
    # previous session took those to 3,064 and 4,738.
    #
    # Raise it for a genuinely thin name, where a session is not 600 bars of
    # anything: AEMD's two sessions came to 299. Each extra session is one
    # more capped tape walk per ticker switch.
    tensec_prior_sessions: int = Field(default=1, ge=0, le=5)


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


class NewsAISettings(BaseModel):
    """The news panel's summary line — Claude Code, read as a child process.

    The reader is the ``claude`` CLI already installed and authenticated on
    this machine, run in print mode with no tools and no session. See
    ``services/news_ai.py`` for why that rather than the API directly.

    ``enabled`` is on: the panel is the feature, and with the CLI absent it
    says so in one line rather than failing. It is off in every test settings
    object for the same reason ``alpaca.news_stream`` is — this spawns a
    process that reaches Anthropic, and no test may leave the machine.
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
    # How long a brief stands before new headlines are allowed to start
    # another reading. A busy pre-market delivers a headline a minute and
    # each one would otherwise launch a process; the panel marks the brief
    # stale in the meantime and the refresh button overrides this.
    min_interval_seconds: float = Field(default=120.0, ge=0)


class SetupAISettings(BaseModel):
    """The AI tab — the whole screen judged against Ross Cameron's framework.

    Same reader as the news summary and the same flags (``services/
    claude_cli.py``); what differs is the prompt and that this one is asked
    for rather than following a feed. A setup is a moving target, so a
    judgement cannot be cached against its inputs — it is dated instead, and
    the panel says when the tape has moved out from under it.

    Off in every test settings object, for the reason the news reader is:
    it spawns a process that reaches Anthropic.
    """

    enabled: bool = True
    command: str = "claude"
    # The same reader as the news panel, and it has to stay the same: the
    # setup judge takes the news reader's score as an input, and a mixed pair
    # is two different readers arguing about one screen.
    model: str = "sonnet"
    # The prompt is much larger than the news one — five pillars, a level
    # ladder, the tape and the news score — and the answer is a considered
    # judgement rather than a summary. Measured at 60-120s against Sonnet,
    # so the ceiling is well clear of the slow end: a reading that times out
    # at 119 seconds has spent the money and thrown away the answer.
    timeout_seconds: float = Field(default=240.0, gt=0)
    max_budget_usd: float = Field(default=0.35, gt=0)


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
    # Trades per minute. Two hundred already excludes the great majority of
    # the tape while still admitting a small cap in the first minutes of a
    # move, before the rate has built — which is the part of a run worth
    # catching, and what a higher floor was cutting off.
    #
    # A first-run seed only. Once config/state.yaml exists it owns this, so
    # changing the number here does nothing on a machine that has already run
    # the terminal — press Apply in the panel instead.
    above_trade_rate: int | None = 200

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
    # The same two ports, reached from another device on the home WiFi. A
    # phone loading the dev server at http://10.0.0.5:3000 sends that as its
    # Origin, and the API it then calls on :8000 is a different origin, so
    # without this every REST call fails while the WebSocket — exempt from
    # CORS — keeps working, which reads as a half-loaded terminal rather than
    # as a configuration problem.
    #
    # Held to the three RFC 1918 ranges, loopback, and Bonjour names, on the
    # dev and preview ports only. A wildcard would be no use anyway: browsers
    # reject "*" alongside allow_credentials. Set it empty to bind the
    # terminal back to this laptop:
    #
    #     TRADERAPP_CORS_ORIGIN_REGEX= make backend
    cors_origin_regex: str = (
        r"^http://("
        r"localhost"
        r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|[A-Za-z0-9-]+\.local"
        r"):(3000|4173)$"
    )

    default_symbol: str = "AAPL"
    default_timeframe: str = "10s"

    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    ibkr: IBKRSettings = Field(default_factory=IBKRSettings)
    history: HistorySettings = Field(default_factory=HistorySettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    regime: RegimeSettings = Field(default_factory=RegimeSettings)
    edgar: EdgarSettings = Field(default_factory=EdgarSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)
    tape: TapeSettings = Field(default_factory=TapeSettings)
    news_ai: NewsAISettings = Field(default_factory=NewsAISettings)
    setup_ai: SetupAISettings = Field(default_factory=SetupAISettings)

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
