# ruff: noqa: F401
"""K2 (order 13): the paper's noun in every review sentence, the plain "not checked" sentence, the CRS of a paper that is not a
datasheet (one label set, quality export, the held count) and the kind cues (old contract cues in the conflict check, list rows,
a transmittal's own number). INVENTED papers; no model, no network."""

from __future__ import annotations

import json

import pytest

from app import (
    access,
    comparison,
    crs_export_quality,
    db,
    kind_words,
    paper_kind,
    review_jobs,
    transmittal_check,
)
from app.config import settings
from tests import agent_review_support as s

BASE = {
    "basis": comparison.BASIS_REQUIRED_FIELDS,
    "fields_required": 0,
    "fields_answered": 0,
    "sufficient": False,
}
TECH = "not enough to recommend a code"


# ---------------------------------------------------------------- the noun, one home


@pytest.mark.parametrize(
    ("kind", "noun"),
    [("datasheet", "datasheet"), ("contract", "contract"), ("procedure", "procedure"), ("transmittal", "transmittal"),
     ("calculation", "calculation"), ("test_record", "test record"), ("other", "document"), (None, "document"), ("", "document")],
)  # fmt: skip
def test_the_noun_of_a_decided_kind(kind, noun):
    assert kind_words.noun_of_kind(kind) == noun


def test_a_datasheet_keeps_its_exact_old_sentences():
    full = {**BASE, "fields_required": 254, "fields_answered": 11}
    assert comparison.plain_reason(
        "Manual Review Required", TECH, full, None, []
    ).startswith(
        "Found 11 of the 254 datasheet values the applicable standards ask for."
    )
    assert (
        "No applicable standard asks this datasheet for a value that was checked."
        in comparison.plain_reason("Manual Review Required", TECH, BASE, None, [])
    )
    assert "asks this datasheet for a value" in comparison._insufficient_reason(BASE)
    assert comparison._standards_sentence(["X 1"], "so it was not checked.").startswith(
        "1 standard the datasheet cites is not"
    )


@pytest.mark.parametrize("noun", ["contract", "procedure", "transmittal"])
def test_no_sentence_of_the_review_calls_another_kind_a_datasheet(noun):
    """Through the two doors every stored or shown reason leaves by: the recommendation and the stored outcome."""
    comp = {**BASE, "paper_noun": noun, "fields_required": 12, "fields_answered": 3}
    zero = {**BASE, "paper_noun": noun}
    got = [
        comparison.recommend_code([], comp, missing_references=["IEC 1"]),
        comparison.recommend_code([], zero, missing_references=["IEC 1"]),
        comparison.recommend_code([], {**zero, "extraction_coverage": 0.1}),
    ]
    stored = [
        {"recommended_code": "Manual Review Required", "reason": TECH, "completeness": c, "missing_references": [{"identifier": "IEC 1"}]}
        for c in (comp, zero)
    ] + [
        {"recommended_code": "Manual Review Required", "reason": "Manual review: no requirement was evaluated", "completeness": zero},
        {"recommended_code": "Manual Review Required", "reason": "NOMINAL ESTIMATE", "completeness": {**comp, "fields_read": 4}},
    ]  # fmt: skip
    texts = [r[k] for r in got for k in ("reason", "details")] + [
        t for o in stored for t in comparison.plain_outcome(o) if t
    ]
    assert texts
    for text in texts:
        assert "datasheet" not in text.lower(), text
    assert any(noun in t for t in texts)


def test_a_review_that_checked_nothing_says_what_was_not_checked_and_why():
    comp = {
        **BASE,
        "paper_noun": "contract",
        "not_checked_plain": kind_words.not_checked_sentence("contract"),
    }
    text = comparison.plain_outcome(
        {"recommended_code": "Manual Review Required", "reason": TECH, "completeness": comp}
    )[0]
    assert text.startswith(
        "No contract checklist is held, so no point of this contract was checked;"
    )
    assert "does not mean the contract is acceptable" in text
    assert (
        kind_words.not_checked_sentence("datasheet") is None
        and kind_words.not_checked_sentence(None) is None
    )
    assert "library" in kind_words.not_checked_sentence("transmittal")
    assert "procedure" in kind_words.not_checked_sentence("procedure")


def _world(tmp_path, monkeypatch, text):
    s.setup_world(tmp_path, monkeypatch)
    conn = db.connect()
    s.add_document(conn, "doc_k2", "k2.pdf", text)
    conn.commit()
    return conn


def test_the_run_records_the_decided_noun_and_the_sentence_only_for_a_paper_that_is_not_a_datasheet(
    tmp_path, monkeypatch
):
    _world(
        tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1 Definitions"
    )
    comp = comparison.completeness_for_run(
        "doc_k2", allowed_document_ids=frozenset({"doc_k2"}), findings=[]
    )
    assert (
        comp["paper_noun"] == "contract"
        and "No contract checklist is held" in comp["not_checked_plain"]
    )
    s.add_document(db.connect(), "doc_ds", "ds.pdf", "PUMP DATA SHEET\nflow 10 m3/h")
    db.connect().commit()
    comp2 = comparison.completeness_for_run(
        "doc_ds", allowed_document_ids=frozenset({"doc_ds"}), findings=[]
    )
    assert (
        "paper_noun" not in comp2 and "not_checked_plain" not in comp2
    )  # a datasheet's record is unchanged


