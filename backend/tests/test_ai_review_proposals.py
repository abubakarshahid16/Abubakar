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
            type="reword",
            row_key="k-rev",
            text=good,
            page=1,
            clause=None,
            value=None,
            reason="Clearer wording for the engineer.",
        ),
        CTX,
    ).accepted
    bad = good.replace("16 barg", "18 barg")
    assert reason_of(
        prop(
            type="reword",
            row_key="k-rev",
            text=bad,
            page=1,
            clause=None,
            value=None,
            reason="Clearer wording for the engineer.",
        )
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
    # a verdict word in a flag's reason is allowed here: the evidence is verified (see the verdict tests below)
    assert arp.verify(_flag(reason="The row complies."), CTX).accepted
    assert reason_of(_flag(reason="The row complies.", evidence=[])) == (
        arp.Reason.PASS_FAIL_WORD.value
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


def test_a_plain_explanation_is_a_good_reason():
    assert arp.verify(
        _reword(reason="Names both tags and keeps the pressures, for clarity."), CTX
    ).accepted


@pytest.mark.parametrize(
    "reason",
    [
        "The limit is ninety nine barg.",
        "Allow one hundred barg.",
        "Use half of it.",
        "The limit is \uff19\uff19 barg.",  # fullwidth digits
        "The limit is \u0669\u0669 barg.",  # Arabic-Indic digits
        "Clause XCIX applies.",
        "The figure is 14 psi.",  # a changed unit on a barg row
        "Pressure in psi is meant.",
        "Allow n\u200bine\u200b barg",  # zero-width characters inside a number word
        "The \u0455et value is 1\u200b4.",
    ],
)
def test_a_reword_reason_holds_no_figure_in_any_spelling(reason):
    assert reason_of(_reword(reason=reason)) == arp.Reason.NUMBER_NOT_VERIFIED.value


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
def test_a_verified_page_quote_is_flagged_as_it_stands_verdict_words_and_all(quote):
    # the quote is the document's own, code-verified; the flag text is built by code around it
    pages = {1: f"Tag P-101B  {quote}"}
    ctx = arp.Context(pages=pages, rows=CTX.rows, held=CTX.held)
    flag = _flag(evidence=[{"page": 1, "quote": f"Tag P-101B  {quote}"}])
    assert arp.verify(flag, ctx).accepted


SPELLINGS_OF_A_NUMBER = [
    "x c i x", "V", "x-c-i-x", "n i n e", "n-i-n-e", "n.i.n.e", "n_i_n_e", "nin ety", "eig ht", "nine ty", "ninety nine", "one hundred",
    "ni\u0578e",  # Armenian letter that looks like n
    "n\u0561ne",  # an Armenian letter with no Latin twin: any leftover non-ASCII letter is refused
    "ni\u200bne", "\uff19\uff19", "\u0669\u0669", "XCIX", "14", "t w e l v e", "do zen",
]  # fmt: skip
SPELLINGS_OF_A_VERDICT = [
    "complies", "compl\u200biant", "c\u043emplies", "c o m p l i e s", "c-o-m-p-l-i-e-s", "p.a.s.s", "approved",
    "in-line with the standard", "in line with the standard", "acceptable", "fulfils", "conformant", "complying",
    "satisfactory", "passes", "meets", "not acceptable", "does not meet", "non-compliant", "rejected", "met",
    "in spec", "no issue", "all clear", "sound", "ready", "good", "fine",
]  # fmt: skip
ORDINARY_WORDS = [
    "done", "often", "component", "bypass", "complete", "content", "passage", "stone", "money", "tone", "compliment",
    "matched", "valid", "safe", "correct", "verified", "confirmed", "suitable",
]  # fmt: skip


@pytest.mark.parametrize("figure", SPELLINGS_OF_A_NUMBER)
def test_a_reword_reason_holds_no_figure_however_it_is_spelled(figure):
    got = reason_of(_reword(reason=f"The limit is {figure} for it."))
    assert got == arp.Reason.NUMBER_NOT_VERIFIED.value


@pytest.mark.parametrize("word", SPELLINGS_OF_A_VERDICT)
def test_a_reword_reason_with_no_evidence_holds_no_verdict_claim(word):
    got = reason_of(_reword(reason=f"Overall the wording {word} here."))
    assert got in {
        arp.Reason.NUMBER_NOT_VERIFIED.value,
        arp.Reason.PASS_FAIL_WORD.value,
    }


@pytest.mark.parametrize("word", ORDINARY_WORDS)
def test_ordinary_engineering_words_are_not_verdict_claims(word):
    assert arp.verify(
        _reword(reason=f"Overall the {word} wording is clearer."), CTX
    ).accepted


@pytest.mark.parametrize("word", SPELLINGS_OF_A_VERDICT)
def test_a_verdict_claim_is_allowed_with_verified_evidence(word):
    remove = dict(
        TAG_REMOVE,
        row_key="k-rev",
        basis="context",
        reason=f"Different tags: the row {word} for the other tag.",
        value="16 barg",
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    assert arp.verify(prop(**remove), CTX).accepted


def test_a_verdict_claim_is_refused_when_the_evidence_is_not_verified():
    remove = dict(
        TAG_REMOVE,
        row_key="k-rev",
        basis="context",
        reason="The row complies, so it goes.",
        evidence=[{"page": 1, "quote": "a quote that is on no page at all"}],
    )
    assert reason_of(prop(**remove)) == arp.Reason.PASS_FAIL_WORD.value
    short = dict(
        remove,
        evidence=[
            {"page": 2, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    assert (
        reason_of(prop(**short)) == arp.Reason.PASS_FAIL_WORD.value
    )  # a quote not on the cited page
    held = dict(
        remove,
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
        clause="9.9",
        standard="SAES-X-100",
    )
    assert (
        reason_of(prop(**held)) == arp.Reason.PASS_FAIL_WORD.value
    )  # a clause that was not read


@pytest.mark.parametrize("word", SPELLINGS_OF_A_VERDICT)
def test_a_verdict_claim_never_lets_the_ai_remove_a_fail_or_make_a_pass(word):
    remove = dict(
        TAG_REMOVE,
        row_key="k-fail",
        basis="context",
        reason=f"The row {word}.",
        evidence=[
            {"page": 1, "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg"}
        ],
    )
    assert reason_of(prop(**remove)) == arp.Reason.FAIL_KEPT.value
    added = arp.verify(prop(reason=f"Valve {word} for the set pressure."), CTX)
    assert not added.accepted or added.row_kind != "conforming"


def test_a_grouped_row_with_a_member_that_cannot_be_looked_up_is_not_removable():
    from app import crs_mapping

    def row(statuses):
        findings = [
            {
                "id": f"m{i}",
                "compliance_status": st,
                "severity": "minor",
                "origin": "review",
                "standard_name": "SPEC-X.pdf",
                "standard_clause": "5.1",
                "standard_page": 7,
                "requirement_source_text": "The pressure shall not exceed 10 barg.",
                "crs_field_label": "PRESSURE",
                "fact_id": "f",
                "equipment_tag": "V-1",
                "contractor_evidence_text": "12 barg",
                "contractor_page": 1,
            }
            for i, st in enumerate(statuses)
        ]
        [r] = crs_mapping.build_crs_rows(findings, [], "ds.pdf")
        return r, {f["id"]: f for f in findings}

    def remove(r):
        return dict(
            TAG_REMOVE,
            row_key=r["comment_key"],
            basis="context",
            evidence=[
                {
                    "page": 1,
                    "quote": "Tag P-101B  Design pressure 12 barg  MAWP 16 barg",
                }
            ],
        )

    r, stored = row(["NEEDS_ENGINEER_REVIEW", "NEEDS_ENGINEER_REVIEW"])
    if len(r["finding_ids"]) < 2:
        pytest.skip("the mapping did not group these findings")

    def ctx(row_):
        return arp.Context(pages=PAGES, rows={row_["comment_key"]: row_}, held=CTX.held)

    arp.carry_results([r], stored.get)
    assert arp.verify(
        prop(**remove(r)), ctx(r)
    ).accepted  # all members known and not Fails
    lost = dict(stored)
    del lost["m1"]  # one member cannot be looked up
    r2, _ = row(["NEEDS_ENGINEER_REVIEW", "NEEDS_ENGINEER_REVIEW"])
    arp.carry_results([r2], lost.get)
    assert r2["ai_review_unknown_member"] is True
    assert arp.verify(prop(**remove(r2)), ctx(r2)).reason == arp.Reason.FAIL_KEPT.value
    blank = dict(stored, m1={"compliance_status": ""})  # a member with no status
    r3, _ = row(["NEEDS_ENGINEER_REVIEW", "NEEDS_ENGINEER_REVIEW"])
    arp.carry_results([r3], blank.get)
    assert arp.verify(prop(**remove(r3)), ctx(r3)).reason == arp.Reason.FAIL_KEPT.value
    # findings behind the row but the results never carried into it: also not removable
    r4, _ = row(["NEEDS_ENGINEER_REVIEW", "NEEDS_ENGINEER_REVIEW"])
    assert arp.verify(prop(**remove(r4)), ctx(r4)).reason == arp.Reason.FAIL_KEPT.value
