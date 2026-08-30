# Dilution Desk — implementation progress

The fundamentals / news / filings dock. Design brief and rationale:
<https://claude.ai/code/artifact/a29e1ebd-b6a2-4e99-bd61-c068c98fd5ec>

This file is the resume point. Each step is independently shippable: the app
builds, tests pass, and something works on screen at the end of every one.

## Why this shape

IBKR denies every fundamentals path on this account — probed live, see
`tmp/ibkr-fundamentals/probe_fundamentals.py`:

| call | result |
| --- | --- |
| `reqFundamentalData` (all 7 reports) | error 10358 "Fundamentals data is not allowed" |
| generic tick 258 / 456 | silent |
| `reqWshMetaData` / `reqWshEventData` | error 10276 "News feed is not allowed" |
| `reqContractDetails`, `reqMatchingSymbols` | free, no entitlement |
| news: 8 providers, historical, live 292, article bodies | entitled and working |

So fundamentals come from SEC EDGAR (free, keyless, 10 req/s) and TradingView
(already a dependency). IBKR is the news provider. OpenBB was measured at
+250 MB / +102 packages / AGPL-3.0 and rejected — it does not compute warrant
overhang or shelf capacity either, so it would not have removed the work.

## Steps

- [x] **1 — EDGAR provider, filing taxonomy, dilution service** — DONE
      `domain/filings.py`, `providers/edgar.py`, `services/dilution.py`,
      `services/api_budget.py` (+edgar bucket), wired into `container.py` and
      the `symbol_info` prefetch loop. 842 backend tests pass, ruff clean.
      Validated against live EDGAR: CELU reads SERIAL (89% warrant overhang,
      5.6 months runway, baby shelf, 6 offerings, delinquent), AAPL CLEAN.
- [x] **2 — Dock shell, mini charts become tab 1** — DONE
      `lib/dock.ts`, `components/Dock.tsx`, `components/DockPanel.tsx`,
      `lib/storage.ts`, `store/useTerminalStore.ts`, `App.tsx`,
      `e2e/tests/mocked/dock.spec.ts`. 184 mocked e2e pass, visual baselines
      regenerated for the tab strip.
- [x] **3 — Fundamentals tab + TopPanel dilution chip** — DONE
      `api/rest.py` (`GET /api/fundamentals/{symbol}`), `services/symbol_info.py`
      (compact `dilution` block on the `info` message, memoised on EDGAR
      document identity), `types/protocol.ts`, `lib/http.ts`,
      `store/selectors.ts` (`buildDilutionView`), `components/FundamentalsTab.tsx`,
      `components/TopPanel.tsx` chip, `tests/integration/edgar_stub.py`.
      849 backend, 271 frontend unit, 195 mocked e2e.
- [x] **4 — News tab** — DONE
      `domain/news.py` (clean, classify, dedup, `to_paragraphs`),
      `services/news.py`, `providers/ibkr.py` (generic tick 292 plus the three
      news calls), `api/rest.py` (`/api/news/{symbol}` and `.../article`),
      `domain/protocol.py` `news` frame, `components/NewsTab.tsx`, store slice.
      921 backend, 205 mocked e2e.
- [x] **5 — Filings tab + live filing alerts** — DONE
      `api/rest.py` (`/api/filings/{symbol}`), `services/filing_watch.py`
      (one poll a minute on the focused symbol), `domain/protocol.py` `filing`
      frame, `components/FilingsTab.tsx`, dock alert badges.
- [x] **6 — TradingView fundamental columns** — DONE
      `domain/screener.py` `SymbolStats` gained 22 fields, `services/tv.py`
      `_COLUMNS`, `business` block on `/api/fundamentals`, a Business group at
      the bottom of the fundamentals tab. All 22 verified against live
      TradingView; they ride the row the info strip already fetches, so the
      query cost is unchanged.

**All six steps are complete.** 933 backend tests, 271 frontend unit tests,
681 e2e across chromium/firefox/webkit/mobile/visual/fullstack. ruff, eslint
and tsc clean.

