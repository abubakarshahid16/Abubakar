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
        pt(1, "Set pressure (PSV-1)", 1, "340 psig (By Contractor)"),
        pt(2, "Set pressure (PSV-2)", 2, "340 psig (By Contractor)"),
        pt(3, "Set pressure (PSV-3)", 3, "120 psig"),
    ]
    assert (
        C.paper_says(members)
        == "pages 1, 2: 340 psig (By Contractor) | page 3: 120 psig"
    )


def test_the_same_text_on_the_same_page_is_said_once():
    members = [pt(n, f"Flow (V{n})", 4, "5 m3/hr (By Contractor)") for n in (1, 2, 3)]
    assert C.paper_says(members) == "5 m3/hr (By Contractor)"
    assert len(C._places(members)) == 3  # three fields: three places


def test_a_quote_that_is_only_the_field_label_says_blank_with_the_label():
    members = [
        pt(1, "Effective area / Actual area (all sheets)", 2, "76   Effective area")
    ]
    assert C.paper_says(members) == "Effective area: blank"  # one text at one place: the page is in the card header
    assert C._places(members)[0]["value"] == "Effective area: blank"


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
        [pt(1, "Set pressure / MAWP (PSV-4301 A/B)", 1, "340 psig (By Contractor)")]
    )
    assert (chip["tag"], chip["page"], chip["value"]) == (
        "PSV-4301 A/B",
        1,
        "340 psig (By Contractor)",
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
