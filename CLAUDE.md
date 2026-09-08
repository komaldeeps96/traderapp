# traderapp

## The machine this runs on

**MacBook Pro, Apple M1 Pro, 8 cores, 16GB RAM, macOS 26.5.**

Sixteen gigabytes is the binding constraint on everything below. Treat it as
a hard limit rather than a preference: on 2026-08-29 an unconstrained browser
test run exhausted memory and **kernel-panicked the machine** — `userspace
watchdog timeout: no successful checkins from configd in 182 seconds`, with
`Compressor Info: 100% of compressed pages limit (BAD)`. Load average reached
262 on 8 cores. Nothing was lost, but the box went down hard.

## Check before you claim

On 2026-08-30 the SEC tabs were empty for SNDL, and this went into a summary
as a limitation: closing that gap "needs a different data source". It did
not. One request to the endpoint the terminal already calls for every symbol
returned 240 `ifrs-full` concepts. The fix was a taxonomy name — and the
wrong claim had already been written down as a thing that could not be done.

**A claim about what is *not* possible needs the check that would settle
it.** Positive claims get tested by whoever uses them next. Negative ones —
"the data isn't there", "that API can't do it", "this would need another
source" — close the question, and nobody re-opens it.

The check is nearly always one call:

    curl -s -H 'User-Agent: traderapp/1.0 (you@example.com)' \
      "https://data.sec.gov/api/xbrl/companyfacts/CIK0001766600.json" \
      | python3 -c 'import json,sys; print(list(json.load(sys.stdin)["facts"]))'

This is also how the rest of this file was written. `fy`/`fp` describing the
filing rather than the fact, NaN passing an `isinstance` check, the EDT
day-join being off by one, which TradingView columns resolve, whether a
column can be compared against another column — every one was found by asking
the source instead of reasoning about it, and every one would have been
stated wrongly otherwise.

Before writing "X is not available" or "this would need Y", run the smallest
thing that proves it. If that is not worth two minutes, the claim is not
worth making: say what was **not** checked instead.

### And then find the way through

A verified limit is a starting point, not an answer. Having established that
something cannot be done *the way it was first tried*, go and find what
would work, and bring that back instead of the refusal.

The same day, the follow-up claim was that foreign filers can have no
quarterly view — "a genuine limit, not something I can parse around". Ten
minutes of checking found three different truths behind that one sentence:

- **Canopy Growth and Tilray file 10-Q.** Their quarterly view already
  worked. The claim was simply wrong, generalised from one company.
- **Alibaba and Novo Nordisk have no interim statements in `companyfacts`** —
  that part held, but only for the SEC as a source.
- **TradingView carries their quarterly fundamentals**, on a row this
  terminal already fetches: `total_revenue_fq`, `net_income_fq`,
  `gross_profit_fq`, `oper_income_fq`, `cash_f_operating_activities_fq`,
  `earnings_per_share_diluted_fq` all resolve, for both.

So the honest report is not "cannot be done". It is: two of them already
work, and the other two need a second source that is already in the building.

**Check what a limit is really a limit of.** "The SEC does not have it" is
not "the terminal cannot show it", and the difference is usually one more
question. Where a second source exists, say which one and what it would
cost — then the choice is the user's, made on facts.

## Running tests

Run suites **one at a time**. Wait for each to finish before starting the
next, and never have two `playwright test` invocations alive at once.

    # Backend — fast, safe, run freely
    cd backend && .venv/bin/python -m pytest -q
    cd backend && .venv/bin/python -m ruff check .

    # Frontend unit + types + lint — fast, safe, run freely
    cd frontend && npx vitest run
    cd frontend && npx tsc --noEmit && npx eslint src
    cd e2e     && npx tsc --noEmit -p . && npx eslint .

    # Browser tests — one project per invocation
    cd e2e && npx playwright test --project=chromium    # ~1.7 min, 410 tests
    cd e2e && npx playwright test --project=visual      # ~8 s,      5 tests
    cd e2e && npx playwright test --project=fullstack   # ~19 s,    26 tests
    cd e2e && npx playwright test --project=firefox     # ~2.5 min, 410 tests
    cd e2e && npx playwright test --project=webkit      # ~3.1 min, 410 tests
    cd e2e && npx playwright test --project=mobile      # ~9 s,      8 tests

