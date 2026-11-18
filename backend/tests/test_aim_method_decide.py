"""`_decide`, code's part of every judgment of the general review: one test per branch (contract section A)."""

from __future__ import annotations

import json

import pytest

from app.aim_review import steps as S
from app.aim_review.paper import Paper

PAGES = {
    1: "Design pressure of the test item: 12 bar gauge at the inlet\nOperating temperature: 80 degC at the outlet\n",
    2: "Noise level of the test item: to be advised by the vendor later\nBody material: carbon steel, grade to buyer list\n",
}
PAPER = Paper(paper_id="doc_p", pages=PAGES)
BOOKS = {"B01": {"alias": "B01", "book": "doc_b", "identifier": "QX-STD-101"}}


def _item(kind="presence", source=S.HELD, **kw):
    it = {
        "id": "C001",
        "book": "B01" if source == S.HELD else "",
        "clause": "4.1",
        "source": source,
        "topic": "t",
        "kind": kind,
    }
    it.update(kw)
    return it


def test_no_answer_is_a_not_judged_question():
    d = S._decide(_item(), None, PAPER, BOOKS, "aim_judge: no_json")
    assert d["label"] == "Question"
    assert d["code"] == S.NOT_JUDGED
    assert d["comment"] == "not judged (aim_judge: no_json)"


def test_an_unverified_quote_never_carries_a_verdict():
    j = {
        "label": "Not met",
        "quote": "a sentence that is on no page of this paper at all",
        "page": 1,
    }
    d = S._decide(_item(), j, PAPER, BOOKS, "")
    assert d["label"] == "Question"
    assert "paper quote not found by code" in d["code"]
    assert d["quote"] == "" and d["quote_unverified"] == j["quote"]


def test_a_verdict_with_no_quote_is_a_question():
    d = S._decide(_item(), {"label": "Met", "quote": ""}, PAPER, BOOKS, "")
    assert d["label"] == "Question"
    assert "no paper quote for a verdict" in d["code"]


def test_a_value_the_vendor_left_open_is_a_question_never_a_verdict():
    j = {
        "label": "Not met",
        "quote": "Noise level of the test item: to be advised by the vendor later",
        "page": 2,
    }
    d = S._decide(_item(), j, PAPER, BOOKS, "")
    assert d["label"] == "Question"
    assert "left open by the vendor" in d["code"]
    assert d["page"] == 2


def test_the_model_saying_deferred_is_enough_for_a_question():
    j = {
        "label": "Met",
        "quote": "Body material: carbon steel, grade to buyer list",
        "page": 2,
        "deferred": True,
    }
    assert S._decide(_item(), j, PAPER, BOOKS, "")["label"] == "Question"


def test_a_paper_value_not_in_the_verified_quote_is_a_question():
    j = {
        "label": "Met",
        "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
        "page": 1,
        "numbers": {
            "paper_value": "15",
            "paper_unit": "bar",
            "operator": "<=",
            "rule_value": "20",
            "rule_unit": "bar",
        },
    }
    d = S._decide(_item(kind="limit"), j, PAPER, BOOKS, "")
    assert d["label"] == "Question"
    assert "not in the verified quote" in d["code"]
    assert d["code_compare"] is None


def test_code_compares_the_numbers_and_decides_the_label():
    quote = "Design pressure of the test item: 12 bar gauge at the inlet"
    fail = {
        "label": "Met",
        "quote": quote,
        "page": 1,
        "numbers": {
            "paper_value": "12",
            "paper_unit": "bar",
            "operator": "<=",
            "rule_value": "10",
            "rule_unit": "bar",
        },
    }
    # the item's verified rule quote states the limit (review R1, B1: the rule value, unit and operator come from it)
    d = S._decide(
        _item(kind="limit", rule_quote="The pressure shall not exceed 10 bar."),
        fail,
        PAPER,
        BOOKS,
        "",
    )
    assert d["label"] == "Not met"  # the model said Met; code compared 12 <= 10: false
    assert d["code_compare"]["result"] == "fail"
    ok = dict(fail, label="Not met", numbers=dict(fail["numbers"], rule_value="20"))
    item = _item(kind="limit", rule_quote="The pressure shall not exceed 20 bar.")
    assert S._decide(item, ok, PAPER, BOOKS, "")["label"] == "Met"


def test_two_units_of_one_quantity_are_converted_by_the_apps_unit_code():
    quote = "Design pressure of the test item: 12 bar gauge at the inlet"
    j = {
        "label": "Met",
        "quote": quote,
        "page": 1,
        "numbers": {
            "paper_value": "12",
            "paper_unit": "bar",
            "operator": "<=",
            "rule_value": "150",
            "rule_unit": "psi",
        },
    }
    d = S._decide(
        _item(kind="limit", rule_quote="The pressure shall not exceed 150 psi."),
        j,
        PAPER,
        BOOKS,
        "",
    )
    assert d["label"] == "Not met"  # 12 bar is about 174 psi
    j["numbers"]["rule_value"] = "200"
    item = _item(kind="limit", rule_quote="The pressure shall not exceed 200 psi.")
    assert S._decide(item, j, PAPER, BOOKS, "")["label"] == "Met"


def test_units_of_different_quantities_are_never_compared():
    quote = "Operating temperature: 80 degC at the outlet"
    j = {
        "label": "Met",
        "quote": quote,
        "page": 1,
        "numbers": {
            "paper_value": "80",
            "paper_unit": "degC",
            "operator": "<=",
            "rule_value": "100",
            "rule_unit": "mm",
        },
    }
    d = S._decide(
        _item(kind="limit", rule_quote="The length shall not exceed 100 mm."),
        j,
        PAPER,
        BOOKS,
        "",
    )
    assert d["label"] == "Question"
    assert d["code_compare"]["result"] == "cannot"


