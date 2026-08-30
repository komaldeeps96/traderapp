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
| 2 | Toggle state per timeframe, served from `state.yaml` | next |
| 3 | Main tab shell, Chart as tab one | |
| 4 | Financials tab (EDGAR `companyfacts`) | |
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
