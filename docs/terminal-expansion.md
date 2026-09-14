# Terminal expansion — phase tracker

Indicators on every timeframe, toggles the server remembers, and earnings
proximity where it is always visible. Each phase landed as its own commit
with tests.

Standing decisions:

- **No day/swing profiles.** Indicators are toggled per timeframe by hand;
  the terminal never guesses a trading style.
- **Toggle state is per timeframe** and lives on the server (`state.yaml`),
  not in `localStorage`.
- **The backend computes every indicator**; the frontend decides what to draw.
  That is what makes a toggle instant instead of a round trip.

| # | Phase | State |
|---|-------|-------|
| 1 | Compute every indicator on every timeframe | **done** |
| 2 | Toggle state per timeframe, served from `state.yaml` | **done** |
| 3 | Earnings proximity, where it is always visible | **done** |
| 4 | FINRA short interest | |

## Phase 1 — every indicator on every timeframe

Key *presence* in `config/indicators.yaml`'s per-indicator `timeframes` map is
what decides whether the backend computes an indicator at all.

Organised around four anchor sets:

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

The mocked suite cannot prove a toggle survives a reload: its session is a
fixed fixture, so it asserts the *command* goes out, and the
round trip is proved in the fullstack suite instead.

## Phase 3 — how many days until it reports

The next earnings date was already in the terminal: buried in the dock's
fundamentals list, as an ISO string, with no sense of how soon. Its own
docstring called it "a date to plan around rather than be surprised by",
which is precisely what a bare `2026-10-29` in a list of twenty rows is not.

It now rides the `info` stream — the same TradingView row that already
carries float and market cap, so it costs nothing — and shows in the price
strip as **days**, toned by proximity: red inside a week, amber inside a
fortnight, quiet beyond, and nothing at all past sixty days.

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
  the fixtures sit in March 2024 so runs stay byte-identical, and wall time
  would measure a gap of years.
