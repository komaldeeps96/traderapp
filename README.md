# TraderApp

A mini trading terminal for US equities, built for small-cap momentum trading
from the 10-second chart. FastAPI backend, React + lightweight-charts frontend,
IBKR and Alpaca market data with automatic failover, TradingView reference
data. TWS/Bloomberg density, TradingView-quality charts.

The point of it is the things a hosted charting service will not do: a native
10-second timeframe, key levels computed exactly how you want them, float and
float rotation next to the tape, and two scanners wired straight into your own
workflow.

```
┌──────────────────┬─────────────────────────────────────────────────┐
│ TRADE-RATE SCAN  │ AAPL  10S 1M 5M 15M 1H 1D 1W  ↑50%:5  09:31 RTH │
│  sym price chg   ├─────────────────────────────────────────────────┤
│  vol float mcap  │ AAPL 303.45 +1.2%  B 303.36×7 A 303.45×12  9¢    │
│  t/1m $/1m       │ VOL 3.2M RVOL 0.06x FLOAT 14.5B ROT 0.0x MCAP…   │
│ KEY LEVELS       ├─────────────────────────────────────────────────┤
│  52W High        │                                                 │
│  PM High         │              10s candles + overlays             │
│  ▸ LAST 303.45   │                                                 │
│  PM Low          ├─────────────────────────────────────────────────┤
│ INDICATORS       │              volume · MACD (1m)                 │
└──────────────────┴─────────────────────────────────────────────────┘
```

The left rail is the IBKR trade-rate scanner — *is anything moving right
now?* — with the key-level ladder and the indicator chips for whatever is
loaded beneath it. Screening proper is left to a standard screener on a second
monitor; TradingView stays wired in on the backend for float, market cap and
the market-regime counts, which appear in the toolbar.

The strip above the chart carries the symbol facts that are not bars: last,
change, bid×ask with sizes, the spread in cents and percent (graded — past
50¢ it flags untradeable), day volume, relative volume, float, float rotation,
pre-market rotation, market cap, previous close, and distance to the LULD halt
bands during regular hours.

Sub-panes are config-driven: volume everywhere, MACD 12/26/9 on the 1-minute
only — where its crossovers mean something.

## Quick start

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # add ",ibkr" for TWS support
cp config/settings.example.yaml config/settings.yaml   # then add Alpaca keys
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (from the repo root)
npm install
npm run dev                                 # http://localhost:3000
```

Or `make dev`, which runs both and prints the addresses.

Without any credentials the app starts and reports that no data source is
available. Alpaca's free tier is enough to get real charts.

## On a phone or tablet

Both servers bind `0.0.0.0`, so anything on the same WiFi opens the terminal
at **`http://<this-mac's-ip>:3000`** — `ipconfig getifaddr en0` prints the
address, and `make dev` echoes it. This is the *dev* server, so hot reload
comes with it: Vite aims its HMR socket at whatever host served the page, and
an edit on the laptop redraws the phone.

Three things make that work, and each is easy to undo by accident:

- `frontend/vite.config.ts` binds `0.0.0.0` rather than `127.0.0.1`, and
  allows `.local` hosts — an IP literal is permitted unconditionally, a
  Bonjour name is not, and the Bonjour name is what survives a DHCP lease.
- `cors_origin_regex` in the backend settings admits the three RFC 1918
  ranges, loopback and `*.local`, on ports 3000 and 4173. Without it the
  phone shows a *half*-loaded terminal rather than an error, because the
  WebSocket is exempt from CORS and connects while every REST call fails.
- macOS asks once whether `node` may accept incoming connections. Answer yes;
  the Python that serves the API is usually already allowed.

`http://<ip>:8000` also works on its own — same origin, no CORS involved — but
it serves whatever `make build` last wrote to `frontend/dist`, which is a
snapshot rather than the code you are editing.

To bind a run back to this laptop: `TRADERAPP_CORS_ORIGIN_REGEX= make backend`,
and `npm run dev -- --host 127.0.0.1`.

