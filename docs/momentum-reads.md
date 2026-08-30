# Momentum reads — implementation progress

Terminal features drawn from the Ross corpus at `~/Desktop/ross/research/`.
This file is the resume point. Each step is independently shippable.

## What the source is, and how much to trust each claim

Two very different tiers of evidence sit behind this list, and the difference
decides how a feature is allowed to present itself.

**Measured.** `FINDINGS.md` §2 and Part XIV are backtests over real bars.
These carry n, t and a sign, so the terminal may state them as numbers.

**Narrated.** The book parts are one trader's account of his own trading,
selected by him and diagnosed by him. Part XII §7.1 says so plainly: a loss
caused by a misread entry is precisely the loss least likely to be narrated
as one. These are worth surfacing as context, never as a claim about
expectancy.

Everything below marks which tier it came from.

## Steps

- [x] **1 + 2 — LULD band tier and the reopen window** — DONE
      `services/halts.py` (`HaltState`, transition times), `symbol_info.py`
      (`halt_band_pct`, `halt_band_cents`, `halt_halted_at`,
      `halt_resumed_at`), `lib/format.ts` (`formatElapsed`),
      `store/selectors.ts` (`reopenRead`), `components/TopPanel.tsx`.
      Backend 100% on `halts.py`; 287 frontend unit, 225 mocked e2e,
      17 fullstack, 5 visual all pass.

      *Band tier (narrated, but it is a rule not a claim — Part II §3.5).*
      The width is fixed by the previous close and holds all session: 10%
      above $3, 20% from $0.75–$3, a flat 15¢ below. We computed it and threw
      it away. It decides whether a break has room to run — Part VII §7.3
      records a sub-$3 close where a break of $4 could only reach 4.07 before
      halting, against 70 cents of downside.

      *Reopen (measured — the one large effect in the whole project).* Over
      66,785 reopens the next fifteen minutes averaged +0.33%; the 2,805
      that reopened **before 10:00 ET** averaged **+3.10%** (median +2.44%,
      t = 9.2, 61% up). The sign flips on an already-run name: 3,121 reopens
      on stocks **extended 30–100%** averaged **−1.09%** (t = −4.6). A wide
      20% band beat a narrow 10% one, +0.66% against +0.19%.

      The chip states which of those conditions hold and expires after the
      fifteen minutes the study covers. It does not say to buy anything —
      none of this has ever been traded.

- [x] **3 — Deepen the WRVOL baseline** — DONE
      `indicators/functions.py` (`windowed_rvol`, `_daily_bar_day`,
      `_WRVOL_LOOKBACK_SESSIONS`), `indicators/engine.py` and
      `services/market_data.py` thread the daily base through both the
      series and the once-a-second paths. 993 backend tests, ruff clean,
      98% on `functions.py`.

      `windowed_rvol` was already time-of-day matched — the earlier claim
      that it was not was wrong. Two real defects, both fixed:

      *Mean → median.* One 45x session anywhere in the lookback made a
      genuinely 4x day read **0.41x** — the meter said "quiet" on a stock
      running four times normal, and kept saying it for as long as the heavy
      session stayed in the window. This is the same contamination Part IV
      §9.6 describes from the other side, where the screener's own 50-day
      average punishes a name for having recently been interesting.

      *Depth: 5 sessions → 50.* No persisted profile was needed and no extra
      fetch. `history.intraday_days` is 5 on purpose — a wider 1-minute
      window costs several Alpaca pages per ticker switch instead of one —
      but the daily base is already loaded forty years deep for the same
      symbol. So the minute base supplies the *shape* (what fraction of a
      session is done by this time, median over the days carrying both
      bases) and the daily base supplies the *level* of each of the last 50
      sessions. That split follows what actually varies: between sessions
      the total moves by orders of magnitude while the curve's shape barely
      does, so the large term comes from deep history and the small one from
      shallow. With no day carrying both bases there is nothing to calibrate
      against, and projection is skipped rather than guessed.

      One trap worth remembering: daily bars anchor to **New York midnight**,
      which is outside the 4:00–20:00 window the offset arithmetic is valid
      over — a naive join is off by one for the eight months of EDT. The
      `_daily_bar_day` nudge to New York noon fixes it, and `TestDayJoin`
      pins both offsets.

