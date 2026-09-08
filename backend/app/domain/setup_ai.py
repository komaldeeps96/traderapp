"""The whole picture, judged: score, grade, and what to do about it.

The news reader answers one question — is this session's news a reason to be
long. This answers the one the trader is actually asking: *given everything
on this screen, is this a trade, and how big?* It gets the five pillars, the
levels, the tape conditions, the dilution read, the regime and the news
score, and it is scored against Ross Cameron's own framework.

Four things about the framework decide how this module is shaped.

**The pillars are evaluated jointly, never as a checklist.** This is the
book's own thesis sentence and the reason a language model earns its place
here: a stock at $19 with a 19M float up exactly 10% on RVOL 5.1 clears all
five pillars marginally and *"realistically he probably shouldn't trade it"*,
while a name exceptional on three and openly failing one is the better trade.
No conjunctive filter expresses that. So every pillar is handed over with its
number and its threshold, and the model is asked for a joint read rather than
a count.

**A low score has to name its gate.** The book's finding on catastrophic
losses is that they are never "the setup looked bad" — they are one specific
gate violated: the jack-knife ignored, the MACD overridden, the easy-to-borrow
traded anyway. So `vetoes` is a separate field from the judgement and the
panel renders it separately.

**Time of day is an input, not a footnote.** The same 40% gap is bullish at
06:45 (room for a fresh catalyst to take the top slot) and a veto at 08:30
(not obvious enough). The snapshot therefore carries the New York clock and
the session phase, and the prompt conditions on both.

**A judgement goes stale on a fast chart.** This is not a summary of a fixed
document; it is a read of a moving tape, and one taken eight minutes and
twelve percent ago is not current. The reading is stamped with the price it
was taken at and the panel says so — `is_stale` below is the whole of that
policy and it is deliberately strict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from ..core.clock import to_ny

MIN_SCORE = 0
MAX_SCORE = 10

# Bands. Cameron's own A/B/C grading carries measured accuracy — A is 5/5
# pillars at 75-90% depending on regime, B is 4/5 at 65-80%, C is 3/5 and
# *loses money in a cold market*. F is a hard veto, which is a different
# statement from "a weak setup" and is kept separate for that reason.
GRADES: tuple[tuple[int, str], ...] = ((8, "A"), (6, "B"), (4, "C"), (0, "F"))

# How far the price may drift before a reading is called stale. Two percent
# is tight on purpose: on a name doing what this terminal is for, two percent
# is under a minute, and a judgement that quietly ages into wrongness is
# worse than one that says it is old.
STALE_MOVE = 0.02
# And the clock, for a name that has gone quiet rather than moved.
STALE_SECONDS = 300

# The ladder is sent nearest-first and cut here. Twenty levels is the whole
# ladder on a name with history; the six above and six below the price are
# what any of this turns on.
MAX_LEVELS = 12


def grade(score: int) -> str:
    for floor, letter in GRADES:
        if score >= floor:
            return letter
    return "F"


@dataclass(frozen=True)
class Judgement:
    """One reading of one moment."""

    symbol: str
    score: int
    grade: str
    headline: str
    judgement: str
    pillars: tuple[dict, ...] = ()
    vetoes: tuple[str, ...] = ()
    watch: tuple[str, ...] = ()
    # The moment judged. Both are needed to say whether the read still holds:
    # a price and a clock answer different questions about staleness.
    price: float | None = None
    generated_at: int = 0
    model: str = ""

    def to_dict(self, *, price_now: float | None = None, now: float | None = None) -> dict:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "grade": self.grade,
            "headline": self.headline,
            "judgement": self.judgement,
            "pillars": [dict(row) for row in self.pillars],
            "vetoes": list(self.vetoes),
            "watch": list(self.watch),
            "price": self.price,
            "generated_at": self.generated_at,
            "model": self.model,
            "stale": self.is_stale(price_now, now),
        }

    def is_stale(self, price_now: float | None, now: float | None) -> bool:
        """Whether the tape has moved out from under this reading."""
        if now is not None and self.generated_at and now - self.generated_at > STALE_SECONDS:
            return True
        if price_now and self.price:
            return abs(price_now / self.price - 1) >= STALE_MOVE
        return False


@dataclass
class Snapshot:
    """Everything the judge is given, in the terminal's own units.

    A plain container rather than a builder: the service assembles it from
    the live services and this module turns it into a prompt, which keeps the
    formatting testable without a running terminal behind it.
    """

    symbol: str
    now: float
    price: float | None = None
    info: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)
    levels: list[dict] = field(default_factory=list)
    headroom: dict | None = None
    regime: dict | None = None
    news: dict | None = None
    values: dict = field(default_factory=dict)


def _finite(value) -> bool:
    """A real number, and not a NaN wearing one's clothes.

    NaN passes ``isinstance(x, float)`` and every comparison against it is
    False, so a missing figure that reached here unguarded would print as a
    number and be scored as one. The same trap the screener rows pay for.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _num(value, digits: int = 2, suffix: str = "") -> str:
    if not _finite(value):
        return "unknown"
    return f"{value:,.{digits}f}{suffix}"


