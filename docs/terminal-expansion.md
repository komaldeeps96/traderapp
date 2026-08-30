# Terminal expansion — phase tracker

Building a Bloomberg/TradingView hybrid: one terminal for trading *and*
fundamental analysis, with tabs in the main chart area and in the scanner
column. Each phase lands as its own commit with tests, so work can resume at
any phase boundary.

Standing decisions from the brief:

- **No watchlist yet.**
- **No day/swing profiles.** Indicators are toggled per timeframe by hand;
  the terminal never guesses a trading style.
- **Toggle state is per timeframe** and lives on the server (`state.yaml`),
  not in `localStorage`.
- **The backend computes every indicator**; the frontend decides what to draw.
  That is what makes a toggle instant instead of a round trip.
- Main-area tabs **add** information; they do not replace the chart.
- Scanner tabs are separate: today's scanners are day-trade tiers, and swing
  gets its own tab.

| # | Phase | State |
|---|-------|-------|
| 1 | Compute every indicator on every timeframe | **done** |
| 2 | Toggle state per timeframe, served from `state.yaml` | **done** |
| 3 | Financials API — EDGAR `companyfacts` → statements | **done** |
| 4 | Main tab shell, Chart as tab one, Financials tab | **done** |
| 5 | Metrics and valuation tab | **done** |
| 6 | Swing scanner tab | **done** |
| 7 | Ownership — insider Form 4 trail | **done** |
| 8 | Peers — ranked against its own industry | **done** |
| 9 | Earnings proximity, where it is always visible | **done** |
| 10 | Foreign private issuers — IFRS filers | **done** |
| 11 | Segments (bulk data sets), FINRA short interest | |

## Phase 1 — every indicator on every timeframe

The daily chart used to carry four indicators and no key levels at all: the
200-day average was missing from the timeframe it is named after. The cause
was in `config/indicators.yaml`, where the `timeframes` map of each daily
level listed intraday timeframes only — and key *presence* in that map is
what decides whether the backend computes an indicator.

Rewritten around four anchor sets:

| anchor | timeframes | default visible |
|--------|-----------|-----------------|
| `intraday` | the 7 intraday | all |
| `every` | all 9 | all |
| `levels` | all 9 | intraday only |
| `levels_on` | all 9 | all |

Session-derived levels (`pm_high`, `pm_low`, `pm_open`, `rth_open`,
`ah_high`, `hod`, `lod`) keep `intraday`: a premarket high has no meaning on
a bar spanning a week. Everything derived from daily bars moved to `levels`,
and the three a daily chart is genuinely read against — `d_sma200`,
`high_52w`, `low_52w` — to `levels_on`.

**Result: 1d and 1w went from 4 computed indicators to 33, with 9 on by
default.** `test_spec.py` pins all of this, including that session levels
stay *off* 1d/1w and that the default-on set stays small enough to read.

Verified against zero default-visibility flips on timeframes that already
computed, so no existing intraday chart changed appearance.

### The cost, measured

The plan claimed computing everything is cheap. It was not, at first:

| | before | after |
|---|---|---|
| 1d snapshot (2,000 bars, 32 series) | 163.6 ms | **49.1 ms** |
| 1m snapshot (2,000 bars, 13 series) | 25.5 ms | 25.2 ms |
| 1d live tick | 0.24 ms | 0.39 ms |

The live tick was never the problem. The snapshot was, and the cause was a
design note in `_level_series` that had quietly stopped being true:

> One lookup per distinct day rather than per bar.

On an intraday chart 2,000 bars span a handful of days, so that holds. On a
**daily** chart every bar *is* a distinct day, so the lookup ran per bar —
and `_previous_bucket` scanned every calendar bucket on each call, making a
snapshot quadratic in the length of history. Two fixes in `levels.py`:

- `_previous_bucket` bisects a sorted key list instead of scanning.
- `_last_index_before` is memoised. Its answer depends only on the day, and
  some thirty span/prev-day levels asked it again for the same day.