## Market data

The chart prefers IBKR and **falls back to Alpaca automatically** whenever TWS
is not reachable — on startup, and if it drops mid-session. The active source
is always shown in the toolbar, and a delayed feed is labelled as such, because
whether a price is live or fifteen minutes old changes what you do with it.

| Source | Used for | Notes |
|---|---|---|
| IBKR | live trades and quotes, native 10s bars, recent 1m bars, trade-rate scanner | needs TWS or Gateway; real time |
| Alpaca | 1m and daily history, the raw trade tape for 10s bars, quotes, live fallback | `iex` free real-time, `delayed_sip` free whole-tape 15-min delayed, `sip` paid real-time |
| TradingView | float, market cap, 10-day average volume, regime counts | no credentials needed |

Set the feed in `backend/config/settings.yaml`. Minute history is always
assembled from both when both are up: Alpaca supplies the long window and IBKR
overwrites the most recent minutes with its own bars, replacing rather than
summing so volume is never double-counted.

Volume follows **IBKR's convention — odd lots excluded from price and volume
alike** — because IBKR's 10s bars are the baseline the minute base is resampled
from, so both timeframes carry one set of numbers. It matches TWS exactly and
runs 21–44% below any SIP-based screener; the gap moves with tape activity and
cannot be scaled away. [`docs/market-data-providers.md`](docs/market-data-providers.md)
documents how both providers handle tick feeds, sale conditions and bar
construction, with the measurements behind that choice.

**The 10-second timeframe is a real base, not a resample.** Its window is
the last twelve hours, IBKR-native — three requests, which reaches back
through the entire pre-market. Rebuilding the same window from Alpaca's raw
tape costs ten to forty sequential pages on a runner (seconds of download for
bars IBKR serves in one request), so the tape walk survives only as the
fallback for the recent slice when TWS is down. Live, both intraday bases
extend tick by tick from the same trade stream. Minute history is one Alpaca
request — the newest ~10k bars — and its freshest minutes (the stretch a
delayed feed cannot serve) are *resampled from the 10s base*, six
consolidated 10-second bars to the minute. A ticker switch therefore costs
exactly three IBKR historical requests: the 10s slices, nothing else.

**Behind those twelve hours sits the previous session, and that one *is* a
tape walk** — because the slow lines need the depth and nothing else can
supply it cheaply. EMA 600 on the 10s chart is the 100-minute EMA, and it
draws nothing at all until it holds 600 bars: measured at midday, twelve
hours held 1,078 for SPWR and 1,741 for WETO, so the line began most of the
way across the chart and at the open did not begin. One previous session
takes those to 3,064 and 4,738. IBKR could serve it natively and it would be
the *expensive* option — its 10s requests cap at four hours each, so reaching
yesterday's 04:00 turns three chunked requests per ticker switch into ten
against a pacing allowance of sixty per ten minutes, two of them the dead
overnight hours. The walk is capped in pages (`alpaca.max_prior_session_pages`)
and runs newest-first, so a tape too heavy to finish leaves the stretch
adjacent to today rather than an island of yesterday morning; it runs in the
background pass, so the first paint is untouched. Depth is
`history.tensec_prior_sessions`, one session by default — raise it for a name
thin enough that a session is not 600 bars of anything (AEMD's two sessions
came to 299; four came to 3,866). The seam it accepts: Alpaca's tape carries
odd lots and IBKR's `Last` slice does not, so the prior sessions read higher
on volume than today does. Prices, and so every moving average, are
unaffected — and the minute base is deliberately *not* re-derived from them,
because Alpaca's own published minutes for a session that closed yesterday
are better than our rebuild of them.

**Loads are two-phase, judged by the first paint.** A symbol switch blanks
the chart immediately (the old instrument must never pose as the new one),
fetches only the daily bars and the viewed timeframe's base — for the 10s
default that is a single IBKR request, typically around a second — and
paints. The remaining bases and the older 10s hours arrive as a background
backfill, delivered as a repeat snapshot that extends the chart without
moving the viewport.