def test_the_progress_words_use_the_decided_kind(tmp_path, monkeypatch):
    _world(
        tmp_path, monkeypatch, "DOCUMENT TRANSMITTAL No. TR-9\nDocuments listed below"
    )
    noun, _unit = review_jobs.document_words("doc_k2")
    assert (
        noun == "transmittal"
        and review_jobs.step_label(0, (noun, "page")) == "reading the transmittal"
    )


# ---------------------------------------------------------------- the CRS of a paper that is not a datasheet


def test_the_crs_meta_of_a_contract_says_not_checked_and_counts_the_held_findings(
    tmp_path, monkeypatch
):
    _world(tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1")
    out = {"completeness": {"fields_required": 0}}
    findings = [{"compliance_status": "NEEDS_ENGINEER_REVIEW"}] * 3 + [
        {"compliance_status": "OK"}
    ]
    got = kind_words.crs_meta(
        {"review_notes": [{"note": "x"}]}, "doc_k2", out, findings, [{}, {}]
    )
    notes = {n["note"]: n for n in got["review_notes"]}
    assert "No contract checklist is held" in notes["Not checked"]["detail"]
    assert notes["Findings held for an engineer"]["count"] == 3
    assert (
        "this CRS has 2 rows" in notes["Findings held for an engineer"]["detail"]
        and "this run's own findings"
        in notes["Findings held for an engineer"]["detail"]
    )
    assert got["export_quality"] is True


def test_the_crs_meta_of_a_datasheet_is_the_same_object(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, "PUMP DATA SHEET\nflow")
    meta = {"review_notes": []}
    assert (
        kind_words.crs_meta(
            meta, "doc_k2", {}, [{"compliance_status": "NEEDS_ENGINEER_REVIEW"}], []
        )
        is meta
    )


def test_one_label_set_rewrites_the_ai_draft_labels_and_nothing_else():
    rows = [
        {"comment_by": "AI Review"}, {"comment_by": "AI - engineer to confirm"},
        {"comment_by": "AI clause review - engineer to confirm"}, {"comment_by": "Playbook check (draft)"},
        {"comment_by": "Confirmed by Ann"}, {"comment_by": ""},
    ]  # fmt: skip
    crs_export_quality.one_label_set(rows)
    assert [r["comment_by"] for r in rows] == [
        crs_export_quality.AI_DRAFT_LABEL
    ] * 3 + ["Playbook check (draft)", "Confirmed by Ann", ""]


# ---------------------------------------------------------------- the kind cues


def _kind(*lines):
    return paper_kind.decide_paper_kind([{"page_no": 1, "text": "\n".join(lines)}])


def test_the_old_contract_cues_count_in_the_conflict_check():
    for cue in ('Schedule "Q"', "GENERAL CONDITIONS OF CONTRACT", "Supply Agreement"):
        got = _kind(cue, "Pump Data Sheet")
        assert (got.paper_kind, got.guess, got.method) == (
            "datasheet",
            True,
            "cues_conflict",
        ), cue
        assert got.candidates == ("contract", "datasheet")


def test_the_list_rows_of_a_transmittal_never_override_its_heading():
    got = _kind(
        "DOCUMENT TRANSMITTAL No. TR-9",
        "1  ABC-100-001  Rev A  datasheet",
        "2  ABC-100-002  Rev B  calculation",
    )
    assert (got.paper_kind, got.method) == ("transmittal", "title_cue")
    assert (
        _kind("HAZOP STUDY PROCEDURE", "Pump data sheet reference").paper_kind
        == "procedure"
    )


def test_a_list_row_is_not_a_heading_even_without_a_strong_first_line():
    got = _kind(
        "Scope of supply", "1  Pump data sheet", "2  Relief valve sizing calculation"
    )
    assert got.method != "cues_conflict"


def test_a_transmittal_does_not_list_its_own_number(tmp_path, monkeypatch):
    conn = _world(
        tmp_path,
        monkeypatch,
        "DOCUMENT TRANSMITTAL No. INV-TR-0001\n1  ABC-100-001  Rev A  for review\n",
    )
    conn.execute(
        "INSERT INTO document_classification (document_id, document_number, revision, suggested_by) VALUES ('d_a','ABC-100-001','A','t')"
    ) if False else None
    got = transmittal_check.check(conn, "doc_k2", frozenset({"doc_k2"}))
    assert [r["number"] for r in got["rows"]] == [
        "ABC-100-001"
    ]  # the transmittal's own number is not a document


# ---------------------------------------------------------------- the label set reaches the CRS the engineer reads


def test_the_exported_crs_view_carries_one_label_set_with_the_quality_export_on():
    from app import crs_export

    def row(by, ref):
        return {
            "document_name": "P-1.pdf", "page_section": "p.2", "comment": f"A problem {ref}.", "comment_by": by,
            "standard_reference": f"STD-1 {ref}", "row_kind": "datasheet_check", "engineer_confirmed": False,
            "priority": 3, "reasoning": "",
        }  # fmt: skip

    meta = {"review_run_id": "run-k2", "export_quality": True, "copy": "internal"}
    rows = [
        row("AI Review", "1"),
        row("AI - engineer to confirm", "2"),
        row("AI clause review - engineer to confirm", "3"),
        row("Playbook check (draft)", "4"),
    ]
    view = crs_export.build_crs_view(rows, meta)
    assert sorted({r["comment_by"] for r in view["rows"]}) == [
        "AI reviewer - engineer to confirm",
        "Playbook check (draft)",
    ]
    off = crs_export.build_crs_view(rows, {**meta, "export_quality": False})
    assert {r["comment_by"] for r in off["rows"]} >= {
        "AI Review",
        "AI clause review - engineer to confirm",
    }  # unchanged when off
