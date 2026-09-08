# Order entry — live trading through IBKR

Six buttons. Three buy in dollars, three sell in percent of position, both
sides sized in whole shares by the backend at the moment the order is sent,
both sides priced as a **marketable limit with 5¢ of slack**. Long only.

This file is the design and the resume point.

## What was checked, before anything was designed

Run against the machine and the installed `ib_async` 2.1.0, 2026-09-05:

| question | answer |
| --- | --- |
| Which TWS port is listening? | **7496 — the live port.** 7497 / 4001 / 4002 are all closed. |
| How does the app connect today? | `app/providers/ibkr.py:245` — `connectAsync(..., readonly=True)`, `client_id: 1`. |
| What does `readonly=True` actually do? | `ib_async/ib.py:2057` — it only skips the client's own open-order and completed-order fetches. **Read-only enforcement is TWS's, not the library's**: Global Configuration → API → Settings → "Read-Only API". If that box is ticked, `readonly=False` in code changes nothing and every order comes back rejected. |
| Does the existing connection already see positions? | Yes. `reqPositionsAsync()` runs on connect regardless of `readonly` (`ib.py:2056`), and `reqAccountUpdatesAsync(account)` follows when a single account resolves. |
| Order API surface | `IB.placeOrder(contract, order) -> Trade`, `cancelOrder`, `openTrades`, `positions`, `pnlSingle`; events `orderStatusEvent`, `execDetailsEvent`, `commissionReportEvent`, `updatePortfolioEvent`, `positionEvent`, `errorEvent`. |
| `LimitOrder` signature | `LimitOrder(action, totalQuantity, lmtPrice, **kwargs)` — `tif`, `outsideRth`, `account`, `orderRef` all ride as kwargs. |
| Does a second client id connect to the same live TWS? | **Yes**, verified against the running one: clientId 2 alongside the data client's 1, server version 178, the account resolved from a single managed account, `AAPL` qualified to conId 265598, whole handshake in 311ms. Nothing was ordered. |
| Manual TWS orders visible to us? | Only on `clientId == 0`, which auto-binds them (`ib.py:2046`). On any other client id we see our own orders and nobody else's. Positions are account-wide and always visible. |

Two of these change the plan outright: the app is pointed at a **live**
account right now, and read-only is a TWS checkbox rather than a code flag.

### And one thing the probe found that no amount of reading would have

The first probe run reported `connected: True` with **no account and no
positions**. That was not a fluke of the probe: `ib_async` marks the socket
connected partway through `connectAsync`, while it is still fetching
positions and orders, so there is a window — measured at ~300ms against live
TWS — in which `isConnected()` is True but our event handlers are not
attached, the account has not resolved, and no position snapshot has arrived.

An order sent in that window would go out with no account and, worse, with
**nothing listening for its fills**; and the strip would draw `FLAT` on an
account that is long, which is the one lie a sell button must never tell. The
window opens exactly when TWS comes back mid-session — precisely when
somebody hits a sell button.

So `is_available` means connected **and** set up, and it is the only thing
`place()` and the panel consult. `socket_connected` is the raw state and only
the connect loop looks at it. There is a matching hazard on the way back in:
re-attaching handlers across a reconnect would double every fill report, so
`_attach` detaches first — which works only because eventkit compares
handlers by equality rather than identity, a bound method being a fresh
object on every access. Both are asserted in `tests/unit/test_ibkr_broker.py`.

## The offset — you are right, and here is why

> "5 cents above ask and 5 cents under bid, correct me if I'm wrong there."

Correct, both sides.

- **Buy** — limit at `ask + 0.05`. Priced *through* the offer, so it crosses
  and fills instead of joining the bid and waiting.
- **Sell** — limit at `bid − 0.05`. Priced *through* the bid, same reason.

The part worth being explicit about, because it reads wrong at first glance:
**the offset is a cap, not a price.** A limit order fills at the best
available price, never at the limit. Ask 4.20, limit buy 4.25 → you fill at
4.20 if there is size there. The 5¢ is only spent if the book moves or thins
between the click and the arrival — which is exactly the case this feature
exists for. It buys certainty of fill in a fast tape and costs nothing in a
slow one.

Two things it is not free of:

- **5¢ is not a constant in percentage terms.** On a $40 name it is 12 bps;
  on a $0.40 name it is 12.5%. So the offset is **`max(offset_cents,
  offset_bps × price)`** — a 5¢ floor that stays proportionate on an
  expensive name and never shrinks below a usable slack on a cheap one. At
  15 bps the two cross at $33.33: below that the 5¢ floor rules, above it
  the basis points do.