def test_a_limit_without_numbers_is_a_question():
    j = {
        "label": "Met",
        "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
        "page": 1,
    }
    d = S._decide(_item(kind="limit"), j, PAPER, BOOKS, "")
    assert d["label"] == "Question"
    assert "a limit with no numbers" in d["code"]


def test_a_presence_item_keeps_a_verified_verdict():
    j = {
        "label": "Met",
        "quote": "Operating temperature: 80 degC at the outlet",
        "page": 1,
    }
    d = S._decide(_item(kind="presence"), j, PAPER, BOOKS, "")
    assert d["label"] == "Met" and d["page"] == 1 and d["code"] == ""


def test_a_knowledge_item_is_never_met_or_not_met():
    j = {
        "label": "Not met",
        "quote": "Operating temperature: 80 degC at the outlet",
        "page": 1,
    }
    d = S._decide(_item(source=S.KNOWLEDGE), j, PAPER, BOOKS, "")
    assert d["label"] == "AI opinion"
    assert "never Met or Not met" in d["code"]
    assert (
        S._decide(_item(source=S.KNOWLEDGE), dict(j, label="Met"), PAPER, BOOKS, "")[
            "label"
        ]
        == "Does not apply"
    )


def test_knowledge_numbers_are_never_compared():
    j = {
        "label": "Met",
        "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
        "page": 1,
        "numbers": {
            "paper_value": "12",
            "paper_unit": "bar",
            "operator": "<=",
            "rule_value": "10",
            "rule_unit": "bar",
        },
    }
    d = S._decide(_item(source=S.KNOWLEDGE, kind="limit"), j, PAPER, BOOKS, "")
    assert d["code_compare"] is None and d["label"] == "Does not apply"


def test_an_unknown_label_is_a_question():
    j = {
        "label": "Compliant",
        "quote": "Operating temperature: 80 degC at the outlet",
        "page": 1,
    }
    assert S._decide(_item(), j, PAPER, BOOKS, "")["label"] == "Question"


def test_the_line_columns_carry_the_comparison_as_json():
    from app.aim_review.engine import to_line

    j = {
        "label": "Met",
        "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
        "page": 1,
        "numbers": {
            "paper_value": "12",
            "paper_unit": "bar",
            "operator": "<=",
            "rule_value": "20",
            "rule_unit": "bar",
        },
    }
    item = _item(kind="limit", rule_quote="The pressure shall not exceed 20 bar.")
    line = to_line(1, S._decide(item, j, PAPER, BOOKS, ""))
    assert json.loads(line["code_compare_json"])["result"] == "pass"
    assert json.loads(line["numbers_json"])["rule_value"] == "20"
    assert line["standard"] == "QX-STD-101" and line["line_no"] == 1


# ---- review R1, B1 and B2: the code stamp rests on the verified quotes only; a value left to the vendor is always a Question ----

RULE_20 = "The design pressure of the item shall not exceed 20 bar gauge in any case."
J12 = {
    "label": "Not met",
    "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
    "page": 1,
}


@pytest.mark.parametrize(
    ("numbers", "why"),
    [
        ({"paper_value": "12", "paper_unit": "bar", "operator": "<=", "rule_value": "10", "rule_unit": "bar"},
         "the rule value is not in the rule's verified words"),
        ({"paper_value": "13", "paper_unit": "bar", "operator": "<=", "rule_value": "20", "rule_unit": "bar"},
         "the paper value is not in the verified quote"),
    ],
)  # fmt: skip
def test_a_value_the_quotes_do_not_state_never_earns_a_code_stamp(numbers, why):
    d = S._decide(
        _item(kind="limit", rule_quote=RULE_20),
        dict(J12, numbers=numbers),
        PAPER,
        BOOKS,
        "",
    )
    assert d["label"] == "Question" and d["code_compare"] is None and why in d["code"]


def test_units_and_operator_are_read_from_the_quotes_not_from_the_answer():
    """The model says MPa and >=; the quotes say 12 bar and 'shall not exceed 20 bar': code compares 12 bar <= 20 bar."""
    nums = {
        "paper_value": "12",
        "paper_unit": "MPa",
        "operator": ">=",
        "rule_value": "20",
        "rule_unit": "bar",
    }
    d = S._decide(
        _item(kind="limit", rule_quote=RULE_20),
        dict(J12, label="Not met", numbers=nums),
        PAPER,
        BOOKS,
        "",
    )
    assert d["code_compare"]["result"] == "pass" and d["label"] == "Met"
    assert d["code_compare"]["why"].startswith("12 bar <= 20 bar")
    assert "read from the quotes" in d["code"]


def test_a_rule_without_a_comparison_word_is_a_question():
    nums = {
        "paper_value": "12",
        "paper_unit": "bar",
        "operator": "<=",
        "rule_value": "20",
        "rule_unit": "bar",
    }
    item = _item(kind="limit", rule_quote="The design pressure is 20 bar.")
    d = S._decide(item, dict(J12, numbers=nums), PAPER, BOOKS, "")
    assert d["label"] == "Question" and "no comparison" in d["code"]