Both are pinned against brute-force scans in `test_levels.py`, and the whole
level surface was diffed against the previous implementation: 27 level keys ×
1,500 days, **0 mismatches**.

A daily snapshot serialises to ~721 KB (32 series, 31,218 points). That is
fine over localhost, and the heavy `prev_day_*` series are computed-but-hidden
by default, which is the point of the phase.

### One thing that looked like a bug and was not

The weekly chart reads `1D SMA 200` differently from the daily chart — 101.12
against 102.01 on CROX. That is not staleness. Levels are evaluated **as of
the bar you are looking at**, and the key-levels panel is a per-bar readout
(`readout = hovered ?? live`), so hovering any historical bar shows that
bar's levels. A weekly bar is stamped with its Monday, so its levels are the
ones that stood entering that week — the same non-repainting contract the
daily chart follows, applied at a coarser bar.

Making the weekly bar read as of the end of its week was tried and reverted:
it made the *current* weekly bar's level move every day, which is exactly the
repaint the contract exists to prevent.

(If that per-bar behaviour is ever unwanted in the panel specifically, the
fix is to give the panel its own timeframe-independent "as of now" value —
not to change what the overlay draws.)

### Verified

- 1017 backend tests, ruff clean; 305 frontend tests, tsc clean.
- Browser: chromium 251, fullstack 17, visual 5 — run one project at a time.
- Real data through Alpaca, 9 tickers across four market-cap tiers × 3
  timeframes = 27 snapshots, **0 failures**, no nulls or NaNs:
  AAPL / MSFT / NVDA, UBER / PANW, CROX / ELF, CELU / SNDL.
- Screenshots taken of CELU (small, $45.7M), AAPL (mega, $4.67T) and CROX
  (mid, $5.86B) on 1D, and CROX on 1W.

## Phase 2 — toggles the server remembers

Indicator visibility was a browser preference in `localStorage`. It is now
in `state.yaml`, keyed by timeframe, and arrives with `/api/session`.

**Only the deltas are stored.** The client sends the whole picture for a
timeframe; the server keeps what differs from `indicators.yaml`:

```yaml
indicators:
  1m:
    ema9: false
    ema20: false
```

That is the load-bearing decision. A saved *copy* of every default would mask
the config forever — change a default and no existing chart would ever see
it. Storing differences means an untouched indicator keeps following the
config, and the file stays the handful of lines a person actually changed.

The server drops ids it no longer defines and ids that do not belong to the
timeframe (`pm_high` on `1d`), so a stale client cannot grow the file or
resurrect a removed indicator. An empty map deletes the timeframe's section
rather than persisting an empty one.

### The seams

- `indicators.visibility` — a new WS command, alongside `scanner.configure`.
- `WsClient` remembers the last map per timeframe and **replays it on
  reconnect**, the same way it replays the subscription. That also covers
  startup, where the migration fires before the socket has finished opening.
- `src/lib/commands.ts` — a one-function sink. The store is plain state and
  knows nothing about sockets; the socket lives in `useTerminal`. A live
  socket handle is not something a component should re-render on, so it is a
  module-level sink rather than a field in the store.
- `/api/session` is now fetched *alongside* the specs rather than after
  them: its overrides have to be in the store before `setSpecs` computes
  what the chart opens with.

### Migration

`takeLegacyVisibility()` reads the old `traderapp.indicators` key once,
deletes it, and pushes each timeframe up. Anything the server already knows
wins, being the newer of the two.

### Verified

- 1030 backend tests, ruff clean; 325 frontend tests, tsc and eslint clean.
- Browser: chromium 256, fullstack 19, visual 5.
- The fullstack tests toggle against the **real** backend and read the value
  back through a reload — the only honest check, since the chart applies a
  toggle optimistically and asserting on the chart alone would pass even if
  the command never left the page. Each restores what it changed and reloads
  again to prove the restore landed, because they share one backend.
