"""The setup judge: what it is given, what it names, and what it refuses.

The reader itself is tested in ``test_claude_cli.py``. What is here is the
part specific to judging a setup: that the prompt carries the numbers with
their thresholds and says "unknown" rather than nothing when a figure is
missing, that the five pillars always come back as five, and that the
staleness policy is the strict one — because a judgement that ages into
wrongness quietly is worse than one that admits it.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.setup_ai import (
    STALE_MOVE,
    STALE_SECONDS,
    Judgement,
    JudgementError,
    Snapshot,
    build_prompt,
    grade,
    session_phase,
    to_judgement,
)
from app.domain.setup_prompt import SYSTEM_PROMPT

NY = ZoneInfo("America/New_York")
# Tuesday 2026-09-08, 08:20 New York — inside the window that matters.
NOW = datetime(2026, 9, 8, 8, 20, tzinfo=NY).timestamp()


def snapshot(**overrides) -> Snapshot:
    base = {
        "symbol": "WETO",
        "now": NOW,
        "price": 3.42,
        "info": {
            "prev_close": 1.98,
            "float_shares": 2_100_000,
            "shares_outstanding": 9_400_000,
            "day_volume": 11_900_000,
            "avg_vol_10d": 340_000,
            "rel_vol": 35.0,
            "float_rotation": 5.67,
            "shortable": "locate",
        },
        "quote": {"bid": 3.41, "ask": 3.44, "bid_size": 4200, "ask_size": 2600},
        "values": {"wrvol": 61.4, "vwap": 3.11},
        "levels": [{"id": "pm_high", "label": "PM High", "value": 3.55}],
        "headroom": {"label": "PM High", "value": 3.55, "percent": 3.8},
        "regime": {"up_50_count": 7, "up_100_count": 2},
        "news": None,
    }
    base.update(overrides)
    return Snapshot(**base)


# ── the phases of the day ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (3, 0, "overnight"),
        (5, 0, "early pre-market"),
        (6, 45, "the scan"),
        (7, 30, "icebreaker size only"),
        (8, 20, "THE WINDOW"),
        (9, 5, "last scheduled news slot"),
        (9, 20, "no new positions"),
        (9, 45, "never initiate"),
        (10, 30, "soft close"),
        (13, 0, "dead zone"),
    ],
)
def test_the_phases_of_the_day(hour, minute, expected):
    """Every boundary here is the framework's own and load-bearing.

    07:00 is when retail brokers let anyone trade, 09:15 is when there is no
    longer time to recover from a red start, and 09:30 switches on LULD
    bands, market orders and stop orders at once.
    """
    when = datetime(2026, 9, 8, hour, minute, tzinfo=NY)
    assert expected in session_phase(when)


def test_a_weekend_is_not_a_session():
    assert "weekend" in session_phase(datetime(2026, 9, 6, 10, 0, tzinfo=NY))


# ── the prompt ─────────────────────────────────────────────────────────


def test_the_prompt_carries_every_pillar_with_its_threshold():
    """A number without its threshold is a number the model has to guess at."""
    prompt = build_prompt(snapshot())

    assert "PILLAR 1: PRICE" in prompt
    assert "$5-$10 the sweet spot" in prompt
    assert "PILLAR 2: PERCENT CHANGE" in prompt
    assert "Floor 10%" in prompt
    assert "PILLAR 3: RELATIVE VOLUME" in prompt
    assert "Hard floor 5x" in prompt
    assert "PILLAR 4: FLOAT" in prompt
    assert "<20M is the screen" in prompt
    assert "PILLAR 5: CATALYST" in prompt


def test_the_prompt_computes_the_change_the_trader_sees():
    prompt = build_prompt(snapshot())
    # 3.42 against a 1.98 previous close.
    assert "+72.7%" in prompt


def test_wrvol_is_given_as_the_one_that_matters():
    """The framework's denominator is a time-matched rate, not a day ratio.

    30,000 shares by 07:00 reading as "343x typical" is only coherent against
    one, so handing over day RVOL alone would be handing over the wrong
    number under the right name.
    """
    prompt = build_prompt(snapshot())
    assert "WRVOL (time-matched" in prompt
    assert "61.40x" in prompt
    assert "WRVOL is the one that matters" in prompt


def test_a_missing_figure_reads_as_unknown_not_as_zero():
    """The easiest way to get a confident wrong answer out of a numeric prompt.

    An absent float is not a small float, and an absent spread is not a tight
    one — but a null rendered as 0.00 says exactly that.
    """
    prompt = build_prompt(snapshot(info={"prev_close": None}, values={}, quote={}))

    assert "0.00" not in prompt.split("── LEVELS")[0]
    assert "unknown" in prompt


def test_a_nan_does_not_reach_the_prompt_as_a_number():
    """NaN passes ``isinstance(x, float)`` and every comparison against it is
    False — the same trap the screener rows already pay for."""
    prompt = build_prompt(snapshot(info={"float_shares": float("nan"), "prev_close": 1.98}))
    assert "nan" not in prompt.lower()


def test_the_prompt_names_blue_sky_when_there_is_nothing_overhead():
    prompt = build_prompt(snapshot(headroom={"label": "", "value": None, "percent": None}))
    assert "BLUE SKY" in prompt
    assert "holding past the first target is licensed" in prompt


def test_headroom_carries_the_two_to_one_gate():
    """A level too close to pay 2:1 declines the trade whatever the pillars say."""
    prompt = build_prompt(snapshot())
    assert "PM High at 3.55" in prompt
    assert "2:1 gate" in prompt


def test_the_pullback_is_given_with_what_makes_one_valid():
    prompt = build_prompt(
        snapshot(
            info={
                "prev_close": 1.98,
                "pullback_leg_pct": 41.0,
                "pullback_depth_pct": 33.0,
                "pullback_bars": 2,
                "pullback_vol_ratio": 0.42,
            }
        )
    )
    assert "retraced 33% of it" in prompt
    assert "holds >=50% of the leg" in prompt


def test_the_session_phase_is_in_the_prompt():
    assert "THE WINDOW" in build_prompt(snapshot())


def test_the_regime_is_given_as_the_multiplier_it_is():
    prompt = build_prompt(snapshot())
    assert "Stocks up 50% today: 7" in prompt
    assert "Zero names over 100% is cold" in prompt


def test_the_news_score_rides_along_when_one_is_held():
    prompt = build_prompt(
        snapshot(
            news={
                "score": 8,
                "verdict": "strong",
                "session": "2026-09-08",
                "summary": "A $12M private placement led by a named institution.",
                "bullets": ["$12M placement priced above market"],
                "risks": [],
            }
        )
    )
    assert "News score 8/10 (strong)" in prompt
    assert "private placement" in prompt


def test_no_news_reading_is_stated_rather_than_omitted():
    assert "No news reading available" in build_prompt(snapshot())


# ── the rubric ─────────────────────────────────────────────────────────


def test_the_rubric_holds_the_joint_evaluation_rule():
    """The framework's own thesis, and the whole reason a model is here.

    A conjunctive filter is what the strip above the chart already is; if
    this sentence goes, the panel is a slower copy of it.
    """
    assert "JOINTLY, never as a checklist" in SYSTEM_PROMPT
    assert "marginal on all five is WORSE" in SYSTEM_PROMPT


def test_the_rubric_keeps_the_vetoes_specific():
    assert "Easy to borrow" in SYSTEM_PROMPT
    assert "a vague veto is how a real" in SYSTEM_PROMPT


def test_the_rubric_knows_a_float_equal_to_shares_out_is_not_a_float():
    """A real company always has *someone* reporting a holding.

    Float == shares outstanding is a missing measurement wearing a number,
    and it is usually the largest float on the screen — so scored naively it
    reads as the worst possible supply picture rather than as no picture.
    """
    assert "equal to shares outstanding is not a measured float" in SYSTEM_PROMPT


def test_the_rubric_refuses_to_size_the_trade():
    """It has not seen the order book and it is not the risk manager."""
    assert "Do not recommend an entry price, a stop, a share count" in SYSTEM_PROMPT


def test_the_rubric_leaves_the_exit_ladder_out_deliberately():
    """Tested on bars it went from +0.32R to -0.52R — it is downstream of a
    win rate this cannot assume, so it is excluded rather than quietly
    omitted."""
    assert "-0.52R" in SYSTEM_PROMPT


# ── the answer ─────────────────────────────────────────────────────────


def answer(**overrides) -> dict:
    payload = {
        "score": 8,
        "headline": "Clean A on a 2.1M float",
        "judgement": "WRVOL 61x on a corroborated float is carrying it.",
        "pillars": [{"name": "float", "state": "strong", "note": "2.10M"}],
        "vetoes": [],
        "watch": ["VWAP 3.11 is the fail line"],
    }
    payload.update(overrides)
    return payload


def judged(**overrides) -> Judgement:
    return to_judgement(
        answer(**overrides), symbol="WETO", price=3.42, generated_at=int(NOW), model="sonnet"
    )


@pytest.mark.parametrize(
    ("score", "letter"), [(10, "A"), (8, "A"), (7, "B"), (6, "B"), (5, "C"), (4, "C"), (3, "F"), (0, "F")]
)
def test_grades(score, letter):
    assert grade(score) == letter


def test_the_five_pillars_always_come_back_as_five():
    """The row is scanned, not read: a gap would be taken for a blank."""
    pillars = judged().pillars

    assert [row["name"] for row in pillars] == ["price", "change", "rvol", "float", "catalyst"]
    assert pillars[3]["state"] == "strong"
    # Everything the reader left out reads as unknown, never as passing.
    assert pillars[0]["state"] == "unknown"


def test_an_unrecognised_state_is_unknown_rather_than_rendered():
    pillars = judged(pillars=[{"name": "float", "state": "excellent", "note": "x"}]).pillars
    assert pillars[3]["state"] == "unknown"


def test_a_score_outside_the_scale_is_clamped():
    assert judged(score=13).score == 10
    assert judged(score=-2).score == 0


def test_a_judgement_with_nothing_written_is_refused():
    """A graded panel with no argument behind it is the one that gets
    overridden — the book's own finding on how the expensive losses happen."""
    with pytest.raises(JudgementError, match="no judgement"):
        judged(judgement="   ")