- **A limit price must land on a valid tick or TWS rejects it.** SEC Rule 612:
  $0.01 above $1.00, $0.0001 below. So the offset is applied and *then*
  rounded in the marketable direction — buy rounds **up**, sell rounds
  **down** — never to nearest, which could round a marketable order back
  inside the spread.

## Sizing

Whole shares, floored, both sides. No fractional.

**Buy.** `shares = floor(dollars / ask)`.

Sized on the **ask**, not on the last trade and not on the limit price. The
ask is what you expect to pay, it is what makes `$25 · 6 sh` the number a
person computes in their head, and the 5¢ above it is protection that
usually goes unused. Worst case a $25 button spends $25.30.

| button | ask 0.80 | ask 3.30 | ask 4.27 | ask 12.40 | ask 41.10 |
| --- | --- | --- | --- | --- | --- |
| $10 | 12 | 3 | 2 | **0** | **0** |
| $25 | 31 | 7 | 5 | 2 | **0** |
| $50 | 62 | 15 | 11 | 4 | 1 |

**Zero is a real outcome, not an edge case** — a $10 button is dead on
anything over $10. Those buttons render `0 sh` and are disabled rather than
silently sending nothing.

**Sell.** `shares = floor(position × fraction)`, and `ALL = position` exactly
— not `floor(position × 1.0)`, so it can never leave a stray share behind on
a rounding step. 25% of a 3-share position is 0 and that button disables too.

**Fees, said once.** IBKR tiered is $0.0035/share with a $0.35 order minimum.
A $10 entry and its exit is $0.70 of commission — 7% round trip. Nothing here
is wrong; it is just what a $10 order costs, and it is worth knowing before
the buttons get used in anger rather than after.

## Where the arithmetic lives

> "on backend share amount will be calculated and also gets updated in button
> real time"

Both, and the split is the important part:

- **The client never sends a quantity.** `trade.buy` carries `{symbol,
  dollars}`; `trade.sell` carries `{symbol, fraction}`. That is all.
- **The backend recomputes shares at the instant of the order**, from its own
  freshest quote and its own IBKR position, and that number is what reaches
  TWS. A client that has been asleep for thirty seconds cannot send a stale
  size.
- **The client previews the same number locally**, off the quote it already
  has in the store, so the label updates the moment the spread moves with no
  extra traffic and no round trip.
- **The ack carries what actually happened** — the shares sent, the limit
  priced — so the panel shows the real figure and any disagreement with the
  preview is visible rather than silent.

The formula therefore exists twice, in Python and in TypeScript, which is a
drift risk. It is handled the way the wire protocol already handles it: one
shared table of cases asserted in both suites, the way
`tests/unit/test_protocol.py` locks the TypedDicts against
`frontend/src/types/protocol.ts`.

## Where the panel goes

The question was bottom or somewhere else. **Bottom of the middle column,
inside the chart column, below the tab panel.**

The reasoning, in the order it mattered:

1. **It has to be where the eyes already are.** The decision to click is made
   at the chart's right edge and the bid/ask readout. The bottom edge of the
   chart is the nearest fixed anchor to a live price that moves vertically;
   the top of the screen is the furthest.
2. **It must never be behind a tab.** Placed inside the chart column but
   *outside* the tab panel, it survives Chart → Financials → Metrics
   unchanged. A position is a thing you can be in while reading a balance
   sheet.
3. **It must not neighbour the symbol input.** The input is in the toolbar at
   the top. Buy buttons up there are one mistyped ticker away from an
   unintended order.
4. **It must not steal chart width.** The right dock already owns that side,
   and a vertical ladder column would compete with it. A horizontal strip
   costs ~70px of height and no width.
5. **It fits.** At 1440px: 1440 − 320 left rail − ~360 dock ≈ 760px of chart
   column. Six buttons at ~90px plus gaps is ~580px, with the status line
   above it, in one row, at the default dock width.

Rejected: **the right dock as a tab** (hidden behind a tab is disqualifying),
**the left column** (competes with key levels, and is the discovery column,
not the execution one), **a floating chart overlay** (occludes price, and
`ChartControls` already owns that idiom for non-destructive toggles).

This is also where every platform built for this puts it — DAS, Sterling,
Lightspeed all sit order entry directly beneath or beside the price display,
not across the window from it.

### The strip

```
┌──────────────────────────────────────────────────────────────────────────┐
│ WETO   POS 14 @ 4.212   +$1.84 +3.1%   BID 4.25 ASK 4.27   ● LIVE DU1234 │
│ ┌──────┐┌──────┐┌──────┐          ┌──────┐┌──────┐┌──────┐               │
│ │ $10  ││ $25  ││ $50  │          │ 25%  ││ 50%  ││ ALL  │      1 working│
│ │ 2 sh ││ 5 sh ││ 11sh │          │ 3 sh ││ 7 sh ││ 14sh │       [Cancel]│
│ └──────┘└──────┘└──────┘          └──────┘└──────┘└──────┘               │
└──────────────────────────────────────────────────────────────────────────┘
```

