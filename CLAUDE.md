# traderapp

## Comments and documentation

Document the code as it is now. Nothing else.

- **Say why, never what.** The code says what.
- **No history.** No "this used to be", "X was removed", "this was wrong
  first", no rejected alternatives, no dated anecdotes. Git holds that.
- **No essay.** No second-person address, no rhetorical framing, no restating
  a point for emphasis, no justifying a decision at length.
- **Cap a comment at ~3 lines**, a module docstring at ~6. More than that
  belongs in `docs/`, referenced by one line.
- **Keep only what the code cannot say**: the constraint a future edit
  breaks, a spec reference, where a magic number comes from.
- **Say it once**, in one file. Elsewhere, name that file.
- **Prefer fixing the code to explaining it.** A clear name, a small function
  or a named constant deletes the comment outright. Structure the code so
  little documentation is needed.

Same rules for `docs/` and this file.

## The machine this runs on

**MacBook Pro, Apple M1 Pro, 8 cores, 16GB RAM, macOS 26.5.** 16GB is a hard
limit: an unconstrained browser run exhausts memory and kernel-panics the box.

## Check before you claim

**A claim about what is *not* possible needs the check that would settle it.**
Positive claims get tested by whoever uses them next; negative ones close the
question. Before writing "X is not available" or "this needs another source",
run the smallest thing that proves it — or say what was **not** checked.

    curl -s -H 'User-Agent: traderapp/1.0 (you@example.com)' \
      "https://data.sec.gov/api/xbrl/companyfacts/CIK0001766600.json" \
      | python3 -c 'import json,sys; print(list(json.load(sys.stdin)["facts"]))'

A verified limit is a starting point: find what does work and bring that back.
"The SEC does not have it" is not "the terminal cannot show it" — foreign
filers with no interim statements in `companyfacts` still have quarterly
fundamentals on the TradingView row we already fetch (`total_revenue_fq`,
`net_income_fq`, `gross_profit_fq`, `oper_income_fq`,
`cash_f_operating_activities_fq`, `earnings_per_share_diluted_fq`). Non-US
filers may report under `ifrs-full` rather than `us-gaap`.

## Running tests

Run suites **one at a time**. Never two `playwright test` invocations at once.

    # Backend — fast, safe, run freely
    cd backend && .venv/bin/python -m pytest -q
    cd backend && .venv/bin/python -m ruff check .

    # Frontend unit + types + lint — fast, safe, run freely
    cd frontend && npx vitest run
    cd frontend && npx tsc --noEmit && npx eslint src
    cd e2e     && npx tsc --noEmit -p . && npx eslint .

    # Browser tests — one project per invocation
    cd e2e && npx playwright test --project=chromium    # ~1.8 min
    cd e2e && npx playwright test --project=visual      # ~9 s
    cd e2e && npx playwright test --project=fullstack   # ~21 s
    cd e2e && npx playwright test --project=firefox     # ~2.6 min
    cd e2e && npx playwright test --project=webkit      # ~3.2 min
    cd e2e && npx playwright test --project=mobile      # ~9 s

A full sequential pass is ~8 minutes and holds memory above 70%.

### Rules that keep it upright

- **One `--project` per command.** Not `--project=a --project=b`.
- **Never run two Playwright processes concurrently.** The worker cap bounds
  one invocation, not two.
- **No `--repeat-each`.** Stress loops are for CI.
- **Never `pkill -9` a browser** — it orphans resident helpers. Plain
  `pkill -f playwright` lets them release memory.
- **Check the machine before and between runs:**

      pgrep -f playwright | wc -l          # want 0
      lsof -ti :4173 :8100 | wc -l         # want 0 (preview + test backend)
      memory_pressure | grep 'free percentage'
      uptime                               # load should be single digits

### Scripts that fan out

