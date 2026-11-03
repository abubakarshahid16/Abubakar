"""Lane 6: the AI-created Pass (`ai_pass_verifier`), through the real entry points: `ai_review_proposals.verify`, the runner
and the internal CRS view. Invented documents and clauses only; no model is called.

A Pass is accepted only with: the switch on, a document quote on the cited page, a clause quote in the stored clause text,
the scope confirmed, the figure compared by code, no Fail or second value on the sheet, and a second reading that agrees.
"""

from __future__ import annotations

import pytest

from app import ai_pass_verifier as apv
from app import ai_review_pass as arpass
from app import ai_review_proposals as arp
from app import crs_ai_review_view as view
from app.config import settings
from tests.test_ai_review_pass import Stub

DOC = {
    1: "Vessel V-9901 data\nHydrotest pressure 12 bar\nDrawing language English",
    2: "Notes page\nRelief valve PSV-9902",
}
CLAUSES = {
    (
        "SAES-X-100.pdf",
        "6.1",
    ): "The hydrotest pressure shall be not less than 10 bar for vessels in sour service.",
    (
        "SAES-X-100.pdf",
        "7.2",
    ): "The drawing language shall be English.",
}
HELD = {"SAES-X-100.pdf": ["6.1", "7.2"]}
FAIL_ROW = {
    "row_kind": "non_compliant",
    "crs_row_key": "k-fail",
    "page_section": "p.2 - Relief capacity",
    "comment": "Relief capacity states 10 bar; requires 12 bar.",
    "standard_reference": "SAES-X-100 cl. 5.1",
}


def ctx(pages=None, rows=None, clauses=None):
    return arp.Context(
        pages=pages or DOC,
        rows=rows or {},
        held=HELD,
        clause_text=CLAUSES if clauses is None else clauses,
        reading_ids=frozenset({"c1", "c2"}),
    )


def good(**kw):
    quote = "Hydrotest pressure 12 bar"
    base = {
        "id": "pp1",
        "type": "pass",
        "page": 1,
        "field": "Hydrotest pressure",
        "standard": "SAES-X-100",
        "clause": "6.1",
        "clause_quote": "not less than 10 bar",
        "scope_applies": "yes",
        "scope_quote": "for vessels in sour service",
        "call_id": "c1",
        "reason": "Both quotes are on the pages.",
        "confidence": "medium",
        "evidence": [{"page": 1, "quote": quote}],
    }
    base.update(kw)
    base["second"] = kw.get(
        "second",
        {
            "field": base["field"],
            "page": base["page"],
            "standard": base["standard"],
            "clause": base["clause"],
            "call_id": "c2",
            "doc_quote": (base["evidence"] or [{}])[0].get("quote"),
            "clause_quote": base["clause_quote"],
            "scope_applies": "yes",
        },
    )
    return base


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_pass_enabled", True)


def reason_of(proposal, context=None):
    verdict = arp.verify(proposal, context or ctx())
    return None if verdict.accepted else verdict.reason


def test_it_is_off_by_default(monkeypatch):
    assert settings.ai_review_pass_enabled is False
    assert reason_of(good()) == apv.PassReason.SWITCH_OFF


def test_a_pass_with_every_check_is_accepted_and_says_what_it_compared(on):
    verdict = arp.verify(good(), ctx())
    assert verdict.accepted and verdict.row_kind == apv.PASS_ROW_KIND
    assert verdict.final_text == (
        "Hydrotest pressure: the submittal states 12 bar and the clause requires >= 10 bar."
    )


def test_5_bar_against_not_less_than_10_bar_is_not_a_pass(on):
    pages = {1: "Vessel data\nHydrotest pressure 5 bar"}
    p = good(evidence=[{"page": 1, "quote": "Hydrotest pressure 5 bar"}])
    assert reason_of(p, ctx(pages)) == apv.PassReason.NOT_SATISFIED


def test_a_unit_that_cannot_be_compared_is_not_a_pass(on):
    pages = {1: "Vessel data\nHydrotest pressure 12 mm"}
    p = good(evidence=[{"page": 1, "quote": "Hydrotest pressure 12 mm"}])
    assert reason_of(p, ctx(pages)) == apv.PassReason.NOT_COMPARABLE


