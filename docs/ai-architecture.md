# The AI layer

One panel on this terminal asks a model to read something: the news tab scores
a session of headlines for catalyst quality. This file is how it is built, what
it is allowed to do, and how it is measured.

The panel's own design lives beside it: [`news-summary.md`](news-summary.md).
This one is the layer under it — the runner, the sandbox and the flags, written
down as the layer rather than as the panel, because that is the part a second
reader would otherwise rebuild wrongly.

## The shape

```
domain/                          pure — no I/O, no network, no clock but the one passed in
  news_ai.py      window selection, the Brief dataclass, payload → object
  news_prompt.py  the catalyst rubric, as a module
services/
  claude_cli.py   ClaudeReader — argv, sandbox, subprocess, envelope parsing
  news_ai.py      the news cache, in-flight coalescing, the headline source
api/rest.py       GET /api/news/{symbol}/brief
```

Two properties fall out of that split and both are load-bearing.

**The prompt is a module, not a string in a service.** `news_prompt.py` is
importable, diffable, and unit-tested — several tests assert that a specific
sentence is still in the text, because those sentences are the whole behaviour.
A rubric kept in a service is a rubric that gets reworded by an edit aimed at
something else.

**Everything scoreable is pure.** Which session a headline belongs to, what a
window covers, how a payload becomes a `Brief` — all of it is in `domain/` and
tested without a subprocess, a clock or a network. What is left in `services/`
is I/O, and I/O is what the fake CLI covers.

## One runner, and its sandbox

The panel spawns the `claude` CLI already installed and authenticated on the
machine. That is a deliberate choice over calling the API: no second key to
hold, no SDK to pin, nothing new in the settings file that can leak — and it is
the same reader the developer works with, so any prompt can be run by hand and
argued with.

```
printf '%s' "$prompt" | claude -p --model sonnet --output-format json \
  --json-schema "$schema" --system-prompt "$rubric" --tools "" \
  --safe-mode --strict-mcp-config --no-session-persistence \
  --permission-prompts none --max-budget-usd 0.25
```

`services/claude_cli.py` exists so those flags are written in exactly one
place. They are not decoration:

| flag | why |
| --- | --- |
| `--tools ""` | No Bash, no Read, no WebFetch. Text in, object out — a press release cannot reach the filesystem however it is worded. |
| `--safe-mode` | No CLAUDE.md, skills, plugins, hooks or MCP servers. This project's instructions are about *writing* the terminal and have no business inside a scoring prompt. |
| `--strict-mcp-config` | Belt and braces on the same point. |
| `--json-schema` | A validated object, not prose to be regex'd. |
| `--max-budget-usd` | A per-reading ceiling. A reading costs about a cent. |
| `cwd=$HOME` | A reader with no tools has no business having the source tree as its working directory either. |

Not `--bare`. That one demands `ANTHROPIC_API_KEY` and never reads the OAuth
credentials the machine actually has —
`test_the_reader_runs_with_no_tools_and_no_project_config` asserts the argv
flag by flag, because this is exactly the sort of thing a later edit tidies
away.

**The prompt goes down stdin, not into argv.** Wire copy runs to thousands of
characters and carries every quoting character there is, and an argument list
has a length limit a busy news day would eventually find.

**Third-party copy arrives fenced**, and the prompt says in as many words that
instructions found inside a fence are content, never instructions. The reader
having no tools is what makes that a defence rather than a hope.

`ReaderSettings` in `claude_cli.py` is a structural type rather than the news
panel's concrete settings class, and that is on purpose: the runner is
deliberately ignorant of what is being read, so a second panel would bring its
own settings model with its own defaults rather than inheriting this one's.

## The model is an alias, on purpose

The panel is set to `sonnet` rather than to a pinned model id, so it picks up a
better reader without an edit. The cost is worth stating plainly: a replay run
months apart may not be the same reader, so a measured result is only
meaningful with the date it was measured on.

## What stops it being expensive, and what stops it being wrong

**It never runs unasked.** The tab has to be open, and the toolbar switch has
to be on. `news.spec.ts` asserts it, because a prefetch would spend a cent a
minute on a tab nobody is looking at.

**A reading is cached against the article ids it covers.** The inputs are a
fixed document, so the same headlines give the same answer; switching symbol
and back costs nothing. A second request while one is in flight joins it rather
than starting another. New headlines mark the brief stale rather than
immediately spending another reading — `min_interval_seconds` is the floor, and
the refresh button overrides it.