A full sequential pass is about eight minutes and holds memory above 70%.
All six browser projects pass clean this way: 410 / 5 / 26 / 410 / 410 / 8,
alongside 1721 backend and 462 frontend unit tests.

### Rules that keep it upright

- **One `--project` per command.** Not `--project=a --project=b`.
- **Never run two Playwright processes concurrently.** Backgrounding a run
  and starting another is what actually caused the panic — the worker cap
  bounds one invocation, not two.
- **No `--repeat-each`.** Stress loops are for CI, not this laptop.
- **Never `pkill -9` a browser.** It orphans helper processes that stay
  resident. Plain `pkill -f playwright` lets them release memory.
- **Check the machine before and between runs:**

      pgrep -f playwright | wc -l          # want 0
      lsof -ti :4173 :8100 | wc -l         # want 0 (preview + test backend)
      memory_pressure | grep 'free percentage'
      uptime                               # load should be single digits

### Scripts that fan out — know before you use them

`e2e/playwright.config.ts` sets `workers: 2` for exactly this reason; the
Playwright default is half the cores, which is four whole browsers here.
The cap is global across projects, so a multi-project run is bounded — but
these still queue a lot of work and are better split up:

- `npm test` (root) → unit tests, then **every** Playwright project.
- `npm run test:e2e` → `playwright test` with no filter: all projects.
- `npm run test:e2e:ci` → five projects in one invocation.

Two that are safe and useful: `npm run test:mocked` (chromium only) and
`npm run test:fullstack`. `test:ci` deliberately omits `visual`, whose
baselines are darwin-specific.

### Reading a browser failure

Timing-sensitive failures measured on a loaded machine are worthless. Check
`uptime` before concluding anything.

**A browser-lifecycle error is always contention, never application code.**
If you see `Target page, context or browser has been closed`, `Test timeout
... while setting up "backend"`, or `page.goto` timing out in a fixture —
with **no failed assertion anywhere** — the browser died. Re-run the spec
alone on a quiet machine before touching a line of source. All three engines
pass 410/410 when run sequentially.

## Layout

- `backend/` — FastAPI, own venv at `backend/.venv`. Not an npm workspace.
- `frontend/` — Vite + React, npm workspace.
- `e2e/` — Playwright, npm workspace. `tests/mocked` intercepts the backend;
  `tests/fullstack` drives the real one with only Alpaca faked;
  `tests/visual` holds pixel baselines (chromium only).

## The screen, as of the terminal expansion

Three columns. The **left** column has its own tab strip: *Day* holds the
four IBKR market-cap scanners, *Swing* holds four TradingView setups that
work with no TWS running. Key levels sit beneath both.

The **middle** is tabbed too — Chart, Financials, Metrics, Insiders, Peers —
and the chart is **hidden with `visibility`, never unmounted**. A
`display:none` container is zero-height and lightweight-charts cannot size a
pane inside one; unmounting would lose the viewport. See
`docs/terminal-expansion.md`. The **order strip** sits across the bottom of
this column, *outside* the tab panel, so a position stays on screen while a
balance sheet is being read.

The **right** dock has five tabs — Charts, AI, Fund, News, Filings — and the
first one is now **one** 1-minute context chart over the **time and sales**
window, where two charts used to stack. A 5-minute candle is a summary of
what the tape already said, and on a small-cap runner the tape says it first.
`MINI_SLOT_COUNT` in `chart/mini.ts` is the one number that decides how many
charts there are; the slot machinery still supports more.

## The tape shows what the bars are built from, and no more