@pytest.mark.parametrize("label", ["Met", "Not met", "AI opinion", "Does not apply"])
@pytest.mark.parametrize(
    "value",
    [
        "*",
        "VTA",
        "TBA",
        "TBD",
        "By Contractor",
        "By Vendor",
        "to be advised by the vendor later",
        "Later",
    ],
)
def test_any_label_on_a_value_left_to_the_vendor_is_a_question_and_reaches_the_store(
    label, value
):
    from app import aim_review_store
    from app.aim_review.engine import to_line

    pages = {1: f"Invented field of the test item: {value}\n"}
    d = S._decide(
        _item(),
        {
            "label": label,
            "quote": f"Invented field of the test item: {value}",
            "page": 1,
        },
        Paper("doc_x", pages),
        BOOKS,
        "",
    )
    assert d["label"] == "Question" and d["deferred"] is True, (label, value)
    line = to_line(1, d)
    assert line["deferred"] is True
    assert aim_review_store.shown_label("Met", None, line["deferred"]) == "Question"


def test_a_stated_value_is_not_taken_for_a_deferred_one():
    pages = {1: "Body material of the test item: carbon steel\n"}
    j = {
        "label": "Met",
        "quote": "Body material of the test item: carbon steel",
        "page": 1,
    }
    d = S._decide(_item(), j, Paper("doc_x", pages), BOOKS, "")
    assert d["label"] == "Met" and d["deferred"] is False


# ---- a provisional figure: a stated figure beside a who-supplies note (the lead's decision of 18 Nov 2026; invented values) ----
# The standing order: a value left to the vendor is a Question, nothing unproven is Pass or Fail. So such a figure is CHECKED by
# code from the verified quotes, but its label is always Question; only a failed check is sent, with both numbers.

OPEN_PAGES = {
    1: "Set pressure 380 psig (By Contractor, as per Code)\nInlet size psig (By Contractor)\n",
    2: "Back pressure 380 psig TBC\nWall thickness 12 mm *\nSeat material By Vendor\n",
}
OPEN_PAPER = Paper(paper_id="doc_open", pages=OPEN_PAGES)
STATED = "Set pressure 380 psig (By Contractor, as per Code)"


def _stated(label="Met", limit="340"):
    j = {"label": label, "quote": STATED, "page": 1, "comment": "the model's words",
         "numbers": {"paper_value": "380", "paper_unit": "psig", "operator": "<=", "rule_value": limit, "rule_unit": "psig"}}  # fmt: skip
    item = _item(
        kind="limit", rule_quote=f"The set pressure shall not exceed {limit} psig."
    )
    return S._decide(item, j, OPEN_PAPER, BOOKS, "")


def _sent(d) -> bool:
    from app import aim_review
    from app.aim_review.engine import to_line

    return aim_review.sendable(to_line(1, d))


def test_a_provisional_figure_over_the_limit_is_a_sent_question_with_both_numbers():
    d = _stated(limit="340")
    assert d["label"] == "Question" and d["code"] == "provisional_fails"
    assert (
        d["code_compare"]["result"] == "fail"
        and d["code_compare"]["read_from"] == "verified quotes"
    )
    assert d["quote"] == STATED and _sent(d)
    assert d["comment"] == (
        "The stated 380 psig (by contractor) appears above the 340 psig limit of QX-STD-101 clause 4.1; please confirm."
    )


def test_a_provisional_figure_under_the_limit_stays_in_all_points_and_is_not_sent():
    d = _stated(limit="400")
    assert d["label"] == "Question" and d["code"] == "provisional"
    assert d["code_compare"]["result"] == "pass" and not _sent(d)


def test_a_provisional_figure_code_cannot_check_is_a_sent_question_with_the_ai_comment():
    """The lead, 18 Nov 2026 (valve-A AFTER run): an unchecked provisional line hid real findings; it is SENT, only a passed
    check is held back."""
    j = {
        "label": "Met",
        "quote": STATED,
        "page": 1,
        "comment": "the model's words",
    }  # no numbers: code cannot check it
    d = S._decide(_item(), j, OPEN_PAPER, BOOKS, "")
    assert (
        d["label"] == "Question" and d["code"] == "provisional_unchecked" and _sent(d)
    )
    assert d["comment"] == "the model's words"


# ---- paper vs paper: the value AND its limit are on the paper (the lead, 18 Nov 2026; invented values) ------------------------

PP_PAGES = {
    1: "Set pressure 380 psig (By Contractor)\nDesign pressure 12 bar gauge at the inlet\n",
    2: "Allowed pressure of the protected item 23.5 barg\nMaximum working pressure of the item 20 bar gauge\n",
}
PP_PAPER = Paper(paper_id="doc_pp", pages=PP_PAGES)
SET_ABOVE = (
    "The set pressure shall not exceed the allowed pressure of the protected item."
)
NO_OP = "The set pressure is chosen against the allowed pressure of the protected item."


def _pp(
    quote,
    value,
    unit,
    limit,
    limit_unit,
    limit_quote,
    rule_quote,
    label="Not met",
    op="<=",
):
    j = {"label": label, "quote": quote, "page": 1, "comment": "the model's words",
         "numbers": {"paper_value": value, "paper_unit": unit, "operator": op, "rule_value": limit,
                     "rule_unit": limit_unit, "limit_quote": limit_quote, "limit_page": 2}}  # fmt: skip
    return S._decide(_item(kind="limit", rule_quote=rule_quote), j, PP_PAPER, BOOKS, "")


