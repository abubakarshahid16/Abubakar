"""#479 (E06): a READY hook that fails is RECORDED as a visible `jobs` row, never raised into
ingestion and never dropped, and the document stays READY.

`test_195_role_after_ready.py` pins the equipment-type hook; the other two hooks that write a
`failed` row had no failure test. Each is driven here with an invented document and a hook body
that raises: the row names the stage and a code, nothing is raised into ingestion and the document
stays READY.
"""

from __future__ import annotations

import pytest

from app import classification, db, ingest, submittal_fill, submittal_review
from app.config import settings
from app.db import connect


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _ready_document() -> str:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES ('d1', 'sheet.pdf', 'sha-d1', 1, '/nowhere', 'ready', '2026-01-01')"
        )
    return "d1"


def _boom(*_a, **_k):
    raise RuntimeError("hook down")


def _failed_rows(stage: str) -> list[dict]:
    rows = connect().execute(
        "SELECT * FROM jobs WHERE document_id = 'd1' AND stage = ? AND state = 'failed'",
        (stage,),
    )
    return [dict(r) for r in rows]


def _status() -> str:
    return (
        connect().execute("SELECT status FROM documents WHERE id = 'd1'").fetchone()[0]
    )


def _run_extract_facts(monkeypatch) -> None:
    monkeypatch.setattr(
        classification,
        "of_document",
        lambda _d: {"document_role": "CONTRACTOR_SUBMITTAL"},
    )
    monkeypatch.setattr(submittal_review, "ensure_facts_extracted", _boom)
    ingest._extract_facts_if_contractor_submittal("d1")


def _run_metadata(monkeypatch) -> None:
    monkeypatch.setattr(submittal_fill, "classify", _boom)
    ingest._classify_metadata_if_contractor_submittal("d1")


def _run_equipment_type(monkeypatch) -> None:
    monkeypatch.setattr(classification, "classify_equipment_type_for_submittal", _boom)
    ingest._classify_equipment_type_if_contractor_submittal("d1")


HOOKS = [
    ("extract_facts", _run_extract_facts),
    ("submittal_metadata_classify", _run_metadata),
    ("equipment_type_classify", _run_equipment_type),
]


@pytest.mark.parametrize(("stage", "run"), HOOKS, ids=[h[0] for h in HOOKS])
def test_a_failing_ready_hook_is_recorded_not_raised(stage, run, monkeypatch):
    _ready_document()
    run(monkeypatch)  # must not raise
    rows = _failed_rows(stage)
    assert len(rows) == 1, "the failure is one visible jobs row"
    assert rows[0]["error_code"]
    assert _status() == "ready", "a failed hook never un-ingests the document"


@pytest.mark.parametrize(("stage", "run"), HOOKS, ids=[h[0] for h in HOOKS])
def test_a_hook_that_works_records_nothing(stage, run, monkeypatch):
    _ready_document()
    monkeypatch.setattr(
        classification,
        "of_document",
        lambda _d: {"document_role": "CONTRACTOR_SUBMITTAL"},
    )
    monkeypatch.setattr(
        submittal_review, "ensure_facts_extracted", lambda *a, **k: None
    )
    monkeypatch.setattr(submittal_fill, "classify", lambda *a, **k: None)
    monkeypatch.setattr(
        classification, "classify_equipment_type_for_submittal", lambda *a, **k: None
    )
    hook = {
        "extract_facts": ingest._extract_facts_if_contractor_submittal,
        "submittal_metadata_classify": ingest._classify_metadata_if_contractor_submittal,
        "equipment_type_classify": ingest._classify_equipment_type_if_contractor_submittal,
    }[stage]
    hook("d1")
    assert _failed_rows(stage) == []
