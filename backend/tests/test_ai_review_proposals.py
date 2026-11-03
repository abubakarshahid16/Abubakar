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
    2: "Relief valve PSV-201  Set pressure 10 barg  Orifice area 650 mm2  Revision stage: IFR",
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
        "text": "Contractor to confirm the set pressure of PSV-201 against the design pressure.",
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


def test_a_removal_of_a_fail_with_no_stated_basis_is_refused():
    assert (
        reason_of(prop(**dict(TAG_REMOVE, row_key="k-fail", basis=None)))
        == arp.Reason.NO_BASIS.value
    )


def test_a_misread_fail_is_removed_only_when_the_row_states_a_figure_the_page_does_not_have():
    misread = dict(
        TAG_REMOVE,
        row_key="k-fail",
        basis="misread",
        value="16 barg",
        row_value="13 barg",
        reason="The row says MAWP 14 barg for P-101B but the page shows 16 barg.",
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    row = dict(
        FAIL_ROW,
        comment="SAES-X-100 cl. 4.2: requires MAWP not less than 20 barg. Datasheet p.1, MAWP states 13 barg.",
    )
    ctx = arp.Context(pages=PAGES, rows={"k-fail": row}, held=CTX.held)
    assert arp.verify(prop(**misread), ctx).accepted
    # the row's own figure (13) is not on the page there, so only a row that printed it can be a misread
    ctx_same = arp.Context(
        pages=PAGES, rows={"k-fail": FAIL_ROW}, held=CTX.held
    )  # the row printed 14, not 13
    assert reason_of(prop(**misread), ctx_same) == arp.Reason.FAIL_KEPT.value
    on_page = dict(misread, row_value="14 barg")  # 14 barg IS on the page: no misread
    assert reason_of(prop(**on_page), ctx_same) == arp.Reason.FAIL_KEPT.value


def test_a_fail_out_of_scope_is_removed_only_when_the_rulebook_says_so():
    scope = dict(
        TAG_REMOVE,
        row_key="k-fail",
        basis="out_of_scope",
        clause="4.2",
        standard="SAES-X-100",
        value=None,
        reason="The clause covers other equipment.",
        evidence=[],
    )
    assert reason_of(prop(**scope)) == arp.Reason.FAIL_KEPT.value
    ctx = arp.Context(
        pages=PAGES,
        rows=CTX.rows,
        held=CTX.held,
        out_of_scope=frozenset({("SAES-X-100", "4.2")}),
    )
    assert arp.verify(prop(**scope), ctx).accepted


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
            "tags": ["P-101A", "PSV-201"],
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


def _misread(**kw):
    base = dict(
        TAG_REMOVE,
        row_key="k-fail",
        basis="misread",
        value="14 barg",
        row_value="20 barg",
        reason="The row cites the wrong figure for P-101A.",
        evidence=[{"page": 1, "quote": "Tag P-101A  Design pressure 12 barg  MAWP 14 barg"}],
    )
    base.update(kw)
    return prop(**base)


@pytest.mark.parametrize("row_value", ["20 barg", "4.2", "1"])
def test_a_true_fail_is_not_removed_by_citing_the_requirement_or_a_clause_as_the_row_value(
    row_value,
):
    # The row printed 14 barg and the page says 14 barg: the Fail is right. 20 barg is the standard's figure, 4.2 a clause.
    assert reason_of(_misread(row_value=row_value)) == arp.Reason.FAIL_KEPT.value


def test_a_misread_needs_the_page_value_and_row_value_in_the_same_unit_and_not_already_in_the_row():
    row = dict(
        FAIL_ROW,
        comment="SAES-X-100 cl. 4.2: requires MAWP not less than 20 barg. Datasheet p.1, MAWP states 13 barg.",
    )
    ctx = arp.Context(pages=PAGES, rows={"k-fail": row}, held=CTX.held)
    good = _misread(
        value="16 barg",
        row_value="13 barg",
        evidence=[{"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}],
    )
    assert arp.verify(good, ctx).accepted
    assert (
        reason_of(dict(good, row_value="13 mm"), ctx) == arp.Reason.FAIL_KEPT.value
    )  # unit differs
    assert (
        reason_of(dict(good, row_value="20 barg"), ctx) == arp.Reason.FAIL_KEPT.value
    )  # the standard's figure
    # no evidence quote: nothing read ON the page backs the removal
    assert reason_of(dict(good, evidence=[]), ctx) in {
        arp.Reason.NO_BASIS.value,
        arp.Reason.FAIL_KEPT.value,
    }


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


def test_a_row_without_a_kind_is_read_as_a_fail_and_a_cased_kind_too():
    for kind in (None, "", "NON_COMPLIANT"):
        row = dict(REVIEW_ROW, row_kind=kind)
        ctx = arp.Context(pages=PAGES, rows={"k-rev": row}, held=CTX.held)
        remove = dict(
            TAG_REMOVE,
            row_key="k-rev",
            basis="context",
            evidence=[{"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}],
        )
        assert reason_of(prop(**remove), ctx) == arp.Reason.FAIL_KEPT.value


def test_understanding_is_one_page_and_not_trivial():
    ctx = arp.Context(pages=PAGES, rows={}, held={})
    one = {"type": "understanding", "confidence": "low", "understanding": {"tags": ["a"]}}
    assert not arp.verify(one, ctx).accepted
    across = {
        "type": "understanding",
        "confidence": "low",
        "understanding": {"service": ["MAWP 16 barg Relief valve PSV-201"]},
    }  # the end of page 1 and the start of page 2
    assert not arp.verify(across, ctx).accepted
    fine = {"type": "understanding", "confidence": "low", "understanding": {"fluids": ["amine"]}}
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
