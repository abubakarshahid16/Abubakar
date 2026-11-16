"""The absence proof by code and the deferral guard of a Pass. INVENTED data only (an invented paper, rule and pages); the field
registry is the product's own file. No model, no network."""

from __future__ import annotations

import pytest

from app import agent_review_absence as A

ROLE = "design_pressure"  # a role of the product's registry (reference/datasheet_checks.json)
CARRIED = frozenset({ROLE, "rated_flow"})
REQ = "The supplier datasheet shall give the design pressure of the casing in bar gauge for every unit supplied."
FILL = "Invented line about the impeller and the casing material, carbon steel to the invented grade, for testing. "
PAGES = {
    1: "Rated flow 120 m3/h\n" + FILL,
    2: "Casing material carbon steel\n" + FILL,
    3: "Impeller bronze\n" + FILL,
}
LEDGER = {
    n: {"native_status": "text", "ocr_status": "not_required", "needs_ocr": False}
    for n in PAGES
}
FACTS = [
    {"field_name": "rated flow", "field_label": "Rated flow", "page": 1},
    {"field_name": "casing material", "field_label": "Casing material", "page": 2},
]
ITEM = {
    "item_id": "R-INV-1",
    "source": "rule",
    "rule_kind": "no_figure",
    "requirement_type": "statement",
    "field_roles": [ROLE],
    "standard": "INV-STD-9",
    "clause": "7.1",
    "rule_quote_ref": "INV-STD-9|7.1",
    "clause_quote_ref": "INV-STD-9|7.1",
    "page_hint": [],
    "rule_condition": None,
    "rule_exceptions": None,
    "rule_row_found": True,
}
ANSWER = {
    "item_id": "R-INV-1",
    "field_label": "",
    "paper_page": 1,
    "paper_quote": "",
    "clause_quote": REQ,
    "pages_searched": [1, 2, 3],
    "reasoning": "The sheet does not give it.",
    "comment": "Provide it.",
    "verdict": "Fail",
    "reason_code": "absent",
}


def prove(
    item=ITEM,
    req=REQ,
    pages=PAGES,
    ledger=LEDGER,
    facts=FACTS,
    carried=CARRIED,
    deferred=None,
):
    return A.prove(
        item, req, pages, max(pages), ledger, facts, carried, deferred=deferred
    )


# ---------------------------------------------------------------- the code proof (pure)


def test_proven_when_every_step_holds():
    p = prove()
    assert p.proven and p.role == ROLE and p.pages_checked == 3 and p.code is None


def test_a_label_with_an_empty_cell_is_nothing_found_and_the_page_is_named():
    pages = {**PAGES, 2: PAGES[2] + "\nDESIGN PRESS. (barg)  ____"}
    p = prove(pages=pages)
    assert p.proven and p.to_json()["empty_label_pages"] == [2]


def test_a_label_with_a_value_a_digit_or_a_following_value_line_is_a_query():
    for tail in (
        "\nDESIGN PRESS. (barg)  ____\nPTV-33 invented value line",  # the next line is not another field label: not shown empty
        "\nDESIGN PRESS. (barg)  12.5",  # a digit
        "\nDESIGN PRESS. (barg)  by vendor",  # a deferral word, never "empty"
    ):
        p = prove(pages={**PAGES, 2: PAGES[2] + tail})
        assert not p.proven and p.code in (
            "absence_field_words_on_page",
            "absence_value_deferred",
        ), tail


def test_one_shared_field_word_on_a_page_is_a_query():
    pages = {
        **PAGES,
        3: PAGES[3] + "\nMax allowable pressure 20 barg",
    }  # not the registry spelling, the same quantity
    assert prove(pages=pages).code == "absence_field_words_on_page"


def test_field_read_from_the_paper_is_a_query():
    facts = [
        *FACTS,
        {"field_name": "design pressure", "field_label": "Design press.", "page": 3},
    ]
    p = prove(facts=facts)
    assert not p.proven and p.code == "absence_field_read" and p.page == 3


@pytest.mark.parametrize(
    "ledger_row,text",
    [
        ({"native_status": "needs_ocr", "ocr_status": "done", "needs_ocr": True}, None),
        ({"native_status": "text", "ocr_status": "failed", "needs_ocr": False}, None),
        (None, None),  # no ledger row
        (
            {"native_status": "text", "ocr_status": "not_required", "needs_ocr": False},
            "short",
        ),  # near-empty page
    ],
)
def test_unreadable_page_is_a_query(ledger_row, text):
    ledger = (
        {**LEDGER, 2: ledger_row}
        if ledger_row
        else {k: v for k, v in LEDGER.items() if k != 2}
    )
    pages = {**PAGES, 2: text} if text else PAGES
    p = prove(pages=pages, ledger=ledger)
    assert not p.proven and p.code == "absence_page_unreadable" and p.page == 2