def _pct(value, digits: int = 1) -> str:
    """A fraction, as a percentage. ``None`` reads as unknown, never as zero."""
    if not _finite(value):
        return "unknown"
    return f"{value * 100:+.{digits}f}%"


def _shares(value) -> str:
    if not _finite(value):
        return "unknown"
    for cut, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= cut:
            return f"{value / cut:.2f}{unit}"
    return f"{value:.0f}"


# The day, in the terms the framework uses. Read as "up to this minute of the
# New York day, it is this". The boundaries are the framework's own and every
# one of them is load-bearing: 07:00 is when retail brokers let anyone trade,
# 09:15 is when there is no longer time to recover from a red start, and
# 09:30 is a structural break — LULD bands, market orders and stop orders all
# switch on at once.
_PHASES: tuple[tuple[int, str], ...] = (
    (4 * 60, "overnight — nothing trades"),
    (6 * 60 + 30, "04:00-06:30 early pre-market — thin, wide, not traded"),
    (7 * 60, "06:30-07:00 the scan — regime read, no positions"),
    (8 * 60, "07:00-08:00 retail liquidity opens — icebreaker size only"),
    (9 * 60, "08:00-09:00 THE WINDOW — the most profitable hour, full size on a cushion"),
    (9 * 60 + 15, "09:00-09:15 last scheduled news slot"),
    (9 * 60 + 30, "09:15-09:30 no new positions — not enough time left to recover"),
    (10 * 60, "09:30-10:00 after the bell — manage what is open, never initiate"),
    (11 * 60, "10:00-11:00 soft close — accuracy declining"),
    (16 * 60, "past 11:00 — the dead zone, flat"),
    (20 * 60, "after hours — flat"),
)


def session_phase(when: datetime) -> str:
    """Where in the day this is, in the terms the framework uses."""
    if when.weekday() >= 5:
        return "weekend — no session"
    minutes = when.hour * 60 + when.minute
    for boundary, label in _PHASES:
        if minutes < boundary:
            return label
    return "closed"


