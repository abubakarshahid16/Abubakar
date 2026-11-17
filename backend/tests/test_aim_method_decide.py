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
