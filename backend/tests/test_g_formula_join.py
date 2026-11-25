"""A firm formula line joins the comment already made on the same finding instead of repeating it (lead 4, 26 Nov 2026: valve-A 55 -> 57 comments).
Pure: invented lines, no model, no database."""

from __future__ import annotations

from app.aim_review import formulas as F


def firm(page=1, a=("380", "psig"), b=("23.5", "barg")):
    return {
        "item_id": "F-set_pressure", "label": "Not met", "field": "Relief set pressure against the limit", "page": page, "quote": "Set pressure  380 psig",
        "comment": "Not met, proven by code: the stated set pressure 380 psig is above the limit 23.5 barg.", "standard": "X-STD", "clause": "X-2",
        "book_document_id": "doc_x", "source": "held standard", "topic": "Relief set pressure against the limit", "code": "formula check set_pressure: code compared",
        "numbers": {"paper_value": a[0], "paper_unit": a[1], "rule_value": b[0], "rule_unit": b[1]},
        "code_compare": {"result": "fail", "read_from": "verified quotes", "why": "380 psig > 23.5 barg: false"}, "deferred": False, "ask": "",
    }  # fmt: skip


def ai(n=1, label="AI opinion", page=1, nums=None, **more):
    return {
        "item_id": f"C{n:03d}", "label": label, "field": "Set pressure vs MAWP", "page": page, "quote": "380 psig (By Contractor)", "comment": "The AI's words.",
        "standard": "Y-STD", "clause": "5.4", "source": "held standard", "code_note": "the AI chose which paper value is the limit", "deferred": False, "ask": "concern",
        "numbers": nums if nums is not None else {"paper_value": "26.2", "paper_unit": "barg", "rule_value": "23.5", "rule_unit": "barg"}, **more,
    }  # fmt: skip


def test_a_firm_line_upgrades_the_ai_comment_with_the_same_two_figures_on_the_same_page_and_adds_no_line():
    decided = [
        ai(1),
        ai(
            2,
            label="Question",
            nums={
                "paper_value": "380",
                "paper_unit": "psig",
                "rule_value": "11.03",
                "rule_unit": "barg",
            },
        ),
    ]
    appended = F.join_into(decided, [firm()])
    assert appended == []  # no second comment
    up = decided[0]
    assert (
        up["label"] == "Not met"
        and up["code_compare"]["result"] == "fail"
        and up["comment"].startswith("Not met, proven by code")
    )
    assert (
        up["standard"] == "X-STD"
        and up["clause"] == "X-2"
        and up["field"] == "Set pressure vs MAWP"
        and up["item_id"] == "C001"
    )  # the place and item stay
    assert (
        F.JOINED in up["code_note"]
        and "formula check" in up["code_note"]
        and "the AI chose" not in up["code_note"]
        and up["ask"] == ""
    )
    assert decided[1]["label"] == "Question"  # another figure pair: untouched


def test_the_figures_match_through_the_unit_code_in_either_order():
    swapped = ai(
        1,
        nums={
            "paper_value": "23.5",
            "paper_unit": "barg",
            "rule_value": "380",
            "rule_unit": "psig",
        },
    )
    assert F.join_into([swapped], [firm()]) == [] and swapped["label"] == "Not met"


def test_only_the_first_matching_line_is_upgraded():
    decided = [ai(1), ai(2)]
    assert F.join_into(decided, [firm()]) == []
    assert [d["label"] for d in decided] == ["Not met", "AI opinion"]


def test_another_page_other_figures_or_a_settled_line_make_the_firm_line_a_new_comment():
    line = firm()
    for decided in (
        [ai(1, page=2)],
        [
            ai(
                1,
                nums={
                    "paper_value": "340",
                    "paper_unit": "psig",
                    "rule_value": "23.5",
                    "rule_unit": "barg",
                },
            )
        ],
        [ai(1, label="Met")],
        [ai(1, label="Not met")],
        [ai(1, deferred=True)],
        [
            ai(
                1,
                nums={
                    "paper_value": "x",
                    "paper_unit": "psig",
                    "rule_value": "23.5",
                    "rule_unit": "barg",
                },
            )
        ],
        [ai(1, nums=None) | {"numbers": None}],
        [
            ai(
                1,
                nums={
                    "paper_value": "26.2",
                    "paper_unit": "bar",
                    "rule_value": "23.5",
                    "rule_unit": "bara",
                },
            )
        ],  # gauge is never set against absolute
    ):
        before = [dict(d) for d in decided]
        assert F.join_into(decided, [line]) == [line], decided
        assert decided == before


def test_a_met_line_is_always_appended_and_never_upgrades_a_comment():
    met = {**firm(), "label": "Met", "comment": ""}
    decided = [ai(1)]
    assert F.join_into(decided, [met]) == [met] and decided[0]["label"] == "AI opinion"


def test_a_stored_line_with_a_code_note_key_is_read_and_written_the_same_way():
    stored = ai(1)
    stored["code"] = stored.pop("code_note")  # an engine line names its note `code`
    assert F.join_into([stored], [firm()]) == [] and F.JOINED in stored["code"]