## Findings worth keeping

- **A bare Form 25 / 25-NSE is not a delisting signal.** Apple files one most
  years to remove a matured note. The unambiguous company-level signal is
  8-K item 3.01 ("failure to satisfy a continued listing rule"); CELU has four,
  Apple none. `dilution.py` reports both but only escalates on the item.
- **Cash-flow XBRL facts are cumulative from the fiscal year start**, not
  discrete quarters — summing the reported periods counts Q1 four times.
  `_annual_flow` prefers a ~365-day span and annualises the longest
  year-to-date span only as a fallback.
- **Mini charts had a latent bug** the dock exposed: engines are fed only by
  wire snapshots, so one built after the snapshot arrived stayed empty. Fixed
  with `hydrateMini` in `useTerminal.ts`, which also fixes the pre-existing
  case of the window crossing the 1280px breakpoint.
- **Preferred stock is excluded from fully-diluted** on purpose: conversion
  ratios live in the charter, not the XBRL facts, so folding it in at 1:1
  would invent a number. It is reported beside the figure instead.
- **Live news headlines carry no contract id.** `ib_async`'s wrapper receives
  the reqId from TWS and drops it, so a 292 headline cannot be attributed
  directly. It is matched on the trailing `>CELU` marker, falling back to the
  single streamed symbol; unmarked headlines with several symbols streaming
  are dropped rather than guessed onto the wrong chart.
- **Dow Jones truncates headlines mid-word**, so the dedup key is a 45-character
  prefix cut at a word boundary, not a word count — "Collab" and
  "Collaboration" are the same story.
- **The e2e backend had to be told to leave EDGAR alone.** `playwright.config.ts`
  now sets `TRADERAPP_EDGAR__ENABLED=false` beside the existing regime switch;
  without it the fullstack suite would dial data.sec.gov.
- **"Investigational use" is not an investigation.** A bare `investigation`
  keyword tinted a Celularity biotech release red; the terms are now specific
  (`under investigation`, `sec investigation`, …). `definitive agreement` was
  dropped from the upside list for the same reason — for a small cap it is as
  often a securities purchase agreement as a merger.

## Found by running the real stack

Driving the live frontend against live TWS and live EDGAR (market closed,
CELU) turned up four things the test suite could not:

- **`www.sec.gov` answers 403 to a User-Agent without a contact address**
  while `data.sec.gov` answers 200 to the same one. The ticker map lives on
  the former, so the CIK lookup failed and every panel filled with nulls —
  and then told the user the company files nothing, which was a lie about a
  config line. Both endpoints now carry a `note`, the panels render it, and
  `settings.example.yaml` documents the setting.
- **The full read ships `warrant_strike` as a dated figure, the compact chip
  block as a bare number.** The TypeScript type inherited the number, so the
  panel rendered `—` and judged every warrant out of the money.
- **Headlines showed only a clock**, so a filing from June read as this
  morning's news. `formatNewsTime` dates anything not from today.
- **`Files 8K - Listing Notice` was untagged** while the filings tab showed
  8-K item 3.01 on the same day — two panels disagreeing about one event.
  It is Briefing.com's wording for exactly that filing.

- **`/api/fundamentals` fetched TradingView rather than peeking**, because the
  panel loads the instant a symbol changes and could beat the subscribe-time
  warm, leaving the Business group permanently missing.

## Conventions this follows

- Providers degrade to `None` and never raise into a caller (`yahoo.py` is the
  model). Prefetch failures stay independent per source.
- Near-static per-symbol data is REST; only genuinely live things get a WS
  frame (`rest.py` docstring states the split).
- Every EDGAR-derived number carries its `as_of` date. XBRL is quarterly and
  lags; a confident stale number is worse than no number.
- Tone enums beside the facts, never instead of them — the `SpreadTone` /
  `PullbackTone` / `BorrowStatus` idiom in `store/selectors.ts`.

## Running the tests

```
backend/.venv/bin/python -m pytest backend/tests -q
cd frontend && npm test -- --run
cd e2e && npx playwright test
```