- By hand in the browser: toggled EMA 9 and EMA 20 off on 1m, confirmed
  `state.yaml` held exactly those two, **cleared `localStorage`**, reloaded,
  and they came back off. 1D still showed both — the timeframes do not leak.
  Toggling back emptied the section and left the rest of the file untouched.

One thing the mocked suite can no longer prove: it used to verify the toggle
survived a reload, which worked when the browser was the store. Its session
is a fixed fixture, so that test now asserts the *command* goes out, and the
round trip is proved in the fullstack suite instead.

## Phase 3 — statements from companyfacts

`/api/financials/{symbol}?period=annual|quarterly` builds an income
statement, balance sheet and cash flow from EDGAR's `companyfacts`.

The phases were re-cut here. The tab shell was going to come first, but a
shell with one tab in it is an empty strip; the API lands first so the shell
ships in Phase 4 with something real inside it.

### Four traps, all found by reading real filings

**`fy` and `fp` name the filing, not the fact.** Apple's FY2016 revenue is
carried by the FY2018 10-K tagged `fy: 2018`, because a 10-K restates prior
years as comparatives. Keying on those fields files six years of history
under one heading. A fact's period is `start`–`end` and nothing else.

**A 10-Q reports the quarter and the year to date in the same list.** One
concept carries 3-, 6-, 9- and 12-month durations together — for Apple's
revenue, 64 quarterly facts beside 32 cumulative ones. Only the duration in
days separates them, so periods are classified by span, not by presence of a
`start`.

**Concepts fragment mid-history.** ASC 606 stopped `Revenues` in 2018 and
continued it under `RevenueFromContractWithCustomerExcludingAssessedTax`.
Resolving a fallback chain to the first concept that answers returns half a
series, so the chains are merged period by period, earlier entries winning
where both report.

**Fiscal year names are a convention, not a fact.** The year ending January
2026 is "FY2026" to Walmart and Salesforce and "fiscal 2025" to Target and
Gap. The filings do not settle it either: the `fy` field contradicts itself
(Salesforce tags two different year-ends as 2025). So periods are labelled by
the calendar year they close in, and **every period carries its exact end
date** — the label is the convention, the end is the fact.

### Two holes that had to be filled

A quarterly view is half empty without them, and both fall out of the same
arithmetic — within a fiscal year the cumulative figures share a `start`, so
consecutive differences are the quarters:

- **Q4 exists in no 10-Q.** The 10-K covers it, so the last quarter of every
  year is blank unless derived as the year minus the nine months.
- **Quarterly cash flow is never reported.** A 10-Q states cash flow year to
  date, so a three-month cash-flow fact often does not exist at all.

What the company stated always wins; the arithmetic only fills what no form
carried. Checked against Apple: the four derived quarters sum to 416.2B of
revenue and 112.0B of net income, which are exactly the annual figures.

### Verified

- 1062 backend tests, ruff clean. 23 unit tests build fact fixtures by hand
  — every trap above has a test that fails without its fix — and 9
  integration tests drive the endpoint through the offline EDGAR stub, which
  gained an income statement and a mid-series concept change.
- Against live SEC data: AAPL (Sep year end), WMT and CRM (Jan year end),
  and CELU (small cap), annual and quarterly. Apple's figures match its
  reported statements; the Jan-year-end pair label their years and quarters
  the way the companies themselves do.

## Phase 4 — the main area becomes tabbed

A **Chart / Financials** strip under the symbol strip, and the statements from
Phase 3 rendered as a proper table: newest period on the left, subtotals in
bold, negatives in red, the period end printed under every column heading and
the XBRL tags behind a hover on each row.

### The chart is hidden, never unmounted

`visibility: hidden`, holding its layout box. Two constraints meet here and
only one arrangement satisfies both:

- `display: none` collapses the container to zero height, and
  lightweight-charts cannot size a pane inside one. The dock hit exactly this
  and unmounts its charts instead — its own docstring records it.