`docs/time-and-sales.md` is the design. Three things about it are easy to
break by accident:

**Nobody's feed publishes the aggressor.** Neither SIP carries a side field,
and neither does IBKR's tick-by-tick. Every green row is `domain/tape.py`
comparing the print against the newest quote to have arrived. The tolerance
is 1e-9 — representation error and nothing wider, because a print one cent
through the offer is a sweep and has to read as one.

**Odd lots never reach the tape**, because it reads the same stream the bars
do and `TICK_TYPE = "Last"` omits them — a measured decision recorded in
`providers/ibkr.py`, worth 26.6% of volume. So this window shows round lots
and up while a Lightspeed tape beside it shows more rows. Changing that means
changing what every volume figure on the screen means; do not do it as a side
effect of a tape change.

**The freeze tracks what it is holding, not the last symbol it saw.** A
symbol switch clears the store's tape a beat before the new company's buffer
arrives, so a paused window has one render where the tape is legitimately
empty. Re-arming on that render latches the empty list for as long as the
pause lasts — a lit pause button over a blank window, which reads as a dead
feed. `TapePanel`'s `frozenOn` ref is null until the new symbol has actually
printed, and `tape.spec.ts` pins it with a delayed snapshot.

**Late reports and average-price prints are shown, not dropped.** They are
real volume at a price that is not a market price now, so they carry a dot
and a filter rather than vanishing. A tape that quietly drops prints cannot
be trusted for what it does show.

### Two traps this codebase has already paid for

**NaN passes `isinstance(x, float)`.** Every screener row comes through
pandas, which fills a missing cell with NaN, and every comparison against NaN
is False — so a row carrying one passes a filter *by failing its test*, and
sorting a list with a few in it scrambles the order. Anything numeric coming
from TradingView goes through `app/domain/screener.finite()`.

**A filing's `fy`/`fp` describe the filing, not the fact.** A 10-K restates
prior years as comparatives, so Apple's FY2016 revenue is tagged `fy: 2018`.
A fact's period is `start`–`end` and nothing else.

**A screener's universe filter is not a lookup filter.** `_common_stock_terms()`
in `services/tv.py` keeps to primary listings of US common stock, which is
right when ranking a list nobody asked for names on and wrong when somebody
typed the symbol. Reusing it in the watchlist blanked three whole classes
while still drawing a row for each: Canopy Growth (`is_primary` is False —
its primary listing is the TSX), every ADR (Alibaba is typed `dr`, not
`stock`), and every ETF. The last one is not even ours: `tradingview_screener`
injects its own default `filter2` that excludes ETFs outright, so the fix was
`set_property("filter2", ...)`. See `services/watchlist.py`.

### The 10-second window is three slices, and only two are IBKR's

The last four hours are the first paint, hours four to twelve the background
extension — both native IBKR requests. Behind them, the previous session is
walked off Alpaca's **trade tape**, because Alpaca's bars endpoint bottoms
out at one minute (checked: `10Sec`, `10S`, `30Sec`, `1Sec` all answer 400
`invalid timeframe`) and IBKR's 10s requests cap at four hours each, so
reaching yesterday natively would cost ten chunks per ticker switch against
a sixty-per-ten-minutes pacing allowance.

That depth exists for one reason: **`ema()` returns nothing at all until it
has `span` values**, and the 10s chart's slowest line is EMA 600. Twelve
hours held 1,078 ten-second bars for SPWR at midday and 1,741 for WETO, so
the line started most of the way across the chart; one previous session took
those to 3,064 and 4,738. A bar exists only where a trade printed, so this
is about the *name*, not the clock — AEMD managed 72 bars in twelve hours and
299 in two sessions, and needs `history.tensec_prior_sessions` raised to draw
a slow line at all.

Two things follow that are easy to undo by accident:

- **The tape walk is capped and newest-first** (`alpaca.max_prior_session_pages`).
  Uncapped, AAPL burns forty pages and ten seconds and still never reaches
  yesterday. Capped, what survives is the stretch adjacent to today, which is
  the part that has to join up.
- **Only the IBKR-served window is folded back into the minute base.**
  `_refresh_minutes_from_tensec` deliberately clamps to the last twelve
  hours: the prior sessions were rebuilt from Alpaca's tape through our own
  condition filter, and Alpaca's *published* minutes for a session that
  closed yesterday are better than our rebuild of them. There is no
  delayed-feed gap to close in a closed session.

Session-scoped indicators are safe across the wider window because every one
of them keys on the New York date — VWAP, HOD/LOD and the pre-market range
all reset per day, so yesterday's bars carry yesterday's lines.

### News comes from two places, and one of them is a socket

IBKR carries eight entitled feeds; Alpaca carries Benzinga. The second exists
because the first goes quiet on exactly the companies this terminal is for —
WETO returned its own halt and its own resume and nothing else, against ten
rows from Benzinga, and AEMD had nothing in thirty days while its catalyst
sat in EDGAR. Both land in one per-symbol dict keyed by article id, so the
dedup runs across them.

**Alpaca news is real time.** The `delayed_sip` entitlement governs the price
tape only. Measured: the newest market-wide REST item was 93 seconds old, and
headlines arrive on the websocket about 1.9 seconds *ahead* of their own
`created_at` stamps.

**Alpaca allows one news socket per account.** A second connection takes it
rather than sharing, and the loser sees a close with no close frame — found
by running a probe beside a live terminal and watching the probe get thrown
off. Two copies of this app will trade the connection back and forth through
their reconnect loops.

**The stream is off in every test** (`TRADERAPP_ALPACA__NEWS_STREAM=false`,
and `news_stream=False` in the integration settings). It is a websocket, so
respx does not intercept it and a live one dials Alpaca for real from a unit
run.

The market-wide rate is about one headline a minute, so an end-to-end check
against live news needs patience or a wide net: forty-five of the most
covered US names produced nothing in four minutes, which was the feed being
quiet and not a bug.

### Two panels ask Claude to read something

`docs/ai-architecture.md` is the layer — the shared runner, the sandbox, the
caching, the measurement harness and what it has found. `docs/news-summary.md`
and `docs/setup-judgement.md` are the two panel designs, and
`.claude/skills/ai-panel/SKILL.md` is the procedure for changing a prompt.
What follows is only what a careless edit breaks.

**The news window is a session, not a calendar day.** This was wrong here first
and is the single easiest thing to break again: a press release at 16:05 is not
today's news, it is *tomorrow's gap*. Keyed on the New York date it lands under
yesterday, so a chart opened at 08:00 on a name that announced an FDA clearance
at 16:10 the night before summarised whatever trivia had printed since
midnight. The window runs from the previous close to now.

**The setup judge is not a checklist, and that is the whole point.** The five
pillars are weighed jointly: a stock at $19 with a 19M float up exactly 10% on
RVOL 5.1 clears all five, marginally, and is a *worse* trade than one
exceptional on three that openly fails a fourth. The strip above the chart is
already the conjunctive filter. If that sentence ever leaves `setup_prompt.py`
the panel becomes a slower copy of the strip —
`test_the_rubric_holds_the_joint_evaluation_rule` is what stops that.

**The score is catalyst quality, not a trade signal.** The news reader sees
headlines and bodies and nothing else. A 2 means *this news is not a reason to
be long*, never *do not trade this*. A test asserts the sentence is still there.

**The flags are the sandbox.** `--tools ""`, `--safe-mode`,
`--strict-mcp-config`, `--permission-prompts none`, `cwd` at `$HOME`. Not
`--bare`: that one demands `ANTHROPIC_API_KEY` and never reads the OAuth this
machine actually has. `test_the_reader_runs_with_no_tools_and_no_project_config`
asserts the argv flag by flag, because this is the sort of thing a later edit
tidies away.