def test_a_provisional_figure_over_a_limit_the_paper_states_is_sent_with_both_numbers():
    d = _pp("Set pressure 380 psig (By Contractor)", "380", "psig", "23.5", "barg",
            "Allowed pressure of the protected item 23.5 barg", SET_ABOVE)  # fmt: skip
    assert d["label"] == "Question" and d["code"] == "provisional_fails" and _sent(d)
    assert (
        d["code_compare"]["read_from"] == "verified paper quotes"
        and d["code_compare"]["result"] == "fail"
    )
    assert d["comment"] == (
        "The stated 380 psig (by contractor) appears above 23.5 barg, which the AI read as the limit on page 2; please confirm."
    )


RULE_OP = "The design pressure shall not exceed the working pressure."


@pytest.mark.parametrize("label", ["Met", "Not met"])
@pytest.mark.parametrize(("limit", "result"), [("20", "pass"), ("10", "fail")])
def test_a_verified_rule_operator_with_a_paper_limit_never_yields_pass_or_fail(
    label, limit, result
):
    """The lead, 18 Nov 2026: the model chose which paper number is the limit, so code did not prove the pairing. Even with the
    operator from the rule's verified words, a paper-vs-paper compare is an AI opinion, never "compared by code"."""
    from app import aim_review_store
    from app.aim_review.engine import to_line

    pages = {**PP_PAGES, 3: f"Maximum working pressure of the item {limit} bar gauge\n"}
    j = {"label": label, "quote": "Design pressure 12 bar gauge at the inlet", "page": 1, "comment": "the model's words",
         "numbers": {"paper_value": "12", "paper_unit": "bar", "operator": "<=", "rule_value": limit, "rule_unit": "bar",
                     "limit_quote": f"Maximum working pressure of the item {limit} bar gauge", "limit_page": 3}}  # fmt: skip
    d = S._decide(
        _item(kind="limit", rule_quote=RULE_OP), j, Paper("doc_pp3", pages), BOOKS, ""
    )
    assert d["label"] == "AI opinion" and d["code_compare"]["result"] == result
    assert d["code_compare"]["op_from"] == "the rule's verified words"
    line = to_line(1, d)
    shown = aim_review_store.shown_label(
        line["label"], line["code_compare_json"], line["deferred"]
    )
    assert shown not in (aim_review_store.PASS_BY_CODE, aim_review_store.FAIL_BY_CODE)
    if result == "pass":
        # held back by APPENDING the note: the line keeps its other notes (light check d8c11c00, note 1)
        assert d["code"].endswith("; paper_compare_passed") and not _sent(d)
    else:
        assert "code compared two values of the paper: 12 bar <= 10 bar: false" in d[
            "code"
        ] and _sent(d)
        assert d["comment"] == (
            "The stated 12 bar is above 10 bar, which the AI read as the limit on page 3; contractor to confirm the value. "
            "the model's words"
        )


def test_a_limit_in_the_judged_quote_itself_names_the_judged_page():
    pages = {
        4: "Operating pressure 18 bar gauge, allowed pressure 15 bar gauge at the inlet\n"
    }
    j = {"label": "Not met", "quote": "Operating pressure 18 bar gauge, allowed pressure 15 bar gauge", "page": 4,
         "numbers": {"paper_value": "18", "paper_unit": "bar", "operator": "<=", "rule_value": "15", "rule_unit": "bar"}}  # fmt: skip
    d = S._decide(
        _item(kind="limit", rule_quote=RULE_OP), j, Paper("doc_pp4", pages), BOOKS, ""
    )
    assert (
        d["label"] == "AI opinion"
        and d["code_compare"]["result"] == "fail"
        and _sent(d)
    )
    assert d["comment"].startswith(
        "The stated 18 bar is above 15 bar, which the AI read as the limit on page 4;"
    )


def test_a_paper_limit_with_no_operator_in_any_rule_is_an_ai_opinion_never_a_code_verdict():
    from app import aim_review_store
    from app.aim_review.engine import to_line

    d = _pp("Design pressure 12 bar gauge at the inlet", "12", "bar", "20", "bar",
            "Maximum working pressure of the item 20 bar gauge", "The design pressure is compared with the working pressure.",
            label="Met")  # fmt: skip
    assert (
        d["label"] == "AI opinion" and d["code_compare"]["op_from"] == "the AI's answer"
    )
    # the numbers PASS with the AI's operator: no finding, held back in All points (the lead, 18 Nov 2026)
    assert d["code"].endswith("; paper_compare_passed") and not _sent(
        d
    )  # notes kept, the hold-back appended
    assert d["code_compare"]["why"] == "12 bar <= 20 bar: true"
    line = to_line(1, d)
    shown = aim_review_store.shown_label(
        line["label"], line["code_compare_json"], line["deferred"]
    )
    assert shown not in (aim_review_store.PASS_BY_CODE, aim_review_store.FAIL_BY_CODE)


def test_a_paper_compare_with_no_rule_operator_that_fails_is_a_sent_ai_opinion():
    d = _pp("Design pressure 12 bar gauge at the inlet", "12", "bar", "20", "bar",
            "Maximum working pressure of the item 20 bar gauge", "The design pressure is compared with the working pressure.",
            label="Not met", op=">=")  # fmt: skip
    assert d["label"] == "AI opinion" and d["code_compare"]["result"] == "fail"
    assert "code compared two values of the paper: 12 bar >= 20 bar: false" in d[
        "code"
    ] and _sent(d)