- Unmounting is not available here, because returning to the chart must
  return it to the same bars at the same zoom, not snap it to the right edge.

Measured rather than assumed: across a tab round-trip the visible logical
range is `{from: 43.02, to: 195.98}` before and `{from: 43.02, to: 195.98}`
after — identical, so the e2e asserts equality rather than closeness.

That test failed first, and the failure was the test's. A range sampled
straight after a zoom is still animating: it drifts from 23.9 to 43.0 over
about a second **whether or not the tabs are touched**. The check now waits
for the range to stop moving before it starts. Attributing the drift before
fixing anything is the whole lesson of the webkit chase in CLAUDE.md.

### A bug only the screen could show

Quarterly **Diluted shares** read **−47.0M**. Differencing year-to-date
figures is right for a flow and meaningless for a *weighted average*: a
nine-month average share count subtracted from a twelve-month one is a
negative number of shares. `LineSpec` gained `additive`, and EPS and share
counts are now left blank in a derived quarter rather than filled with a
number that is wrong. EPS very nearly survived the arithmetic — Apple's
derived 1.84 against a reported 1.85 — which is exactly why it needed
catching by rule rather than by eye.

### Verified

- 1064 backend, 331 frontend, 270 chromium, 19 fullstack, 5 visual.
- Visual baselines regenerated: the tab strip shifts the layout, so three
  snapshots legitimately failed. Asserted the new element renders *first*,
  per the standing hazard in CLAUDE.md, then regenerated.
- In the browser against live SEC data: AAPL annual (eight years) and
  quarterly (with derived Q4 and quarterly cash flow), and SNDL — a Canadian
  issuer filing 40-F, which correctly shows "No XBRL statements on file"
  rather than an empty grid.

## Phase 5 — metrics and valuation

`/api/metrics/{symbol}` and a third main tab. Nothing in `metrics.py` reads
XBRL: it consumes what `build_statements` already resolved, so a concept
chain or a derived quarter is fixed once and every ratio built on it follows.

Two rules run through it, and both are about what it declines to compute.

**A ratio needs both its sides from the same period.** A margin against a
blank revenue is not a small number, it is not a number.

**A negative denominator is refused, not reported.** P/E on a loss,
debt/equity on negative book value, coverage on negative operating income —
each is arithmetically fine and financially meaningless, and "−14.2×" invites
being read as cheap. Growth from a negative base goes the same way: revenue
rising from −2 to 1 is a sign change, not 150% growth.

A refusal reaches the screen as a dash. The frontend never turns it back into
a zero.

**A trailing year needs four quarters.** Three and a gap is not a year, and
summing what is there would understate the denominator — which on a multiple
reads as *cheaper* than the company is.

The valuation strip deliberately mixes two sources: the filings for trailing
figures, the quote side for market cap. A book value is as of a quarter end,
and comparing today's price against it is the entire exercise. Which basis is
on screen is printed rather than assumed.

Checked against Apple: gross margin 46.9%, operating margin 32.0%, ROE 151.9%,
current ratio 0.89, FCF $98.8B, P/E 41.65×, EV $4.71T — all matching the
filings and the tape.

`formatCompact` gained a trillion branch on the way. Apple's market cap
rendered as "$4665.76B", which has to be counted rather than read, and mega
caps are exactly what this expansion added. The visual baselines did *not*
need regenerating for it, and that was checked rather than assumed: the
info-strip fixture's market cap is $62M, nowhere near the boundary.

### Verified

- 1086 backend, 338 frontend, 279 chromium, 19 fullstack, 5 visual.
- In the browser against live data: AAPL, eight fiscal years, with the
  valuation strip priced off the live market cap and interest coverage
  correctly blank in the two years Apple reported no interest expense.

## Phase 6 — the scanner column gets tabs

**Day** holds the four market-cap scanners unchanged. **Swing** is new, and
answers a different question from a different source.