- [x] **4 — Spike-unlocked baby-shelf capacity** — DONE
      `services/dilution.py` (`ShelfCapacity`, `shelf_capacity`,
      `with_live_shelf`, `SHELF_LOOKBACK_DAYS`), `services/symbol_info.py`
      (`_lookback_high`, `_live_shelf`), `types/protocol.ts`,
      `components/FundamentalsTab.tsx`. 1009 backend tests, 248 e2e, ruff and
      eslint clean.

      The cap everybody quotes comes off `dei:EntityPublicFloat` — measured
      once a year, on the cover of the 10-K. The rule re-measures public
      float on the **date of every sale**, against a price from a 60-day
      look-back, and the cap stops applying entirely above $75M. So the tape
      is what sets the ceiling, not the filing — and on a spike that means
      the run is the legal precondition for diluting at that size, not
      merely an opportunity to dilute into. (It cuts the other way just as
      often on a faded name; see the real-ticker section below, which is
      where that turned out to be the commoner case.)

      Float *shares* now come from TradingView and the price from the 60-day
      high, with the reported dollar figure kept only for contrast. On the
      fixture that is a $9.47M ceiling becoming $20.23M, and past $75M the
      row reads **lifted** rather than quietly showing a bigger number.

      Two things worth remembering. The daily store is strictly historical —
      today's candle is folded in only on read — so the look-back high takes
      the max of both bases or it would miss the very run that moves the
      number. And the capacity is attached *outside* the dilution memo,
      which is keyed on the identity of the EDGAR documents: caching a
      tape-priced figure against the filings would freeze it at whatever the
      stock was worth when those documents last changed.

      The screenshot caught something the assertions did not: the verdict's
      own reason still read "baby shelf limits apply" directly above a row
      saying they were lifted. `with_live_shelf` now reconciles the two,
      because only there is the live figure knowable.

- [x] **5 — Session clock strip** — DONE *(added after reading Part XI)*
      `lib/session.ts` (`NEWS_SLOTS`, `newsWindow`, `slotLabel`,
      `LAST_INITIATION_MINUTE`, `NEWS_WATCH_SECONDS`),
      `components/SessionClock.tsx`. 295 frontend unit, 251 e2e.

      The chip has three states, and the clock is frozen in the tests because
      it is a function of the wall clock and nothing else:

      * `8:30 1:30` — counting down to the next scheduled release window.
        `data-dense` marks 8:00 and 8:30, the two the calendar and the P&L
        both peak behind.
      * `8:30 +0:42` — the mark has passed and anything moving now is
        presumed to be moving on it. Two minutes wide: wire-to-scanner
        latency is 3–15 seconds, the rest is reaction time. Silence through
        the window closes it, which is the other half of the rule.
      * `NO NEW` — past 9:15. No slot is left to wait for and a first trade
        taken now has no runway. The phase badge still reads PRIME beside
        it, which is right: prime is about managing what is open, and this is
        about not starting something. Every documented post-open disaster is
        an initiation; several post-open triumphs are continuations.

      Worth recording: **the visual baselines passed while stale.** A chip
      added to the toolbar is far under the 0.4% tolerance, so the suite went
      green against a screenshot that no longer matched what ships. Caught by
      checking whether the chip rendered at the frozen time rather than
      trusting the pass; baselines regenerated. The tolerance comment already
      warned about exactly this and it still nearly slipped through.

- [x] **6 — Headroom to the next daily level** — DONE
      `store/selectors.ts` (`headroom`, `HeadroomView`,
      `CAPPED_HEADROOM_PERCENT`), `hooks/useKeyLevels.ts`,
      `components/TopPanel.tsx`. 302 frontend unit, 253 e2e.

      Every level already existed — prior day/week/month/quarter/year highs
      and lows, 13/26/52-week extremes, the daily 20/50/200 averages, the
      all-time high. What was missing was the derived read, and Part VIII
      §8.2 is clear that it is not context but the variable that *selects the
      regime*: clear overhead → hold and ladder; a 200-day average sitting
      just above → base hit, because the move stops there.

      Three tones. `ROOM 4.1%` names the nearest visible level overhead;
      `capped` below 3%, where a 15–20 cent target stops covering the 10–20
      cents the round trip costs; `BLUE SKY` when nothing is above at all.
      Hidden levels are excluded — the ladder is the trader's own account of
      what counts as resistance here — and so are levels a thousand percent
      up, which are context rather than a ceiling.

      The chip and the sidebar ladder share one computation in
      `useKeyLevels`, so they cannot disagree about what is next in the way.

      **The visual baselines went stale a second time**, on a chip added to
      the very panel one baseline captures. Same cause as step 5: the diff is
      under the 0.4% tolerance. Worth treating as a standing hazard rather
      than two incidents — a green visual run is not evidence that a small
      component change was noticed, so any strip or toolbar change should be
      checked by asserting the element renders and then regenerating.