def test_a_limit_quote_that_is_not_on_the_paper_is_never_compared():
    d = _pp("Design pressure 12 bar gauge at the inlet", "12", "bar", "20", "bar",
            "Maximum working pressure 20 bar gauge as invented here", SET_ABOVE, label="Met")  # fmt: skip
    assert d["label"] == "Question" and d["code_compare"] is None
    assert "nor in a verified quote of the paper" in d["code"]


@pytest.mark.parametrize(
    "rule_quote,op",
    [
        ("The set pressure shall not exceed the allowed pressure.", "<="),
        ("The thickness shall be at least the minimum required by the code.", ">="),
        ("The set pressure is chosen against the allowed pressure.", None),
        (
            "The minimum design temperature shall not exceed the operating temperature.",
            None,
        ),  # two comparisons: never guessed
    ],
)
def test_the_rule_operator_is_read_only_when_the_words_name_one(rule_quote, op):
    from app.aim_review.verify import rule_operator

    assert rule_operator(rule_quote) == op


@pytest.mark.parametrize("label", ["Met", "Not met", "AI opinion", "Question"])
@pytest.mark.parametrize("limit", ["340", "400"])
def test_a_who_supplies_line_is_never_met_or_not_met_nor_shown_pass_or_fail(
    label, limit
):
    from app import aim_review_store
    from app.aim_review.engine import to_line

    d = _stated(label=label, limit=limit)
    assert d["label"] == "Question", (label, limit)
    line = to_line(1, d)
    shown = aim_review_store.shown_label(
        line["label"], line["code_compare_json"], line["deferred"]
    )
    assert shown not in (aim_review_store.PASS_BY_CODE, aim_review_store.FAIL_BY_CODE)


@pytest.mark.parametrize(
    "quote,page",
    [
        ("Inlet size psig (By Contractor)", 1),  # a who-supplies note with no figure
        ("Back pressure 380 psig TBC", 2),  # a pending marker beside a figure
        ("Wall thickness 12 mm *", 2),  # a lone star beside a figure
        ("Seat material By Vendor", 2),  # who supplies, nothing stated
    ],
)
@pytest.mark.parametrize("label", ["Met", "Not met"])
def test_a_value_left_open_is_a_plain_sent_question(quote, page, label):
    d = S._decide(
        _item(), {"label": label, "quote": quote, "page": page}, OPEN_PAPER, BOOKS, ""
    )
    assert d["label"] == "Question" and d["deferred"] is True, (quote, label)
    assert d["code"] not in ("provisional", "provisional_fails") and _sent(d)


@pytest.mark.parametrize(
    "quote,left_open,provisional",
    [
        ("Set pressure 380 psig (By Contractor, as per Code)", False, True),
        ("Set pressure: 380 psig by vendor", False, True),
        ("Set pressure psig (By Contractor)", True, False),
        ("380 psig TBC", True, False),
        ("12 mm *", True, False),
        ("380 (*) psig", True, False),
        ("By Vendor", True, False),
        ("Noise level: 85 dBA, vendor to confirm", True, False),
        ("Noise level: to be confirmed", True, False),
        ("Rated speed 1480 rpm later", True, False),
        (
            "Rated flow 24 m3/h * see note 3",
            False,
            False,
        ),  # a star that points at a note is no value mark
        (
            "Item 2 set pressure: psig by vendor",
            True,
            False,
        ),  # "Item 2" is a pointer, no figure for the value
        ("Body material: carbon steel", False, False),
        ("Seal flush plan: N/A", False, False),
    ],
)
def test_pending_who_supplies_and_provisional_are_told_apart(
    quote, left_open, provisional
):
    from app import blank_markers

    assert blank_markers.value_left_open(quote) is left_open, quote
    assert blank_markers.is_provisional_figure(quote) is provisional, quote


# ---- light check d8c11c00 (18 Nov 2026): note 1, the AI's own Not met on its own operator is sent ------------------------------


def test_a_passed_paper_compare_on_the_ais_operator_is_sent_when_the_ai_said_not_met():
    d = _pp("Design pressure 12 bar gauge at the inlet", "12", "bar", "20", "bar",
            "Maximum working pressure of the item 20 bar gauge", "The design pressure is compared with the working pressure.",
            label="Not met")  # fmt: skip
    assert d["label"] == "AI opinion" and d["code_compare"]["result"] == "pass"
    assert "paper_compare_passed" not in d["code"] and _sent(d)
    assert "code compared two values of the paper: 12 bar <= 20 bar: true" in d["code"]


# ---- light check d8c11c00, L1: the forms the round-1 list caught are open again (invented values) -----------------------------


@pytest.mark.parametrize(
    "quote",
    [
        "Design pressure of the test item: 25 bar gauge (HOLD)",  # hold, bracketed beside a figure
        "Design pressure of the test item: 25 bar gauge HOLD",
        "Flushing plan of the test item: later stage",
        "Gasket of the test item: to be supplied",
        "Gasket of the test item: to be provided",
        "Gasket of the test item: to be furnished",
    ],
)
@pytest.mark.parametrize("label", ["Met", "Not met", "AI opinion"])
def test_a_hold_a_later_stage_or_a_to_be_supplied_value_is_a_question(quote, label):
    from app import aim_review_store
    from app.aim_review.engine import to_line

    pages = {1: quote + "\n"}
    j = {"label": label, "quote": quote, "page": 1,
         "numbers": {"paper_value": "25", "paper_unit": "bar", "operator": "<=", "rule_value": "20", "rule_unit": "bar"}}  # fmt: skip
    d = S._decide(
        _item(kind="limit", rule_quote=RULE_20), j, Paper("doc_l1", pages), BOOKS, ""
    )
    assert d["label"] == "Question", (quote, label, d["label"])
    line = to_line(1, d)
    shown = aim_review_store.shown_label(
        line["label"], line["code_compare_json"], line["deferred"]
    )
    assert shown not in (aim_review_store.PASS_BY_CODE, aim_review_store.FAIL_BY_CODE)