def test_missing_page_is_a_query():
    pages = {1: PAGES[1], 3: PAGES[3]}
    assert prove(pages=pages).code == "absence_page_unreadable"


def test_unknown_role_is_a_query():
    item = {**ITEM, "field_roles": ["an invented field nobody registered"]}
    assert prove(item=item).code == "absence_field_unknown"
    assert (
        prove(
            item={**ITEM, "field_roles": []},
            req="The supplier shall state the invented thing.",
        ).code
        == "absence_field_unknown"
    )


def test_role_the_paper_kind_does_not_carry_is_a_query():
    assert prove(carried=frozenset({"rated_flow"})).code == "absence_not_carried"
    assert (
        prove(carried=None).code == "absence_no_field_list"
    )  # a procedure: no field list
    assert A.carried_roles("procedure", "Centrifugal Pump") is None
    assert ROLE in (A.carried_roles("datasheet", "Centrifugal Pump") or ())


def test_role_named_in_the_requirement_when_the_rule_stores_none():
    p = prove(item={**ITEM, "field_roles": []})
    assert p.proven and p.role == ROLE and p.role_source == "named in the requirement"


def test_deferral_mark_is_a_query():
    p = prove(deferred=lambda words: 2)
    assert not p.proven and p.code == "absence_value_deferred" and p.page == 2


@pytest.mark.parametrize(
    "patch,req,code",
    [
        ({"source": "skill"}, REQ, "absence_not_a_rule"),
        ({"rule_kind": "advice"}, REQ, "absence_advice"),
        ({"requirement_type": "recommendation"}, REQ, "absence_advice"),
        ({}, REQ.replace("shall", "should"), "absence_not_binding"),
        ({}, REQ + " when specified by the buyer", "absence_conditional"),
        (
            {"requirement_type": "numeric_limit", "rule_condition": "carbon steel"},
            REQ,
            "absence_conditional",
        ),
        ({"rule_exceptions": "except invented units"}, REQ, "absence_exception"),
    ],
)
def test_item_not_provably_required_is_a_query(patch, req, code):
    assert prove(item={**ITEM, **patch}, req=req).code == code


def test_the_comment_has_no_number_and_no_paper_words():
    text = A.comment(prove().field_words, "INV-STD-9", "7.1")
    assert "not stated on the paper" in text and "INV-STD-9 clause 7.1" in text
    assert not any(ch.isdigit() for ch in text.replace("7.1", "").replace("9", ""))


def test_a_rule_whose_requirement_row_was_not_found_is_a_query():  # review 4
    assert (
        prove(item={**ITEM, "rule_row_found": False}).code == "absence_rule_not_found"
    )
    assert (
        prove(item={k: v for k, v in ITEM.items() if k != "rule_row_found"}).code
        == "absence_rule_not_found"
    )


def test_an_unknown_equipment_type_has_no_field_list():  # review 5
    assert A.carried_roles("datasheet", "An Invented Machine Type") is None
    assert A.carried_roles("datasheet", None) is None
    assert (
        prove(carried=A.carried_roles("datasheet", "An Invented Machine Type")).code
        == "absence_no_field_list"
    )


def test_every_known_field_of_the_rule_must_be_absent():  # review 8
    item = {
        **ITEM,
        "field_roles": [ROLE, "rated_flow"],
    }  # the second field stands on page 1 and is read
    p = prove(item=item)
    assert not p.proven and p.code in (
        "absence_field_read",
        "absence_field_words_on_page",
    )


# ---------------------------------------------------------------- the deferral guard of a Pass (owner rule 10 Nov)

DEFERRED_PAGES = {1: "Design pressure 12 bar By Contractor", 2: "Rated flow 120 m3/h"}


def test_pass_guard_unknown_field_words_is_a_query_on_the_safe_side():
    got = A.pass_guard({"field_roles": []}, "", PAGES)
    assert (
        got is not None
        and got[0]["verdict"] == "Query"
        and got[1] == "field_unknown_cannot_check_deferral"
    )
    assert got[2] is None
    assert (
        A.pass_guard({"field_roles": ["", " "]}, "", PAGES)[1]
        == "field_unknown_cannot_check_deferral"
    )


def test_pass_guard_a_value_marked_deferred_is_a_query_naming_the_page():
    got = A.pass_guard({"field_roles": [ROLE]}, "", DEFERRED_PAGES)
    assert got is not None and got[1] == "value_deferred" and got[2] == 1
    assert got[0]["verdict"] == "Query" and "page 1" in got[0]["why"]
    assert (
        A.pass_guard({"field_roles": []}, "Design pressure", DEFERRED_PAGES)[1]
        == "value_deferred"
    )  # the label counts