- **The ticker is the leftmost thing on the strip, large.** The single worst
  failure mode of a six-button trading UI is buying the symbol you were
  looking at a moment ago. It is spelled out where the click starts.
- **A gap between the groups.** Buys green-tinted and ascending, sells
  red-tinted and ascending, with dead space between. The two innermost
  neighbours are `$50` and `25%` — the least costly mis-click pair available.
  `ALL` sits at the far edge, furthest from every buy button.
- **Fixed button widths and tabular figures**, so a share count going from
  9 to 10 does not shift the row under a finger already moving.
- **Disabled is visible, and says why** — `no position`, `0 sh`, `no NBBO`,
  `halted`, `TWS down`.
- **Paper or live is on the strip, always.** Read from the port: 7496 live
  TWS, 7497 paper TWS, 4001 live gateway, 4002 paper gateway.

Under it, a one-line positions rail — `AAPL 12 +$3.20 · TSLA 5 −$0.80` — each
chip loading that symbol on click. Not asked for, but a six-button entry UI
that shows only the focused name is a way to end a day long something you
forgot about.

## The connection

**A second IBKR connection, its own client id, `readonly=False`, dark by
default.** Not the existing one.

- The data client is `readonly=True` and that is a safety property worth
  keeping. It is also the client that runs four scanner subscriptions,
  tick-by-tick streams and pacing-limited history, and reconnects through a
  backoff loop whenever TWS blinks. Order flow does not belong on it.
- The broker client does almost nothing: one contract qualification per
  symbol, an order now and then, and three event subscriptions. It is quiet,
  so it stays connected.
- Failure isolates in both directions. A history storm cannot disturb order
  state; trading being off cannot disturb market data.
- IBKR allows 32 concurrent API clients. Two is free.

`client_id: 2` for the broker, against the existing `1`.

Not `clientId 0`, which would auto-bind orders placed by hand in TWS. That is
tempting — it would show manual orders in our panel — but it also means every
manual order becomes something this app's cancel-all can kill. If that is
wanted it is a one-line change and a deliberate one.

## Order shape

```python
LimitOrder(
    action="BUY" | "SELL",
    totalQuantity=shares,          # whole, floored, computed server-side
    lmtPrice=limit,                # tick-rounded in the marketable direction
    tif="DAY",
    outsideRth=True,
    account=settings.trading.account or "",
    orderRef="traderapp",
)
```

`Stock(symbol, "SMART", "USD")`, qualified on the broker connection.

**`outsideRth=True` is not optional.** Small-cap momentum runs pre-market;
without it a limit order simply sits unfilled until 09:30. It is also why
these are limit orders and not market orders — TWS refuses market orders
outside regular hours outright.

**`tif` is the one genuine fork, and it is a risk preference:**

- `DAY` — an unfilled remainder rests. Visible in the working-orders count,
  cancellable. The danger is a stale resting buy at the old ask+5¢ filling on
  the retrace, entering as the move fades.
- `IOC` — an unfilled remainder cancels instantly. No stale fills. The danger
  is on the *exit*: a sell that silently cancels leaves you long, believing
  you are flat.

At 2–14 shares a marketable limit essentially always fills, so this is a tail
either way. **`DAY` is the choice**, because the failure it produces is a
resting order you can see and cancel, while IOC's is a position you think you
do not have. It is one settings line to flip.

The strictly better third option is `DAY` plus a client-side cancel after ~3
seconds unfilled — IOC's staleness protection with DAY's visibility. Worth
building second, not first.

## Safety

Real money, six buttons, no confirmation dialog — because a confirmation
dialog defeats a one-click momentum entry, which is the entire feature. The
protection is elsewhere:

1. **`trading.enabled: false` by default**, and explicitly false in every
   test settings object, exactly as `alpaca.news_stream` already is. With it
   off the broker never connects and `place()` is unreachable.
2. **`max_order_dollars` — a hard server-side cap**, rejected before anything
   reaches TWS. A bug in the dollar arithmetic cannot become a $50,000 order.
3. **Long-only is enforced on the backend**, not by disabling a button. Sell
   quantity is clamped to the current long position; a sell can never exceed
   it and so can never open a short.
4. **In-flight guard per button.** A double-click sends one order. The button
   goes to `sending…` and comes back on the ack.