**Both are off in every test** — `news_ai.enabled=False`, `setup_ai.enabled=False`
in the integration settings and `TRADERAPP_*__ENABLED=false` in
`playwright.config.ts`, beside `news_stream` and `trading` and for the same
reason: respx cannot see a subprocess any more than it can see a websocket. The
service is tested against a shell script in `tmp_path` that reads stdin and
prints an envelope. When that fake sleeps, **redirect its stdout** — a child
holding the pipe keeps the transport alive past the test and surfaces as an
unraisable "Event loop is closed".

**Both panels stay on the same model, and it stays an alias.** `sonnet`, not a
pinned id: the judge consumes the news reader's score, so a mixed pair is two
readers arguing about one screen, and a pin is a panel that stops improving.

**Point-in-time float exists and is in the backtesting repo**, which I claimed
it was not, off a directory listing rather than a check —
`03_reference/build_insider_float.py`. Consume it **only through `pit_float()`**:
amendment resolution, owner-group carry-forward, role-aware staleness and split
restatement all live in that function, and its own README says a hand join
silently re-derives at least one of them wrong. `pit_market_cap()` is its twin.

## Order entry spends real money

`docs/order-entry.md` is the design; the rules that matter from here:

- **`trading.enabled` is False**, in settings and written out explicitly in
  the integration settings beside `news_stream`. It is a raw socket to TWS on
  this machine, respx cannot see it, and the thing on the other end places
  real orders against a **live** account, on `port: 7496` — the live TWS
  port, not the paper one. Never flip it to run a test.
- **The client never sends a share count.** It sends the dollar amount or the
  fraction; `services/trading.py` recomputes the quantity from the freshest
  quote and IBKR's own position. The command models forbid extra fields, so a
  quantity cannot be smuggled past that even by a hand-written client.
- **The arithmetic exists twice** — `domain/orders.py` and `lib/orders.ts` —
  and is integer micro-dollars in both, because that is what makes them agree
  bit for bit. In floats, `0.98 - 0.05` is 0.9299999999999999 and the tick
  snap turned that into a limit of **0.9299**. Both are asserted against one
  table, `frontend/src/lib/order-cases.json`. Add a case there, not to a suite.
- **`is_available` means connected *and* set up.** `ib_async` marks the socket
  connected partway through `connectAsync`; for ~300ms the account has not
  resolved and no handler is attached, so an order would go out with nothing
  listening for its fills and the strip would draw FLAT on a long account.
  `socket_connected` is the raw state and only the connect loop wants it.
- **Read-only is a TWS checkbox, not a code flag.** `ib_async`'s `readonly=`
  only skips the client's own open-order fetch. Global Configuration → API →
  Settings → "Read-Only API" is what actually rejects orders, and it cannot be
  detected until the first one is tried.
- **The strip renders nothing with trading off**, so it changes no visual
  baseline. That absence is asserted, not assumed.

## Visual baselines

Tolerance is `maxDiffPixelRatio: 0.004`. A small added chip is well under
that, so **a green visual run is not evidence that a small component change
was noticed** — this has silently passed against stale baselines twice. After
any toolbar or strip change, assert the new element renders, then regenerate.

**Regenerate with `--update-snapshots=all`, not `--update-snapshots`.** The
bare flag only rewrites a baseline whose comparison *failed*, and the whole
problem is that these changes do not fail. A toolbar star and a third sidebar
tab left all five baselines untouched under the bare flag and rewrote three
under `=all`.

## The audit suite

`backend/tests/audit/` checks our own figures against **yfinance** and
**TradingView**, over the network, for twenty companies spanning market-cap
tiers, sixteen sectors, four countries and four reporting currencies.

It is excluded from every normal run — `addopts` carries `-m 'not audit'`, so
`pytest tests` still never leaves the machine. Run it deliberately:

    cd backend && .venv/bin/pip install -e '.[audit]'
    cd backend && .venv/bin/pytest -m audit          # ~60 s, 511 tests