`e2e/playwright.config.ts` sets `workers: 2`; the Playwright default is half
the cores, four whole browsers here. The cap is global across projects, so a
multi-project run is bounded, but these queue a lot of work:

- `npm test` (root) → unit tests, then **every** Playwright project.
- `npm run test:e2e` → all projects.
- `npm run test:e2e:ci` → five projects in one invocation.

Safe: `npm run test:mocked` (chromium only) and `npm run test:fullstack`.
`test:ci` omits `visual`, whose baselines are darwin-specific.

### Reading a browser failure

Timing failures measured on a loaded machine are worthless — check `uptime`
first.

**A browser-lifecycle error is contention, never application code.** `Target
page, context or browser has been closed`, `Test timeout ... while setting up
"backend"`, or `page.goto` timing out in a fixture, with **no failed
assertion**, means the browser died. Re-run the spec alone on a quiet machine
before touching source. All three engines pass in full sequentially.

## Layout

- `backend/` — FastAPI, own venv at `backend/.venv`. Not an npm workspace.
- `frontend/` — Vite + React, npm workspace.
- `e2e/` — Playwright, npm workspace. `tests/mocked` intercepts the backend;
  `tests/fullstack` drives the real one with only Alpaca faked;
  `tests/visual` holds pixel baselines (chromium only).

## The screen

Three columns. `docs/terminal-expansion.md` is the design.

**Left** has its own tab strip: *Day* holds the four IBKR market-cap scanners,
*Swing* four TradingView setups that need no TWS. Key levels sit beneath both.

**Middle** is tabbed — Chart, Financials, Metrics, Insiders, Peers. The chart
is **hidden with `visibility`, never unmounted**: a `display:none` container
is zero-height and lightweight-charts cannot size a pane inside one;
unmounting loses the viewport. The order strip sits across the bottom
*outside* the tab panel, so a position stays on screen while a balance sheet
is read.

**Right dock** has four tabs — Charts, Fund, News, Filings. The first stacks
1-minute over 5-minute context charts; `MINI_SLOT_COUNT` in `chart/mini.ts`
decides how many there are.

### Two traps already paid for

**NaN passes `isinstance(x, float)`.** Every screener row comes through
pandas, which fills a missing cell with NaN, and every comparison against NaN
is False — so a row carrying one passes a filter *by failing its test*, and
sorting scrambles the order. Numerics from TradingView go through
`app/domain/screener.finite()`.

**A filing's `fy`/`fp` describe the filing, not the fact.** A 10-K restates
prior years, so Apple's FY2016 revenue is tagged `fy: 2018`. A fact's period
is `start`–`end` and nothing else.

**A screener's universe filter is not a lookup filter.** `_common_stock_terms()`
in `services/tv.py` keeps to primary listings of US common stock — right when
ranking a list nobody named, wrong when somebody typed the symbol. In a
watchlist it blanks secondary listings (`is_primary` False), ADRs (typed
`dr`) and ETFs, while still drawing a row for each. ETFs are excluded by
`tradingview_screener`'s own default `filter2`, so that needs
`set_property("filter2", ...)`. See `services/watchlist.py`.

### The 10-second window is three slices

The last four hours are the first paint, hours four to twelve the background
extension — both native IBKR. Behind them the previous session is walked off
Alpaca's **trade tape**: Alpaca's bars endpoint bottoms out at one minute
(`10Sec`, `10S`, `30Sec`, `1Sec` all answer 400 `invalid timeframe`) and
IBKR's 10s requests cap at four hours each, so reaching yesterday natively
costs ten chunks per ticker switch against a 60-per-10-minutes allowance.

That depth exists because **`ema()` returns nothing until it has `span`
values**, and the slowest line is EMA 600. A bar exists only where a trade
printed, so coverage is about the *name*, not the clock: a thin symbol needs
`history.tensec_prior_sessions` raised to draw a slow line at all.

- **The tape walk is capped and newest-first**
  (`alpaca.max_prior_session_pages`). What survives is the stretch adjacent to
  today, which is the part that has to join up.