#: Every form of the round-1 list (the experiment's `_DEFERRED` plus `blank_markers.names_a_marker`), as printed there.
ROUND1_FORMS = [
    "TBA", "TBC", "TBD", "to be advised", "to be confirmed", "to be determined", "to be provided", "to be supplied",
    "by vendor", "by the vendor", "by contractor", "by the contractor", "by manufacturer", "by others", "by seller",
    "by supplier", "by bidder", "by contractor / vendor", "later stage", "later", "(later)", "hold", "(hold)",
    "to be specified", "to be furnished", "to be decided", "vendor to advise", "vendor to confirm", "vendor to specify",
    "vendor to furnish", "vendor to provide", "vendor to state", "vendor to determine", "vendor to decide",
    "contractor to advise", "manufacturer to confirm", "supplier to provide", "seller to state", "bidder to decide",
]  # fmt: skip


@pytest.mark.parametrize("form", ROUND1_FORMS)
def test_no_form_of_the_round1_list_is_lost(form):
    """Alone it leaves the value open; beside a figure it is open or provisional: never a verdict either way."""
    from app import blank_markers

    assert blank_markers.value_left_open(f"Value of the test item: {form}"), form
    beside = f"Value of the test item: 25 bar {form}"
    assert blank_markers.value_left_open(beside) or blank_markers.is_provisional_figure(
        beside
    ), form


@pytest.mark.parametrize(
    "quote",
    [
        "Hydrotest hold time: 30 min",
        "Hold-down bolts of the test item: M20",
        "Drawing: see later revision 2",
    ],
)
def test_a_hold_time_a_hold_down_bolt_and_a_later_revision_are_values(quote):
    from app import blank_markers

    assert not blank_markers.value_left_open(quote)


# ---- several sheets of the same kind in one paper: one line per failing place (the lead, 18 Nov 2026; invented values) ---------

SHEETS = {
    n: f"Sheet {n} of 3, item tag QX-{n}0\nDesign pressure of the test item: {v} bar gauge at the inlet\n"
    for n, v in ((1, 12), (2, 25), (3, 30))
}
SHEET_PAPER = Paper(paper_id="doc_sheets", pages=SHEETS)
RULE_20_ANY = (
    "The design pressure of the item shall not exceed 20 bar gauge in any case."
)


def _on_sheet(n, value, label):
    quote = f"Design pressure of the test item: {value} bar gauge at the inlet"
    return {"label": label, "page": n, "quote": quote, "comment": f"sheet {n}",
            "numbers": {"paper_value": str(value), "paper_unit": "bar", "operator": "<=", "rule_value": "20", "rule_unit": "bar"}}  # fmt: skip


def test_an_item_that_fails_on_two_sheets_gives_two_sent_lines_each_with_its_own_quote():
    js = [
        _on_sheet(1, 12, "Met"),
        _on_sheet(3, 30, "Not met"),
        _on_sheet(2, 25, "Not met"),
    ]
    lines = S._lines_of(
        _item(kind="limit", rule_quote=RULE_20_ANY), js, SHEET_PAPER, BOOKS, "", False
    )
    assert [ln["page"] for ln in lines] == [2, 3] and [
        ln["finding_no"] for ln in lines
    ] == [1, 2]
    assert [ln["quote"] for ln in lines] == [
        "Design pressure of the test item: 25 bar gauge at the inlet",
        "Design pressure of the test item: 30 bar gauge at the inlet",
    ]
    assert all(
        ln["label"] == "Not met"
        and ln["code_compare"]["result"] == "fail"
        and _sent(ln)
        for ln in lines
    )


def test_an_item_that_holds_on_every_sheet_gives_one_line():
    js = [_on_sheet(1, 12, "Met"), _on_sheet(2, 12, "Met"), _on_sheet(3, 12, "Met")]
    pages = {n: SHEETS[1].replace("Sheet 1", f"Sheet {n}") for n in (1, 2, 3)}
    lines = S._lines_of(
        _item(kind="limit", rule_quote=RULE_20_ANY),
        js,
        Paper("doc_h", pages),
        BOOKS,
        "",
        False,
    )
    assert (
        len(lines) == 1 and lines[0]["label"] == "Met" and lines[0]["finding_no"] == 1
    )


def test_the_same_place_from_two_windows_is_one_line():
    js = [
        _on_sheet(2, 25, "Not met"),
        _on_sheet(2, 25, "Not met"),
        {"id": "C001", "not_here": True},
    ]
    lines = S._lines_of(
        _item(kind="limit", rule_quote=RULE_20_ANY), js, SHEET_PAPER, BOOKS, "", True
    )
    assert len(lines) == 1 and lines[0]["page"] == 2


def test_at_most_six_places_per_item_and_the_rest_are_counted():
    pages = {
        n: f"Sheet {n}\nDesign pressure of the test item: {20 + n} bar gauge at the inlet\n"
        for n in range(1, 9)
    }
    js = [_on_sheet(n, 20 + n, "Not met") for n in range(1, 9)]
    lines = S._lines_of(
        _item(kind="limit", rule_quote=RULE_20_ANY),
        js,
        Paper("doc_cap", pages),
        BOOKS,
        "",
        False,
    )
    assert len(lines) == S.MAX_FINDINGS == 6 and [ln["page"] for ln in lines] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert "2 more place(s) of this item not listed (at most 6 per item)" in lines[0][
        "code"
    ] and _sent(lines[0])