The day scanners rank the tape — trade rate, rotation — and answer "what is
moving *now*". They need IBKR, so they are dark whenever TWS is not running,
which is most of the time outside a session. A swing setup is a question
about daily structure: what has been working, and is it at a place worth
buying. It answers from TradingView, so **that tab fills with nothing else
connected** — which is most of when a swing trader is actually looking.

Four screens, each stating its own setup in a line, because two of them
differ only in how far off the high they want and no name carries that:

| screen | what it wants |
|---|---|
| Trend continuation | above a rising 50 and 200, within 10% of the 52-week high |
| Breakout | at the high on ≥1.5× relative volume |
| Pullback to the 50 | above the 200, 5–25% off the high, back at the 50-day |
| Momentum leaders | strongest month, above the 50-day |

### The filters cannot be sent

TradingView's query language compares a column against a *number*, never
against another column — `col('close') > col('price_52_week_high') * 0.9`
raises `TypeError: unsupported operand type(s) for *`. So "within 10% of the
high" and "back at the 50-day" cannot travel in the request. The coarse terms
go to the server; the proximity tests run locally on rows that came back,
which is why each screen fetches 300 and shows fifteen.

That split is where the tests concentrate: `off_high` is *negative* below the
high, and a sign error there silently turns the pullback screen into a second
breakout screen. There is a test for exactly that inversion.

### A bug that took down the whole terminal

Clicking Swing unmounted the entire app — chart, scanners, key levels —
leaving a white screen. `payload.screens[0]` assumed the array existed, and
the payload arrived without it, so the throw propagated out of React.

The bad payload was the mock's fault: **Playwright uses the last matching
route registered**, so `'**/api/swing/*'` silently answered
`/api/swing/screens` too, returning the rows fixture. But the mock only
*revealed* the fault. One panel's malformed response must never take the
chart down with it, so the panel now validates the shape it got, and an e2e
test feeds it `{unexpected: true}` and asserts the terminal survives.

(The same precedence rule bit the financials mock an hour earlier, where the
comment claimed the opposite. Both are now single handlers that read the URL
rather than two globs racing.)

### Verified

- 1105 backend, 338 frontend, 289 chromium, 19 fullstack, 5 visual.
- 19 unit tests drive the service through an injected fetch, so nothing
  leaves the machine.
- In the browser against live TradingView: all four screens returning real
  candidates with **no IBKR connected**. Breakout returned two names, both
  within 2% of the high at 1.73× and 1.69× volume — a strict screen on a
  quiet day, which is the honest answer rather than a padded list.
- Sidebar visual baselines regenerated; the new strip was asserted first.

## Phase 7 — insiders

`/api/ownership/{symbol}` and a fourth main tab. Taken ahead of the
percentile work because insider buying is directly tradeable and a
market-wide ratio ranking is not.

### Most of a Form 4 trail is payroll

Grants, option exercises and shares withheld to cover the tax on a vest move
the share count and say nothing about what anyone thinks. Counting them is
how "insiders dumped stock" gets written about a vesting date, and it is the
single most common way this data is misread.

Two things carry information, and the module exists to separate them:

- **An open-market purchase** — an insider paying their own cash at the
  market price.
- **A *discretionary* sale** — one not made under a 10b5-1 plan. Plan sales
  are scheduled months ahead and are as automatic as a payroll deduction. The
  form says which is which (`aff10b5One`), so there is no reason to guess.

A plan excuses a sale; it does not excuse cash out of pocket, so a purchase
under a plan is still counted as a purchase.

Only Table 1 is read. A derivative grant and its later exercise would
otherwise land as two rows for one piece of compensation.

**Apple, live:** 38 transactions parsed, of which zero were open-market
purchases or discretionary sales. The panel says "No open-market insider
activity in the window" while showing $1.37M of scheduled plan sales and
$4.85M of compensation beside it. A naive tracker headlines that as
$1.4M of insider selling.

### Cost

