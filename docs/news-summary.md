# The news summary — one session, read and scored

The news panel is split. The bottom half is the feed it has always been:
thirty days of headlines from IBKR's eight entitled wires and Alpaca's
Benzinga, deduplicated across both and tinted by what each does to the tape.
The top half is one day of that feed, read by Claude and scored out of ten,
so the rows below can be skimmed rather than opened one at a time.

This file is the design and the resume point.

## What it looks like

```
┌──────────────────────────────────────────────────────┐
│ AI READ   TUE, MAR 5 · 3 HEADLINES              ⟳    │
│ ┌──┐  FDA cleared the Hemopurifier for advanced      │
│ │2 │  solid tumors at 08:30, then an hour later the  │
│ │WK│  company priced a $12.0M registered direct with │
│ └──┘  immediately exercisable warrants. The          │
│       clearance is real; it is being sold into.      │
│       · FDA 510(k) clearance for Hemopurifier        │
│       · $12.0M registered direct: 6M at $2.00        │
│       ⚠ Priced at-the-market — sold into the run     │
│       ⚠ Warrants exercisable now at $2.00            │
├──────────────────────────────────────────────────────┤
│ 3 FEEDS · BENZINGA + DOW JONES                       │
│ Mar 5  DJ-N   Announces Pricing of $8M Public Off…   │
│ Mar 5  DJ-N   Not in Compliance With Nasdaq Rule…    │
│ Mar 5  DJ-N   MuseCell U.S. Manufacturing Collab  +2 │
│ …                                                    │
└──────────────────────────────────────────────────────┘
```

The switch is on the toolbar, beside the theme toggle, because the panel is
three clicks away behind a dock tab and a control you cannot find while the
thing it controls is running is not a control.

## Why this exists

The feed already tags every row `supply`, `distress` or `upside` from a
substring table in `domain/news.py`. That is a good filter and a poor reader.
It cannot tell a $260M defence contract from a $260k one. It cannot see that
the "strategic partnership" has no counterparty and no figure. And it cannot
tell you the thing that actually decides the trade: that the FDA clearance
four rows up and the registered direct one row down are the same morning, and
that the clearance is what is being sold into.

That last case is the one in the picture above, and it is the argument for the
whole panel. The substring classifier tints the clearance green. The reading
scores the day a 2.

## The rubric is Ross Cameron's, not a general news sense

`domain/news_prompt.py` is the whole prompt, compressed out of the book at
`research/book_ross`. What survived compression is what the book states with a
number, a worked example, or a loss attached.

The organising idea, which the book never names but which every one of its
verdicts obeys, is **cost of production**:

> Did an outside party with money or authority have to act, or did the company
> simply write a sentence?

A regulator approving something, a customer signing for a stated amount, an
institution wiring a private placement — costly, and the book's top three
categories. An intention, a strategy, a board authorisation, an exploration, a
partnership with no figure — free to produce, and the junk list.

Layered on that are the checks that override the category:

- **Planned is not actual.** A company that *bought* a $400M stake ran 600%;
  one whose board "approved the pursuit of" one did nothing.
- **Check the figure against the company.** A micro-cap announcing a $1B
  purchase programme is a tell, not a catalyst.
- **Named counterparties carry the credibility**, and headline size does not:
  a $1.3B term sheet from an unknown issuer is worth less than a $50M deal
  anyone believes.
- **The underwriter is itself a signal.** A financing naming a shop known for
  punitive terms is worse than the same financing without one.

And the dilution structures that score 1-2 however the release is worded: an
active ATM, a registered direct, warrants exercisable now at a low strike, a
shelf filed in the last fortnight, an offering with shares still unsold, a
reverse split where the split *is* the headline. A shelf registration on its
own is deliberately *not* disqualifying — most companies have one — so it is
graded on recency, size, cash and warrant strike rather than vetoed on the
word.

## Three decisions that are load-bearing

**The window is a session, not a calendar day.** This is the correction that
matters most, and it was wrong here first. A press release at 16:05 is not
today's news — it is *tomorrow's gap*. Keying on the New York date filed it
under the day it was published, so a chart opened at 08:00 on a name that
announced an FDA clearance at 16:10 the night before would summarise whatever
trivia had printed since midnight and drop the catalyst entirely.

The window therefore runs from the **previous session's close (16:00 NY) to
now**, and what the panel names is the *session it feeds*. On a Sunday that
reads "for Monday, since Friday 16:00", which is both the honest description
and the useful one. A quiet name steps the window back a session at a time
rather than widening it, up to five, so what comes back is still one session's
news and is dated as such — past that the answer is "nothing recent", not a
fortnight-old date that invites being read as today's.

**One session, not thirty days.** The list below keeps a month because an
offering from last week still matters. The question up here is "what happened,
and is it a reason to be long *now*", and a month of headlines answers it by
burying it.

**A roundup does not decide which session.** "12 Industrials Stocks Moving
Friday" names this company among eleven others. One landing on Saturday
morning would otherwise make the weekend the window and hide the 8-K that
actually moved it, so a window counts as having news only if something in it
is about *this* company.
Roundups from that date still go in, marked, because being on the list is
itself a small tell. A feed of nothing but roundups still gets a day: "one
movers list, nothing of its own" beats an empty panel that looks broken.

