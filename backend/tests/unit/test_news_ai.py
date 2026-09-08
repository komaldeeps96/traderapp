"""The day's reading: what is in scope, what is asked, and what comes back.

The service half runs against a *fake* ``claude`` binary — a shell script in
``tmp_path`` that reads stdin and prints an envelope. That is the point: the
subprocess path is where the bugs live (argv, stdin, exit codes, timeouts,
single-flight) and stubbing at the Python level would test none of it, while
the real binary would spend money and leave the machine.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date

import pytest

from app.core.clock import to_ny
from app.core.settings import NewsAISettings
from app.domain.news import build
from app.domain.news_ai import (
    CLOSE_FENCE,
    MAX_BODY_CHARS,
    OPEN_FENCE,
    BriefError,
    band,
    build_prompt,
    digest,
    parse_output,
    previous_session,
    select_session,
    session_for,
    to_brief,
    window_for,
)
from app.domain.news_prompt import SYSTEM_PROMPT
from app.services.news_ai import NewsAIService

DAY = 86_400
# 10:00 New York on Friday 2026-09-04 — well inside a session.
FRIDAY = 1_788_530_400
# 15:00 the same Friday: the reading is taken mid-session, an hour before
# the close that would roll the window on.
FRIDAY_NOW = 1_788_548_400


def raw(article_id: str, headline: str, when: int, **extra) -> dict:
    return {
        "article_id": article_id,
        "provider": extra.pop("provider", "DJ-N"),
        "time": when,
        "headline": headline,
        **extra,
    }


def headlines(rows: list[dict]):
    return build(rows)


# ── scope: which session, and which rows are in it ─────────────────────


def test_the_session_a_moment_belongs_to():
    # Friday at 10:00 and Friday at 18:00 are both Friday's session: an
    # 18:00 release is part of what Friday's chart has to explain.
    assert session_for(FRIDAY).isoformat() == "2026-09-04"
    assert session_for(FRIDAY + 8 * 3600).isoformat() == "2026-09-04"
    # Saturday and Sunday both feed Monday.
    assert session_for(FRIDAY + DAY).isoformat() == "2026-09-07"
    assert session_for(FRIDAY + 2 * DAY).isoformat() == "2026-09-07"


def test_previous_session_steps_over_the_weekend():
    assert previous_session(date(2026, 9, 7)).isoformat() == "2026-09-04"
    assert previous_session(date(2026, 9, 4)).isoformat() == "2026-09-03"


def test_the_window_opens_at_the_previous_close():
    session, start, end = window_for(FRIDAY_NOW)
    assert session.isoformat() == "2026-09-04"
    assert to_ny(start).strftime("%a %H:%M") == "Thu 16:00"
    assert end == int(FRIDAY_NOW)


def test_a_release_after_the_close_is_the_next_sessions_news():
    """The correction this whole window exists for.

    An FDA clearance at 16:10 on Thursday is what Friday gaps on. Keyed on
    the calendar date it lands under Thursday and a chart opened at 08:00 on
    Friday summarises whatever trivia printed after midnight instead.
    """
    after_close = int(FRIDAY - 18 * 3600)  # Thursday 16:00 NY
    rows = headlines(
        [
            raw("catalyst", "Acme Receives FDA Clearance for Widget", after_close + 600),
            raw("noise", "Acme to Present at Investor Conference", int(FRIDAY - 3 * 3600)),
        ]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert window.session.isoformat() == "2026-09-04"
    assert {row.article_id for row in window.headlines} == {"catalyst", "noise"}


def test_a_release_before_the_close_belongs_to_the_session_that_closed():
    """15:00 Thursday is Thursday's news, and Friday must not re-read it."""
    rows = headlines(
        [
            raw("thursday", "Acme Announces Pricing of $8M Offering", int(FRIDAY - 19 * 3600)),
            raw("friday", "Acme Receives FDA Clearance for Widget", int(FRIDAY)),
        ]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert [row.article_id for row in window.headlines] == ["friday"]
    assert [row.article_id for row in window.prior] == ["thursday"]


def test_a_quiet_name_steps_back_a_session_rather_than_widening():
    """What comes back is still one session's news, and it is dated."""
    rows = headlines([raw("1", "Acme Receives FDA Clearance", int(FRIDAY - 26 * 3600))])
    window = select_session(rows, FRIDAY_NOW)

    assert window.session.isoformat() == "2026-09-03"
    assert [row.article_id for row in window.headlines] == ["1"]


def test_nothing_recent_is_nothing():
    """Past a week the honest answer is "no recent news", not an old date."""
    rows = headlines([raw("1", "Acme Receives FDA Clearance", int(FRIDAY - 30 * DAY))])
    assert not select_session(rows, FRIDAY_NOW)


def test_a_roundup_cannot_be_what_makes_a_session_the_one_read():
    """A movers list must not hide the previous session's catalyst.

    Benzinga publishes "12 Stocks Moving" naming this company among eleven
    others; on its own it is not a reason to stop looking.
    """
    rows = headlines(
        [
            raw("list", "12 Health Care Stocks Moving Friday", int(FRIDAY), symbol_count=12),
            raw("real", "Acme Receives FDA Clearance", int(FRIDAY - 26 * 3600)),
        ]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert window.session.isoformat() == "2026-09-03"
    assert [row.article_id for row in window.headlines] == ["real"]


def test_a_roundup_inside_the_chosen_session_still_goes_in():
    rows = headlines(
        [
            raw("list", "12 Health Care Stocks Moving Friday", int(FRIDAY + 60), symbol_count=12),
            raw("real", "Acme Receives FDA Clearance", int(FRIDAY)),
        ]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert {row.article_id for row in window.headlines} == {"list", "real"}


def test_a_feed_of_nothing_but_roundups_still_gets_a_session():
    rows = headlines(
        [raw("list", "12 Health Care Stocks Moving Friday", int(FRIDAY), symbol_count=12)]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert window.session is not None
    assert len(window.headlines) == 1


def test_the_run_up_rides_along_as_context():
    """A rehash and an escalating run are invisible inside one session."""
    rows = headlines(
        [
            raw("today", "Acme Announces Strategic Partnership", int(FRIDAY)),
            raw("d1", "Acme Announces Strategic Partnership", int(FRIDAY - 2 * DAY)),
            raw("d2", "Acme Announces Letter of Intent", int(FRIDAY - 3 * DAY)),
        ]
    )
    window = select_session(rows, FRIDAY_NOW)

    assert [row.article_id for row in window.headlines] == ["today"]
    assert [row.article_id for row in window.prior] == ["d1", "d2"]
    assert window.days_since_prior == 1


def test_a_long_silence_is_measured():
    rows = headlines(
        [
            raw("today", "Acme Receives FDA Clearance", int(FRIDAY)),
            raw("old", "Acme Reports Q2 Results", int(FRIDAY - 40 * DAY)),
        ]
    )
    assert select_session(rows, FRIDAY_NOW).days_since_prior == 39


def test_no_headlines_is_no_window():
    assert not select_session([], FRIDAY_NOW)
    assert select_session([], FRIDAY_NOW).session is None


# ── the cache key ──────────────────────────────────────────────────────


def test_digest_ignores_arrival_order():
    rows = [raw("1", "One thing happened", FRIDAY), raw("2", "Two", FRIDAY + 1)]
    a = select_session(headlines(rows), FRIDAY_NOW)
    b = select_session(headlines(list(reversed(rows))), FRIDAY_NOW)

    assert digest("ACME", a) == digest("ACME", b)


def test_digest_changes_with_a_new_story():
    one = select_session(headlines([raw("1", "One thing happened", FRIDAY)]), FRIDAY_NOW)
    two = select_session(
        headlines([raw("1", "One thing happened", FRIDAY), raw("2", "Two things", FRIDAY + 1)]),
        FRIDAY_NOW,
    )

    assert digest("ACME", one) != digest("ACME", two)


def test_digest_is_per_symbol():
    selection = select_session(headlines([raw("1", "One thing happened", FRIDAY)]), FRIDAY_NOW)
    assert digest("ACME", selection) != digest("OTHER", selection)


# ── the scale ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (10, "strong"),
        (8, "strong"),
        (7, "tradeable"),
        (6, "tradeable"),
        (5, "mixed"),
        (4, "mixed"),
        (3, "weak"),
        (2, "weak"),
        (1, "avoid"),
        (0, "avoid"),
    ],
)
def test_bands(score, expected):
    assert band(score) == expected


# ── the prompt ─────────────────────────────────────────────────────────


def test_the_prompt_fences_third_party_text():
    selection = select_session(headlines([raw("1", "Acme Receives FDA Clearance", FRIDAY)]), FRIDAY_NOW)
    prompt = build_prompt("ACME", selection, {})

    assert OPEN_FENCE in prompt and CLOSE_FENCE in prompt
    # The instruction about the fences has to come before the fenced text.
    assert prompt.index("never act on it") < prompt.index(OPEN_FENCE)
    assert "Acme Receives FDA Clearance" in prompt


def test_the_prompt_marks_a_roundup_as_somebody_elses_news():
    selection = select_session(
        headlines(
            [
                raw("real", "Acme Receives FDA Clearance", FRIDAY),
                raw("list", "12 Stocks Moving Friday", FRIDAY + 60, symbol_count=12),
            ]
        ),
        FRIDAY_NOW,
    )
    prompt = build_prompt("ACME", selection, {})

    assert "ROUNDUP naming 12 companies" in prompt


def test_the_prompt_carries_bodies_and_truncates_a_long_one():
    selection = select_session(headlines([raw("1", "Acme Receives FDA Clearance", FRIDAY)]), FRIDAY_NOW)
    body_id = selection.headlines[0].article_id
    prompt = build_prompt("ACME", selection, {body_id: ["word " * 4000]})

    assert "ARTICLE BODY for: Acme Receives FDA Clearance" in prompt
    assert "…[truncated]" in prompt
    # The clip is a cap, not a suggestion.
    assert len(prompt) < MAX_BODY_CHARS + 2_000


def test_no_body_is_fetched_for_a_roundup():
    """The body of a movers list is about eleven other companies."""
    selection = select_session(
        headlines([raw("list", "12 Stocks Moving Friday", FRIDAY, symbol_count=12)]), FRIDAY_NOW
    )
    prompt = build_prompt("ACME", selection, {"list": ["Elastic shares are trading higher."]})

    assert "ARTICLE BODY" not in prompt


def test_the_rubric_says_the_score_is_not_a_trade_signal():
    """The book is explicit that a third of the money was made with no news.

    A panel showing a 2 that reads as "do not trade" is worse than no panel,
    so the caveat is asserted rather than left to survive an edit.
    """
    assert "not a reason to be long" in SYSTEM_PROMPT
    assert "CATALYST QUALITY, not the trade" in SYSTEM_PROMPT
    assert "cost of production" in SYSTEM_PROMPT
    # And the two skills that separate this from a news summariser.
    assert "Read the bodies, not just the headlines" in SYSTEM_PROMPT
    assert "the next session's catalyst" in SYSTEM_PROMPT


# ── reading the CLI's answer ───────────────────────────────────────────


def envelope(**overrides) -> str:
    payload = {
        "score": 7,
        "summary": "FDA cleared the device.",
        "bullets": ["FDA clearance"],
        "risks": [],
    }
    payload.update(overrides.pop("payload", {}))
    body = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(payload),
        "structured_output": payload,
    }
    body.update(overrides)
    return json.dumps(body)


def test_parses_the_structured_output():
    assert parse_output(envelope())["score"] == 7


def test_falls_back_to_the_text_result():
    """The CLI puts the object in one field or the other; both are answers."""
    raw_text = json.loads(envelope())
    raw_text.pop("structured_output")
    assert parse_output(json.dumps(raw_text))["score"] == 7


def test_an_error_envelope_is_reported_not_parsed():
    with pytest.raises(BriefError, match="ran out"):
        parse_output(json.dumps({"is_error": True, "result": "the budget ran out"}))


@pytest.mark.parametrize("text", ["", "   ", "not json at all", "[1, 2, 3]"])
def test_unusable_output_raises(text):
    with pytest.raises(BriefError):
        parse_output(text)


def selection_for(day_rows=None):
    return select_session(
        headlines(day_rows or [raw("1", "Acme Receives FDA Clearance", FRIDAY)]), FRIDAY_NOW
    )


def test_a_score_outside_the_scale_is_clamped():
    """The number is the product; a 12 means "very good", not "unusable"."""
    brief = to_brief(
        {"score": 12, "summary": "Very good.", "bullets": [], "risks": []},
        symbol="ACME",
        selection=selection_for(),
        generated_at=FRIDAY,
        model="sonnet",
    )
    assert brief.score == 10


def test_a_scored_answer_with_nothing_written_is_refused():
    """A number with no argument behind it is worse than saying it failed."""
    with pytest.raises(BriefError, match="no summary"):
        to_brief(
            {"score": 9, "summary": "   ", "bullets": [], "risks": []},
            symbol="ACME",
            selection=selection_for(),
            generated_at=FRIDAY,
            model="sonnet",
        )


def test_a_missing_score_is_refused():
    with pytest.raises(BriefError, match="no score"):
        to_brief(
            {"summary": "Something happened."},
            symbol="ACME",
            selection=selection_for(),
            generated_at=FRIDAY,
            model="sonnet",
        )


def test_a_brief_carries_its_day_and_verdict():
    brief = to_brief(
        {"score": 2, "summary": "A raise.", "bullets": ["x"], "risks": ["y"]},
        symbol="ACME",
        selection=selection_for(),
        generated_at=FRIDAY,
        model="sonnet",
    )
    payload = brief.to_dict()

    assert payload["session"] == "2026-09-04"
    assert payload["verdict"] == "weak"
    assert payload["headline_count"] == 1
    assert payload["risks"] == ["y"]


# ── the service, against a fake binary ─────────────────────────────────


class FakeNews:
    """The two methods the service uses of the news cache."""

    def __init__(self, rows=None, bodies=None):
        self.rows = rows if rows is not None else [raw("1", "Acme Receives FDA Clearance", FRIDAY)]
        self.bodies = bodies or {}
        self.article_calls: list[tuple[str, str]] = []

    def peek(self, symbol):
        return build(self.rows)

    async def article(self, provider, article_id):
        self.article_calls.append((provider, article_id))
        return self.bodies.get(article_id, "")


def fake_cli(tmp_path, body: str, *, exit_code: int = 0, sleep: float = 0.0, stderr: str = ""):
    """A shell script standing in for ``claude``.

    It records each invocation's stdin, so a test can assert both that the
    prompt went down the pipe and how many processes were started.

    ``sleep`` redirects its own output. A child that inherits the pipe keeps
    it open after the shell is killed, which leaves the transport alive past
    the end of the test and surfaces as an unraisable "Event loop is closed".
    """
    script = tmp_path / "claude"
    log = tmp_path / "calls"
    script.write_text(
        "#!/bin/sh\n"
        f'cat >> "{log}"\n'
        f'printf "\\n---CALL---\\n" >> "{log}"\n'
        + (f"sleep {sleep} >/dev/null 2>&1\n" if sleep else "")
        + (f'printf %s {json.dumps(stderr)} >&2\n' if stderr else "")
        + f"printf %s {json.dumps(body)}\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return script, log


def calls(log) -> list[str]:
    if not log.exists():
        return []
    text = log.read_text()
    return [part for part in text.split("\n---CALL---\n") if part.strip()]


def service(tmp_path, news=None, **settings):
    binary, log = fake_cli(tmp_path, settings.pop("body", envelope()), **{
        key: settings.pop(key) for key in ("exit_code", "sleep", "stderr") if key in settings
    })
    config = NewsAISettings(command=str(binary), **settings)
    return NewsAIService(config, news or FakeNews()), log


@pytest.mark.asyncio
async def test_switched_off_spawns_nothing(tmp_path):
    reader, log = service(tmp_path, enabled=False)
    result = await reader.brief("ACME")

    assert result["status"] == "off"
    assert result["available"] is False
    assert calls(log) == []


@pytest.mark.asyncio
async def test_a_missing_cli_says_so_rather_than_failing(tmp_path):
    reader = NewsAIService(NewsAISettings(command=str(tmp_path / "nope")), FakeNews())
    result = await reader.brief("ACME")

    assert result["status"] == "no-cli"
    assert "not found" in result["note"]


@pytest.mark.asyncio
async def test_a_company_with_no_headlines_spawns_nothing(tmp_path):
    reader, log = service(tmp_path, news=FakeNews(rows=[]))
    result = await reader.brief("ACME")

    assert result["status"] == "no-news"
    assert calls(log) == []


@pytest.mark.asyncio
async def test_reads_the_day_and_returns_it(tmp_path):
    reader, log = service(tmp_path)
    result = await reader.brief("ACME")

    assert result["status"] == "ready"
    assert result["brief"]["score"] == 7
    assert result["brief"]["verdict"] == "tradeable"
    assert result["brief"]["session"] == "2026-09-04"
    # The prompt went down stdin, not into argv.
    assert "Acme Receives FDA Clearance" in calls(log)[0]


@pytest.mark.asyncio
async def test_the_body_is_fetched_and_sent(tmp_path):
    news = FakeNews(bodies={"1": "<p>The FDA granted 510(k) clearance today.</p>"})
    reader, log = service(tmp_path, news=news)
    await reader.brief("ACME")

    assert news.article_calls == [("DJ-N", "1")]
    assert "granted 510(k) clearance today" in calls(log)[0]


@pytest.mark.asyncio
async def test_a_second_ask_for_the_same_stories_is_free(tmp_path):
    """Switching away and back must not spend a cent."""
    reader, log = service(tmp_path)
    first = await reader.brief("ACME")
    second = await reader.brief("ACME")

    assert first["brief"] == second["brief"]
    assert len(calls(log)) == 1


@pytest.mark.asyncio
async def test_new_stories_inside_the_cooldown_mark_the_reading_behind(tmp_path):
    """A busy pre-market delivers a headline a minute; each is not a process."""
    news = FakeNews()
    reader, log = service(tmp_path, news=news, min_interval_seconds=600)
    await reader.brief("ACME")

    news.rows.append(raw("2", "Acme Announces Pricing of $8M Public Offering", FRIDAY + 300))
    again = await reader.brief("ACME")

    assert again["brief"]["stale"] is True
    assert len(calls(log)) == 1


@pytest.mark.asyncio
async def test_refresh_overrides_the_cooldown(tmp_path):
    news = FakeNews()
    reader, log = service(tmp_path, news=news, min_interval_seconds=600)
    await reader.brief("ACME")
    await reader.brief("ACME", force=True)

    assert len(calls(log)) == 2


@pytest.mark.asyncio
async def test_new_stories_past_the_cooldown_are_read(tmp_path):
    news = FakeNews()
    reader, log = service(tmp_path, news=news, min_interval_seconds=0)
    await reader.brief("ACME")

    news.rows.append(raw("2", "Acme Announces Pricing of $8M Public Offering", FRIDAY + 300))
    await reader.brief("ACME")

    assert len(calls(log)) == 2


@pytest.mark.asyncio
async def test_two_askers_share_one_process(tmp_path):
    reader, log = service(tmp_path, sleep=0.4)
    first, second = await asyncio.gather(reader.brief("ACME"), reader.brief("ACME"))

    assert first["brief"] == second["brief"]
    assert len(calls(log)) == 1


@pytest.mark.asyncio
async def test_a_failing_reader_reports_its_last_line(tmp_path):
    reader, _ = service(tmp_path, exit_code=2, stderr="Credit balance is too low\n")
    result = await reader.brief("ACME")

    assert result["status"] == "failed"
    assert "Credit balance is too low" in result["note"]


@pytest.mark.asyncio
async def test_a_hung_reader_is_killed_and_reported(tmp_path):
    reader, _ = service(tmp_path, sleep=5, timeout_seconds=0.3)
    started = time.monotonic()
    result = await reader.brief("ACME")

    assert result["status"] == "failed"
    assert "longer than" in result["note"]
    # Killed rather than waited out.
    assert time.monotonic() - started < 3


@pytest.mark.asyncio
async def test_a_failure_does_not_poison_the_next_attempt(tmp_path):
    reader, _ = service(tmp_path, exit_code=1)
    assert (await reader.brief("ACME"))["status"] == "failed"
    assert (await reader.brief("ACME"))["status"] == "failed"
