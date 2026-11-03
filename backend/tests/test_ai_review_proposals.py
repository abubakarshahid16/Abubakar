"""Lane 6, part 1: the AI engineering review pass's proposal verifier. Invented rows and pages only.

A proposal is accepted only when every value, page and clause it cites is verified; a Pass can never be created; a Fail is
never removed without a verified reason.
"""

from __future__ import annotations

import pytest

from app import ai_review_proposals as arp

PAGES = {
    1: "Tag P-101A  Design pressure 12 barg  MAWP 14 barg  Service: lean amine  Fluid: amine\n"
    "Tag P-101B  Design pressure 12 barg  MAWP 16 barg",
    2: "Relief valve PSV-9901  Set pressure 10 barg  Orifice area 650 mm2  Revision stage: IFR",
}
FAIL_ROW = {
    "row_kind": "non_compliant",
    "crs_row_key": "k-fail",
    "page_section": "p.1 - MAWP",
    "standard_reference": "SAES-X-100 cl. 4.2 (p.9)",
    "comment": "SAES-X-100 cl. 4.2: requires MAWP not less than 20 barg. Datasheet p.1, MAWP states 14 barg.",
}
REVIEW_ROW = {
    "row_kind": "needs_engineer_review",
    "crs_row_key": "k-rev",
    "page_section": "p.1 - MAWP",
    "standard_reference": "SAES-X-100 cl. 4.2 (p.9)",
    "comment": "Engineer to check MAWP: tags P-101A and P-101B state 14 barg and 16 barg.",
}
SAFETY_ROW = {
    "row_kind": "safety_tick",
    "crs_row_key": "k-safe",
    "comment": "Safety tick.",
}
CTX = arp.Context(
    pages=PAGES,
    rows={r["crs_row_key"]: r for r in (FAIL_ROW, REVIEW_ROW, SAFETY_ROW)},
    held={"SAES-X-100.pdf": ["4.2", "5.1"]},
)


def prop(**kw):
    base = {
        "id": "p1",
        "type": "add",
        "row_key": None,
        "page": 2,
        "clause": "5.1",
        "standard": "SAES-X-100",
        "field": "Set pressure",
        "value": "10 barg",
        "reason": "The valve set pressure should be confirmed.",
        "text": "Contractor to confirm the set pressure of PSV-9901 against the design pressure.",
        "confidence": "medium",
        "basis": None,
        "evidence": [],
    }
    base.update(kw)
    return base


def reason_of(p, ctx=CTX):
    v = arp.verify(p, ctx)
    return None if v.accepted else v.reason


# ------------------------------------------------------------------ add
def test_a_verified_add_is_accepted_and_its_kind_is_chosen_by_code():
    v = arp.verify(prop(), CTX)
    assert v.accepted and v.row_kind == arp.ADDED_KIND


def test_an_add_citing_a_value_that_is_not_on_the_page_is_refused():
    assert reason_of(prop(value="11 barg")) == arp.Reason.VALUE_NOT_ON_PAGE.value


def test_an_add_citing_a_value_that_is_on_another_page_is_refused():
    assert reason_of(prop(value="12 barg")) == arp.Reason.VALUE_NOT_ON_PAGE.value


def test_an_add_citing_a_page_the_document_does_not_have_is_refused():
    assert reason_of(prop(page=9)) == arp.Reason.PAGE_NOT_IN_DOCUMENT.value


@pytest.mark.parametrize(
    "clause, standard",
    [("9.9", "SAES-X-100"), ("5.1", "SAES-Y-200"), ("", "SAES-X-100")],
)
def test_an_add_whose_clause_is_not_read_from_a_held_standard_is_refused(
    clause, standard
):
    assert (
        reason_of(prop(clause=clause, standard=standard))
        == arp.Reason.CLAUSE_NOT_VERIFIED.value
    )


def test_an_add_with_a_number_on_no_cited_page_is_refused():
    assert (
        reason_of(prop(text="Contractor to confirm the margin of 15 percent is kept."))
        == arp.Reason.NUMBER_NOT_VERIFIED.value
    )


@pytest.mark.parametrize("word", ["complies", "is not acceptable", "approved", "fails"])
def test_an_add_with_a_pass_or_fail_word_is_refused(word):
    assert (
        reason_of(prop(text=f"The set pressure {word} here."))
        == arp.Reason.PASS_FAIL_WORD.value
    )


def test_confidence_high_is_refused():
    assert reason_of(prop(confidence="high")) == arp.Reason.BAD_CONFIDENCE.value


def test_an_add_for_a_field_and_page_that_already_has_a_row_is_refused():
    assert (
        reason_of(prop(page=1, field="MAWP", value="14 barg"))
        == arp.Reason.DUPLICATE_ROW.value
    )