## What testing across real tickers changed

Thirty-two real tickers through the live EDGAR and TradingView paths — serial
diluters, heavy reverse splits, sub-penny names, mega caps, and several that
no longer resolve. **Zero exceptions**; eight tickers did not resolve at all
(delisted or renamed), which is the known CIK-identity limitation degrading
honestly rather than failing.

Two things only real data showed:

**The shelf row was claiming something dramatic about companies the rule has
never touched.** Apple's float at the 60-day high is roughly $4.66 *trillion*,
so `capped` is false and the panel rendered "Baby-shelf cap: lifted" in red.
"Lifted" has to have lifted *from* something. The row now renders only where
the cap is or was in play — `baby_shelf` true, or capped right now — which on
the sweep means 13 small caps and none of AAPL/NVDA/TSLA/MSFT/AMD/PLTR/GME.

**The read cuts both ways, and the framing here had it one-sided.** The
emphasis has been on a run *raising* the ceiling, which is the dangerous case.
But most of the sweep's small caps price *below* their last reported float —
AEMD at 0.3×, CENN 0.2×, SNTI 0.2×, APVO 0.4× — because they have faded since
the 10-K. Their live cap is correspondingly *smaller* than the filed one. The
rule is not "the spike unlocks capacity", it is "capacity is measured now",
and the spike is the direction that hurts.

## Formatting: signed versus unsigned

`formatPercent` signs everything, which is right for a change and wrong for a
magnitude. Three places in the strip were rendering quantities that cannot be
negative — spread, pre-market float rotation, headroom — as "+0.4%", "+13%",
"+4.1%", which reads as a change. `formatUnsignedPercent` now covers those.
VWAP delta, bar change and scanner change stay signed, correctly.

The LULD arrows were a different problem wearing the same clothes. The arrow
carries the direction, so "+9.2%" was noise — but the *negative* case is not
a distance at all. The band reference is a five-minute mean, so on a fast
mover price trades through the upper band routinely, and "↑−6.8% ↓+23.7%"
reads as room in both directions when one side is simply gone. It now reads
`↑PAST`.

## A standing hazard, now seen three times

Visual baselines went stale twice on added chips (steps 5 and 6) and were
caught the third time by the sign changes above. The difference is size: a
new chip is far under the 0.4% tolerance, a text-width change across several
fields is not. So a green visual run is *not* evidence that a small component
change was noticed. Any strip or toolbar change should be checked by
asserting the element renders and then regenerating.

## Known flake, not ours

`scanner.spec.ts › clears the price bounds when the fields are emptied` failed
once under parallel load and passes in isolation and on every re-run. It is a
`waitForCommand` race in the scanner filter path, untouched by this work.

## Deferred, with reasons

**Halt reason (LULD vs news).** IBKR's `halted` magnitude already
distinguishes them (1 general, 2 volatility) and Alpaca sends LULD reason
codes; `providers/ibkr.py` collapses both to a boolean. Carrying the reason
through is what makes the *reopening collar* computable — 5% of the reference
applied asymmetrically for an LULD pause, ±10% or ±$1 symmetric for a news
halt, and the news regime applies 04:00–20:00 while LULD does not. Left out
of step 1–2 to hold its scope; the plumbing change touches four providers.

**MACD 12/26/9 on the 1-minute.** The most-cited hard veto in the corpus and
worth a measured +0.078R (Part XIV §6.6), but `config/indicators.yaml` drops
it. Cheap to restore; belongs with a decision about default panes.

**ATM detection, cross-sectional attention, CIK-keyed identity.** Attention
concentration across the top gainers is the single highest-consequence thing
no per-stock scanner can supply (Part IV §9.9), and it is the one with no
obvious data path.

## Caveats worth keeping in view

The reopen numbers are the only large measured effect here, and they have
never been traded. Part II §6.2 is the counterweight: four independent teams
in three top-tier journals find that attention-driven moves in hard-to-value,
costly-to-arbitrage stocks **revert during the session** — which is the same
cohort. The reconciliation, if there is one, is horizon: the reversal
literature measures across the overnight-to-intraday boundary, and a
fifteen-minute hold is inside the pressure phase that *causes* the reversal
it measures. That is a coherent story, not a proven one.

There is also a hard regime break at **2025-07-14**, when the news-halt
reopening collars changed. Any halt study spanning it mixes two mechanisms.
