"""Headline cleaning, catalyst tagging and Dow Jones deduplication.

The fixtures are real wire headlines captured from IBKR during the research
that produced this feature — ``tmp/ibkr-news/CELU_20260827T150637Z.json``.
"""

from __future__ import annotations

import pytest

from app.domain.news import (
    MAX_ARTICLE_CHARS,
    Catalyst,
    build,
    classify,
    clean_headline,
    is_continuation,
    stem,
    to_paragraphs,
)

HOUR = 3600


def raw(headline: str, time: int, article_id: str = "", provider: str = "DJ-N") -> dict:
    return {
        "headline": headline,
        "time": time,
        "article_id": article_id or f"id-{abs(hash(headline)) % 10000}",
        "provider": provider,
    }


class TestClean:
    def test_strips_the_routing_tag(self):
        assert (
            clean_headline("{A:800015:L:en}Celularity Files 8K - Listing Notice >CELU")
            == "Celularity Files 8K - Listing Notice"
        )

    def test_strips_the_bulletin_asterisk(self):
        assert clean_headline("* Celularity Names Steven N. Gordon COO") == (
            "Celularity Names Steven N. Gordon COO"
        )

    def test_strips_several_ticker_markers(self):
        assert clean_headline("Deal announced >CELU >XYZ") == "Deal announced"

    def test_leaves_an_ordinary_headline_alone(self):
        assert clean_headline("Celularity prices offering") == "Celularity prices offering"

    def test_a_ticker_inside_the_text_survives(self):
        """Only trailing markers are markers; a mention is part of the story."""
        assert clean_headline("CELU rallies on news") == "CELU rallies on news"

    @pytest.mark.parametrize("value", ["", "   ", "{A:1:L:en}"])
    def test_nothing_left_is_empty(self, value):
        assert clean_headline(value) == ""


class TestContinuation:
    @pytest.mark.parametrize(
        "headline",
        ["Press Release: Celularity and MuseCell -2-", "Something long -3-"],
    )
    def test_spots_a_continuation(self, headline):
        assert is_continuation(headline)

    @pytest.mark.parametrize(
        "headline",
        ["Celularity prices offering", "Q3 results -- strong", "Phase 2 data"],
    )
    def test_leaves_ordinary_headlines_alone(self, headline):
        assert not is_continuation(headline)


class TestClassify:
    @pytest.mark.parametrize(
        "headline",
        [
            "Celularity Announces Pricing of Public Offering",
            "XYZ Announces $20M Registered Direct Offering",
            "ABC enters at-the-market offering agreement",
            "DEF announces 1-for-10 reverse stock split",
            "GHI issues convertible note to institutional investor",
            "JKL warrant exercise generates proceeds",
        ],
    )
    def test_supply(self, headline):
        assert classify(headline) is Catalyst.SUPPLY

    @pytest.mark.parametrize(
        "headline",
        [
            "Celularity: Not in Compliance With Nasdaq Listing Rule 5250(C)(1)",
            "Celularity Remains Delinquent in Filing Quarterly Report",
            "XYZ receives delisting notice",
            "ABC files for Chapter 11",
            "DEF auditor raises going concern doubt",
        ],
    )
    def test_distress(self, headline):
        assert classify(headline) is Catalyst.DISTRESS

    @pytest.mark.parametrize(
        "headline",
        [
            "XYZ receives FDA approval for its lead candidate",
            "ABC awarded $40M Department of Defense contract",
            "Celularity and MuseCell Announce U.S. Manufacturing Collaboration",
            "DEF announces uplisting to Nasdaq",
            "GHI reports positive topline Phase 3 results",
        ],
    )
    def test_upside(self, headline):
        assert classify(headline) is Catalyst.UPSIDE

    def test_supply_outranks_upside(self):
        """A raise announced alongside good news is still a raise."""
        assert (
            classify("XYZ announces FDA approval and pricing of public offering")
            is Catalyst.SUPPLY
        )

    def test_regaining_compliance_is_upside_despite_the_distress_words(self):
        """"Regained Compliance With Nasdaq Listing Rule" carries a distress
        term inside good news, so the pattern has to win."""
        assert classify("XYZ Regained Compliance With Nasdaq Listing Rule") is Catalyst.UPSIDE
        assert (
            classify("Celularity Announces Filing of Form 10-K, Regains Nasdaq Compliance")
            is Catalyst.UPSIDE
        )

    def test_a_registration_form_number_is_supply(self):
        assert classify("ABC files S-3 shelf registration") is Catalyst.SUPPLY

    def test_investigational_use_is_not_an_investigation(self):
        """A drug "for investigational use" is the ordinary description of one
        in trials, and used to tint a Celularity release red."""
        assert (
            classify("Celularity Announces Availability of Cenplacel-L for Investigational Use")
            is not Catalyst.DISTRESS
        )

    def test_an_exchange_notice_is_distress(self):
        assert (
            classify("Celularity Receives Nasdaq Notice Regarding Form 10-Q")
            is Catalyst.DISTRESS
        )

    def test_the_wire_summary_of_a_listing_deficiency_is_distress(self):
        """Briefing.com renders an 8-K item 3.01 as "Files 8K - Listing
        Notice". Untagged, the news and filings tabs disagreed about the same
        event on the same day."""
        assert classify("Celularity Files 8K - Listing Notice") is Catalyst.DISTRESS

    def test_a_definitive_agreement_is_too_ambiguous_to_tag(self):
        """For a small cap it is as often a securities purchase agreement as a
        merger; a tag that could mean either is worse than no tag."""
        assert classify("Celularity Files 8K - Entry Into Definitive Agreement") is Catalyst.NONE

    def test_an_ordinary_headline_is_untagged(self):
        assert classify("Celularity Names Steven N. Gordon Chief Operating Officer") is (
            Catalyst.NONE
        )