**The reader is given the run-up, not just the window.** Two of the book's
sharpest tells are invisible inside a single session: a headline that is a
rehash of one from two days ago, and three escalating releases in three days
that read as somebody trying very hard to be noticed. So the prompt carries a
short history of what came before the window — dates and headlines only, no
bodies — and says what it is for. It is also what lets the reader say "first
news in three weeks", which is a different fact from "one headline today".

**The score is catalyst quality, not a trade signal.** The reader sees the
headlines and the article bodies and nothing else — no float, no gap, no
relative volume, no regime. The book is explicit that catalyst value is
credibility × theme × regime temperature and that only credibility is a
property of the news itself; it is equally explicit that a third of the money
was made on names with no news at all. So a 2 means *this news is not a reason
to be long*, never *do not trade this stock*, and the prompt and the chip's
tooltip both say so.

## How the reading is run

The reader is the `claude` CLI already installed and authenticated on this
machine, spawned as a child process in print mode. That is a deliberate choice
over calling the API directly: there is no second key to hold, no SDK to pin,
nothing new in the settings file that could leak — and it is the same reader
the user works with, so the prompt can be run by hand and argued with.

```sh
printf '%s' "$prompt" | claude -p --model sonnet \
  --output-format json --json-schema "$schema" --system-prompt "$rubric" \
  --tools "" --safe-mode --strict-mcp-config \
  --no-session-persistence --permission-prompts none --max-budget-usd 0.25
```

Five flags do the safety work, and none is decoration:

| Flag | What it buys |
|---|---|
| `--tools ""` | No Bash, no Read, no WebFetch. Text in, object out. |
| `--safe-mode` | No CLAUDE.md, skills, plugins, hooks or MCP servers. Auth still works, which is why this rather than `--bare` — that one demands an API key and never reads OAuth. |
| `--strict-mcp-config` | Belt and braces on the same point. |
| `--json-schema` | A validated object, not prose to be regex'd. |
| `--max-budget-usd` | A per-reading ceiling. A run costs about a cent. |

The prompt goes down **stdin**, not into argv: wire copy runs to thousands of
characters and carries every quoting character there is, and an argument list
has a length limit a busy news day would eventually find. The process runs
with `cwd` set to the home directory — the reader has no tools, and it has no
business having the source tree as its working directory either.

## The content is fenced, and the fences mean something

A press release is written by the company whose stock is being scored, which
makes it the one input on this screen with a motive. It arrives between
`<<<NEWS_DATA` and `NEWS_DATA>>>`, and the system prompt says — before the
model sees any of it — that instructions found there are a fact about the
release to be reported in `risks`, never followed.

With no tools attached, the worst a hostile release can buy is a wrong number
in a panel. But the number is the entire product, so it is worth saying twice.

## What stops it being expensive

A reading costs about a cent and five to twenty seconds. Three things bound
that, and all three are tested:

- **Cached against the article ids it covers**, not against a count or a
  timestamp. Switching away from a symbol and back costs nothing, and a live
  headline that collapsed into a story already on screen — the usual case, the
  starred bulletin ahead of its own press release — changes no id and starts
  nothing.
- **A cooldown**, `min_interval_seconds`, default two minutes. When the ids
  genuinely do change inside it the panel serves the last reading and marks it
  `behind` rather than launching a process for a row already visible in the
  list. The refresh button overrides it.
- **One process per symbol.** Two clients, or a client and a live headline,
  arriving together share the one child rather than starting two. The await is
  shielded, so the first to give up cannot cancel the reading the second is
  still waiting for.

Article bodies are capped too: six stories, never a roundup — its body is
about eleven other companies — and 2,400 characters each, because a press
release says what happened in its first two paragraphs and spends the rest on
forward-looking statements and the investor-relations phone number.

## It is off in every test

`news_ai.enabled` is `False` in the integration settings and
`TRADERAPP_NEWS_AI__ENABLED=false` in the Playwright backend, for the same
reason `alpaca.news_stream` and `trading.enabled` are: it spawns a process
that reaches Anthropic, and respx cannot see a subprocess any more than it can
see a websocket.

The service is tested against a *fake* `claude` — a shell script in `tmp_path`
that reads stdin and prints an envelope. That is the point rather than a
shortcut: the subprocess path is where the bugs live (argv, stdin, exit codes,
timeouts, single-flight), and stubbing at the Python level would test none of
it. One test asserts the real argv, flag by flag, because those flags are the
difference between a scoring prompt and an agent with a shell, and they are
exactly the sort of thing a later edit tidies away as noise.

## Where things are

| | |
|---|---|
| `backend/app/domain/news_ai.py` | Scope, prompt assembly, parsing, the bands |
| `backend/app/domain/news_prompt.py` | The rubric, in full |
| `backend/app/services/news_ai.py` | The child process, the cache, the cooldown |
| `backend/app/api/rest.py` | `GET /api/news/{symbol}/brief?refresh=` |
| `frontend/src/components/NewsBrief.tsx` | The panel's top half |
| `frontend/src/components/Toolbar.tsx` | The switch |
| `backend/tests/unit/test_news_ai.py` | Domain + the fake binary |
| `e2e/tests/mocked/news.spec.ts` | The panel, and that the switch stops the request |
