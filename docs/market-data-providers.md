# Market data: how IBKR and Alpaca actually behave

Reference for the tick feeds, sale conditions and bar construction this app is
built on. Everything here was measured, not read off a datasheet; the numbers are
from FGI (small-cap gapper) and NVDA on 2026-08-13. Where a claim is inferred
rather than measured it says so.

Written because these two providers disagree with each other — and IBKR disagrees
with *itself* between two of its own products — in ways that are invisible until
you line the numbers up.

---

## The short version

| | convention |
|---|---|
| **Our bars** | IBKR's: odd lots excluded from price **and** volume |
| Baseline | IBKR historical 10s bars; the minute base is resampled from them |
| Live stream | `reqTickByTickData(contract, "Last")` |
| Bucketing | the print's **exchange timestamp**, `bucket_start(trade.time, tf)` |
| Consequence | volume matches TWS exactly; runs 21–44% below any SIP-based screener |

The rule lives in `app/market/conditions.py`. It is applied identically to both
providers so a failover cannot change what a bar means.

---

## IBKR

### Tick streams: `Last` vs `AllLast`

`AllLast` is the whole consolidated tape. `Last` is IBKR's last-sale-eligible slice
of it — IBKR applies the filter before sending. Same subscription cost, same
`reqTickByTickData` call, one market-data line either way.

Measured on one contract, sequential 180-second windows:

```
tick type   prints   odd lots         shares
Last           744    0    (0.0%)    166,563
AllLast      3,781  2,767 (73.2%)    262,691
```

Roughly **5× the messages** on `AllLast`. Odd lots are the bulk of the difference,
but `AllLast` also carries combos, derivatively-priced crosses and average-price
blocks that `Last` strips.

Conditions arrive in `specialConditions` as a **packed single-character string**
(e.g. `"@TI"`), not a list. `classify_conditions` accepts either.

On `Last` the only code seen in practice is `F` (intermarket sweep) — which is
price-forming — so the classifier is defence in depth there rather than the primary
filter. It still runs, because it is what makes the Alpaca failover path mean the
same thing by a bar.

### Timestamps are whole seconds

IBKR tick timestamps have **one-second resolution**, and round at the boundary.
Measured: a print at `07:00:59.994634` (7.7974, 172 shares) and one at
`07:00:59.999662` (2 shares) both landed in IBKR's `07:01:00` second, while Alpaca
assigns them to `07:00`.

Impact is confined to prints in the last few milliseconds of a bucket — on a
12,438-print minute it moved 2 prints, 174 shares (0.02%) and set the bar's open
one tick away from Alpaca's. Nothing can fix it; IBKR does not publish sub-second
tick times.

Since 5s and 10s bucket boundaries fall on whole seconds, there is no *additional*
ambiguity at those sizes — a whole-second timestamp buckets unambiguously.

### `reqHistoricalTicks`

- Caps at **1000 ticks per request**.
- **Walks forward from `startDateTime` and ignores `endDateTime`.** Ask for a
  window containing more than 1000 prints in one call and it silently returns a
  *thinned* sample spanning the whole range rather than erroring.
- Within the cap it is **complete** — see the tape comparison below.
- Carries the **full tape including odd lots** (measured `I×819` of 958 ticks),
  even though IBKR's historical *bars* exclude them.

To cover a longer window, chain: request, take the last tick's time as the next
`startDateTime`, repeat. Trim the overlap **positionally**, not by content — see
Traps.

### Historical bars

- Built from the last-sale-eligible slice: **odd lots excluded from both price and
  volume**. This is not SIP-conformant; the SIP counts odd-lot shares.
- Bucket by **exchange timestamp**, the same way we do.
- Two `reqRealTimeBars(5)` bars compose byte-identically into one historical 10s bar.

### Real-time bars (`reqRealTimeBars`) bucket differently

**IBKR's real-time bars and its historical bars do not agree with each other.**
Historical bars bucket by exchange timestamp; real-time bars bucket by *when IBKR
processed the print*. During any burst that smears shares across boundaries.

We do not use `reqRealTimeBars`, so this costs nothing — but it is the reason a
naive live-vs-bars comparison looks like catastrophic data loss when it is not.

### Volume convention

Every IBKR surface — historical bars, real-time bars, the `Last` stream, and the
TWS window — quotes volume **net of odd lots**. Recording the full tape alongside
`reqRealTimeBars(5)`:

```
tape slice                Σ tape / Σ bars
whole tape (AllLast)      460,409 / 363,779   (1.266)
minus odd lots            364,268 / 363,779   (1.001)   <- what IBKR aggregates
```

IBKR is internally consistent and simply not on the SIP's volume convention.

---

## Alpaca

### Feeds and entitlements

| feed | what it is |
|---|---|
| `iex` | free, real time, **IEX exchange only** — a small fraction of volume |
| `delayed_sip` | free, full consolidated tape, **delayed 15 minutes** |
| `sip` | paid, full tape, real time |
| `otc` | OTC tape |

**`delayed_sip` is a streaming feed name only.** The REST bars and trades endpoints
reject it with `400 {"message":"invalid feed: delayed_sip"}`. Pass `sip` instead
and clamp the window end to `now - 15min`, or you get
`403 "subscription does not permit querying recent SIP data"`. This app does that
in `AlpacaProvider._resolve_feed_window`.

### Trades endpoint

10,000 trades per page, `next_page_token` for the rest. Conditions arrive as a
**list** in `c`; timestamps are RFC3339 with **nanosecond precision**.

### How Alpaca builds bars

Alpaca does not invent a rule — it follows the SIPs' own specifications: the **CTS
Pillar Output Specification** (Tape A/B), the **UTP Binary Output Spec** (Tape C)
and **TDDS 2.1** (Tape O). Their wording:

> "Trades are 1) aggregated by the time the trade was executed, 2) filtered by
> 'trade condition', then 3) have the appropriate function applied."

**The filtering is per field, not per trade.** From Alpaca's FAQ tables:

| Field | Excluded conditions |
|---|---|
| Open / Close | B C H I M N P\* Q R T† U V Z\* 4\* 7 9\* |
| High / Low | B C **G\*** H I M N P\* Q R T† U V Z\* 4\* 7 9\* |
| Volume | **M Q 9† only** |

`*` minute bars only · `†` daily bars only

Two consequences worth remembering:

- **`G` is barred from High/Low but allowed to set Open/Close.** A single boolean
  per trade cannot express this. Ours cannot.
- **`T` (extended hours) is excluded only for *daily* bars.** Keeping extended-hours
  prints price-forming intraday is the spec, not a liberty — the official daily OHLC
  is the regular session, which is why `T` drops out there.

---

## Sale conditions: what we implement

`app/market/conditions.py`:

- **`SKIP`** (dropped outright) — `M` `Q` `9`, market-centre official open/close and
  corrected-close reprints whose size double-counts auction volume already on the
  tape; plus **`I` (odd lot)**, our one deliberate divergence.
- **`VOLUME_ONLY`** (counted in volume, barred from OHLC) — `C` `G` `H` `N` `P` `R`
  `U` `V` `W` `Z` `4` `7`.
- Everything else is price-forming.

`T` stays price-forming intraday: on a small-cap gapper **100% of pre-open prints
carry it** (measured, 123,276 prints), so excluding it would leave 04:00–09:30 blank.
`U` — the *out-of-sequence* extended-hours flavour — is treated like its
regular-session twin `Z`.

### Known gaps against the spec

| gap | status |
|---|---|
| `B` is a spec-listed OHLC exclusion, missing from `_VOLUME_ONLY` | never appeared in 166k prints |
| `G` should be High/Low-only; we exclude it from all four | needs per-field rule, not a boolean |
| `W` is in ours but absent from the FAQ's table | confirm against the CTS spec directly |

All three are lower risk under `Last`, since IBKR filters before we see the print.

---

## The volume gap, and why it cannot be corrected with a constant

Odd lots are the whole story, and their share **varies with tape activity**:

| sample | odd-lot share of volume |
|---|---|
| full active premarket session | 21–26% |
| quiet premarket window (06:07–06:10) | **43.7%** |
| Alpaca published 1m vs IBKR 1m, 170 bars | +36.7% total, **median 1.55×** per bar |

Quiet minutes are proportionally far more retail odd lots; busy minutes have more
institutional round lots. The median exceeding the aggregate is the same effect.

**Practical consequence:** a TradingView or screener volume figure cannot be scaled
to match ours, and ours cannot be scaled to match theirs. They will disagree by a
moving 21–44%. Our numbers agree with TWS exactly, which is the right thing to
cross-check against.