def test_a_unit_in_another_unit_of_the_same_quantity_is_converted_by_code(on):
    pages = {1: "Vessel data\nHydrotest pressure 1500 kPa"}
    p = good(evidence=[{"page": 1, "quote": "Hydrotest pressure 1500 kPa"}])
    assert arp.verify(p, ctx(pages)).accepted  # 1500 kPa is 15 bar
    pages = {1: "Vessel data\nHydrotest pressure 500 kPa"}
    p = good(evidence=[{"page": 1, "quote": "Hydrotest pressure 500 kPa"}])
    assert reason_of(p, ctx(pages)) == apv.PassReason.NOT_SATISFIED


def test_two_figures_in_the_document_quote_are_not_a_pass(on):
    pages = {1: "Hydrotest pressure 12 bar Design pressure 14 bar"}
    p = good(
        evidence=[
            {"page": 1, "quote": "Hydrotest pressure 12 bar Design pressure 14 bar"}
        ]
    )
    assert reason_of(p, ctx(pages)) == apv.PassReason.NO_FIGURE


def test_a_quote_from_the_wrong_page_is_not_a_pass(on):
    p = good(page=2, evidence=[{"page": 2, "quote": "Hydrotest pressure 12 bar"}])
    assert reason_of(p) == apv.PassReason.NO_DOC_QUOTE
    p = good(evidence=[{"page": 2, "quote": "Hydrotest pressure 12 bar"}])
    assert (
        reason_of(p) == apv.PassReason.NO_DOC_QUOTE
    )  # the quote names a page other than the cited one


def test_a_clause_quote_that_is_not_in_the_stored_text_is_not_a_pass(on):
    assert (
        reason_of(good(clause_quote="not less than 8 bar"))
        == apv.PassReason.CLAUSE_QUOTE
    )
    assert reason_of(good(clause="9.9")) == apv.PassReason.NO_CLAUSE
    assert reason_of(good(), ctx(clauses={})) == apv.PassReason.NO_CLAUSE


def test_a_scope_that_is_unsure_or_not_shown_is_not_a_pass(on):
    for answer in ("unsure", "no", "", None):
        assert reason_of(good(scope_applies=answer)) == apv.PassReason.SCOPE
    # the clause has a condition ("for vessels in sour service"): it must be shown as a quote of the stored text
    assert reason_of(good(scope_quote="")) == apv.PassReason.SCOPE
    assert (
        reason_of(good(scope_quote="for vessels in sweet service"))
        == apv.PassReason.SCOPE
    )


def test_a_fail_on_the_sheet_for_the_same_field_blocks_the_pass(on):
    fail = dict(
        FAIL_ROW,
        page_section="p.1 - Hydrotest pressure",
        comment="Hydrotest pressure states 8 bar; requires 10 bar.",
    )
    assert reason_of(good(), ctx(rows={"k-fail": fail})) == apv.PassReason.FAIL_PRESENT
    other = dict(FAIL_ROW)  # a Fail about another field does not
    assert arp.verify(good(), ctx(rows={"k-fail": other})).accepted


def test_two_values_for_the_field_in_the_document_block_the_pass(on):
    pages = dict(DOC)
    pages[2] = "Notes page\nHydrotest pressure 8 bar"
    assert reason_of(good(), ctx(pages)) == apv.PassReason.CONFLICT


def test_a_second_reading_that_disagrees_or_is_missing_is_not_a_pass(on):
    bad = good()
    bad["second"] = dict(bad["second"], clause="7.2")
    assert reason_of(bad) == apv.PassReason.READINGS
    bad["second"] = dict(good()["second"], scope_applies="unsure")
    assert reason_of(bad) == apv.PassReason.READINGS
    missing = good()
    del missing["second"]
    assert reason_of(missing) == apv.PassReason.READINGS


@pytest.mark.parametrize(
    "tail", ["unless stated", "not applicable", "no deviation", "without change"]
)
def test_silence_and_negation_in_the_document_quote_are_never_a_pass(on, tail):
    quote = f"Hydrotest pressure 12 bar {tail}"
    pages = {1: quote}
    assert reason_of(good(evidence=[{"page": 1, "quote": quote}]), ctx(pages)) in {
        apv.PassReason.NEGATION,
        apv.PassReason.UNREADABLE,
        apv.PassReason.PLACEHOLDER,
    }


def _term(**kw):
    base = good(
        field="Drawing language",
        clause="7.2",
        clause_quote="shall be English",
        scope_quote="for all drawings",
        evidence=[{"page": 1, "quote": "Drawing language English"}],
    )
    base.update(kw)
    return base