def build_prompt(snapshot: Snapshot) -> str:
    """The user turn: one moment, in labelled blocks.

    Flat text rather than JSON. The model reads it either way, and a value
    that is unknown has to read as *unknown* rather than as a null the model
    might treat as zero — which is the single easiest way to get a confident
    wrong answer out of a numeric prompt.
    """
    info = snapshot.info or {}
    quote = snapshot.quote or {}
    ny = to_ny(snapshot.now)
    price = snapshot.price
    prev_close = info.get("prev_close")
    change = (price / prev_close - 1) if price and prev_close else None
    market_cap_now = (
        info["shares_outstanding"] * price
        if price and info.get("shares_outstanding")
        else None
    )

    lines = [
        f"TICKER {snapshot.symbol}   {info.get('description') or ''}".rstrip(),
        f"Exchange {info.get('exchange') or 'unknown'} · Sector {info.get('sector') or 'unknown'}",
        f"New York time {ny:%Y-%m-%d %H:%M} ({ny:%A})",
        f"Session phase: {session_phase(ny)}",
        "",
        "── PILLAR 1: PRICE ─────────────────────────────────────────",
        f"Last {_num(price)}   Previous close {_num(prev_close)}",
        "Band: $2-$20 is the lane, $5-$10 the sweet spot. Above $20 the payoff inverts.",
        "",
        "── PILLAR 2: PERCENT CHANGE ────────────────────────────────",
        f"Change on the day {_pct(change)}",
        f"Pre-market volume {_shares(info.get('pm_volume'))}",
        "Floor 10%; conviction 25-30%; 50%+ is the small club worth chasing.",
        "",
        "── PILLAR 3: RELATIVE VOLUME ───────────────────────────────",
        f"RVOL (day vs 10-day average) {_num(info.get('rel_vol'))}x",
        f"WRVOL (time-matched: this 04:00-now window vs a typical session by "
        f"the same clock) {_num(snapshot.values.get('wrvol'))}x",
        f"Day volume {_shares(info.get('day_volume'))}   "
        f"10-day average {_shares(info.get('avg_vol_10d'))}",
        "Hard floor 5x. No upper bound — 80-100x is the target, higher is better.",
        "WRVOL is the one that matters: it is the time-matched rate, which is",
        "what 'five times average volume' means at 07:00 with an hour of tape.",
        "",
        "── PILLAR 4: FLOAT (the only supply measure) ───────────────",
        f"Float {_shares(info.get('float_shares'))}   "
        f"Shares outstanding {_shares(info.get('shares_outstanding'))}",
        f"Float rotation today {_num(info.get('float_rotation'))}x   "
        f"pre-market {_num(info.get('pm_float_rotation'))}x",
        f"Market cap on the previous close {_shares(info.get('market_cap'))}   "
        f"right now {_shares(market_cap_now)}",
        f"Second-source float (Yahoo) {_shares(info.get('yahoo_float'))}",
        "<20M is the screen, <10M better, <5M explosive. >=28M is normally out.",
        "",
        "── PILLAR 5: CATALYST ──────────────────────────────────────",
        _news_block(snapshot.news),
        "",
        "── THE TAPE RIGHT NOW ──────────────────────────────────────",
        _quote_block(quote),
        _halt_block(info),
        f"Borrow: {info.get('shortable') or 'unknown'}"
        + (
            f" ({_shares(info.get('shortable_shares'))} shares available)"
            if info.get("shortable_shares")
            else ""
        ),
        "Easy-to-borrow is a VETO, not a convenience: cheap borrow means shorts",
        "pile in on the pop, and on a claimed sub-10M float it means the float",
        "number is probably fiction.",
        _pullback_block(info),
        _vwap_block(snapshot.values, price),
        "",
        "── LEVELS AND HEADROOM ─────────────────────────────────────",
        _levels_block(snapshot.levels, price),
        _headroom_block(snapshot.headroom),
        "",
        "── SUPPLY RISK ─────────────────────────────────────────────",
        _dilution_block(info),
        "",
        "── MARKET REGIME ───────────────────────────────────────────",
        _regime_block(snapshot.regime),
    ]
    lines.append("")
    lines.append(
        "Score this setup out of 10 and give the judgement a trader can act on "
        "in five seconds."
    )
    return "\n".join(line for line in lines if line is not None)


def _news_block(news: dict | None) -> str:
    if not news:
        return "No news reading available for this session."
    rows = [
        f"News score {news.get('score')}/10 ({news.get('verdict')}) for the "
        f"{news.get('session')} session",
        f"  {news.get('summary') or ''}".rstrip(),
    ]
    for line in news.get("bullets") or []:
        rows.append(f"  · {line}")
    for line in news.get("risks") or []:
        rows.append(f"  ! {line}")
    if news.get("stale"):
        rows.append("  (newer headlines have arrived since this reading)")
    return "\n".join(rows)


def _quote_block(quote: dict) -> str:
    bid, ask = quote.get("bid"), quote.get("ask")
    if not bid or not ask:
        return "Quote: unknown."
    spread = ask - bid
    mid = (ask + bid) / 2
    return (
        f"Bid {_num(bid)} x {_shares(quote.get('bid_size'))}   "
        f"Ask {_num(ask)} x {_shares(quote.get('ask_size'))}   "
        f"Spread {_num(spread)} ({_pct(spread / mid if mid else None)})\n"
        "Spread bites around 10c on a mid-single-digit name, 20c is a decline, "
        "50c is the hard ceiling."
    )