This is the only read in the terminal priced per *filing* rather than per
company — the numbers live inside each Form 4 — so it is capped at 24 forms,
cached for fifteen minutes, routed through the same SEC budget as everything
else, and never warmed at subscribe time. It runs when the tab is opened and
not before.

### Verified

- 1133 backend, 338 frontend, 297 chromium, 19 fullstack, 5 visual.
- 28 unit tests build Form 4 XML by hand, so nothing leaves the machine.
- One visual test failed during the full sequential pass and passed alone on
  a quiet machine — contention, per the rule in CLAUDE.md, and re-checked
  rather than assumed either way.

## Phase 8 — peers

`/api/peers/{symbol}` and a fifth main tab, ranking a company against its own
industry on nine measures with the industry median beside each.

This **replaces** the planned SEC `frames` percentile work. Frames would give
a percentile across some six thousand filers, and "80th percentile gross
margin among all US issuers" says almost nothing — the comparison set is
dominated by businesses with no relationship to this one. A 39× earnings
multiple is expensive for a utility and cheap for a chip designer, and only
the industry can tell them apart. It is also one TradingView request instead
of two large frame fetches per ratio.

Which end counts as first depends on the measure: a low P/E ranks well, a low
gross margin does not. The backend owns that; the table only draws it.

**Apple, live:** 1/29 on return on equity and 2/30 on operating margin, but
27/28 on price-to-book and 26/29 on leverage. The most profitable name in the
industry and the most expensive — which is the sentence a peer table exists
to produce.

### A NaN that had been silently wrong

The first peer table put Apple **first of thirty-one** on price-to-book, at
43× against a peer median of 2×. Three peers reported no book value, and
pandas fills a missing cell with NaN — for which `isinstance(nan, float)` is
**True**, so the type guard let it straight through.

NaN then fails silently rather than loudly. Every comparison against it is
False, so a row carrying one **passes a filter by failing its test**, and
sorting a list containing a few puts everything in arbitrary order.

The same guard was in three places — `tv.py`, `swing.py` and `peers.py` — so
the swing screens could have shown a stock with no 52-week high inside a
"within 10% of the high" screen, and `SymbolStats` could have carried a NaN
market cap. All three now go through one `finite()` in the domain layer, and
`_passes` re-checks rather than trusting its caller, because it is the
function whose failure is invisible.

A second scaling bug rode along: TradingView quotes margins as whole
percents, and converting them in the table cell but not in the ranking strip
produced an industry median return on equity of **690%**. The conversion now
happens once, at the boundary.

### Verified

- 1148 backend, 338 frontend, 305 chromium, 19 fullstack, 5 visual.
- Fifteen new unit tests cover the NaN guard alone, including that a filter
  rejects a NaN rather than passing it.
- In the browser against live TradingView: 31 industry peers, Apple's own row
  highlighted, ranks and medians agreeing.

## Phase 9 — how many days until it reports

The next earnings date was already in the terminal: buried in the dock's
fundamentals list, as an ISO string, with no sense of how soon. Its own
docstring called it "a date to plan around rather than be surprised by",
which is precisely what a bare `2026-10-29` in a list of twenty rows is not.

It now rides the `info` stream — the same TradingView row that already
carries float and market cap, so it costs nothing — and shows in the price
strip as **days**, toned by proximity: red inside a week, amber inside a
fortnight, quiet beyond, and nothing at all past sixty days. The same column
was added to the swing rows, where a breakout three days before a report is a
different trade from the one it looks like.

Two things it refuses to draw:

- **A date already past.** The source keeps serving the last scheduled date
  for a while after the event, and "ERN -3d" reads as a date still to come.
- **A date beyond the horizon.** Four months out is not a fact about today's
  position.

`daysUntil` counts **calendar** days through the New York calendar, not
24-hour blocks and not an offset in seconds. A report at six tomorrow morning
is "1d" whether it is eighteen hours away or thirty, because what is being
decided is how many sessions the position has to survive — and an offset in
seconds is only correct inside a session, while a release is stamped at any
hour. There is a test for the spring-forward day, where a 23-hour day breaks
the arithmetic version.