`companyfacts` is cached under `tests/audit/.cache/` so a second run costs
nothing and the SEC is not asked twice.

`test_watchlist.py` is the exception to the two-auditor pattern below: it has
no outside source to compare against, because it is not checking a *figure*.
It asks the live screener whether ten named symbols — an ADR, an ETF, a
second share class, a secondary listing — come back with a price at all. That
class of fault is invisible to a unit test, since every symbol still produced
a row and every one of those rows was empty.

The two auditors answer different questions. **yfinance** reports in the
filer's own currency, so it checks the *parse*: the right concept, the right
period, before anything is restated. **TradingView** publishes in USD, so it
checks the *conversion*. Failing one and passing the other localises a fault
immediately, which is the reason for using two.

`test_indicators.py` and `test_screens.py` cover the chart half. The chart
has no published truth — nobody else computes a moving average over *our*
bars — so it checks the two things that can be: that our bars agree with
everyone else's (our closes match TradingView's exactly), and that our
arithmetic over them lands where theirs does. It does, to the fourth decimal.

Two differences there are **design, not error**, and are asserted rather than
tolerated. A drawn level excludes today's bar so it cannot repaint mid-
session, which is a deliberate one-bar difference from every other terminal.
The yearly extremes used to run over 252 *bars*, which is an approximation of
a year that drifts at the edge — exactly where a yearly extreme tends to sit.
They now span calendar weeks (`high:52w` in `indicators.yaml`, against
`high:252` for a bar count), and every symbol matches the market's figure to
0.0000%.

`test_key_levels.py` walks every level a chart draws and holds it against
what other platforms show, because a level is a line a trader acts on and
ours sitting somewhere nobody else's does means a different chart. The
rolling extremes, previous close, and weekly and monthly bucketing all agree
to 0.00%.

One level has no TradingView column to check it with. `High.YTD` resolves as
a column name and comes back null for every symbol asked, mega caps included,
so the year-to-date high is audited against yfinance's own daily bars — the
highest print since 1 January, by hand. It agrees to the fourth decimal on
every US subject.

Two differences there are real and are **asserted**, not tolerated. The day's
range runs 04:00–20:00 rather than the regular session, because on a small
cap the high of day is very often set before 09:30 — Apple's low on
2026-08-28 was its pre-market low, 0.18% under the figure TradingView shows.
And pre-market extremes sit within a few basis points of another vendor's,
because two consolidated tapes disagree about which prints set an extreme.

The screens have no external truth at all — they are our own definition — so
they are checked against their own printed claim. A panel headed "within 10%
of the 52-week high" returning something 40% below is worse than an empty
panel, because it is believed.

The ratio audit (`test_ratios.py`) covers what is built *on* the statements,
which is where a mistake reaches a decision. It exists because that layer
drifted unnoticed: every multiple was quoted on the latest fiscal year while
the rest of the world quotes a trailing twelve months.

### Reading a disagreement

**A disagreement is not automatically our bug.** The first run produced 49,
and 38 were one thing: yfinance publishes an *adjusted* "Operating Income"
alongside "Total Operating Income As Reported", and only the second is the
figure in the filing. For Crocs in 2025 they are $888M and $150M, the
difference being a goodwill impairment. Compare against the wrong one and
the audit condemns thirty-eight correct readings.

Before changing anything, find out which side is right — usually by reading
the concept straight out of `companyfacts`.

Genuine differences live in two tables in the suite, each entry carrying its
reason: `EXPECTED_DIVERGENCE` (a bank's "revenue" has no single definition;
yfinance folds redeemable minority interests into equity and US GAAP does
not) and `INCOHERENT_PERIODS` (Celularity's 2020, where `companyfacts` holds
both the SPAC's balance sheet and the predecessor's under one date because
the dimensions that separate them are not published). The point of an audit
is lost the moment those become a way to silence a failure.
