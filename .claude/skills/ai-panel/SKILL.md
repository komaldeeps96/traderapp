---
name: ai-panel
description: Change a prompt, rubric, schema or reader behaviour for the terminal's two AI panels — the news catalyst score and the setup judgement. Use when editing news_prompt.py, setup_prompt.py, news_ai.py, setup_ai.py or claude_cli.py, or when a panel's answer needs to change shape.
---

# Working on an AI panel

Read [`docs/ai-architecture.md`](../../../docs/ai-architecture.md) first — it is
the layer. This is the procedure for changing it without breaking the things
that are easy to break.

## The prompts are the behaviour

`domain/news_prompt.py` and `domain/setup_prompt.py` are the features. Nearly
everything a user sees is decided by their text, so treat an edit to them the
way you would treat an edit to an algorithm, not to a comment.

Several sentences in them are pinned by tests, deliberately, because they are
the sentences a later tidy-up would remove:

- `test_the_rubric_holds_the_joint_evaluation_rule` — the five pillars are
  weighed **jointly**, never counted. Lose that and the panel becomes a slower
  copy of the strip above the chart, which is already the conjunctive filter.
- The news score is **catalyst quality, not a trade signal**. A 2 means "this
  news is not a reason to be long", never "do not trade this".
- `test_the_reader_runs_with_no_tools_and_no_project_config` — the argv, flag
  by flag.

If a change makes one of those tests fail, the test is almost certainly right.
Change the prompt, or change the test *and say why in the same commit*.

## Before editing

1. Read the panel's design doc — `docs/news-summary.md` or
   `docs/setup-judgement.md`. Both record decisions that look arbitrary and are
   not.
2. Run the prompt by hand. The reader is the `claude` CLI, so a prompt is a
   pipe away from being argued with:

   ```bash
   cd backend && .venv/bin/python -c "
   from app.domain.setup_prompt import SYSTEM_PROMPT; print(SYSTEM_PROMPT)"
   ```

3. Decide what evidence would tell you the change is an improvement. "It reads
   better" is not evidence for a scoring rubric.

## After editing

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_news_ai.py \
  tests/unit/test_setup_ai.py tests/unit/test_claude_cli.py -q
cd backend && .venv/bin/python -m ruff check .
cd e2e && npx playwright test --project=chromium
```

The browser suite matters here: the panels' contracts — score *and* grade in
the DOM, a veto rendered above the prose, five pillars always in order, a stale
judgement saying so — are held in `ai.spec.ts` and `news.spec.ts`, not in the
Python tests.

## Rules that are not negotiable

- **Never enable a panel in a test.** `news_ai.enabled` and `setup_ai.enabled`
  are False in the integration settings and `TRADERAPP_*__ENABLED=false` in
  `playwright.config.ts`. respx cannot intercept a subprocess, so an enabled
  panel dials Anthropic for real out of what looks like an offline run.
- **Never add a tool to the reader.** `--tools ""` is what makes it safe to
  feed a model third-party wire copy. If a reading needs a fact it does not
  have, assemble that fact server-side in `services/setup_ai.py` and put it in
  the prompt.
- **Keep both panels on the same model.** The setup judge consumes the news
  reader's score; a mixed pair is two readers arguing about one screen.
- **Do not pin the model to an id.** Both are set to the `sonnet` alias so the
  panels track the newest Sonnet without an edit.
- **Never let the browser assemble the snapshot.** The client sends a symbol.

## If you are changing what a reading is scored on

Do not change a rubric on intuition alone. `tmp/news-agent-investigation/`
replays both panels over two years of real movers and is the only thing here
that can tell you whether a change helped:

```bash
cd tmp/news-agent-investigation
../../../backtesting/venv/bin/python 04_replay.py --limit 200 \
  --min-change 0.20 --min-rvol 5 --price-min 2 --price-max 20 --out scored.jsonl
../../../backtesting/venv/bin/python 07_outcomes.py --scored scored.jsonl
../../../backtesting/venv/bin/python 05_score.py --scored scored_r.jsonl --horizon 30
```

The number to beat is in `docs/ai-architecture.md` under **Measurement**:
mean R30 −0.423 with 18.1% winners, over 869 candidates. Grade against the
R-based first-touch label, never against excursion from a fixed clock — that
was tried, and it ranked "already fell" above "holding up", which is backwards.

Record what the run said in the investigation README **whether or not it is
flattering**. A harness that only records improvements is a harness that
measures nothing.