def _halt_block(info: dict) -> str:
    rows = [
        f"Halts today {info.get('halts_today', 0)}"
        + ("  — HALTED RIGHT NOW" if info.get("halted") else "")
    ]
    band = info.get("halt_band_percent")
    if band:
        rows.append(
            f"LULD tier ±{band:.0f}% (set by the previous close, fixed all session)   "
            f"up {_pct(info.get('halt_up_percent'))} / down {_pct(info.get('halt_down_percent'))} away"
        )
    resumed = info.get("halt_resumed_at")
    if resumed:
        rows.append(f"Last reopen at epoch {resumed} — the first 15 minutes after a")
        rows.append(
            "  reopen before 10:00, on a name not already extended 30%+, measured "
            "+3.10% mean over 2,805 reopens; already-extended reopens measured -1.09%."
        )
    return "\n".join(rows)


def _pullback_block(info: dict) -> str:
    depth = info.get("pullback_depth_pct")
    if depth is None:
        return "Pullback: no leg measured on the current session."
    return (
        f"Pullback: leg {_num(info.get('pullback_leg_pct'), 0)}%, retraced "
        f"{_num(depth, 0)}% of it, {info.get('pullback_bars')} bars off the high, "
        f"volume ratio {_num(info.get('pullback_vol_ratio'))}\n"
        "Valid: holds >=50% of the leg (retracement <=50%), lighter volume than the "
        "impulse, 1-3 candles. A single heavy red candle inside it is a veto on its own."
    )


def _vwap_block(values: dict, price: float | None) -> str:
    vwap = values.get("vwap")
    if not vwap or not price:
        return "VWAP: unknown."
    return (
        f"VWAP {_num(vwap)} — price is {_pct(price / vwap - 1)} from it.\n"
        "Below VWAP is a selection veto; a genuine reclaim is the only softener."
    )


def _levels_block(levels: list[dict], price: float | None) -> str:
    if not levels:
        return "Levels: none drawn."
    rows = []
    for level in levels[:MAX_LEVELS]:
        distance = (
            f"{(level['value'] / price - 1) * 100:+.1f}%" if price and level.get("value") else "—"
        )
        rows.append(f"  {level['label']:<22} {_num(level.get('value'))}  {distance}")
    return "Levels nearest the price, high to low:\n" + "\n".join(rows)


def _headroom_block(headroom: dict | None) -> str:
    if headroom is None:
        return "Headroom: unknown."
    if not headroom.get("label"):
        return (
            "Headroom: BLUE SKY — nothing overhead in the ladder. The one condition "
            "under which holding past the first target is licensed rather than greedy."
        )
    return (
        f"Headroom: {headroom['label']} at {_num(headroom.get('value'))}, "
        f"{_num(headroom.get('percent'), 1, '%')} away.\n"
        "The 2:1 gate: (next resistance - entry) must be at least twice "
        "(entry - stop) after slippage, or the trade is declined whatever the "
        "pillars say."
    )


def _dilution_block(info: dict) -> str:
    rows = []
    dilution = info.get("dilution") or {}
    if dilution:
        rows.append(f"Dilution read: {dilution.get('tone')} — {dilution.get('detail')}")
    if info.get("reverse_split_ratio"):
        rows.append(
            f"Reverse split 1:{info['reverse_split_ratio']:.0f}, "
            f"{info.get('reverse_split_days')} days ago. An amplifier beside unrelated "
            "fresh news; the first act of split -> news -> squeeze -> offering otherwise."
        )
    if info.get("listed_days") is not None:
        rows.append(f"Days of listing history: {info['listed_days']}")
    if info.get("earnings_next"):
        rows.append(f"Next scheduled earnings: {info['earnings_next']}")
    return "\n".join(rows) if rows else "No supply flags."