**Request budgets are enforced and visible.** Every Alpaca REST call and
IBKR historical request takes a slot from a sliding-window budget
(pyrate-limiter under the hood: 200/min for Alpaca, ~60/10min for IBKR
pacing) and waits rather than fails when a window is full. The two meters in
the toolbar centre read the same buckets — green means switch tickers
freely, amber means the window is half spent, red means the next flurry will
queue behind the limiter.

The trade-rate scanner is IBKR-only — there is no Alpaca equivalent — so
without TWS the panel says so rather than showing an empty table.

## Scanner

The scan is IBKR's `TOP_TRADE_RATE` over listed US common stock: **under $50,
$1M–$2,000M market cap, up 10%+**, with ETFs, ETNs, closed-end funds and
managed funds excluded by stock type. Rows are ordered by prints per minute,
the busiest tape first, with dollar volume breaking ties — and each carries
price, change, session volume, float, market cap, trades/min and $/min.

Two details that are easy to get wrong and were measured rather than assumed:
IBKR's stock-type filter is silently ignored on the subscription object and
only works through the generic filter list, and its day-volume tick counts
*lots*, not shares. Both are documented in
[`docs/market-data-providers.md`](docs/market-data-providers.md).

Symbols climbing the list carry a `▲4` / `▼2` mark, and one arriving from
outside it reads `NEW` — rank velocity turns before rank level does, so a
name is often several places into a climb before it reaches anywhere worth
noticing.

TradingView supplies float and market cap per row, and the market-regime
counts in the toolbar: how many listed common stocks are up more than 50% and
100% today. Zero names over 100% is itself information — the tape is cold.
The same reference data feeds the strip above the chart, where rotation is
computed live against our own session volume, and pre-market rotation —
pre-market volume as a share of the float — flags the runners before 9:30.

## Key levels

Key levels are the setup, not decoration, so all of them are on by default and
the sidebar lists them **sorted by price with the last trade slotted into its
true position**. The row above the marker is the next level in the way; the row
below is the first thing that would catch a pullback. Distance is in percent,
because that is how the decision gets sized.

Levels for a given day are computed only from daily bars that closed *before*
it. That rule is load-bearing: it is what stops a "prev day close" or a
"52-week high" drifting as today trades.

Shipped levels: pre-market high/low, previous day/week/month high/low/close,
13/26/52-week high/low, and daily SMA/EMA 20/50/200 projected onto intraday —
all of them on the 10-second chart too. Whole and half dollars are drawn as
faint gridlines directly on the chart (they are traded levels, not decoration),
with the step widening automatically so a high-priced chart never turns into
wallpaper.

### The 10-second chart

Six 10-second candles fit inside every 1-minute candle, so the pullback that
reads as a single topping tail on the 1-minute is visible structure on the
10s. The EMAs there run at six times their minute spans — **EMA 54, 120, 270
and 600 are the 1-minute 9, 20, 45 and 100 projected onto the 10-second
chart** — same line, same colour, same toggle, relabelled per timeframe. The
slowest of them is why the window reaches back past yesterday's open: a
100-minute EMA needs 600 bars before it draws its first point, and a session
does not reliably hold that many.

VWAP anchors at 4:00 a.m. and resets on the New York day, so it describes
today's session no matter how far behind it the window reaches — by the 7:00
open it already carries three hours of pre-market history, and yesterday's
bars carry yesterday's line rather than extending today's.

The toolbar clock shows New York time, the session (PRE/RTH/AH), the working
window (prime 7:00–9:30, conditional to 10:00, wind-down to 11:00), and a
countdown to the current candle's close — on a 10-second chart, the read only
firms up in the final seconds.

### Confluence bands

Levels sitting at effectively the same price are merged into one band carrying
a strength count. Twenty-three levels on a real small cap typically collapse to
thirteen or fourteen bands, and the shelves stand out instead of smearing:

