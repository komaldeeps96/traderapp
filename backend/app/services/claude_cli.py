"""The reader: Claude Code, run as a child process with nothing attached.

Spawns the ``claude`` CLI already installed and authenticated on this machine
rather than calling the API directly: no second key to hold, no SDK to pin, and
the same reader a prompt can be run against by hand.

    printf '%s' "$prompt" | claude -p --model sonnet --output-format json \\
      --json-schema "$schema" --system-prompt "$rubric" --tools "" \\
      --safe-mode --strict-mcp-config --no-session-persistence \\
      --permission-prompts none --max-budget-usd 0.25

The flags are the sandbox, written once here:

``--tools ""``          no Bash, Read or WebFetch. Text in, object out.
``--safe-mode``         no CLAUDE.md, skills, plugins, hooks or MCP servers,
                        with auth still working — ``--bare`` demands
                        ANTHROPIC_API_KEY and ignores this machine's OAuth.
``--strict-mcp-config`` belt and braces on the same point.
``--json-schema``       a validated object, not prose to be regex'd.
``--max-budget-usd``    per-reading ceiling; a run costs about a cent.

The prompt goes down **stdin**, not argv: wire copy runs to thousands of
characters and argv has a length limit. ``cwd`` is the home directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class ReaderSettings(Protocol):
    """What a panel's settings block has to carry to drive a reading.

    A structural type because the runner is ignorant of what is being read: a
    second panel brings its own model and defaults rather than inheriting
    these.
    """

    enabled: bool
    command: str
    model: str
    timeout_seconds: float
    max_budget_usd: float


# Where the CLI installs itself when it is not on the server's PATH: a process
# launched from a desktop icon or LaunchAgent inherits a much thinner PATH than
# the shell that installed Claude Code.
_EXTRA_BIN_DIRS = (
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


class ReaderError(RuntimeError):
    """The reading did not produce a usable answer."""


class ClaudeReader:
    """One configured way of asking Claude to read something."""

    def __init__(self, settings: ReaderSettings) -> None:
        self._settings = settings
        self._binary: str | bool | None = False  # False = not looked for yet.

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled)

    @property
    def model(self) -> str:
        return self._settings.model

    def resolve_binary(self) -> str | None:
        """The ``claude`` executable, or None when it is not installed.

        Looked up once and remembered. A settings value carrying a separator is
        taken as a path and used as given.
        """
        if self._binary is not False:
            return self._binary  # type: ignore[return-value]

        command = self._settings.command
        if os.sep in command:
            found = command if os.access(command, os.X_OK) else None
        else:
            found = shutil.which(command)
            if found is None:
                for directory in _EXTRA_BIN_DIRS:
                    candidate = directory / command
                    if os.access(candidate, os.X_OK):
                        found = str(candidate)
                        break
        self._binary = found
        if found is None:
            logger.warning(
                "An AI panel is on but %r is not on PATH — it will say so.", command
            )
        return found

    def argv(self, binary: str, *, schema: dict, system_prompt: str) -> list[str]:
        """The command line. Separated so a test can assert it flag by flag."""
        return [
            binary,
            "-p",
            "--model",
            self._settings.model,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--system-prompt",
            system_prompt,
            "--tools",
            "",
            "--safe-mode",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--permission-prompts",
            "none",
            "--max-budget-usd",
            f"{self._settings.max_budget_usd:g}",
        ]

    async def run(self, *, prompt: str, schema: dict, system_prompt: str) -> str:
        """One process, fed on stdin and read to completion."""
        binary = self.resolve_binary()
        if binary is None:
            raise ReaderError(f"The {self._settings.command!r} CLI was not found.")

        process = await asyncio.create_subprocess_exec(
            *self.argv(binary, schema=schema, system_prompt=system_prompt),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home()),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode()),
                timeout=self._settings.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            # Reaped with a bound rather than awaited outright: a killed
            # process whose children still hold its pipes can take as long again
            # to release them. The shielded wait still collects the child.
            with contextlib.suppress(ProcessLookupError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(process.wait()), timeout=1.0)
            raise ReaderError(
                f"The reader took longer than {self._settings.timeout_seconds:g}s."
            ) from exc

        if process.returncode != 0:
            detail = (stderr or b"").decode(errors="replace").strip().splitlines()
            reason = detail[-1] if detail else f"exit {process.returncode}"
            raise ReaderError(f"The reader failed: {reason}")
        return (stdout or b"").decode(errors="replace")


def parse_output(stdout: str) -> dict:
    """The model's answer, out of the CLI's ``--output-format json`` envelope.

    ``structured_output`` is the parsed tool call a successful run carries;
    ``result`` is the assistant's text, holding the same JSON when the schema
    was honoured through the text path. Both are tried before giving up.
    """
    text = (stdout or "").strip()
    if not text:
        raise ReaderError("the reader returned nothing")
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReaderError(f"unreadable output from the reader: {exc}") from exc

    if not isinstance(envelope, dict):
        raise ReaderError("unreadable output from the reader")
    if envelope.get("is_error"):
        raise ReaderError(str(envelope.get("result") or "the reader reported an error"))

    payload = envelope.get("structured_output")
    if not isinstance(payload, dict):
        with_result = envelope.get("result")
        if isinstance(with_result, str):
            try:
                candidate = json.loads(with_result)
            except json.JSONDecodeError:
                candidate = None
            if isinstance(candidate, dict):
                payload = candidate
    if not isinstance(payload, dict):
        raise ReaderError("the reader returned no scored answer")
    return payload