### Verified

- 1148 backend, 344 frontend, 311 chromium, 19 fullstack, 5 visual.
- The e2e counts from the fixture's own frozen clock rather than wall time —
  the fixtures sit in March 2024 so runs stay byte-identical, and the first
  version of the test measured a gap of two and a half years.

## Phase 10 — foreign private issuers

The SEC tabs were empty for SNDL, and I said closing that gap needed a
different data source. **That was wrong.** The data was already in hand: the
same free `companyfacts` endpoint the terminal fetches for every symbol
returns 200 for SNDL with 240 concepts. The tabs were empty because
`financials.py` only looked in the `us-gaap` taxonomy.

A company filing a 40-F or 20-F tags under **`ifrs-full`**. Every line the
terminal draws has an IFRS equivalent, so each `LineSpec` chain simply gained
its counterparts. No branching: a filer that *switched* taxonomies — Canopy
Growth carries both — gets one continuous series from the same period-by-period
merge that already handles the ASC 606 break.

### The currency was the real work

These filers do not report in dollars, and the unit key is the currency:
`CAD`, not `USD`, and `CAD/shares` for earnings per share. Two consequences:

- **The reporting currency is read, not assumed**, and stated on the table.
  A figure with no currency beside it cannot be compared to anything.
- **Valuation multiples are refused across a currency boundary.** Market cap
  for a US listing is quoted in USD while the statements are in the filer's
  own currency, so every multiple would be wrong by the exchange rate — and
  wrong *quietly*, since a P/E of 12 where the truth is 17 looks like
  nothing. Converting needs an FX rate the terminal does not have, so it
  declines and prints why. Margins, growth and balance ratios are one
  currency over itself and survive untouched.

A frontend bug fell out of the same change: `formatStatementValue` tested for
the literal `'USD/shares'`, so a CAD filer's EPS of −0.06 went down the money
branch and rendered as "−$0". It now matches on shape.

### What it actually opened up

Not just Canadian small caps — every foreign private issuer on a US exchange:

| filer | form | currency | revenue |
|---|---|---|---|
| SNDL | 40-F | CAD | 946M |
| Canopy Growth | 40-F | CAD | 285M |
| Tilray | 40-F | USD | 915M |
| Shopify | 20-F | USD | 11,556M |
| Novo Nordisk | 20-F | DKK | 309,064M |
| Alibaba | 20-F | CNY | 1,023,670M |

**Correction to an earlier claim here.** This section first said the
quarterly view "stays empty for these" because foreign private issuers file
6-K interims. That was generalised from SNDL and is wrong. Checked properly:

- **Canopy Growth and Tilray file 10-Q**, so their quarterly view already
  works — CGC back to FY2026 Q2 in CAD, TLRY four quarters in USD.
- **Alibaba, Novo Nordisk and SNDL** genuinely have no interim statements in
  `companyfacts`: BABA carries only three six-month `ProfitLoss` facts,
  SNDL's sub-annual durations are ten-month stub periods, NVO has none.
- But **TradingView carries the latest quarter for all of them** on a row the
  terminal already fetches — `total_revenue_fq`, `net_income_fq`,
  `gross_profit_fq`, `oper_income_fq`, `cash_f_operating_activities_fq`
  and `earnings_per_share_diluted_fq` all resolve for BABA and NVO.

So the gap is one quarter of data from a second source, not an impossibility.
Not built yet, and it carries one hazard worth deciding deliberately:
TradingView normalises to **USD** while these filers report in CNY and DKK,
so it must not share a table with the SEC annuals.

### Verified

- 1162 backend, 344 frontend, 316 chromium, 19 fullstack, 5 visual.
- In the browser: SNDL showing eight fiscal years captioned "in CAD" with EPS
  at −0.06, and its metrics tab dashing every multiple with the reason
  printed beside them.