def test_a_missing_score_is_refused():
    with pytest.raises(JudgementError, match="no score"):
        to_judgement(
            {"judgement": "Something."}, symbol="X", price=1.0, generated_at=0, model="sonnet"
        )


def test_a_missing_headline_falls_back_rather_than_failing():
    """The headline is a convenience; the judgement is the product."""
    assert judged(headline="").headline.startswith("WRVOL 61x")


# ── staleness ──────────────────────────────────────────────────────────


def test_a_reading_goes_stale_when_the_price_moves():
    """Two percent is under a minute on the names this is for."""
    judgement = judged()
    assert not judgement.is_stale(3.42 * (1 + STALE_MOVE / 2), NOW)
    assert judgement.is_stale(3.42 * (1 + STALE_MOVE), NOW)
    # And in both directions — a name giving it back is just as stale.
    assert judgement.is_stale(3.42 * (1 - STALE_MOVE), NOW)


def test_a_reading_goes_stale_on_the_clock_too():
    """A name that has gone quiet rather than moved is still an old read."""
    judgement = judged()
    assert not judgement.is_stale(3.42, NOW + STALE_SECONDS - 1)
    assert judgement.is_stale(3.42, NOW + STALE_SECONDS + 1)


def test_staleness_is_unknowable_without_a_price():
    assert not judged().is_stale(None, NOW)


def test_the_payload_carries_the_price_it_was_read_at():
    payload = judged().to_dict(price_now=3.50, now=NOW)
    assert payload["price"] == 3.42
    assert payload["grade"] == "A"
    assert payload["stale"] is True
