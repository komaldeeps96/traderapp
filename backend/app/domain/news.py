"""Headlines, cleaned up and read for what they do to the tape.

Two sources feed this. IBKR is the entitled one — eight feeds, thirty days of
history, live headlines on generic tick 292, and full article bodies. Alpaca's
Benzinga feed is the second, and it is here because the first goes quiet on
some of exactly the companies this terminal exists for: WETO returned its own
halt and its own resume and nothing else, while Benzinga had ten rows, and
AEMD's catalyst 8-K was there when IBKR had nothing in thirty days.

What arrives from IBKR is not usable as-is:

    {A:800015:L:en}Celularity Files 8K - Listing Notice >CELU

The brace prefix is a legacy routing tag, the trailing ``>SYMBOL`` is a ticker
marker, and Dow Jones sends the same story three times — a bulletin prefixed
``*``, a full "Press Release:" version, and one or more ``-2-`` continuations
carrying the rest of the body. Left alone, one press release eats five rows of
a panel that has about twenty.

The catalyst tag is the point of the panel. A momentum trader reading a feed
mid-run is asking one question — is this a reason to be long, or is it an
offering? — and "Announces Pricing of Public Offering" should be the loudest
row on the screen. Supply and distress outrank upside for the same reason the
8-K item classifier takes the worst item: a raise announced alongside good
news is still a raise.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NamedTuple

# A story naming more than this many companies is a roundup, not this
# company's news. Benzinga's movers lists run to twelve and twenty; a market
# summary names a handful. A real press release names one, occasionally two
# in a partnership or a merger.
ROUNDUP_SYMBOLS = 2


class Catalyst(str, Enum):
    SUPPLY = "supply"
    DISTRESS = "distress"
    UPSIDE = "upside"
    NONE = "none"


# Stock is being sold, or is about to be.
_SUPPLY_TERMS = (
    "public offering",
    "registered direct",
    "private placement",
    "at-the-market",
    "at the market offering",
    "atm program",
    "announces pricing",
    "pricing of",
    "priced offering",
    "underwritten offering",
    "shelf registration",
    "securities purchase agreement",
    "equity line",
    "equity purchase agreement",
    "convertible note",
    "convertible debenture",
    "warrant",
    "dilut",
    "reverse split",
    "reverse stock split",
    "offering of common stock",
    "proposed offering",
    "upsized offering",
    "share issuance",
)

# The company is in trouble, which is where supply usually comes from next.
_DISTRESS_TERMS = (
    "not in compliance",
    "non-compliance",
    "noncompliance",
    "listing rule",
    "listing standard",
    "deficiency",
    "delist",
    "bankrupt",
    "chapter 11",
    "chapter 7",
    "going concern",
    "default",
    "restatement",
    "restate",
    "delinquent",
    "late filing",
    "auditor resign",
    "class action",
    "subpoena",
    # Not bare "investigation": biotech headlines say "for investigational
    # use", which is the ordinary description of a drug in trials, and a
    # Celularity press release was tinted red by it during testing.
    "under investigation",
    "sec investigation",
    "doj investigation",
    "internal investigation",
    "formal investigation",
    "fraud",
    "receivership",
    "wind down",
    "halt",
    # The exchange writing to you is never good news, and the wire words it
    # this way before it ever says "deficiency".
    "nasdaq notice",
    "notice from nasdaq",
    "nyse notice",
    "receives notice regarding",
    # Briefing.com's auto-generated 8-K summaries word it this way. Verified
    # against live data: CELU's "Files 8K - Listing Notice" headlines on
    # 2026-07-29 and 2026-06-12 are the same filings the filings tab shows as
    # 8-K item 3.01, so leaving them untagged had the two panels disagreeing
    # about the same event.
    "listing notice",
)

# A reason to be long.
_UPSIDE_TERMS = (
    "fda approv",
    "fda clear",
    "510(k)",
    "breakthrough therapy",
    "orphan drug",
    "fast track",
    "topline",
    "phase 3",
    "phase iii",
    "phase 2",
    "contract award",
    "awarded",
    "wins contract",
    "partnership",
    "collaboration",
    "acquisition",
    "to acquire",
    "merger",
    "uplist",
    # Bare "patent" catches patent *litigation*, which is not upside.
    "patent granted",
    "receives patent",
    "notice of allowance",
    "share repurchase",
    "buyback",
    "record revenue",
    "raises guidance",
    "raises outlook",
    "beats",
    "letter of intent",
    # "definitive agreement" is deliberately absent: for a small cap it is as
    # often a securities purchase agreement as it is a merger, and a tag that
    # could mean either is worse than no tag.
)

# A few readings need more than a substring, because the wire varies the
# wording around the word that matters — "Regains Nasdaq Compliance",
# "Regained Compliance With Listing Rule". Written as patterns rather than as
# a growing list of near-identical strings.
_CATALYST_PATTERNS: tuple[tuple[Catalyst, re.Pattern[str]], ...] = (
    (Catalyst.UPSIDE, re.compile(r"regain\w*\s+(?:\w+\s+)?compliance")),
    (Catalyst.SUPPLY, re.compile(r"\bs-[13]\b|\b424b\d\b")),
)

# Worst first: a raise announced alongside good news is still a raise.
_CATALYST_TERMS: tuple[tuple[Catalyst, tuple[str, ...]], ...] = (
    (Catalyst.SUPPLY, _SUPPLY_TERMS),
    (Catalyst.DISTRESS, _DISTRESS_TERMS),
    (Catalyst.UPSIDE, _UPSIDE_TERMS),
)

# ``{A:800015:L:en}`` — a routing tag the wire has carried since forever.
_TAG = re.compile(r"^\{[^}]*\}\s*")
# ``>CELU`` or ``>CELU >XYZ`` at the end — the ticker markers.
_TICKERS = re.compile(r"(\s*>[A-Z][A-Z0-9.\-]{0,9})+\s*$")
# ``-2-``, ``-3-`` — a Dow Jones continuation of the story before it.
_CONTINUATION = re.compile(r"\s-\s*\d+\s*-\s*$")
# Bulletin marker and wire-service prefixes, stripped for the dedup key only.
_LEAD_NOISE = re.compile(
    r"^(\*+\s*|press release:\s*|dj\s*|correct(?:ion|ed)?:\s*|update\s*\d*:\s*)+",
    re.IGNORECASE,
)
# Trademark marks. The wire is inconsistent about them — the same story runs
# as "MuseCell Innovations(R)" on one copy and "MuseCell Innovations" on the
# next — so they are removed before the two are compared.
_TRADEMARK = re.compile(r"\((?:r|tm|c)\)|[®™©]", re.IGNORECASE)
# Periods inside a word: "U.S." and "US" have to stem alike, and leaving the
# dots in splits one abbreviation into several words of the key's budget.
_INNER_DOT = re.compile(r"\.(?=\w)|(?<=\w)\.")
_PUNCT = re.compile(r"[^a-z0-9 ]+")

# Characters of the normalised headline that form the dedup key.
#
# Measured in characters rather than words because the wire truncates at a
# character limit and cuts mid-word: the same story runs as "…Announce U.S.
# Manufacturing Collab" on the bulletin and "…Manufacturing Collaboration for
# the Dezawa" on the press release. A word count would compare "collab"
# against "collaboration" and call them different stories.
#
# Long enough that two different announcements from one company do not
# collide; comfortably shorter than the ~110 characters the wire truncates at,
# so the cut never lands inside the key.
_STEM_CHARS = 45

# Two headlines only collapse if they arrive within this of each other. The
# same company can legitimately announce the same *kind* of thing twice in a
# month, and that is two events, not one.
_DEDUPE_WINDOW_SECONDS = 6 * 3600


@dataclass(frozen=True)
class Headline:
    """One row of the news panel."""

    article_id: str
    provider: str
    time: int
    headline: str
    catalyst: Catalyst
    # Set only by sources that publish one. An IBKR article is fetched by id
    # over the wire connection; a Benzinga one is a link, and its body has
    # already arrived, so the two are opened by different routes.
    url: str = ""
    # How many companies the story is about. A press release names one; a
    # "12 Industrials Stocks Moving" roundup names twelve, and showing it as
    # though it were this company's news is how a feed stops being read.
    # IBKR reports no such count and its rows are fetched per symbol, so one
    # is the honest default.
    symbol_count: int = 1
    # Continuations and duplicate bulletins folded into this row, newest
    # first. Kept rather than dropped so the reader can still open the rest
    # of a long press release.
    related: tuple[str, ...] = ()

    @property
    def is_roundup(self) -> bool:
        """A story about a basket rather than about this company."""
        return self.symbol_count > ROUNDUP_SYMBOLS

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "provider": self.provider,
            "time": self.time,
            "headline": self.headline,
            "catalyst": self.catalyst.value,
            "related": list(self.related),
            "url": self.url,
            "symbol_count": self.symbol_count,
            "roundup": self.is_roundup,
        }


# Article bodies arrive as an HTML fragment — <pre>, <p>, and entities for
# every newline. Tags that mean "new paragraph" become one before the rest are
# stripped, so the structure survives into plain text.
_BLOCK_TAG = re.compile(r"</?(?:p|pre|br|div|tr|li|h[1-6])\b[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")
_BLANK_RUN = re.compile(r"\n{2,}")

# A body longer than this is truncated. Wire articles run to a few thousand
# characters; anything past this is a data problem, not an article.
MAX_ARTICLE_CHARS = 40_000


def to_paragraphs(raw_html: str) -> list[str]:
    """An article body as plain-text paragraphs.

    The wire sends an HTML fragment. It is turned into text here rather than
    rendered as markup in the browser: the body is third-party content on a
    page that also holds the trading UI, and there is no version of that where
    injecting provider HTML into the DOM is the right call. Paragraph breaks
    are preserved because a press release without them is unreadable.
    """
    if not raw_html:
        return []
    text = _BLOCK_TAG.sub("\n", raw_html[:MAX_ARTICLE_CHARS])
    text = _ANY_TAG.sub("", text)
    text = html_module.unescape(text)
    # Entities decode to real newlines; normalise the lot before splitting.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RUN.sub("\n", text)
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def extract_tickers(raw: str) -> tuple[str, ...]:
    """The trailing ``>CELU`` markers, before they are stripped for display.

    Live headlines arrive on generic tick 292 with no contract id attached —
    ``ib_async`` discards the request id its wrapper receives — so this marker
    is the only thing on the wire that says which company a live headline is
    about. Not every headline carries one, which is why the caller needs a
    fallback.
    """
    match = _TICKERS.search(_TAG.sub("", raw or "").strip())
    if match is None:
        return ()
    return tuple(part[1:] for part in match.group(0).split() if part.startswith(">"))


def clean_headline(raw: str) -> str:
    """Strip the routing tag, the ticker markers and the bulletin asterisk."""
    text = _TAG.sub("", raw or "").strip()
    text = _TICKERS.sub("", text).strip()
    text = re.sub(r"^\*+\s*", "", text).strip()
    return text


def is_continuation(headline: str) -> bool:
    """``Press Release: Celularity and MuseCell -2-`` — the rest of a story."""
    return bool(_CONTINUATION.search(headline))


def classify(headline: str) -> Catalyst:
    """What this headline does to the tape."""
    text = headline.lower()
    for catalyst, pattern in _CATALYST_PATTERNS:
        if pattern.search(text):
            return catalyst
    for catalyst, terms in _CATALYST_TERMS:
        if any(term in text for term in terms):
            return catalyst
    return Catalyst.NONE


def stem(headline: str) -> str:
    """The dedup key: the first few significant words, normalised.

    Dow Jones publishes one story as a starred bulletin, a "Press Release:"
    version and a run of continuations, each truncated at a different length.
    Normalising the lead-in and keying on the opening words is what makes
    those three collapse into one row without merging unrelated stories.
    """
    text = _LEAD_NOISE.sub("", (headline or "").lower())
    text = _CONTINUATION.sub("", text)
    text = _TRADEMARK.sub("", text)
    text = _INNER_DOT.sub("", text)
    text = " ".join(_PUNCT.sub(" ", text).split())
    if len(text) <= _STEM_CHARS:
        return text
    # Never end the key on a partial word — that is the whole point.
    cut = text[:_STEM_CHARS]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


class _Copy(NamedTuple):
    """One wire copy of a story. Indexed positionally by the matcher."""

    time: int
    article_id: str
    provider: str
    headline: str
    url: str = ""
    symbol_count: int = 1


# Benzinga rides in on Alpaca's connection, so it needs a provider code of its
# own — IBKR's are two-to-seven letters like ``DJ-N``, and this must not be
# mistaken for one when an article body is fetched.
BENZINGA_CODE = "BZ-ALP"

# Article ids are integers on this feed and short numeric strings on IBKR's,
# so they are namespaced before they share a dict.
_BENZINGA_ID = "bz:"


def to_benzinga_row(entry: dict) -> dict | None:
    """One Alpaca news item, in the shape ``build`` already reads.

    ``symbols`` is the field that earns its keep. Benzinga publishes movers
    lists naming a dozen tickers, and the symbol asked for is simply one of
    them — so "Why Elastic Shares Are Trading Higher By 22%" comes back under
    AEMD. Carrying the count lets the panel show those without letting them
    pose as this company's news.
    """
    headline = str(entry.get("headline") or "").strip()
    identifier = entry.get("id")
    if not headline or identifier is None:
        return None
    published = _epoch(str(entry.get("created_at") or ""))
    if published is None:
        return None
    symbols = entry.get("symbols")
    return {
        "article_id": f"{_BENZINGA_ID}{identifier}",
        "provider": BENZINGA_CODE,
        "time": published,
        "headline": headline,
        "url": str(entry.get("url") or ""),
        "symbol_count": len(symbols) if isinstance(symbols, list) and symbols else 1,
    }


def _epoch(timestamp: str) -> int | None:
    """RFC 3339 as the wire sends it — ``2026-08-31T14:14:47Z``."""
    if not timestamp:
        return None
    try:
        return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


@dataclass
class _Group:
    """One story, with every wire copy of it collected."""

    key: str
    time: int
    members: list[_Copy]


def build(raw_headlines: list[dict]) -> list[Headline]:
    """Clean, classify and collapse a batch of raw wire headlines.

    ``raw_headlines`` carries ``article_id``, ``provider``, ``time`` and
    ``headline``. The result is newest first, which is how a feed is read.
    """
    rows: list[_Copy] = []
    for raw in raw_headlines:
        headline = clean_headline(str(raw.get("headline") or ""))
        if not headline:
            continue
        rows.append(
            _Copy(
                time=int(raw.get("time") or 0),
                article_id=str(raw.get("article_id") or ""),
                provider=str(raw.get("provider") or ""),
                headline=headline,
                url=str(raw.get("url") or ""),
                symbol_count=max(1, int(raw.get("symbol_count") or 1)),
            )
        )
    rows.sort(key=lambda row: row.time, reverse=True)

    groups: list[_Group] = []
    for row in rows:
        group = _match(groups, row)
        if group is None:
            key = stem(row.headline)
            if not key:
                continue
            groups.append(_Group(key=key, time=row.time, members=[row]))
        else:
            group.members.append(row)

    return [_headline_for(group) for group in groups]


def _match(groups: list[_Group], row: _Copy) -> _Group | None:
    """The story this wire copy belongs to, if any.

    A copy too short to produce a full stem is matched by prefix instead:
    ``Press Release: Celularity and MuseCell -2-`` stems to three words where
    its parent stems to eight, and the wire truncates its bulletins at a
    different length again. An equality test would leave every one of those as
    a row of its own, which is the noise this exists to remove.

    A stub can in principle prefix-match an unrelated story that opens with
    the same words. Inside a six-hour window, about the same company, that is
    overwhelmingly the same story — and the cost of being wrong is one row
    folded, not one row lost: the copy is kept in ``related``.
    """
    time, headline = row.time, row.headline
    key = stem(headline)
    if not key:
        return None
    for group in groups:
        if abs(time - group.time) > _DEDUPE_WINDOW_SECONDS:
            continue
        if group.key == key or _prefix_match(group.key, key):
            return group
    return None


def _prefix_match(a: str, b: str) -> bool:
    """One key is a truncation of the other.

    Tested in both directions because the copies arrive in no useful order:
    the bulletin can precede or follow the press release, and whichever comes
    first is the one that opened the group.
    """
    if len(a) == len(b):
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return len(shorter) < _STEM_CHARS and longer.startswith(shorter)


def _headline_for(group: _Group) -> Headline:
    """Collapse a story's wire copies into the row that represents it.

    The longest headline wins: the same story arrives as a truncated bulletin,
    a fuller press-release version and a stub continuation, and the longest is
    the one that actually says what happened. The catalyst is read across all
    of them, so a bulletin that only mentions the offering in its second line
    still tints the row.
    """
    best = max(group.members, key=lambda row: len(row.headline))
    catalyst = Catalyst.NONE
    for copy in group.members:
        found = classify(copy.headline)
        if found is not Catalyst.NONE and (
            catalyst is Catalyst.NONE or _worse(found, catalyst)
        ):
            catalyst = found
    return Headline(
        article_id=best.article_id,
        provider=best.provider,
        time=max(row.time for row in group.members),
        headline=_CONTINUATION.sub("", best.headline).strip(),
        catalyst=catalyst,
        related=tuple(
            row.article_id for row in group.members if row.article_id != best.article_id
        ),
        url=best.url,
        # The narrowest copy wins. The same story reaching us twice — once as
        # a press release and once inside a movers list — is this company's
        # news, and the roundup is the duplicate, not the other way round.
        symbol_count=min(row.symbol_count for row in group.members),
    )


_CATALYST_RANK = {
    Catalyst.SUPPLY: 3,
    Catalyst.DISTRESS: 2,
    Catalyst.UPSIDE: 1,
    Catalyst.NONE: 0,
}


def _worse(a: Catalyst, b: Catalyst) -> bool:
    return _CATALYST_RANK[a] > _CATALYST_RANK[b]