5. **Halts disable the side.** `HaltTracker` already knows; the strip shows
   `HALTED` and the buttons go dead.
6. **Rejections are loud.** `errorEvent` and a rejected `orderStatus` land on
   the strip in red and stay there until the next action, rather than in a
   log nobody is reading during a move.
7. **`Cancel all`** on the strip, always live.

### Setup that is not code

- TWS → Global Configuration → API → Settings → **untick "Read-Only API"**.
  Without this every order is rejected, whatever the code says.
- The same page: Socket port, and whether this is the live or paper login.
- Precautionary settings on that page (order size limit, order value limit,
  percentage-off-market limit) will block orders silently-looking if left at
  defaults on a new install. A 5¢ offset trips none of them; a zero-share
  order does.

## Settings

```yaml
trading:
  enabled: false            # master switch; off here and off in tests
  host: 127.0.0.1
  port: 7496                # the live account, same TWS as the data client
  client_id: 2              # the data client is 1
  account: ""               # blank = the single managed account
  offset_cents: 5           # the floor
  offset_bps: 15            # and the proportionate part; the larger wins
  buy_dollars: [10, 25, 50]
  sell_fractions: [0.25, 0.5, 1.0]
  tif: DAY                  # or IOC — see above
  outside_rth: true
  max_order_dollars: 60     # hard cap, server-side
```

This points at the **live** account, so the cap does the work the port
default was going to do: 60 is a hair above the largest button, which means
no arithmetic bug anywhere in the stack can produce an order larger than the
one you meant to click. Raising the buttons means raising the cap, on
purpose, in the same file.

## Wire protocol

Inbound, added to the command union in `domain/protocol.py`:

```
{action: "trade.buy",  symbol, dollars}
{action: "trade.sell", symbol, fraction}
{action: "trade.cancel_all"}
```

Outbound:

```
{type: "trading",  enabled, connected, account, paper, note}
{type: "position", symbol, shares, avg_cost, unrealized, realized}
{type: "order",    order_id, symbol, side, shares, limit, status,
                   filled, avg_fill, message}
```

Positions and orders broadcast on change, off `updatePortfolioEvent` and
`orderStatusEvent`. Position truth is IBKR's, never our own fill arithmetic —
the account may be traded from TWS at the same time.

## Steps

Each one leaves the app building and the suites green.

- [x] **1 — `TradingSettings`, off by default.** Settings, example yaml, and
      the explicit `enabled=False` in the integration settings.
- [x] **2 — `domain/orders.py`.** Pure arithmetic, no IO: `shares_for_dollars`,
      `shares_for_fraction`, `limit_price`, tick rounding. Unit tested against
      the shared case table, including sub-dollar ticks and the zero-share
      cases.
- [x] **3 — `providers/ibkr_broker.py`.** The second connection, `readonly=
      False`, positions and order events out, `place` and `cancel_all` in.
      Never reachable with `enabled: false`.
- [x] **4 — `services/trading.py`.** The cap, the long-only clamp, the
      in-flight guard, the quote and position lookups, the fan-out.
- [x] **5 — Protocol and WS dispatch.** The three commands, the three
      messages, the TypeScript mirror, the protocol test.
- [x] **6 — `lib/orders.ts` + `OrderPanel.tsx`.** The preview arithmetic
      against the shared table, then the strip.
- [x] **7 — Positions rail, cancel-all, rejection surface.**
- [x] **8 — Visual baselines.** *Not regenerated, and that is the correct
      outcome:* with trading off the strip renders **nothing**, so the
      terminal's default appearance is unchanged and all five baselines still
      pass. This is not the stale-baseline trap in CLAUDE.md — the absence is
      asserted positively (`the strip is not rendered at all`) rather than
      inferred from a green run.

## Where it stands

Green: 1556 backend, 420 frontend unit, and 375 / 5 / 23 / 375 / 375 / 8
across the six browser projects.

**What has not been exercised is the order path itself.** The connection, the
account resolution, the position feed and contract qualification are all
verified against the live TWS; `placeOrder` has never been called. The first
real order is the test, and these are the things to watch on it:

1. TWS's **Read-Only API** checkbox — if it is ticked the order is rejected
   and the strip says so, which is the expected first result on a fresh
   install rather than a bug.
2. TWS's **precautionary settings** (order size, order value, percentage
   off market). A 5¢ offset trips none of them, but a fresh install can
   have limits that reject a first order for reasons of its own.
3. That the fill actually reaches the strip. The position and the
   acknowledgement both come off `orderStatusEvent` / `updatePortfolioEvent`,
   and those are the handlers the readiness gate exists to protect.

Start with one `$10` click on a liquid name, in the regular session, and read
the strip rather than TWS.
