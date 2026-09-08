# Time and sales — the tape, under the context chart

Every print on the open symbol, newest first, tinted by which side of the book
took it. Two greens and two reds, the convention every direct-access platform
uses, because on a small-cap runner the tape turns before the candle does.

It replaced the second context chart in the dock. This file is the design and
the resume point.

## What it looks like

```
┌────────────────────────────────────────────┐
│ 1M   AAPL                        −  +  ↺   │
│                                            │
│              1-minute candles              │
│                  volume                    │
├────────────────────────────────────────────┤
│ T&S  All sizes  Block 1K     AGG  REG  ❚❚  │
│ TIME       PRICE      SIZE              EX │
│ 09:41:07    2.5400   2,500              K  │  ← paid through the offer
│ 09:41:07    2.5300     400              Q  │  ← lifted the offer
│ 09:41:06    2.5250     300              D  │  ← inside; nobody gave way
│ 09:41:06    2.5200     100              Q  │  ← hit the bid
│ 09:41:05    2.5100   5,000              P  │  ← sold through the bid
│ 09:41:04    2.4000     400              •  │  ← late report, not the market
│ ▲ 12.4K  ▼ 5.5K  ████████░░░░░   69% buy   │
└────────────────────────────────────────────┘
```

## Nobody publishes the aggressor

This is the fact the whole feature turns on, and it is worth stating plainly
because it looks like it ought to be false. So it was checked rather than
assumed, 2026-09-06:

| question | answer |
| --- | --- |
| What is on an Alpaca trade? | One live call to `/v2/stocks/AAPL/trades`: every trade carried exactly `c i p s t x z` — conditions, id, price, size, time, market centre, tape. **No side.** |
| What is on an IBKR tick? | `ib_async` 2.1.0, `TickByTickAllLast._fields`: `tickType, time, price, size, tickAttribLast, exchange, specialConditions`. **No side.** |
| Is a quote available at the moment of a print? | Yes. `QuoteService` already holds the newest top-of-book per symbol, on the same stream, for the spread readout. |
| What did that same call show about odd lots? | The first prints back were `["@","I"]`, one share, venue `D` — odd lots off-exchange, which is exactly the cohort discussed below. |

There is nowhere for a side field to come from: the tape reports a trade, not
who was impatient.

So every green row drawn off a public tape is somebody's *inference*, made by
comparing the print against the top of book that was standing for it. Ours is
`backend/app/domain/tape.py`:

| print, against the standing quote | verdict | row |
| --- | --- | --- |
| above the ask | `above` | strong green |
| at the ask | `ask` | green |
| between | `mid` | no tint |
| at the bid | `bid` | red |
| below the bid | `below` | strong red |
| no quote yet, or a crossed book | `unk` | no tint |

The tolerance is 1e-9 — enough to absorb the float representation of a decimal
and nothing more. A print one cent through the offer is a sweep and has to
read as one, so there is deliberately no "near enough to the ask" band.
Sub-penny price improvement lands `mid`, which is correct: it took neither
side.

**The known weakness, stated rather than hidden.** The quote used is the
newest one to have *arrived*, not the one standing at the print's own
timestamp. A print that overtakes its own quote update is judged a few
milliseconds late. It is inherent to inferring a side from two streams rather
than being told one; the alternative is keeping a quote history and binding
each print to it, which costs more than the answer is worth on a window where
no single row is read. It moves a row by one shade, not from green to red.

## Odd lots are not on this tape, and that is on purpose

`app/providers/ibkr.py` subscribes to tick type `"Last"`, not `"AllLast"`.
Measured on a small-cap gapper and recorded there: IBKR's own bars reproduce
the `Last` tape to within 0.1%, while the full tape overshoots volume by
26.6%. Since this app's 10-second history *is* IBKR bars and the minute base
is resampled from it, matching that slice is what keeps the chart consistent.
`app/market/conditions.py` drops condition `I` on the Alpaca side for the same
reason, so a failover does not change what a bar means.

The tape inherits that filter, because it reads the same stream. On a
small-cap gapper odd lots are ~73% of prints and ~21-26% of shares, so this is
not a rounding difference — it is the reason this window shows round lots and
up while a Lightspeed tape beside it shows more rows.

**That is a choice, not a wall.** Odd lots are one constant away —
`TICK_TYPE = "AllLast"` in `app/providers/ibkr.py`, with a matching change to
`_ODD_LOT` in `app/market/conditions.py`. The price is real and should be paid
knowingly: five times the messages to parse and classify per symbol, and
either a tape on a different volume convention from the bars beside it, or a
25% jump in every reported volume, RVOL and float-rotation figure on the
screen. For reading momentum it is also not obviously a gain — a hundred-share
floor is the first thing most traders set on a tape anyway.

What *is* here that a naive tape would drop: **late reports, average-price
blocks and every other non-price-forming print**. They carry real volume at a
price that is not a market price now, so they are shown, marked with a dot in
the venue column, and filterable with `REG`. A tape that quietly drops prints
is a tape that cannot be trusted for what it does show.

## The filters

The standard set, in the order they run — the order is load-bearing.

1. **`REG` — irregulars first.** So a late report at a stale price can never
   be folded into a group of live ones.
2. **`AGG` — then aggregation.** Merges runs of same-price, same-side prints
   that landed within a second of each other. Fifty 100-share prints at 2.50
   become one 5,000-share row marked `×50`, which is the thing actually being
   looked for. The one-second window is what stops it inventing a block out of
   the same price half a minute later.
