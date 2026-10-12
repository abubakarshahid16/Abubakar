"""End-to-end CRS quality test: the real pipeline against `crs_planted_defects`
(synthetic standards + datasheets, made-up values only - CLAUDE.md rule 3).

CRS quick wins (2026-09-27). Rebuilt from the CRS audit's own harness
(`/tmp/claude-0/audit/crs/run_e2e.py`): upload -> classify -> ingest (real
extract/chunk/embed) -> requirement extraction -> facts -> applicability ->
comparison -> crs_mapping -> crs_export, scored against the audit's gold
issue list (`crs_planted_defects.score`).

The audit's own baseline, judged the same way, on the same documents: issue
recall 4/19 = 21%, row precision 4/7 = 57%. THE MUTATION TARGET of this
file is every fix behind that baseline at once - it is not itself a unit for
any one of them (see `test_crs_mapping.py`, `test_field_links.py`,
`test_blank_markers.py`, `test_datasheets.py` for those). It needs the
embedding model, so it is the one test in this module that loads it, and it
is skipped outright when the model directory is not present.

RESOURCE NOTE: one ingest + one comparison run per datasheet, e5-small only
(no OCR, no reranker, no AI/web checks) - run alone, not batched with other
model-loading tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import crs_planted_defects as gold  # noqa: E402

from app.config import settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (Path(__file__).parents[1] / "models" / "e5-small").exists(),
    reason="backend/models/e5-small not present - symlink it to run this test")


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    from app import db, submittal_review, keyword, standards, datasheets as ds_mod, page_ledger

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "crs_gold.sqlite")
    monkeypatch.setattr(settings, "embed_model_dir", Path(__file__).parents[1] / "models" / "e5-small")
    monkeypatch.setattr(settings, "watch_folder", "")
    if hasattr(settings, "applicability_taxonomy_path"):
        monkeypatch.setattr(settings, "applicability_taxonomy_path", None)
    db.reset_connection(); db.init_db()
    submittal_review.ensure_schema(); submittal_review.migrate_facts_to_per_document()
    keyword.ensure_schema()
    for mod in (standards, ds_mod, page_ledger):
        fn = getattr(mod, "ensure_schema", None)
        if fn:
            fn()
    yield tmp_path
    db.reset_connection()


def _run(tmp_path):
    from app import (classification, comparison, crs_export, crs_mapping,
                     datasheets, db, ingest, standards, submittal_review, upload)

    docs = tmp_path / "docs"
    docs.mkdir()
    for name, (builder, _role) in gold.DOCUMENTS.items():
        builder(str(docs / name))

    ids: dict[str, str] = {}
    worker = ingest.IngestionWorker()
    for name, (_builder, role) in gold.DOCUMENTS.items():
        with open(docs / name, "rb") as fh:
            row, _job, _dup = upload.ingest(fh, name)
        ids[name] = row["id"]
        classification.set_role(row["id"], role)
        worker.process(row["id"])

    while True:
        job = standards.next_extraction_job("w1")
        if not job:
            break
        standards.run_extraction_job(job, "w1")

    scope = frozenset(ids.values())
    names = {v: k for k, v in ids.items()}
    rows_by_sheet: dict[str, list[dict]] = {}
    for name in ("DS-V-2001.pdf", "DS-P-101.pdf"):
        sub = ids[name]
        run_id = submittal_review.create_review_run(
            submittal_document_id=sub, allowed_document_ids=scope)
        submittal_review.ensure_facts_extracted(sub, scope, review_run_id=run_id)
        from app import applicability
        sel = applicability.select(sub, allowed_document_ids=scope,
                                   review_run_id=run_id, persist=True)
        res = comparison.run_comparison(
            run_id, allowed_document_ids=scope,
            reference_coverage=sel.get("reference_coverage"),
            missing_references=[m["identifier"] for m in sel["missing_references"]])
        findings = submittal_review.list_run_findings(run_id, allowed_document_ids=scope)
        for f in findings:
            f["standard_name"] = names.get(f.get("standard_document_id"))
        rows = crs_mapping.build_crs_rows(
            findings, [m["identifier"] for m in sel["missing_references"]], name,
            unread_pages=(res.get("page_coverage") or {}).get("pages_not_read_into_fields"))
        meta = {"document_title": name, "review_run_id": run_id}
        view = crs_export.build_crs_view(rows, meta)
        rows_by_sheet[name] = view["rows"]
    return rows_by_sheet


def test_crs_rows_recall_and_precision_beat_the_audit_baseline(pipeline):
    """The audit's own hand-judged baseline on these documents: issue recall
    4/19 = 21%, row precision 4/7 = 57%. The quick wins (itemised blanks,
    field synonyms, categorical comparison, engineer-voice comment) must
    measurably beat both - printed so a human can read the before/after."""
    rows_by_sheet = _run(pipeline)
    result = gold.score(rows_by_sheet)
    print("\nCRS quality (this run) vs audit baseline (recall 0.21, precision 0.57):")
    print(f"  recall    {result['recall']} ({result['issues_found']}/{result['issues_total']})")
    print(f"  precision {result['precision']} ({result['correct_rows']}/{result['rows_total']})")
    for sheet, detail in result["sheets"].items():
        print(f"  {sheet}: found {detail['found']}")
        print(f"  {sheet}: missed {detail['missed']}")
    assert result["recall"] is not None and result["recall"] > 0.21, (
        f"recall regressed to {result['recall']} (audit baseline 0.21): {result}")
    assert result["precision"] is not None and result["precision"] >= 0.57, (
        f"precision regressed to {result['precision']} (audit baseline 0.57): {result}")
