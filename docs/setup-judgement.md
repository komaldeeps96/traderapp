# The AI tab — the setup, judged

Every other panel on this screen reports. The strip above the chart has the
float, the rotation, the relative volume and the spread; the sidebar has the
level ladder; the news tab has the catalyst scored out of ten. All of it is
true and none of it answers the question the trader is actually asking, which
is what the **combination** is.

That is this tab.

## What it looks like

```
┌──────────────────────────────────────────────────────┐
│ SETUP · WETO   READ AT 3.42 · 45s AGO           ⟳    │
│ ┌──┐  Clean A on a 2.1M float — size the 3.55 break  │
│ │8 │                                                 │
│ │A │                                                 │
│ └──┘                                                 │
│ ✕ Easy to borrow on a claimed 2.1M float             │
│ PRICE $3.42  CHG +72.7%  RVOL 61x  FLOAT 2.10M ...   │
│                                                      │
│ WRVOL 61x on a corroborated 2.10M float is carrying  │
│ this, and +72% ranks it top-three of the seven names  │
│ up 50% today. The single problem is headroom: PM High │
│ 3.55 sits 3.8% overhead, so the pullback entry here   │
│ doesn't pay 2:1 — the trade is the break of 3.55.     │
│                                                      │
│ WHAT CHANGES THIS                                    │
│ › 3.55 must break and hold — no 2:1 beneath it       │
│ › VWAP 3.11 is the fail line                         │
└──────────────────────────────────────────────────────┘
```

## Why a model and not a scoring function

Because the framework it applies explicitly cannot be expressed as one. Ross
Cameron's own thesis about his five pillars is that they are weighed jointly
and never counted:

> A stock at $19, 19M float, up exactly 10%, boring catalyst, RVOL 5.1 —
> technically clears all five pillars. *"Realistically he probably shouldn't
> trade it."*

**A five-pillar stock marginal on all five is worse than a four-pillar stock
exceptional on three.** No conjunctive filter says that. The strip above the
chart is already the conjunctive filter; this is the other thing.

The reverse is in the framework too, as a worked comparison the prompt carries
verbatim: a $21 name up 26% on RVOL 5.5 with news and a **19M float** is "right
on the cusp, I probably wouldn't trade it at all", while a $5 name up 75% on
RVOL 20 with a **1.9M float** is "take more risk on this" — and the isolating
counterfactual is that at only +26% and RVOL 5.5, the 1.9M float would *still*
make it a trade. Float rescues a mediocre setup and condemns a good-looking
one. That is an interaction, not a threshold.

## What it is given

Assembled on the server from six services, not posted by the browser. The
frontend has every one of these numbers on screen and it would be less code to
let it send them — but then the thing being judged is whatever the client says
it is, and a judgement is worth exactly what its inputs are worth.

| Block | From |
|---|---|
| Price, change, previous close, market cap now and then | `symbol_info` + the bar stream |
| Float, shares outstanding, rotation, pre-market rotation, second-source float | `symbol_info` (TradingView + Yahoo) |
| RVOL, **WRVOL**, day volume, 10-day average | `symbol_info` + the `wrvol` indicator |
| Spread, bid/ask and sizes | `quotes` |
| Halts, LULD tier and distances, seconds since reopen | `halts` |
| Borrow status and shortable shares | IBKR |
| The level ladder and headroom | `market_data.series` — the same series the chart draws |
| Pullback leg, depth, bars, volume ratio | `symbol_info` |
| Dilution tone, reverse split, listing age, earnings date | `symbol_info` + EDGAR |
| Regime — names up 50% and 100% today | `regime` |
| The news score, its summary and its risks | `news_ai.peek` |

**WRVOL is handed over as the one that matters**, and the prompt says so. The
framework's denominator is a *time-matched rate* — 30,000 shares by 07:00
reading as "343× typical" is only coherent against one — so day RVOL alone
would be the wrong number under the right name.

The news score is `peek`ed, never fetched: the judge must not spawn a second
process behind the first, and a setup read is worth having with the catalyst
marked unknown.