```
  52W High                    2.880   +670.88%
  2 levels        ×2          1.199   +220.83%
    26W High · 1D SMA 200   1.197–1.200
  PM High                     0.4114   +10.12%
▍ 8 levels        ×8          0.4040    +8.14%     ← one shelf, not eight lines
    PM Low · Prev Day Close · Prev Week …
  LAST                        0.3736
```

Two channels carry two different things, because a single one cannot say both:

- **Colour marks what is actionable.** Only the nearest band overhead and the
  nearest underneath are coloured — the next thing in the way, and the first
  thing that would catch a pullback. Everything else stays recessive so those
  two can actually be seen. Colour follows the price, so a broken resistance
  becomes support on its own.
- **Weight counts agreement.** A band's line thickens with the number of levels
  in it, and it is labelled once on the price axis (`PM Low +7`) rather than
  once per level. Eight colliding axis labels was the problem this solves.

Only the three moving averages carry categorical hues; those were validated for
colour-vision separation against both chart surfaces, and a fourth does not
clear the gates in dark mode. So the levels deliberately do not each get a
colour — hue is spent on what changes a decision, and identity comes from the
axis label and the sidebar.

Tune the merge threshold with `DEFAULT_CLUSTER_TOLERANCE_PERCENT` in
`frontend/src/store/selectors.ts` (default 0.35% of price).

### Sub-dollar tickers

Price precision follows magnitude — four decimals under $1, three under $10,
two above. At $0.37 a cent is nearly 3%, so two decimals would round a level
and the price standing on it onto the same number.

## Adding an indicator

Most indicators are a YAML edit, no code:

```yaml
- id: ema100
  type: ema
  label: EMA 100
  span: 100
  color: '#2a78d6'
  color_dark: '#3987e5'
  line_width: 2
  last_value: true
  group: moving_averages
  timeframes:
    1m: { enabled: true }
    1d: { enabled: true }
```

The schema is validated at startup, so a typo fails loudly with the offending
entry named rather than silently drawing nothing.

For something YAML cannot express, add a pure function to
`backend/app/indicators/functions.py` and a branch in `engine.py`. Everything
there takes plain numbers and returns plain numbers, so it is unit-testable on
its own — no dataframes, no clock, no globals.

## Architecture

```
backend/app/
  core/        settings, logging, time
  domain/      bars, timeframes, sessions, wire protocol
  indicators/  pure maths, key levels, YAML specs, engine
  market/      bar builder, resampling, in-memory store
  providers/   alpaca, ibkr, and the router that fails over
  services/    subscriptions, market data, scanner, broadcaster
  api/         REST + WebSocket
frontend/src/
  chart/       lightweight-charts engine wrapper (bars never enter React)
  store/       zustand state and derived selectors
  components/  the terminal UI
e2e/           Playwright: mocked-wire and full-stack suites
```

A few decisions worth knowing:

**Subscriptions are per connection.** Two windows can watch different symbols;
upstream feeds are reference-counted and a symbol is dropped from memory when
the last client leaves. (The previous version broadcast one globally-active
ticker to every client, so a second window silently hijacked the first.)

**Only `10s`, `1m` and `1d` are fetched.** Every other timeframe is resampled
from one of those, which keeps the provider layer small and makes each derived
timeframe a pure function.

**Bars never enter React.** Thousands arrive per snapshot and the newest one
changes every second, so they go straight to the canvas; React renders only the
small readouts.

**Updates are coalesced.** Trades arrive far faster than a chart can usefully
redraw, so the broadcaster sends at most one message per watched chart per
second, and only when that symbol's data actually changed.

**Indicators are computed server-side** and sent as series, so the browser
never recomputes an EMA and every client agrees on the numbers.

## Testing