class TestStem:
    def test_the_bulletin_and_the_press_release_share_a_stem(self):
        bulletin = "* Celularity and MuseCell Innovations Announce U.S. Manufacturing Collab"
        release = (
            "Press Release: Celularity and MuseCell Innovations(R) Announce U.S. "
            "Manufacturing Collaboration for the Dezawa"
        )
        assert stem(bulletin) == stem(release)

    def test_different_stories_do_not_collide(self):
        assert stem("Celularity prices public offering") != stem(
            "Celularity names new chief operating officer"
        )


class TestBuild:
    def test_collapses_the_dow_jones_triple(self):
        """One press release arrives as a bulletin, a full version and a
        continuation. It is one row."""
        rows = build(
            [
                raw(
                    "* Celularity and MuseCell Innovations Announce U.S. Manufacturing Collab",
                    1000,
                    "a",
                ),
                raw(
                    "Press Release: Celularity and MuseCell Innovations(R) Announce U.S. "
                    "Manufacturing Collaboration for the Dezawa",
                    1000,
                    "b",
                ),
                raw("Press Release: Celularity and MuseCell -2-", 1000, "c"),
            ]
        )
        assert len(rows) == 1
        assert rows[0].article_id == "b"  # the longest, most complete version
        assert set(rows[0].related) == {"a", "c"}

    def test_the_continuation_marker_is_not_shown(self):
        rows = build([raw("Press Release: Celularity and MuseCell -2-", 1000, "c")])
        assert not rows[0].headline.endswith("-2-")

    def test_the_same_story_a_month_later_is_a_second_event(self):
        headline = "Celularity announces pricing of public offering"
        rows = build([raw(headline, 1000, "a"), raw(headline, 1000 + 40 * 24 * HOUR, "b")])
        assert len(rows) == 2

    def test_unrelated_stories_stay_separate(self):
        rows = build(
            [
                raw("Celularity prices $10M public offering", 1000, "a"),
                raw("Celularity names Steven Gordon chief operating officer", 1200, "b"),
            ]
        )
        assert len(rows) == 2

    def test_newest_first(self):
        rows = build(
            [
                raw("Older unrelated story about widgets", 1000, "a"),
                raw("Newer unrelated story about gadgets", 5000, "b"),
            ]
        )
        assert [row.article_id for row in rows] == ["b", "a"]

    def test_the_catalyst_is_read_across_every_copy(self):
        """A bulletin too short to mention the offering still tints the row
        when its fuller sibling says so."""
        rows = build(
            [
                raw("* Celularity announces proposed", 1000, "a"),
                raw("Celularity announces proposed public offering of common stock", 1000, "b"),
            ]
        )
        assert len(rows) == 1
        assert rows[0].catalyst is Catalyst.SUPPLY

    def test_the_worst_catalyst_across_the_copies_wins(self):
        """One wire copy leads on the FDA news and another on the raise. The
        row has to read as supply — the same rule the 8-K item classifier
        follows, for the same reason."""
        rows = build(
            [
                raw("XYZ Announces FDA Approval of Lead Candidate and Concurrent", 1000, "a"),
                raw(
                    "XYZ Announces FDA Approval of Lead Candidate and Concurrent Public "
                    "Offering of Common Stock",
                    1000,
                    "b",
                ),
            ]
        )
        assert len(rows) == 1
        assert rows[0].catalyst is Catalyst.SUPPLY

    def test_an_upside_copy_still_wins_over_an_untagged_one(self):
        rows = build(
            [
                raw("XYZ Announces Positive Topline Results From Its Pivotal", 1000, "a"),
                raw("XYZ Announces Positive Topline Results From Its Pivotal Trial", 1000, "b"),
            ]
        )
        assert rows[0].catalyst is Catalyst.UPSIDE

    def test_the_routing_tag_never_reaches_a_row(self):
        rows = build([raw("{A:800015:L:en}Celularity Files 8K - Listing Notice >CELU", 1000)])
        assert rows[0].headline == "Celularity Files 8K - Listing Notice"

    def test_empty_headlines_are_dropped(self):
        assert build([raw("", 1000), raw("{A:1:L:en}", 1200)]) == []

    def test_it_serialises_for_the_wire(self):
        rows = build([raw("Celularity prices public offering", 1000, "a")])
        payload = rows[0].to_dict()
        assert payload["catalyst"] == "supply"
        assert payload["article_id"] == "a"
        assert payload["related"] == []