def test_a_requirement_with_no_figure_reads_its_term_from_the_clause_by_code(on):
    assert arp.verify(_term(), ctx()).accepted
    # the AI's own required_term is never used: a wrong one changes nothing, a right one does not rescue a wrong value
    assert arp.verify(_term(required_term="Arabic"), ctx()).accepted
    pages = {1: "Drawing language Arabic"}
    p = _term(
        evidence=[{"page": 1, "quote": "Drawing language Arabic"}],
        required_term="Arabic",
    )
    p["second"] = dict(p["second"], doc_quote="Drawing language Arabic")
    assert reason_of(p, ctx(pages)) == apv.PassReason.NO_TERM


def test_the_other_checks_still_apply_to_a_pass(on):
    assert reason_of(good(confidence="high")) == arp.Reason.BAD_CONFIDENCE.value
    assert reason_of(good(evidence=[])) == apv.PassReason.NO_DOC_QUOTE


def test_a_pass_never_removes_a_fail_or_changes_a_row(on):
    rows = {"k-fail": dict(FAIL_ROW)}
    before = {k: dict(v) for k, v in rows.items()}
    arp.verify(good(), ctx(rows=rows))
    assert rows == before
    remove = {
        "id": "x",
        "type": "remove",
        "row_key": "k-fail",
        "page": 1,
        "basis": "context",
        "value": "12 bar",
        "reason": "Hydrotest pressure complies with the clause.",
        "confidence": "medium",
        "evidence": [{"page": 1, "quote": "Hydrotest pressure 12 bar"}],
    }
    got = arp.verify(remove, ctx(rows=rows))
    assert not got.accepted and got.reason == arp.Reason.FAIL_KEPT.value


def test_the_runner_stores_the_pass_and_the_internal_copy_says_how_it_was_decided(
    on, monkeypatch
):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    stub = Stub([good()])
    summary = arpass.run(
        "rv-pass",
        [],
        pages=DOC,
        held=HELD,
        provider=stub,
        clause_text=CLAUSES,
        reading_ids={"c1", "c2"},
    )
    assert summary["accepted"]["pass"] == 1
    rows: list[dict] = []
    view.apply(rows, "rv-pass")
    [row] = rows
    assert row["row_kind"] == apv.PASS_ROW_KIND and row["engineer_confirmed"] is False
    assert row["ai_review_comment"].startswith(
        "Pass, decided by AI judgement with verified quotes. "
    )
    assert row["comment"] == row["ai_comment"]  # the plain statement
    assert (
        row["ai_comment"]
        == "Hydrotest pressure: the submittal states 12 bar and the clause requires >= 10 bar."
    )


def test_with_the_switch_off_the_runner_stores_nothing(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    summary = arpass.run(
        "rv-off", [], pages=DOC, held=HELD, provider=Stub([good()]), clause_text=CLAUSES
    )
    assert summary["accepted"]["pass"] == 0
    assert summary["refused"].get(apv.PassReason.SWITCH_OFF) == 1
    rows: list[dict] = []
    view.apply(rows, "rv-off")
    assert rows == []


def test_the_contractor_copy_never_carries_an_unconfirmed_ai_pass(on, monkeypatch):
    from app import crs_export

    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(
        "rv-x",
        [],
        pages=DOC,
        held=HELD,
        provider=Stub([good()]),
        clause_text=CLAUSES,
        reading_ids={"c1", "c2"},
    )
    rows: list[dict] = []
    view.apply(rows, "rv-x")
    [row] = rows
    internal = crs_export.build_crs_view([row], {"copy": "internal"})["rows"]
    issue = crs_export.build_crs_view([row], {"copy": "issue"})["rows"]
    assert any(apv.INTERNAL_LABEL in r["ai_review_comment"] for r in internal)
    assert issue == []  # not confirmed, so the contractor copy does not carry it
    # once an engineer confirms it, the contractor copy shows the plain statement and never the internal wording
    confirmed = dict(row, engineer_confirmed=True)
    shown = crs_export.build_crs_view([confirmed], {"copy": "issue"})["rows"]
    assert shown and "Pass, decided" not in str(shown)


def test_a_quote_that_stands_on_another_page_than_the_cited_one_is_not_a_pass(on):
    pages = dict(DOC)
    pages[2] = (
        "Notes page\nHydrotest pressure 12 bar"  # the same quote stands on page 2 too
    )
    p = good(
        evidence=[{"page": 2, "quote": "Hydrotest pressure 12 bar"}]
    )  # but page 1 is cited
    assert reason_of(p, ctx(pages)) == apv.PassReason.NO_DOC_QUOTE