def test_a_findings_list_in_one_row_is_read_as_places():
    class _Model:
        def ask(self, **_kw):
            return {"judgments": [{"id": "C001", "findings": [_on_sheet(2, 25, "Not met"), _on_sheet(3, 30, "Not met")]},
                                  {"id": "C002", **_on_sheet(1, 12, "Met")}]}  # fmt: skip

    class _Text:
        def pages(self, _doc):
            return {}

        def page(self, _doc, _n):
            return None

    full = {
        "what_to_check": "x",
        "applies_when": "always",
        "paper_fields": [],
        "paper_pages": [],
    }
    one = _item(kind="limit", rule_quote=RULE_20_ANY, **full)
    items = [one, dict(one, id="C002")]
    lines, stop = S.s4_judge(_Model(), SHEET_PAPER, {"books": list(BOOKS.values())}, _Text(), items=items,
                             windows=[[1, 2, 3]], lead="claude-sonnet-5-5")  # fmt: skip
    assert stop == "" and [(ln["item_id"], ln["page"]) for ln in lines] == [
        ("C001", 2),
        ("C001", 3),
        ("C002", 1),
    ]


# ---- S5, the editor: it may only take a sent line off the sheet, each move checked by code (the lead, 18 Nov 2026; light check
# of 5293a8f6, E1: a code-proven failure is never offered; a repeat is the same place; a contradiction answers a "not stated") ----

EDIT_PAGES = {
    1: "Back pressure of the test item: 3 bar gauge built up\nSet pressure of the test item: 25 bar gauge\n"
    "Operating temperature of the test item: 80 degC\n",
    2: "Seat material of the test item: stainless steel\nSet pressure of the test item: 31 bar gauge\n",
}
EDIT_PAPER = Paper(paper_id="doc_edit", pages=EDIT_PAGES)
BP_Q = "Back pressure of the test item: 3 bar gauge built up"


def _sent_line(
    item, field, label="Question", page=1, quote="", comment="c", code="", cmp_=None
):
    return {"item_id": item, "field": field, "label": label, "page": page, "quote": quote, "comment": comment, "code": code,
            "code_compare": cmp_}  # fmt: skip


def _fail(value):
    return {"result": "fail", "why": f"{value} bar <= 20 bar: false", "paper": [float(value), "bar"], "rule": [20.0, "bar"],
            "read_from": "verified quotes", "op": "<="}  # fmt: skip


class _Editor:
    def __init__(self, moves=None, fail=None):
        self.moves, self.fail, self.asked = moves or [], fail, []

    def ask(self, **kw):
        self.asked.append(kw)
        if self.fail:
            from app.aim_review.engine import StepFailed

            raise StepFailed(f"aim_edit: {self.fail}")
        return {"moves": self.moves}


def _edit(lines, moves):
    return S.s5_edit(_Editor(moves), EDIT_PAPER, lines, "claude-sonnet-5-5")


def _code_failures():
    q1, q2 = (
        "Set pressure of the test item: 25 bar gauge",
        "Set pressure of the test item: 31 bar gauge",
    )
    return [
        _sent_line("C001", "set pressure", label="Not met", page=1, quote=q1, comment="25 bar is above 20 bar", cmp_=_fail(25)),
        _sent_line("C001", "set pressure", label="Not met", page=2, quote=q2, comment="31 bar is above 20 bar", cmp_=_fail(31)),
        _sent_line("C002", "back pressure", comment="the back pressure is not stated"),
    ]  # fmt: skip


def test_probe_a_any_real_words_of_the_page_never_move_a_code_proven_failure():
    lines = _code_failures()
    moves = [
        {
            "n": 1,
            "reason": "paper_states_otherwise",
            "page": 1,
            "quote": "Operating temperature of the test item: 80 degC",
        }
    ]
    assert _edit(lines, moves) == 0 and all(_sent(d) for d in lines)


def test_probe_b_a_failure_at_another_place_is_never_moved_as_a_repeat():
    lines = _code_failures()
    assert _edit(lines, [{"n": 2, "reason": "repeats", "of": 1}]) == 0 and _sent(
        lines[1]
    )


def test_a_code_proven_failure_is_never_offered_to_the_editor():
    lines = _code_failures()
    provisional = _sent_line("C003", "set pressure", page=1, quote="Set pressure of the test item: 25 bar gauge",
                             code="provisional_fails")  # fmt: skip
    model = _Editor()
    S.s5_edit(model, EDIT_PAPER, [*lines, provisional], "claude-sonnet-5-5")
    shown = model.asked[0]["prompt"]
    assert '"n": 3' in shown and all(f'"n": {n}' not in shown for n in (1, 2, 4))