class TestToParagraphs:
    """The article sanitiser.

    IBKR sends an article body as an HTML fragment. It is turned into text
    here rather than rendered as markup in the browser, because it is
    third-party content on the page that also holds the trading UI — so what
    matters is that no tag survives in a form the DOM could act on, and that
    the paragraph breaks a press release needs survive anyway.
    """

    def test_block_tags_become_paragraph_breaks(self):
        body = "<p>First para</p><p>Second para</p>"
        assert to_paragraphs(body) == ["First para", "Second para"]

    def test_the_real_wire_shape_reads_as_prose(self):
        # Straight from tmp/ibkr-news: <pre> spacers and &#10; for newlines.
        body = (
            "<pre>&#10; </pre>&#10;<p>&#10;  Celularity Inc. (CELU) filed a Form 8K "
            "with the U.S Securities and Exchange Commission. </p>&#10;"
            "<pre>&#10; </pre>&#10;<p>&#10;  Effective June 26, Vincent LeVien "
            "resigned from the Board. </p>"
        )
        assert to_paragraphs(body) == [
            "Celularity Inc. (CELU) filed a Form 8K with the U.S Securities and "
            "Exchange Commission.",
            "Effective June 26, Vincent LeVien resigned from the Board.",
        ]

    def test_a_script_tag_is_reduced_to_inert_text(self):
        assert to_paragraphs("<p>hi</p><script>alert(1)</script>") == ["hi", "alert(1)"]

    @pytest.mark.parametrize(
        "body",
        [
            '<img src=x onerror="alert(1)">',
            "<a href=\"javascript:alert(1)\">click</a>",
            "<iframe src='//evil'></iframe>",
            "<svg/onload=alert(1)>",
        ],
    )
    def test_no_tag_survives_in_any_form(self, body):
        for paragraph in to_paragraphs(body):
            assert "<" not in paragraph
            assert ">" not in paragraph

    def test_entities_are_decoded(self):
        assert to_paragraphs("<p>Company&apos;s Q3 &amp; Q4 &lt;results&gt;</p>") == [
            "Company's Q3 & Q4 <results>"
        ]

    def test_a_decoded_entity_cannot_reintroduce_a_tag(self):
        """Unescaping runs after the tags are stripped, so "&lt;script&gt;"
        decodes to visible text rather than back into markup."""
        assert to_paragraphs("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>") == [
            "<script>alert(1)</script>"
        ]

    def test_runs_of_whitespace_collapse(self):
        assert to_paragraphs("<p>  too    much\t space  </p>") == ["too much space"]

    def test_blank_lines_do_not_become_empty_paragraphs(self):
        assert to_paragraphs("<p>one</p><p></p><pre>  </pre><p>two</p>") == ["one", "two"]

    def test_carriage_returns_are_normalised(self):
        assert to_paragraphs("line one\r\nline two\rline three") == [
            "line one",
            "line two",
            "line three",
        ]

    def test_an_oversized_body_is_truncated(self):
        body = "<p>" + ("word " * 20_000) + "</p>"
        joined = " ".join(to_paragraphs(body))
        assert len(joined) <= MAX_ARTICLE_CHARS

    @pytest.mark.parametrize("body", ["", "   ", "<p></p>"])
    def test_nothing_to_say_is_no_paragraphs(self, body):
        assert to_paragraphs(body) == []
