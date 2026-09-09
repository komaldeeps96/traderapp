---
name: ai-panel
description: Change the prompt, rubric, schema or reader behaviour for the terminal's AI panel — the news catalyst score. Use when editing news_prompt.py, news_ai.py or claude_cli.py, or when the panel's answer needs to change shape.
---

# Working on the AI panel

Read [`docs/ai-architecture.md`](../../../docs/ai-architecture.md) first — it is
the layer. This is the procedure for changing it without breaking the things
that are easy to break.

## The prompt is the behaviour

`domain/news_prompt.py` is the feature. Nearly everything a user sees is
decided by its text, so treat an edit to it the way you would treat an edit to
an algorithm, not to a comment.

Several sentences in it are pinned by tests, deliberately, because they are the
sentences a later tidy-up would remove:

- The score is **catalyst quality, not a trade signal**. A 2 means "this news
  is not a reason to be long", never "do not trade this" — the framework is
  explicit that much of the money is made on names with no news at all.
- **The window is a session, not a calendar day.** A 16:05 press release is the
  next morning's gap, and keying it on the New York date puts it under
  yesterday.
- `test_the_reader_runs_with_no_tools_and_no_project_config` — the argv, flag
  by flag.

If a change makes one of those tests fail, the test is almost certainly right.
Change the prompt, or change the test *and say why in the same commit*.

## Before editing

1. Read the panel's design doc, [`docs/news-summary.md`](../../../docs/news-summary.md).
   It records decisions that look arbitrary and are not.
2. Run the prompt by hand. The reader is the `claude` CLI, so a prompt is a
   pipe away from being argued with:

   ```bash
   cd backend && .venv/bin/python -c "
   from app.domain.news_prompt import SYSTEM_PROMPT; print(SYSTEM_PROMPT)"
   ```

3. Decide what evidence would tell you the change is an improvement. "It reads
   better" is not evidence for a scoring rubric.

## After editing

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_news_ai.py \
  tests/unit/test_claude_cli.py -q
cd backend && .venv/bin/python -m ruff check .
cd e2e && npx playwright test --project=chromium
```

The browser suite matters here: the panel's contract — the score in the DOM as
a number and a verdict, the risks rendered, a brief that says when it is behind
the feed — is held in `news.spec.ts`, not in the Python tests.

## Rules that are not negotiable

- **Never enable the panel in a test.** `news_ai.enabled` is False in the
  integration settings and `TRADERAPP_NEWS_AI__ENABLED=false` in
  `playwright.config.ts`. respx cannot intercept a subprocess, so an enabled
  panel dials Anthropic for real out of what looks like an offline run.
- **Never add a tool to the reader.** `--tools ""` is what makes it safe to
  feed a model third-party wire copy. If a reading needs a fact it does not
  have, assemble that fact server-side in `services/news_ai.py` and put it in
  the prompt.
- **Do not pin the model to an id.** It is set to the `sonnet` alias so the
  panel tracks the newest Sonnet without an edit.
- **Never let the browser assemble the question.** The client sends a symbol.

## If you are changing what a reading is scored on

Do not change the rubric on intuition alone — and be aware that the thing that
could have told you whether a change helped no longer exists. The replay
harness at `tmp/news-agent-investigation/` was deleted on 2026-09-09 with its
corpus and its one unanalysed scored run. There is currently **no way to
measure a rubric change in this repo**.

So either rebuild it — refetch the movers and the Benzinga bodies from Alpaca,
replay the live `news_prompt.py` over them, grade against the R-based
first-touch label — or say plainly, in the commit and in
`docs/ai-architecture.md`, that the change is unmeasured. Do not let an
unmeasured change be written up as an improvement.

The numbers that survived are in `docs/ai-architecture.md` under
**Measurement**: the baseline to beat is mean R30 −0.423 with 18.1% winners
over 869 candidates, and the label must be R-based with a first-touch rule.
Grading on excursion from a fixed clock was tried and ranked "already fell"
above "holding up", which is backwards — a rebuild that repeats that mistake
will look like it found an edge.