def test_a_repeat_needs_the_same_page_and_the_same_quote_or_compared_value():
    same = "Seat material of the test item: stainless steel"
    lines = [
        _sent_line("C004", "seat material", page=2, quote=same, comment="is the seat material to the buyer list?"),
        _sent_line("C005", "seat", page=2, quote=same, comment="please confirm the seat material grade"),  # same place
        _sent_line("C004", "seat material", page=1, quote=BP_Q, comment="same item and field, another place"),
        _sent_line("C006", "seat material", page=2, quote="Set pressure of the test item: 31 bar gauge", comment="x"),
    ]  # fmt: skip
    moves = [
        {"n": 2, "reason": "repeats", "of": 1},  # same page, same quote: moved
        {
            "n": 3,
            "reason": "repeats",
            "of": 1,
        },  # same item and field, another page: refused (no "same field" path)
        {
            "n": 4,
            "reason": "repeats",
            "of": 1,
        },  # same page and field, another quote: refused
        {"n": 1, "reason": "repeats", "of": 9},  # no line 9: refused
        {
            "n": 1,
            "reason": "repeats",
            "of": 2,
        },  # line 2 is already off the sheet: refused (never both)
    ]
    assert _edit(lines, moves) == 1
    assert lines[1]["code"] == "edited: repeats line 1" and not _sent(lines[1])
    assert all(_sent(lines[i]) for i in (0, 2, 3))


def test_a_repeat_by_the_same_compared_value_on_the_same_page():
    cmp_ = {"result": "pass", "why": "3 bar <= 5 bar: true", "paper": [3.0, "bar"], "rule": [5.0, "bar"],
            "read_from": "verified paper quotes", "op": "<=", "op_from": "the AI's answer"}  # fmt: skip
    lines = [
        _sent_line("C007", "back pressure", label="AI opinion", quote=BP_Q, cmp_=cmp_),
        _sent_line("C008", "built-up back pressure", label="AI opinion", quote="Back pressure of the test item: 3 bar gauge",
                   cmp_=dict(cmp_)),
    ]  # fmt: skip
    assert _edit(lines, [{"n": 2, "reason": "repeats", "of": 1}]) == 1 and not _sent(
        lines[1]
    )


def test_a_contradiction_only_answers_a_line_that_says_a_thing_is_not_stated():
    lines = [
        _sent_line("C002", "back pressure", comment="the back pressure is not stated"),
        _sent_line(
            "C009",
            "back pressure",
            comment="is the back pressure built up or superimposed?",
        ),  # no "not stated" claim
    ]
    moves = [
        {"n": i, "reason": "paper_states_otherwise", "page": 1, "quote": BP_Q}
        for i in (2, 1)
    ]
    assert _edit(lines, moves) == 1
    assert lines[0][
        "code"
    ] == f'edited: paper states otherwise (page 1: "{BP_Q}")' and _sent(lines[1])


def test_a_contradiction_quote_must_be_on_the_lines_page_and_hold_its_field_with_a_value():
    def one(**kw):
        return [
            _sent_line(
                "C002", "back pressure", comment="the back pressure is not stated", **kw
            )
        ]

    seat = "Seat material of the test item: stainless steel"
    assert (
        _edit(
            one(page=2),
            [{"n": 1, "reason": "paper_states_otherwise", "page": 1, "quote": BP_Q}],
        )
        == 0
    )  # not its page
    assert (
        _edit(
            one(),
            [{"n": 1, "reason": "paper_states_otherwise", "page": 2, "quote": seat}],
        )
        == 0
    )  # its page is 1
    assert (
        _edit(
            one(page=2),
            [{"n": 1, "reason": "paper_states_otherwise", "page": 2, "quote": seat}],
        )
        == 0
    )  # not its field
    no_page = one(
        page=None
    )  # a "not on any page" line: the editor's page, and still its field with a value
    assert (
        _edit(
            no_page,
            [{"n": 1, "reason": "paper_states_otherwise", "page": 1, "quote": BP_Q}],
        )
        == 1
    )


def test_a_field_label_with_a_blank_or_deferral_is_no_value():
    assert S._states_value(
        "Back pressure of the test item: 3 bar gauge built up", "back pressure"
    )
    for empty in (
        "Back pressure: TBA",
        "Back pressure: ____",
        "Back pressure: By Contractor",
        "Back pressure:",
    ):
        assert not S._states_value(empty, "back pressure"), empty


def test_a_moved_line_stays_in_all_points_with_its_label_and_reason():
    from app.aim_review.engine import to_line

    lines = _code_failures()
    _edit(
        lines, [{"n": 3, "reason": "paper_states_otherwise", "page": 1, "quote": BP_Q}]
    )
    assert (
        len(lines) == 3
        and lines[2]["label"] == "Question"
        and lines[2]["comment"] == "the back pressure is not stated"
    )
    assert to_line(3, lines[2])["code_note"].startswith(
        "edited: paper states otherwise (page 1:"
    ) and not _sent(lines[2])


def test_the_editor_can_never_add_rewrite_or_relabel_a_line():
    lines = _code_failures()
    before = [dict(d) for d in lines]
    moves = [
        {"n": 99, "reason": "repeats", "of": 1},
        {"add": {"label": "Not met", "comment": "a new finding"}},
        {"n": 3, "label": "Met", "comment": "rewritten"},
        {"n": 3, "reason": "rewrite", "comment": "rewritten"},
        "not a move",
    ]
    assert _edit(lines, moves) == 0 and lines == before


def test_a_failed_editor_call_moves_nothing_and_no_offered_line_means_no_call():
    lines = _code_failures()
    assert (
        S.s5_edit(_Editor(fail="stop budget"), EDIT_PAPER, lines, "claude-sonnet-5-5")
        == 0
    )
    assert all(d["code"] == "" for d in lines)
    quiet = _Editor()
    assert (
        S.s5_edit(quiet, EDIT_PAPER, lines[:2], "claude-sonnet-5-5") == 0
        and quiet.asked == []
    )  # only code failures
