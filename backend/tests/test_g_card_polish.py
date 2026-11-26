"""Card polish (planner 18 Nov 23:30/23:40): PAPER SAYS says each text once with its pages and says "blank" for a blank value; the chips
carry tag, page and value; RULE SAYS gives the requirement in a few words. Invented values only."""

from __future__ import annotations

from app import aim_review_card as C


def pt(n, field, page, quote, **kw):
    return {"n": n, "field": field, "page": page, "quote": quote, "topic": "Set pressure at most the vessel limit", "source": "held standard",
            "standard": "QX-STD-101", "clause": "4.1", "compared": "", "comment": "Please confirm.", "shown_label": "Question", "code_note": "",
            "deferred": False, "ask": "concern", **kw}  # fmt: skip


def test_the_same_text_on_two_pages_is_said_once_with_both_pages():
    members = [
        pt(1, "Set pressure (Skid one)", 1, "315 psig (By Contractor)"),
        pt(2, "Set pressure (Skid two)", 2, "315 psig (By Contractor)"),
        pt(3, "Set pressure (Skid three)", 3, "120 psig"),
    ]
    assert (
        C.paper_says(members)
        == "pages 1, 2: 315 psig (By Contractor) | page 3: 120 psig"
    )


def test_the_same_field_on_several_pages_is_one_chip_with_all_its_pages():
    """Planner 19 Nov, item 3: no repeated field in APPLIES TO."""
    members = [pt(1, "Bonnet vent arrangement", 1, "Bolted closed"), pt(2, "Bonnet vent arrangement", 2, "Bolted closed"),
               pt(3, "Bonnet vent arrangement", 3, "Bolted open"), pt(4, "Rated area", 2, "12 in2")]  # fmt: skip
    chips = C._places(members)
    assert [c["field"] for c in chips] == ["Bonnet vent arrangement", "Rated area"]
    assert chips[0]["pages"] == [1, 2, 3] and chips[0]["page"] == 1
    assert (
        chips[0]["value"] == ""
    )  # it says different things on different pages: the quotes are in the evidence
    assert chips[1]["value"] == "12 in2" and chips[1]["pages"] == [2]


def test_the_same_text_on_the_same_page_is_said_once():
    members = [pt(n, f"Flow (V{n})", 4, "5 m3/hr (By Contractor)") for n in (1, 2, 3)]
    assert C.paper_says(members) == "5 m3/hr (By Contractor)"
    assert len(C._places(members)) == 3  # three fields: three places


def test_a_quote_that_is_only_the_field_label_is_left_out_never_replaced_by_a_summary_word():
    """Planner 19 Nov, item 2: PAPER SAYS is a code-verified quote or nothing; "blank" was a summary word, not the paper's."""
    members = [
        pt(1, "Effective area / Actual area (all sheets)", 2, "76   Effective area")
    ]
    assert C.paper_says(members) == ""
    assert C._places(members)[0]["value"] == ""
    assert "blank" not in str(C._places(members))


def test_an_unverified_quote_is_never_said_as_the_paper_says():
    members = [pt(1, "Wall", 2, "Wall 12 mm", quote_unverified=True)]
    assert C.paper_says(members) == ""


def test_a_quote_with_any_other_word_or_number_is_a_value():
    for q in (
        "Effective area 12.5 in2",
        "Effective area TBA",
        "Effective area By Vendor",
        "Orifice J",
    ):
        assert not C.is_blank(q, "Effective area")
    assert C.is_blank("Effective area", "Effective area / Over pressure")
    assert not C.is_blank("", "Effective area")


def test_the_chip_carries_the_tag_the_page_and_the_value():
    (chip,) = C._places(
        [pt(1, "Set pressure / MAWP (North skid)", 1, "315 psig (By Contractor)")]
    )
    assert (chip["tag"], chip["page"], chip["value"]) == (
        "North skid",
        1,
        "315 psig (By Contractor)",
    )
    (bare,) = C._places([pt(2, "Set pressure", 3, "120 psig")])
    assert bare["tag"] == ""


def test_the_rule_says_the_requirement_then_the_book_and_clause():
    assert (
        C.rule_says(pt(1, "f", 1, "q"))
        == "Set pressure at most the vessel limit (QX-STD-101 clause 4.1)"
    )
    assert C.rule_says(pt(1, "f", 1, "q", compared="12 <= 10: false")).endswith(
        ": 12 <= 10: false"
    )
    assert (
        C.rule_says(pt(1, "f", 1, "q", source="not from a held standard"))
        == C.KNOWLEDGE
    )


def test_an_always_checked_card_is_titled_by_its_field_not_by_the_words_always_checked():
    """FTU 19 Nov: four pump cards were all titled "always checked"."""
    assert (
        C.title(pt(1, "NPSH available at rated flow", 2, "q", topic="always checked"))
        == "NPSH available at rated flow"
    )
    assert (
        C.title(
            pt(1, "Anything", 2, "q", topic="Set pressure at most the vessel limit")
        )
        == "Set pressure at most the vessel limit"
    )