- **Only the IBKR-served window is folded back into the minute base.**
  `_refresh_minutes_from_tensec` clamps to twelve hours: Alpaca's published
  minutes for a closed session beat our rebuild of them from its tape, and
  there is no delayed-feed gap to close in a closed session.

Session-scoped indicators are safe across the wider window: VWAP, HOD/LOD and
the pre-market range all key on the New York date.

### News comes from two places, one a socket

IBKR carries eight entitled feeds; Alpaca carries Benzinga, which is the one
that covers small caps. Both land in one per-symbol dict keyed by article id,
so dedup runs across them.

**Alpaca news is real time** — `delayed_sip` governs the price tape only.

**Alpaca allows one news socket per account.** A second connection takes it
rather than sharing, and the loser sees a close with no close frame. Two
copies of this app trade the connection through their reconnect loops.

**The stream is off in every test** (`TRADERAPP_ALPACA__NEWS_STREAM=false`,
`news_stream=False` in integration settings) — respx cannot intercept a
websocket, and a live one dials Alpaca for real from a unit run.

### One panel asks Claude to read something

`docs/ai-architecture.md` is the layer; `docs/news-summary.md` the panel
design; `.claude/skills/ai-panel/SKILL.md` the procedure for changing the
prompt. What follows is only what a careless edit breaks.

**The news window is a session, not a calendar day.** A press release at 16:05
is not today's news, it is tomorrow's gap; keyed on the New York date it lands
under yesterday. The window runs from the previous close to now.

**The score is catalyst quality, not a trade signal.** The reader sees
headlines and bodies and nothing else. A 2 means *this news is not a reason to
be long*, never *do not trade this*. A test asserts the sentence is there.

**The flags are the sandbox.** `--tools ""`, `--safe-mode`,
`--strict-mcp-config`, `--permission-prompts none`, `cwd` at `$HOME`. Not
`--bare`: it demands `ANTHROPIC_API_KEY` and never reads this machine's OAuth.
`test_the_reader_runs_with_no_tools_and_no_project_config` asserts argv flag
by flag.

**It is off in every test** — `news_ai.enabled=False` in integration settings,
`TRADERAPP_NEWS_AI__ENABLED=false` in `playwright.config.ts`, for the same
reason as `news_stream` and `trading`. The service is tested against a shell
script in `tmp_path`. When that fake sleeps, **redirect its stdout** — a child
holding the pipe keeps the transport alive past the test and surfaces as an
unraisable "Event loop is closed".

**The model stays an alias** — `sonnet`, not a pinned id.

**Point-in-time float is in the backtesting repo**,
`03_reference/build_insider_float.py`. Consume it **only through
`pit_float()`**: amendment resolution, owner-group carry-forward, role-aware
staleness and split restatement all live there. `pit_market_cap()` is its twin.

## Order entry spends real money

`docs/order-entry.md` is the design.

- **`trading.enabled` is False**, in settings and explicitly in the
  integration settings. It is a raw socket to TWS, respx cannot see it, and
  the far end places real orders against a **live** account on `port: 7496`.
  Never flip it to run a test.
- **The client never sends a share count.** It sends the dollar amount or the
  fraction; `services/trading.py` recomputes quantity from the freshest quote
  and IBKR's own position. The command models forbid extra fields.
- **The arithmetic exists twice** — `domain/orders.py` and `lib/orders.ts` —
  as integer micro-dollars in both, which is what makes them agree bit for
  bit. Both are asserted against one table,
  `frontend/src/lib/order-cases.json`. Add a case there, not to a suite.
- **`is_available` means connected *and* set up.** `ib_async` marks the socket
  connected partway through `connectAsync`; for ~300ms the account has not
  resolved and no handler is attached, so an order would go out with nothing
  listening for fills. `socket_connected` is the raw state, wanted only by the
  connect loop.