This is also why the **RVOL denominator matters**: if the 50-day average volume is
not on IBKR's convention, the ratio is wrong by a varying amount and a 5× gate will
move names across it unpredictably.

---

## Measured results

**IBKR's tape *is* the SIP** — the choice of `Last` is ours, not a data limitation
(`tapediff.py`, FGI 05:55–05:59):

```
                 prints        shares
SIP (Alpaca)        376        18,530
IBKR (ticks)        376        18,530     376 matched, 0 missing, 0 extra
```

**Either convention is reproducible to the share** from IBKR historical ticks
through the production classifier and `BarBuilder` (`histticks.py`):

```
rule applied          compared against        result
SIP (odd lots in vol) Alpaca published 1m     volume 3/3, OHLC 3/3, count 3/3
SIP                   Alpaca published 1m     volume 4/4, OHLC 4/4, count 4/4
IBKR (odd lots out)   IBKR historical 10s     volume 20/20, OHLC 20/20  ratio 1.0000
IBKR                  IBKR historical 1m      volume 4/4, OHLC 4/4      ratio 1.0000
```

That is the important result: **the condition table is correct**, and the remaining
choice is only which baseline to sit on.

**The live stream loses essentially nothing** (`liveloss.py`, `Last` +
`reqRealTimeBars(5)` on one contract, 300s):

```
                     FGI (9,005 prints)   NVDA (3,016 prints)
Σ tape / Σ bars              0.9957              0.9986
net difference              -0.43%              -0.14%
per-bucket surplus        +309,468             +82,882
per-bucket deficit        -319,767             -83,654
gross churn                629,235             166,536  shares (26% / 31% of volume)
arrived after their
bucket had closed             0                   0
```

Surplus and deficit cancel; nothing arrives late; disagreements come in **adjacent
offsetting pairs**:

```
FGI  10:34:45   ours 117,339   IBKR  44,305   +73,034
     10:34:50   ours  33,649   IBKR 112,453   -78,804
```

Prints are not missing — they are in the next bucket over, because we bucket by
exchange timestamp and `reqRealTimeBars` buckets by IBKR's processing order. Our
attribution is the one that matches Alpaca *and* IBKR's own historical bars.

---

## Traps

Each of these produced a confidently wrong conclusion before being caught.

1. **ib_async returns one shared `Ticker` per contract.** Subscribing to `Last` and
   `AllLast` on the same contract cross-contaminates them — the `Last` bucket
   receives `AllLast`'s prints. Use separate processes or separate windows.
2. **`reqHistoricalTicks` silently thins.** It ignores `endDateTime` and caps at
   1000. A window with more prints than that returns a *sample* spanning the range,
   which looks exactly like real data loss. Verify you walked past the window end.
3. **Never de-duplicate ticks by content.** The same price and size on the same
   venue in the same second is a routine pair of prints, not a repeat. Collapsing
   them undercounted a 4-minute window by 47 prints. Trim request overlap
   positionally instead.
4. **`delayed_sip` is invalid on the REST endpoints.** Use `sip` with a clamped
   window.
5. **IBKR real-time bars ≠ IBKR historical bars.** Different bucketing. Comparing
   against the wrong one makes correct code look broken.
6. **A tape-vs-bars volume gap is not automatically loss.** Split it into per-bucket
   surplus and deficit. If they cancel, it is attribution. If the deficit dominates,
   it is loss. We called it loss for most of a day on the strength of a bucket-match
   count alone.
7. **A `BarBuilder` that drops volume-only prints arriving before a bar opens loses
   real volume.** Measured at 4.2% while odd lots were volume-only. Such prints are
   now held and folded in when the period opens.

---

## Re-measuring

The probes used here lived in `tmp/bar-construction/` (gitignored, so they may no
longer exist):

| script | question it answers |
|---|---|
| `tapediff.py` | does IBKR's tape differ from the SIP? |
| `histticks.py` | do our bars reproduce a given provider's bars, at a given timeframe? |
| `liveloss.py` | is the live stream losing prints, or misattributing them? |
| `whichtape.py` | which slice of the tape does IBKR aggregate into its own bars? |
| `settle.py` | what does each tick type actually deliver? |

All follow the same shape: pull a known window from both sides, run the tape
through the **production** `classify_conditions` and `BarBuilder` rather than a
reimplementation, and compare field by field. Comparing against a reimplementation
tests nothing.