def test_a_pass_can_never_be_created():
    """Whatever the AI writes in the kind or status, an accepted add is a question or (by the code comparison) a Fail."""
    for extra in (
        {"row_kind": "compliant"},
        {"status": "pass"},
        {"kind": "approved"},
        {"row_kind": "conforming"},
    ):
        v = arp.verify(prop(**extra), CTX)
        assert v.accepted and v.row_kind == arp.ADDED_KIND
    for answer in ("compliant", "pass", "conforming", None, "needs_engineer_review"):
        ctx = arp.Context(
            pages=PAGES, rows=CTX.rows, held=CTX.held, compare=lambda *a, _x=answer: _x
        )
        assert arp.verify(prop(), ctx).row_kind == arp.ADDED_KIND
    assert arp.ADDED_KIND != "non_compliant"
    assert not {"compliant", "pass", "conforming"} & {arp.ADDED_KIND, arp.FAIL_KIND}


def test_only_the_code_comparison_can_make_an_added_row_a_fail():
    ctx = arp.Context(
        pages=PAGES, rows=CTX.rows, held=CTX.held, compare=lambda *a: "non_compliant"
    )
    assert arp.verify(prop(), ctx).row_kind == arp.FAIL_KIND
    assert arp.verify(prop(row_kind="non_compliant"), CTX).row_kind == arp.ADDED_KIND