Everything is automated and needs no credentials, no running TWS, and no open
market. The suites run on their own ports — backend 8100, preview 4173, the
Alpaca fixture 9899 — and build to `frontend/dist-e2e`, so a development
backend on 8000, the Vite dev server, and the production `dist/` bundle all
survive a test run untouched.

```bash
# Backend: unit + integration
cd backend && .venv/bin/python -m pytest -m "not live"
cd backend && .venv/bin/python -m pytest -m "not live" --cov=app

# Frontend: unit
npm run test:unit

# Browser: three engines + visual + full stack; servers start themselves
npm run test:e2e

# Everything, including the linters
make check
```

Counts are deliberately not quoted here — they go stale on the commit after
the one that writes them. `make check` prints the current numbers.

### Linting

`make lint` runs both, and CI runs them before the suites.

| Tool | Covers | Config |
|---|---|---|
| `ruff` | `backend/app`, `backend/tests` | `backend/pyproject.toml` |
| `eslint` | `frontend/src`, `e2e` | `eslint.config.js` |

Neither repeats what a type checker already does. `tsc` runs with
`noUncheckedIndexedAccess` and `noUnusedLocals`, so ESLint is configured for
what types structurally cannot see — floating promises, stale React hook
dependency arrays, dead assertions. Ruff covers the same ground on the Python
side plus naive datetimes, which in a market-data codebase are always a bug.

Where a rule is deliberately turned off, the reason is in the config next to
it rather than left to be rediscovered. A `# noqa` in the source carries its
reason on the same line; ruff's `RUF100` fails the build if one stops being
necessary, so they cannot accumulate.

Three layers, each mocking at a boundary rather than inside the app:

| Layer | What runs | What is faked |
|---|---|---|
| `backend/tests` | the real app, real services, real WebSocket | Alpaca's HTTP, via `respx` |
| `frontend/src/**/*.test.ts` | pure logic — formatting, transport, selectors | a scriptable WebSocket |
| `e2e/tests/mocked` | the real frontend bundle | the whole backend, via Playwright interception |
| `e2e/tests/fullstack` | the real backend *and* frontend together | only Alpaca's HTTP, via a fixture server |

No test-only code ships in production paths — there is no synthetic data
provider and no test control plane.

Both providers are covered without their upstreams. Alpaca's socket half is
tested by feeding recorded frames straight into the decoder, and IBKR — whose
library is not even installed for the test run, which is what proves it is
optional — is tested against a stand-in for `ib_async`, covering bar
conversion, tick handling and the scanner's sliding-window metrics. What is
deliberately *not* covered is either provider's connection handshake and
reconnect loop, which genuinely need a live gateway.

The browser suite covers chart rendering and navigation, symbol and timeframe
switching (10-second included, rebuilt from the trade tape in the full-stack
suite), indicator toggles and their persistence, the key-levels table and its
confluence banding, sub-dollar price precision, crosshair readout, live
updates, reconnection after a dropped socket, delayed feeds and source
failover, both scanners and their filters, the quote/info strip and spread
grading, theming, tablet layout, accessibility (axe, zero violations), and
visual regression.

```bash
npm run test:e2e -- --project=chromium      # one engine
npm run test:e2e -- --ui                    # watch it run
cd e2e && npx playwright test --project=visual --update-snapshots   # rebaseline
```

Visual baselines are committed and pinned to a fixed session date and timezone.

## Configuration

Anything in `backend/config/settings.yaml` can also come from the environment,
which wins over the file. Nested keys use a double underscore:

```bash
TRADERAPP_ALPACA__KEY_ID=...
TRADERAPP_ALPACA__FEED=delayed_sip
TRADERAPP_IBKR__ENABLED=false
TRADERAPP_LOG_LEVEL=DEBUG
```

`settings.yaml` and `state.yaml` are gitignored; credentials never sit next to
volatile state.

## Notes

- `legacy/` holds the pre-rewrite code for reference and is gitignored. Delete
  it when you no longer want it.
- Requires Python 3.11+ and Node 20+.
- Data is for charting. Nothing here places orders.