def test_pass_guard_a_plain_value_passes_the_guard():
    assert (
        A.pass_guard(
            {"field_roles": [ROLE]},
            "",
            {1: "Design pressure 12 bar", 2: "Rated flow 120 m3/h"},
        )
        is None
    )
    assert (
        A.pass_guard({"field_roles": ["rated_flow"]}, "", DEFERRED_PAGES) is None
    )  # another field carries the mark


def test_deferred_mark_needs_all_the_field_words_and_a_mark_on_one_line():
    assert A.deferred_mark("design pressure", DEFERRED_PAGES) == 1
    assert (
        A.deferred_mark("design pressure", {1: "Design pressure 12 bar\nBy Contractor"})
        is None
    )  # two lines
    assert (
        A.deferred_mark("casing material", {1: "Casing 12 mm By Contractor"}) is None
    )  # a word missing
    assert (
        A.deferred_mark("casing material", {1: "Casing material steel By Contractor"})
        == 1
    )
    assert A.deferred_mark("", DEFERRED_PAGES) is None
    assert A.deferred_mark("design pressure", {}) is None


# ---------------------------------------------------------------- a label line, then the value line with the mark

LABEL_THEN_MARK = {1: "DATA SHEET\nCasing material\nBy Contractor\nRated flow\n120 m3/h"}


def test_a_mark_on_the_line_after_the_field_label_is_the_fields_deferral():
    assert A.deferred_mark("casing material", LABEL_THEN_MARK) == 1
    assert A.deferred_mark("rated flow", LABEL_THEN_MARK) is None  # its own value is a figure
    got = A.pass_guard({"field_roles": ["casing_material"]}, "", LABEL_THEN_MARK)
    assert got is not None and got[1] == "value_deferred" and got[2] == 1
    assert got[0]["verdict"] == "Query" and "page 1" in got[0]["why"]


def test_a_mark_line_does_not_belong_to_a_field_when_the_line_before_is_not_its_label():
    no = (
        {1: "Casing material 12 mm\nBy Contractor"},  # the label line holds a figure
        {1: "Bearing type\nBy Contractor"},  # another field's label
        {1: "Casing material\n\nBy Contractor"},  # the mark is not directly after
        {1: "Casing material\nfiller line\nBy Contractor"},  # the mark is not directly after
        {1: "By Contractor\nCasing material"},  # the mark is before the label
        {1: "Casing\nBy Contractor"},  # a word of the field is missing
    )
    for pages in no:
        assert A.deferred_mark("casing material", pages) is None, pages


def test_a_pass_on_a_field_deferred_on_the_next_line_becomes_a_query_and_nothing_becomes_a_pass():
    # the guard only ever answers Query (or None); it has no way to answer Pass or Fail
    for pages in (LABEL_THEN_MARK, {1: "Casing material\nSteel"}, {}, {1: "Casing material 5\nBy Contractor"}):
        got = A.pass_guard({"field_roles": ["casing_material"]}, "", pages)
        assert got is None or got[0]["verdict"] == "Query"
    assert A.pass_guard({"field_roles": ["casing_material"]}, "", {1: "Casing material\nSteel"}) is None


def test_the_request_modules_deferred_mark_is_the_same_rule():
    class Pages:
        def page(self, paper, n):
            return {1: "Bearing type\nSleeve", 2: LABEL_THEN_MARK[1]}.get(n)

    import app.agent_review_request as R

    assert R.deferred_mark("casing material", Pages(), "p", 3) == 2
    assert R.deferred_mark("bearing type", Pages(), "p", 3) is None


ABBREVIATED = {1: "DATA SHEET\nCsg matl\nBy Contractor\nRated flow\n120 m3/h"}


def test_the_label_as_printed_is_tried_when_the_role_words_tie_nothing():
    item = {"field_roles": ["casing_material"]}
    assert A.pass_guard(item, "", ABBREVIATED) is None  # the role words are not on the sheet
    got = A.pass_guard(item, "Csg matl", ABBREVIATED)
    assert got is not None and got[1] == "value_deferred" and got[2] == 1
    assert got[0]["verdict"] == "Query"
    assert A.pass_guard(item, "Rated flow", ABBREVIATED) is None  # that label's value is a figure
    assert A.pass_guard(item, "Csg matl", {1: "Csg matl 5\nBy Contractor"}) is None  # figure on the label line
    assert A.pass_guard(item, "Csg matl", {1: "Csg matl\nSteel"}) is None  # no mark


def test_the_review_runners_guard_also_tries_the_printed_label():
    from app.agent_review_decide import DecideMixin

    class Run(DecideMixin):
        paper, total_pages = "p", 1

        class pages:  # noqa: N801
            @staticmethod
            def page(paper, n):
                return ABBREVIATED[1]

    item = {"field_roles": ["casing_material"]}
    assert Run().pass_guard(item, "") is None
    got = Run().pass_guard(item, "Csg matl")
    assert got is not None and got[1] == "value_deferred" and got[0]["verdict"] == "Query"
