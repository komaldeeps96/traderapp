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
| 4 | Main tab shell, Chart as tab one, Financials tab | next |
| 5 | Metrics and valuation, with `frames` percentiles | |
| 6 | Swing scanner tab | |
| 7 | Ownership — Form 4, 13D/G, 13F | |
| 8 | Events and peers | |
| 9 | Segments (bulk data sets), FINRA short interest | |

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
