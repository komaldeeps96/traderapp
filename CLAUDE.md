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
    cd e2e && npx playwright test --project=chromium    # ~1.3 min, 311 tests
    cd e2e && npx playwright test --project=visual      # ~7 s,      5 tests
    cd e2e && npx playwright test --project=fullstack   # ~16 s,    19 tests
    cd e2e && npx playwright test --project=firefox     # ~1.9 min, 311 tests
    cd e2e && npx playwright test --project=webkit      # ~2.5 min, 311 tests
    cd e2e && npx playwright test --project=mobile      # ~8 s,      8 tests

A full sequential pass is about seven minutes and holds memory above 80%.
All six browser projects pass clean this way: 311 / 5 / 19 / 311 / 311 / 8,
alongside 1148 backend and 344 frontend unit tests.

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
pass 251/251 when run sequentially.

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
`docs/terminal-expansion.md`.

The **right** dock is unchanged: context charts, fundamentals, news, filings.

### Two traps this codebase has already paid for

**NaN passes `isinstance(x, float)`.** Every screener row comes through
pandas, which fills a missing cell with NaN, and every comparison against NaN
is False — so a row carrying one passes a filter *by failing its test*, and
sorting a list with a few in it scrambles the order. Anything numeric coming
from TradingView goes through `app/domain/screener.finite()`.

**A filing's `fy`/`fp` describe the filing, not the fact.** A 10-K restates
prior years as comparatives, so Apple's FY2016 revenue is tagged `fy: 2018`.
A fact's period is `start`–`end` and nothing else.

## Visual baselines

Tolerance is `maxDiffPixelRatio: 0.004`. A small added chip is well under
that, so **a green visual run is not evidence that a small component change
was noticed** — this has silently passed against stale baselines twice. After
any toolbar or strip change, assert the new element renders, then regenerate
with `--update-snapshots`.

## The audit suite

`backend/tests/audit/` checks our own figures against **yfinance** and
**TradingView**, over the network, for twenty companies spanning market-cap
tiers, sixteen sectors, four countries and four reporting currencies.

It is excluded from every normal run — `addopts` carries `-m 'not audit'`, so
`pytest tests` still never leaves the machine. Run it deliberately:

    cd backend && .venv/bin/pip install -e '.[audit]'
    cd backend && .venv/bin/pytest -m audit          # ~35 s, 352 tests

`companyfacts` is cached under `tests/audit/.cache/` so a second run costs
nothing and the SEC is not asked twice.

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
And the yearly extremes run over 252 *bars* where TradingView uses 52
calendar *weeks*; the windows differ by a few days at the edge, which shows
only when the extreme sits there.

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
