# traderapp

## The machine this runs on

**MacBook Pro, Apple M1 Pro, 8 cores, 16GB RAM, macOS 26.5.**

Sixteen gigabytes is the binding constraint on everything below. Treat it as
a hard limit rather than a preference: on 2026-08-29 an unconstrained browser
test run exhausted memory and **kernel-panicked the machine** — `userspace
watchdog timeout: no successful checkins from configd in 182 seconds`, with
`Compressor Info: 100% of compressed pages limit (BAD)`. Load average reached
262 on 8 cores. Nothing was lost, but the box went down hard.

## Running tests

Run suites **one at a time**. Wait for each to finish before starting the
next, and never have two `playwright test` invocations alive at once.

    # Backend — fast, safe, run freely
    cd backend && .venv/bin/python -m pytest -q
    cd backend && .venv/bin/python -m ruff check .

    # Frontend unit + types + lint — fast, safe, run freely
    cd frontend && npx vitest run
    cd frontend && npx tsc --noEmit && npx eslint src
    cd e2e     && npx tsc --noEmit -p . && npx eslint .

    # Browser tests — one project per invocation
    cd e2e && npx playwright test --project=chromium    # ~1 min, 251 tests
    cd e2e && npx playwright test --project=visual      # ~6 s,    5 tests
    cd e2e && npx playwright test --project=fullstack   # ~15 s,  17 tests
    cd e2e && npx playwright test --project=firefox     # ~1.6 min
    cd e2e && npx playwright test --project=webkit      # ~2 min
    cd e2e && npx playwright test --project=mobile      # ~7 s,    8 tests

A full sequential pass is about six minutes and holds memory above 85%.
All six browser projects pass clean this way: 251 / 5 / 17 / 251 / 251 / 8.

### Rules that keep it upright

- **One `--project` per command.** Not `--project=a --project=b`.
- **Never run two Playwright processes concurrently.** Backgrounding a run
  and starting another is what actually caused the panic — the worker cap
  bounds one invocation, not two.
- **No `--repeat-each`.** Stress loops are for CI, not this laptop.
- **Never `pkill -9` a browser.** It orphans helper processes that stay
  resident. Plain `pkill -f playwright` lets them release memory.
- **Check the machine before and between runs:**

      pgrep -f playwright | wc -l          # want 0
      lsof -ti :4173 :8100 | wc -l         # want 0 (preview + test backend)
      memory_pressure | grep 'free percentage'
      uptime                               # load should be single digits

### Scripts that fan out — know before you use them

`e2e/playwright.config.ts` sets `workers: 2` for exactly this reason; the
Playwright default is half the cores, which is four whole browsers here.
The cap is global across projects, so a multi-project run is bounded — but
these still queue a lot of work and are better split up:

- `npm test` (root) → unit tests, then **every** Playwright project.
- `npm run test:e2e` → `playwright test` with no filter: all projects.
- `npm run test:e2e:ci` → five projects in one invocation.

Two that are safe and useful: `npm run test:mocked` (chromium only) and
`npm run test:fullstack`. `test:ci` deliberately omits `visual`, whose
baselines are darwin-specific.

### Reading a browser failure

Timing-sensitive failures measured on a loaded machine are worthless. Check
`uptime` before concluding anything.

**A browser-lifecycle error is always contention, never application code.**
If you see `Target page, context or browser has been closed`, `Test timeout
... while setting up "backend"`, or `page.goto` timing out in a fixture —
with **no failed assertion anywhere** — the browser died. Re-run the spec
alone on a quiet machine before touching a line of source. All three engines
pass 251/251 when run sequentially.

## Layout

- `backend/` — FastAPI, own venv at `backend/.venv`. Not an npm workspace.
- `frontend/` — Vite + React, npm workspace.
- `e2e/` — Playwright, npm workspace. `tests/mocked` intercepts the backend;
  `tests/fullstack` drives the real one with only Alpaca faked;
  `tests/visual` holds pixel baselines (chromium only).

## Visual baselines

Tolerance is `maxDiffPixelRatio: 0.004`. A small added chip is well under
that, so **a green visual run is not evidence that a small component change
was noticed** — this has silently passed against stale baselines twice. After
any toolbar or strip change, assert the new element renders, then regenerate
with `--update-snapshots`.