def _regime_block(regime: dict | None) -> str:
    if not regime:
        return "Regime: unknown."
    up50 = regime.get("up_50_count")
    up100 = regime.get("up_100_count")
    return (
        f"Stocks up 50% today: {up50}.  Up 100%: {up100}.\n"
        "This single count drives everything else: in a hot tape C-grade setups "
        "are tradeable and the float ceiling relaxes toward 20M; in a cold one only "
        "A and B are, and the ceiling tightens toward 5M. Zero names over 100% is cold."
    )


SCHEMA: dict = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "minimum": MIN_SCORE,
            "maximum": MAX_SCORE,
            "description": "The setup out of 10, judged jointly, not as a checklist.",
        },
        "headline": {
            "type": "string",
            "description": (
                "One line, at most about ten words, in a trader's register — what "
                "this is and what to do. e.g. 'Clean A on a 2.1M float — size it' "
                "or 'Easy to borrow on a claimed 800k float — pass'."
            ),
        },
        "judgement": {
            "type": "string",
            "description": (
                "Two to four sentences. What the configuration is, which factor is "
                "carrying it or killing it, and what that means for size. Name the "
                "numbers. No preamble."
            ),
        },
        "pillars": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": ["price", "change", "rvol", "float", "catalyst"],
                    },
                    "state": {"type": "string", "enum": ["strong", "ok", "weak", "fail"]},
                    "note": {"type": "string", "description": "The number, in a few words."},
                },
                "required": ["name", "state", "note"],
                "additionalProperties": False,
            },
            "description": "All five, always, in this order.",
        },
        "vetoes": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": (
                "Hard gates that fired, named specifically — 'easy to borrow', "
                "'below VWAP', 'spread 62c', 'retraced 68% of the leg'. Empty when "
                "none did. Never a general misgiving."
            ),
        },
        "watch": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
            "description": (
                "What would change this read, in either direction — the level that "
                "has to hold, the thing to check on the tape, the time it expires."
            ),
        },
    },
    "required": ["score", "headline", "judgement", "pillars", "vetoes", "watch"],
    "additionalProperties": False,
}


class JudgementError(RuntimeError):
    """The reading did not produce a usable answer."""


def to_judgement(
    payload: dict,
    *,
    symbol: str,
    price: float | None,
    generated_at: int,
    model: str,
) -> Judgement:
    """The model's object, validated into the panel's row.

    A score outside the scale is clamped rather than rejected — the number is
    the product and a 12 means "very good". A missing judgement is not
    recoverable the same way: a graded panel with nothing written on it is a
    number with no argument behind it, and the book's own finding is that a
    low score which cannot name its gate is the one that gets overridden.
    """
    raw = payload.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise JudgementError("the reader returned no score")
    score = max(MIN_SCORE, min(MAX_SCORE, round(float(raw))))

    text = " ".join(str(payload.get("judgement") or "").split())
    if not text:
        raise JudgementError("the reader returned no judgement")

    return Judgement(
        symbol=symbol,
        score=score,
        grade=grade(score),
        headline=" ".join(str(payload.get("headline") or "").split()) or text[:60],
        judgement=text,
        pillars=_pillars(payload.get("pillars")),
        vetoes=_lines(payload.get("vetoes")),
        watch=_lines(payload.get("watch")),
        price=price,
        generated_at=generated_at,
        model=model,
    )


_PILLAR_NAMES = ("price", "change", "rvol", "float", "catalyst")
_PILLAR_STATES = ("strong", "ok", "weak", "fail")


def _pillars(value: object) -> tuple[dict, ...]:
    """The five, in a fixed order, whatever order they came back in.

    Rendered as a row of chips, so a missing one would silently change what
    the row means. Anything the model left out reads as unknown rather than
    as passing.
    """
    given = {}
    if isinstance(value, list):
        for row in value:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").lower()
            if name in _PILLAR_NAMES:
                state = str(row.get("state") or "").lower()
                given[name] = {
                    "name": name,
                    "state": state if state in _PILLAR_STATES else "unknown",
                    "note": " ".join(str(row.get("note") or "").split()),
                }
    return tuple(
        given.get(name, {"name": name, "state": "unknown", "note": ""})
        for name in _PILLAR_NAMES
    )


def _lines(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(" ".join(str(item).split()) for item in value if str(item).strip())