- **Read-only is a TWS checkbox, not a code flag.** `ib_async`'s `readonly=`
  only skips the client's own open-order fetch. Global Configuration → API →
  Settings → "Read-Only API" is what rejects orders, and it cannot be detected
  until the first one is tried.
- **The strip renders nothing with trading off**, so it changes no visual
  baseline. That absence is asserted.

## Visual baselines

Tolerance is `maxDiffPixelRatio: 0.004`, so a small added chip is well under
it: **a green visual run is not evidence that a small component change was
noticed.** After any toolbar or strip change, assert the new element renders,
then regenerate.

**Regenerate with `--update-snapshots=all`, not `--update-snapshots`.** The
bare flag only rewrites a baseline whose comparison *failed*, and these
changes do not fail.

## The audit suite

`backend/tests/audit/` checks our figures against **yfinance** and
**TradingView**, over the network, for twenty companies spanning market-cap
tiers, sixteen sectors, four countries and four reporting currencies.

Excluded from every normal run — `addopts` carries `-m 'not audit'`. Run it
deliberately:

    cd backend && .venv/bin/pip install -e '.[audit]'
    cd backend && .venv/bin/pytest -m audit          # ~60 s

`companyfacts` is cached under `tests/audit/.cache/`.

The two auditors answer different questions. **yfinance** reports in the
filer's own currency, so it checks the *parse*: right concept, right period,
before restatement. **TradingView** publishes in USD, so it checks the
*conversion*. Failing one and passing the other localises a fault.

`test_watchlist.py` has no outside source, because it is not checking a
figure: it asks the live screener whether ten named symbols (an ADR, an ETF, a
second share class, a secondary listing) come back with a price at all. A unit
test cannot see that fault — every symbol produces a row, and every row is
empty.

`test_indicators.py` and `test_screens.py` cover the chart. Nobody else
computes a moving average over *our* bars, so it checks the two things that
can be: our closes match TradingView's exactly, and our arithmetic lands where
theirs does, to the fourth decimal.

Four differences are **design, asserted rather than tolerated**:

- A drawn level excludes today's bar so it cannot repaint mid-session.
- Yearly extremes span calendar weeks (`high:52w`, not `high:252` bars), which
  is what matches the market's figure to 0.0000%.
- The day's range runs 04:00–20:00, not the regular session, because on a
  small cap the high of day is often set before 09:30.
- Pre-market extremes sit within a few basis points of another vendor's: two
  consolidated tapes disagree about which prints set an extreme.

`test_key_levels.py` holds every drawn level against other platforms. Rolling
extremes, previous close, and weekly and monthly bucketing agree to 0.00%.
`High.YTD` resolves as a TradingView column but returns null for every symbol,
so the year-to-date high is audited against yfinance's daily bars instead.

The screens have no external truth — they are our own definition — so they are
checked against their own printed claim. A panel headed "within 10% of the
52-week high" returning something 40% below is worse than an empty panel,
because it is believed.

`test_ratios.py` covers what is built *on* the statements, where a mistake
reaches a decision: multiples are quoted on a trailing twelve months.

### Reading a disagreement

**A disagreement is not automatically our bug.** yfinance publishes an
*adjusted* "Operating Income" alongside "Total Operating Income As Reported",
and only the second is the figure in the filing — comparing against the wrong
one condemns correct readings by the dozen. Before changing anything, read the
concept out of `companyfacts` and find which side is right.

Genuine differences live in two tables, each entry carrying its reason:
`EXPECTED_DIVERGENCE` (a bank's "revenue" has no single definition; yfinance
folds redeemable minority interests into equity and US GAAP does not) and
`INCOHERENT_PERIODS` (`companyfacts` holding a SPAC's balance sheet and its
predecessor's under one date, because the separating dimensions are not
published). The point of an audit is lost the moment those become a way to
silence a failure.