# ------------------------------------------------------------------ remove
TAG_REMOVE = {
    "type": "remove",
    "row_key": "k-rev",
    "page": 1,
    "clause": None,
    "standard": None,
    "field": "MAWP",
    "value": "16 barg",
    "text": None,
    "basis": "tag_difference",
    "reason": "Tags P-101A and P-101B are different items; a different MAWP for each tag is normal.",
    "evidence": [
        {"page": 1, "quote": "Tag P-101A  Design pressure 12 barg  MAWP 14 barg"},
        {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"},
    ],
}


def test_a_removal_of_a_question_row_with_verified_evidence_is_accepted():
    assert arp.verify(prop(**TAG_REMOVE), CTX).accepted


def test_a_removal_with_a_quote_that_is_not_on_the_page_is_refused():
    bad = dict(TAG_REMOVE, evidence=[{"page": 1, "quote": "Tag P-101C  MAWP 20 barg"}])
    assert reason_of(prop(**bad)) == arp.Reason.EVIDENCE_NOT_ON_PAGE.value


def test_a_removal_with_no_evidence_is_refused():
    assert reason_of(prop(**dict(TAG_REMOVE, evidence=[]))) == arp.Reason.NO_BASIS.value


def test_a_removal_of_a_fail_with_the_tag_argument_is_refused():
    assert (
        reason_of(prop(**dict(TAG_REMOVE, row_key="k-fail")))
        == arp.Reason.FAIL_KEPT.value
    )


def test_a_safety_row_and_an_unknown_row_are_never_removed():
    assert (
        reason_of(prop(**dict(TAG_REMOVE, row_key="k-safe")))
        == arp.Reason.PROTECTED_ROW.value
    )
    assert (
        reason_of(prop(**dict(TAG_REMOVE, row_key="nope")))
        == arp.Reason.NO_SUCH_ROW.value
    )


# ------------------------------------------------------------------ reword, understanding, batch
def test_a_reword_goes_through_the_comment_lock():
    good = "Engineer to check MAWP: tags P-101A and P-101B state 14 barg and 16 barg; please confirm."
    assert arp.verify(
        prop(
            type="reword", row_key="k-rev", text=good, page=1, clause=None, value=None
        ),
        CTX,
    ).accepted
    bad = good.replace("16 barg", "18 barg")
    assert reason_of(
        prop(type="reword", row_key="k-rev", text=bad, page=1, clause=None, value=None)
    ).startswith(arp.Reason.REWORD_REFUSED.value)


def test_understanding_may_only_name_what_the_document_says():
    ok = {
        "type": "understanding",
        "confidence": "low",
        "reason": "x",
        "understanding": {
            "equipment": "Relief valve",
            "tags": ["P-101A", "PSV-9901"],
            "fluids": ["amine"],
            "revision_stage": "IFR",
        },
    }
    assert arp.verify(ok, CTX).accepted
    bad = dict(ok, understanding={"tags": ["P-999"]})
    assert arp.verify(bad, CTX).reason == arp.Reason.NOT_IN_DOCUMENT.value
    assert (
        arp.verify(
            dict(ok, understanding={"service": "this is acceptable"}), CTX
        ).reason
        == arp.Reason.PASS_FAIL_WORD.value
    )


def test_malformed_and_unknown_proposals_are_refused_and_the_batch_is_bounded():
    assert arp.verify("text", CTX).reason == arp.Reason.MALFORMED.value
    assert (
        arp.verify({"type": "delete_everything"}, CTX).reason
        == arp.Reason.BAD_TYPE.value
    )
    many = [prop() for _ in range(arp.MAX_PROPOSALS + 3)]
    verdicts = arp.verify_all(many, CTX)
    assert (
        len(verdicts) == len(many)
        and [v.reason for v in verdicts[-3:]] == [arp.Reason.TOO_MANY.value] * 3
    )
    assert arp.verify_all("not a list", CTX)[0].accepted is False


def test_one_change_per_row():
    two = [prop(**TAG_REMOVE), prop(**TAG_REMOVE, id="p2")]
    first, second = arp.verify_all(two, CTX)
    assert first.accepted and not second.accepted


@pytest.mark.parametrize("quote", ["a", "Tag", "P-101A", "  1  "])
def test_a_removal_of_any_row_needs_a_meaningful_evidence_quote(quote):
    remove = dict(
        TAG_REMOVE,
        row_key="k-rev",
        basis="context",
        evidence=[{"page": 1, "quote": quote}],
    )
    verdict = arp.verify(prop(**remove), CTX)
    assert not verdict.accepted
    assert verdict.reason == arp.Reason.EVIDENCE_TOO_SHORT.value


def test_the_quote_must_carry_the_value_the_reason_relies_on():
    remove = dict(
        TAG_REMOVE,
        row_key="k-rev",
        basis="context",
        value="16 barg",
        evidence=[{"page": 1, "quote": "Tag P-101A  Design pressure 12 barg"}],
    )
    assert reason_of(prop(**remove)) == arp.Reason.EVIDENCE_NOT_ON_PAGE.value


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (None, arp.Reason.PROTECTED_ROW.value),
        ("", arp.Reason.PROTECTED_ROW.value),
        ("engineer_comment", arp.Reason.PROTECTED_ROW.value),
        ("carried_forward", arp.Reason.PROTECTED_ROW.value),
        ("some_new_kind", arp.Reason.PROTECTED_ROW.value),
        ("NON_COMPLIANT", arp.Reason.FAIL_KEPT.value),  # cased: still a Fail
    ],
)
def test_only_an_allow_list_of_row_kinds_can_be_removed(kind, reason):
    row = dict(REVIEW_ROW, row_kind=kind)
    ctx = arp.Context(pages=PAGES, rows={"k-rev": row}, held=CTX.held)
    remove = dict(
        TAG_REMOVE,
        row_key="k-rev",
        basis="context",
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    assert reason_of(prop(**remove), ctx) == reason


@pytest.mark.parametrize(
    "words",
    [
        "The row is in-line with the standard.",
        "The row is in  line  with the standard.",
        "The value is consistent with the standard.",
        "This is consistent.",
    ],
)
def test_hyphenated_and_spaced_verdict_wording_is_refused(words):
    assert reason_of(prop(text=words)) == arp.Reason.PASS_FAIL_WORD.value


def test_understanding_is_one_page_and_not_trivial():
    ctx = arp.Context(pages=PAGES, rows={}, held={})
    one = {
        "type": "understanding",
        "confidence": "low",
        "understanding": {"tags": ["a"]},
    }
    assert not arp.verify(one, ctx).accepted
    across = {
        "type": "understanding",
        "confidence": "low",
        "understanding": {"service": ["MAWP 16 barg Relief valve"]},
    }  # the end of page 1 and the start of page 2
    assert not arp.verify(across, ctx).accepted
    fine = {
        "type": "understanding",
        "confidence": "low",
        "understanding": {"fluids": ["amine"]},
    }
    assert arp.verify(fine, ctx).accepted


@pytest.mark.parametrize(
    "words",
    [
        "The row is in line with the standard.",
        "This is in accordance with the standard.",
        "The value is within limits.",
        "This is okay.",
    ],
)
def test_more_verdict_wording_is_refused(words):
    assert reason_of(prop(text=words)) == arp.Reason.PASS_FAIL_WORD.value


FAIL_SPELLINGS = [
    "non_compliant",
    "NON_COMPLIANT",
    "Non-Compliant",
    " non compliant ",
    "noncompliant",
    "fail",
]


@pytest.mark.parametrize("kind", FAIL_SPELLINGS)
@pytest.mark.parametrize(
    "basis", ["tag_difference", "context", "misread", "out_of_scope", None]
)
def test_a_fail_is_never_removed_whatever_the_basis_or_the_spelling_of_its_kind(
    kind, basis
):
    row = dict(FAIL_ROW, row_kind=kind)
    ctx = arp.Context(
        pages=PAGES,
        rows={"k-fail": row},
        held=CTX.held,
        out_of_scope=frozenset({("SAES-X-100", "4.2")}),
    )
    remove = dict(
        TAG_REMOVE,
        row_key="k-fail",
        basis=basis,
        row_value="20 barg",
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    assert reason_of(prop(**remove), ctx) == arp.Reason.FAIL_KEPT.value


def _flag(**kw):
    base = {
        "type": "flag",
        "row_key": "k-fail",
        "page": 1,
        "value": "16 barg",
        "reason": "The row's datasheet figure looks misread.",
        "confidence": "medium",
        "evidence": [
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    }
    base.update(kw)
    return base


def test_a_suspected_misread_is_a_flag_built_by_code_from_the_verified_quote():
    verdict = arp.verify(_flag(text="Everything is wrong here"), CTX)
    assert verdict.accepted
    assert verdict.final_text == (
        "AI suspects the datasheet value was misread: page 1 shows "
        '"Tag P-101B  Design pressure 12 barg  MAWP 16 barg"'
    )
    assert (
        "wrong" not in verdict.final_text and "looks misread" not in verdict.final_text
    )


def test_a_flag_is_refused_without_a_verified_quote_value_or_row():
    assert reason_of(_flag(row_key="nope")) == arp.Reason.NO_SUCH_ROW.value
    assert reason_of(_flag(value="99 barg")) == arp.Reason.VALUE_NOT_ON_PAGE.value
    assert reason_of(_flag(evidence=[])) == arp.Reason.NO_BASIS.value
    assert reason_of(_flag(evidence=[{"page": 1, "quote": "MAWP"}])) == (
        arp.Reason.EVIDENCE_TOO_SHORT.value
    )
    assert (
        reason_of(_flag(evidence=[{"page": 1, "quote": "Tag P-101A  MAWP 14 barg"}]))
        == arp.Reason.EVIDENCE_NOT_ON_PAGE.value
    )  # the quote does not carry the value
    assert (
        reason_of(_flag(reason="The row complies.")) == arp.Reason.PASS_FAIL_WORD.value
    )


def test_a_flag_changes_no_row_and_a_flag_and_a_removal_of_one_row_are_not_both_taken():
    rows_before = {k: dict(v) for k, v in CTX.rows.items()}
    both = arp.verify_all(
        [
            _flag(),
            dict(
                TAG_REMOVE,
                row_key="k-fail",
                basis="context",
                evidence=[
                    {
                        "page": 1,
                        "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg",
                    }
                ],
            ),
        ],
        CTX,
    )
    assert both[0].accepted and not both[1].accepted
    assert CTX.rows == rows_before


GOOD_WORDS = "Engineer to check MAWP: tags P-101A and P-101B state 14 barg and 16 barg; please confirm."


def _reword(**kw):
    base = prop(
        type="reword", row_key="k-rev", text=GOOD_WORDS, page=1, clause=None, value=None
    )
    base.update(kw)
    return base


@pytest.mark.parametrize(
    "reason",
    [
        "The maximum allowed is 99 barg per clause 7.7.",
        "SAES-X-200 clause 4.2 says so.",
        "Clearer for the 14 barg tag and the 18 barg tag.",
    ],
)
def test_a_reword_reason_with_a_number_the_row_does_not_hold_is_refused(reason):
    assert reason_of(_reword(reason=reason)) == arp.Reason.NUMBER_NOT_VERIFIED.value


def test_a_reword_reason_may_repeat_the_rows_own_numbers():
    assert arp.verify(
        _reword(reason="Names both tags and keeps 14 barg and 16 barg, cl. 4.2."), CTX
    ).accepted


@pytest.mark.parametrize(
    "kind",
    [
        "standard_not_cited",
        "carried_forward",
        "engineer_comment",
        "missing_information",
        "safety_tick",
        None,
    ],
)
def test_a_flag_is_refused_on_a_row_with_no_datasheet_value(kind):
    ctx = arp.Context(
        pages=PAGES, rows={"k-fail": dict(FAIL_ROW, row_kind=kind)}, held=CTX.held
    )
    assert reason_of(_flag(), ctx) == arp.Reason.ROW_HAS_NO_VALUE.value


@pytest.mark.parametrize(
    "quote", ["Status complies  MAWP 16 barg", "MAWP 16 barg accepted OK"]
)
def test_a_flag_quote_with_a_verdict_word_is_refused(quote):
    pages = {1: f"Tag P-101B  {quote}"}
    ctx = arp.Context(pages=pages, rows=CTX.rows, held=CTX.held)
    flag = _flag(evidence=[{"page": 1, "quote": f"Tag P-101B  {quote}"}])
    assert reason_of(flag, ctx) == arp.Reason.PASS_FAIL_WORD.value