**The score is catalyst quality, not a trade signal.** The reader sees
headlines and bodies and nothing else: no float, no gap, no RVOL, no regime. A
2 means *this news is not a reason to be long*, never *do not trade this* — the
framework is explicit that a large share of the money is made on names with no
news at all. The prompt says so and a test asserts the sentence survives.

## Testing

**It is off in every test** — `news_ai.enabled=False` in the integration
settings, with the matching `TRADERAPP_NEWS_AI__ENABLED=false` in
`playwright.config.ts`, beside `news_stream` and `trading` and for the same
reason: respx cannot see a subprocess any more than it can see a websocket, so
an un-disabled panel would dial Anthropic for real out of a unit run.

The service is tested against **a shell script written into `tmp_path`** that
reads stdin and prints an envelope — which exercises the real argv, the real
pipes and the real timeout path without a model. One trap, paid for once: when
that fake sleeps, redirect its stdout. A child holding the pipe keeps the
transport alive past the end of the test and surfaces later as an unraisable
"Event loop is closed".

The mocked browser suite serves the route itself, so `news.spec.ts` holds the
contract around the answer — that the score reaches the DOM as a number and a
verdict, that the risks render, and that a brief behind the feed says so.

## Measurement

A prompt that is never scored against outcomes is a prompt nobody can improve.
The harness that did that scoring — `tmp/news-agent-investigation/`, seven
scripts that replayed the panel over two years of real movers by importing the
live modules rather than copies of them — **was deleted on 2026-09-09**, along
with its fetched corpus and a 200-case scored run that had never been analysed.
Rebuilding it means refetching the movers and the news bodies from Alpaca and
paying for the readings again.

What it found is worth keeping, because the findings outlived the code and each
one cost something to learn.

| | |
| --- | --- |
| Universe | 25,644 mover-days over 501 sessions, split-rebased |
| News | 29,552 articles **with bodies**, from Alpaca's Benzinga feed |
| Cases | 21,936 at an 08:00 NY decision minute |
| Float | point-in-time, from SEC Forms 3/4/5, on 72% of cases |
| Candidates | 869 — $2–$20, +20%, RVOL ≥ 5× at 08:00 |

**Point-in-time float** comes from the backtesting repository's
`build_insider_float.py` — `float = shares_out_PIT − insider_held_PIT`,
validated against TradingView at IF MAE 0.118 and ~94% low-float agreement. It
is consumed **only** through `pit_float()`: amendment resolution, owner-group
carry-forward, role-aware staleness and split restatement all live in that
function, and a hand join silently re-derives at least one of them wrong. That
repository still has it; only the replay harness here is gone.

**The first label was wrong, and finding that out was the point.** Grading on
maximum favourable and adverse excursion from a fixed clock made "below VWAP"
look far better than "above VWAP" — that is, *buy the ones that have already
fallen*, the opposite of the method under test. A fixed clock measures
extension, not edge. The replacement was R-based with a first-touch rule: a bar
that breaks the stop closes the trade at −1R even if its high cleared the
target, because that is the order the tape actually filled them in. Any rebuilt
harness starts there rather than rediscovering it.

**The honest baseline**, buying every candidate blind at 08:00:

```
mean R30  -0.423     R > 0  18.1%     R >= 2  3.0%
stopped within 30m  55.4%   median risk  16.1% of entry
```

None of the framework's own criteria separate that population on their own —
`float < 10M & RVOL >= 20` scores −0.450, *worse* than the population it is
drawn from. That is the number any change to the rubric has to beat, and
nothing in the prompt has been changed on the strength of a measured result
yet. This file will say so until one has.

## Where things are

| | |
| --- | --- |
| Runner and sandbox | `backend/app/services/claude_cli.py` |
| News window, rubric, brief | `backend/app/domain/news_ai.py`, `news_prompt.py` |
| Service | `backend/app/services/news_ai.py` |
| Endpoint | `backend/app/api/rest.py` |
| Panel | `frontend/src/components/NewsBrief.tsx` |
| Settings | `news_ai:` in `backend/config/settings.example.yaml` |
| Working on the prompt | `.claude/skills/ai-panel/SKILL.md` |