3. **Size floor last**, so it measures the row as displayed. With aggregation
   on, `≥ 500` keeps that 5,000-share group; filtering first would have thrown
   away every print it was built from.

Plus **Block**, which emphasises rather than hides — a size at or above it
draws bold — and **❚❚**, which freezes the reading and not the filling. The
buffer keeps running behind a paused window, so unfreezing lands on the live
tape rather than replaying a backlog. Filters still apply while frozen, which
is what lets a floor be dialled in against a burst that has already gone past.

Everything but the freeze is remembered across restarts. The freeze is not, on
purpose: coming back to a terminal to find a frozen tape reads as a dead feed.

A symbol switch breaks the freeze open, and the way it does is worth knowing.
Prints are facts about one instrument, so a frozen window left under a new
ticker would be showing the last company's tape — the one thing this window
must never do. But the store clears the tape the instant the symbol changes
and the new company's buffer arrives a beat later, so there is a render in
between where the window is legitimately empty. `TapePanel` therefore tracks
*what the freeze is holding* rather than which symbol it last saw: null until
the new symbol has actually printed, so the empty gap cannot be latched. It
was, once — a lit pause button over a blank window, which reads as a dead
feed rather than as a freeze, and `tape.spec.ts` now pins it with a delayed
snapshot so the gap is certain rather than lucky.

## The lean

One strip under the rows: shares taken at or through the offer against shares
taken at or through the bid, over exactly what is on screen. "Are buyers in
control" is the question the colours are being scanned for, and a bar answers
it faster than the eye reads three hundred rows. Computed over the filtered
rows so it can never disagree with what is above it.

## Where the numbers are

- `backend/app/domain/tape.py` — the print, the five verdicts, the comparison.
- `backend/app/services/tape.py` — the per-symbol ring buffer and its bounds.
- `backend/app/services/broadcaster.py` — `_tick_tape`, the coalescing.
- `frontend/src/lib/tape.ts` — filters, aggregation, the lean, the caps.
- `frontend/src/components/TapePanel.tsx` — the rendering.
- `frontend/src/index.css` — the four tints.

## Bounds, and why each exists

| bound | value | why |
| --- | --- | --- |
| `tape.buffer` | 600 rows/symbol | How far back a scroll reaches through a halt-resume burst. |
| `tape.max_symbols` | 16 | Nothing tells this service a chart was closed. Least-recently-printed is evicted; the cap sits above a session's worth of flipping. |
| `MAX_PRINTS_PER_TICK` | 250 | A resumption can print hundreds in a second. Past this the oldest are dropped, because a tape is read from the top. |
| `TAPE_KEPT` | 400 rows | What the browser holds. |
| `TAPE_RENDERED` | 200 rows | What React reconciles each second. Past this nobody is reading — they are scrolling. |

## Wire protocol

One message type, the chattiest on the socket, so the keys are short.

```json
{"type": "tape", "symbol": "AAPL", "reset": false,
 "prints": [{"q": 4182, "t": 1725638467123, "p": 2.53, "s": 400,
             "a": "ask", "x": "Q", "c": ["@"], "f": 0}]}
```

`q` is a per-symbol sequence, strictly increasing. `t` is epoch
**milliseconds** — the one time on this wire that is not seconds, because at
second resolution the ordering inside a burst is lost and that ordering is
what says whether one order swept five venues. `x`, `c` and `f` are omitted
when empty, which is most prints.

`reset: true` marks the backlog sent on subscribe: the client replaces its
list. It is sent on **every** subscribe, empty buffer included, because that
empty frame is what clears the previous symbol's prints out of a window
somebody is looking at.

Incremental batches deliberately overlap that backlog. The broadcaster keeps
one cursor per symbol, shared by every connected client, and it cannot rewind
for a late joiner — so the client drops anything at or below the sequence it
already holds. One cursor and a cheap dedupe beat a cursor per connection.

## The venue column

Whatever the source calls it, untranslated: a single CTA/UTP character from
Alpaca (`D` is FINRA's ADF — the off-exchange prints), a name like `NASDAQ`
from IBKR. Building a lookup table from memory would be inventing data, and
the raw code is what a trader watching for dark-pool prints is reading anyway.

## What is tested

- `backend/tests/unit/test_tape.py` — every boundary between the five
  verdicts, the buffer, the eviction order, the sequence, the wire shape, and
  the broadcaster's coalescing and overlap.
- `backend/tests/integration/test_websocket.py::TestTape` — the opening frame,
  and that a symbol switch replaces rather than appends.
- `frontend/src/lib/tape.test.ts` — the filter order, aggregation's four
  boundaries, the lean, the dedupe and the caps.
- `e2e/tests/mocked/tape.spec.ts` — that each verdict draws its own tint, that
  the two greens are genuinely different colours on screen, and that the
  controls are wired to the filters.

## Steps

- [x] Classify against the standing book, server-side.
- [x] Ring buffer per symbol, coalesced onto the broadcast tick.
- [x] The four tints, in both themes, above the contrast floor.
- [x] Size floor, block emphasis, irregular filter, aggregation, freeze.
- [x] The lean strip.
- [ ] A drag handle on the seam between the chart and the tape. It is a fixed
      4:6 split today, which is right for a laptop and arbitrary anywhere else.
- [ ] Highlight a print that lands at a drawn key level. The levels are
      already in the store; the tape does not read them yet.
