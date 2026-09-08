"""The child process both AI panels run, and the flags that fence it in.

These flags are the difference between a scoring prompt and an agent with a
shell, and they are exactly the sort of thing a later edit tidies away as
noise. So they are asserted one at a time, by name, against the argv the real
method builds — not against a comment describing them.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.core.settings import NewsAISettings
from app.services import claude_cli
from app.services.claude_cli import ClaudeReader, ReaderError, parse_output

SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}}}


def reader(**overrides) -> ClaudeReader:
    return ClaudeReader(NewsAISettings(**overrides))


def test_the_reader_has_no_tools_and_no_project_configuration():
    argv = reader().argv("/bin/claude", schema=SCHEMA, system_prompt="rubric")

    assert argv[0] == "/bin/claude"
    assert "-p" in argv
    # No Bash, no Read, no WebFetch: text in, object out.
    assert argv[argv.index("--tools") + 1] == ""
    # No CLAUDE.md, skills, plugins, hooks or MCP servers.
    assert "--safe-mode" in argv
    assert "--strict-mcp-config" in argv
    # Nothing may wait on a terminal that is not there.
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--no-session-persistence" in argv
    # A validated object rather than prose to be regex'd.
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert argv[argv.index("--system-prompt") + 1] == "rubric"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert float(argv[argv.index("--max-budget-usd") + 1]) > 0


def test_not_bare_mode():
    """``--bare`` looks right and would break auth on this machine.

    It demands ANTHROPIC_API_KEY and never reads OAuth or the keychain, so a
    subscription install answers every request with an auth error. Asserted
    because it is the obvious "even more locked down" edit to make.
    """
    assert "--bare" not in reader().argv("/bin/claude", schema=SCHEMA, system_prompt="x")


def test_the_model_is_settable():
    argv = reader(model="opus").argv("/bin/claude", schema=SCHEMA, system_prompt="x")
    assert argv[argv.index("--model") + 1] == "opus"


@pytest.mark.asyncio
async def test_the_prompt_goes_down_stdin_and_the_cwd_is_not_the_repository(monkeypatch):
    """Wire copy carries every quoting character there is, and argv has a
    length limit a busy news day would eventually find."""
    seen: dict = {}

    async def fake_exec(*argv, **kwargs):
        seen["argv"] = list(argv)
        seen["cwd"] = kwargs.get("cwd")
        raise RuntimeError("not started")

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)
    instance = reader(command="/bin/sh")  # exists and is executable
    with pytest.raises(RuntimeError):
        await instance.run(prompt="p", schema=SCHEMA, system_prompt="s")

    assert seen["cwd"] == str(Path.home())
    # The prompt is nowhere in the argument list.
    assert "p" not in seen["argv"]


def test_a_missing_binary_is_reported_not_raised_as_a_crash(tmp_path):
    instance = reader(command=str(tmp_path / "nope"))
    assert instance.resolve_binary() is None


def test_a_path_with_a_separator_is_used_as_given():
    assert reader(command="/bin/sh").resolve_binary() == "/bin/sh"


@pytest.mark.asyncio
async def test_a_timeout_kills_rather_than_waits(tmp_path):
    script = tmp_path / "claude"
    # stdout redirected: a child holding the pipe keeps the transport alive
    # past the test and surfaces as an unraisable "Event loop is closed".
    script.write_text("#!/bin/sh\ncat >/dev/null\nsleep 5 >/dev/null 2>&1\n")
    script.chmod(0o755)
    instance = reader(command=str(script), timeout_seconds=0.3)

    started = asyncio.get_running_loop().time()
    with pytest.raises(ReaderError, match="longer than"):
        await instance.run(prompt="p", schema=SCHEMA, system_prompt="s")
    assert asyncio.get_running_loop().time() - started < 3


# ── reading the envelope ───────────────────────────────────────────────


def envelope(**overrides) -> str:
    payload = {"score": 7}
    body = {
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
    body = json.loads(envelope())
    body.pop("structured_output")
    assert parse_output(json.dumps(body))["score"] == 7


def test_an_error_envelope_is_reported_not_parsed():
    with pytest.raises(ReaderError, match="ran out"):
        parse_output(json.dumps({"is_error": True, "result": "the budget ran out"}))


@pytest.mark.parametrize("text", ["", "   ", "not json at all", "[1, 2, 3]"])
def test_unusable_output_raises(text):
    with pytest.raises(ReaderError):
        parse_output(text)