**Unknown is a rendered state.** Every figure goes through a formatter that
prints "unknown" rather than a zero, and NaN is caught explicitly — it passes
`isinstance(x, float)` and every comparison against it is False, which is the
same trap the screener rows already pay for. An absent float is not a small
float, and a null rendered as `0.00` says exactly that.

## What it gives back

- **score** 0-10 and **grade** A/B/C/F. The grades are the framework's own and
  carry measured accuracy: A is five pillars at 75-90% in a hot tape and
  68-75% in a cold one; B is four at 65-80%; C is three, tradeable in a hot
  tape and **losing money in a cold one**. F means a gate fired, which is a
  different statement from a weak setup and is kept separate for that reason.
- **headline** — about ten words, a decision not a label.
- **judgement** — two to four sentences naming the factor that carries or
  kills it, with the numbers in.
- **pillars** — all five, always, in a fixed order. Anything the reader left
  out renders as *unknown*, never as passing; the row is scanned rather than
  read and a gap in it would be taken for a blank.
- **vetoes** — gates that actually fired, named specifically. Rendered above
  the prose, in the colour every other disqualifier on this screen uses.
- **watch** — what would change the read, in either direction.

### Why vetoes are their own field

The book's finding on catastrophic losses is that they are never "the setup
looked bad generally" — they are one specific rule overridden: the jack-knife
ignored, the MACD negative, the easy-to-borrow traded anyway, size added while
red. So a refusal has to *name its gate*, and a vague veto is how a real one
gets talked past. "Easy to borrow on a claimed 800k float" is a veto;
"structure looks weak" is not.

## It is asked for, and it goes stale

A judgement costs about a cent and one to two minutes. Two consequences.

**Nothing runs until the tab is open.** No polling, no prefetch; opening the
tab asks once and the button asks again. A chart left open all morning spends
nothing.

**It carries the price it was read at.** A setup is a moving target and a
reading eight minutes and twelve percent old is not current, so the panel
marks itself `stale` at **2% of price or five minutes**, whichever comes
first. That is deliberately tight: on the names this terminal is for, two
percent is under a minute, and a judgement that quietly ages into wrongness is
worse than one that admits it is old.

## What it will not do

- **No entry, stop or size.** It says "size it", "quarter size" or "pass"; the
  numbers are the trader's. It has not seen the order book.
- **No exit plan.** When this framework's taught exit ladder — half off at 1R,
  stop to breakeven — was tested on bars it went from **+0.32R** at the real
  trader's hit rate to **-0.52R** at a mechanical one. It is downstream of a
  win rate the judge cannot assume, so it is excluded deliberately rather than
  quietly omitted.
- **No invented numbers.** "Unknown" is a real state and the prompt says so.

## Testing and cost

Off in every test settings object — `setup_ai.enabled=False` in the
integration settings and `TRADERAPP_SETUP_AI__ENABLED=false` in
`playwright.config.ts` — beside `news_ai`, `news_stream` and `trading`, and
for the same reason: it spawns a process that reaches Anthropic, which respx
cannot see any more than it can see a websocket.

The process and its flags live in `services/claude_cli.py`, shared with the
news reader so the sandbox argv exists once, and `tests/unit/test_claude_cli.py`
asserts it flag by flag.

`tmp/news-agent-investigation/` replays both agents over two years of real
movers using these same modules. Float there is point-in-time, from the
backtesting repo's `pit_float()` — `shares_out_PIT − insider_held_PIT` off SEC
Forms 3/4/5 — never a vendor's current float stamped backward, which is the
bias that would make a replay flatter itself. Borrow is the input that
genuinely has no historical source, and that gap is stated in its README.

## Where things are

| | |
|---|---|
| `backend/app/domain/setup_ai.py` | The snapshot, the prompt, the schema, staleness |
| `backend/app/domain/setup_prompt.py` | The framework, in full |
| `backend/app/services/setup_ai.py` | Assembly from six services, the cache |
| `backend/app/services/claude_cli.py` | The child process and its flags |
| `backend/app/api/rest.py` | `GET /api/setup/{symbol}?refresh=` |
| `frontend/src/components/AiTab.tsx` | The panel |
| `backend/tests/unit/test_setup_ai.py` | Prompt contents, pillars, staleness |
| `e2e/tests/mocked/ai.spec.ts` | The panel, and that nothing runs unopened |
