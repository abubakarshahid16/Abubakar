"""Order 14 lane E: `document_kind.classify_contract`: the contract kind stored for a document of any role, only when the
general decision says contract. Invented covers."""

from __future__ import annotations

import pytest

from app import db, doc_router, document_kind
from app.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


SCHEDULE_COVER = 'ACME PLANT PROJECT\nCONTRACT No. ZZ-001\nSCHEDULE "W"\nGeneral Terms\nPage 1 of 9\n1. DEFINITIONS'
DATASHEET_COVER = (
    "ACME PLANT PROJECT\nCONTRACT No. ZZ-001\nPUMP DATA SHEET\n1 Rated flow 100 m3/h"
)


def _doc(doc_id, text, role=None, kind=None, state=None):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (doc_id, f"{doc_id}.pdf", doc_id, 1, "x", "ready", "2026-11-01"),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,?,0)",
            (doc_id, text, len(text)),
        )
        if role:
            conn.execute(
                "INSERT INTO document_classification (document_id, suggested_by, document_role) VALUES (?,?,?)",
                (doc_id, "t", role),
            )
        if state:
            conn.execute(
                "INSERT INTO document_kinds (document_id, kind, state, evidence, router_version, routed_at)"
                " VALUES (?,?,?,?,?,?)",
                (doc_id, kind, state, "{}", "1", "2026-11-01"),
            )


def test_a_contract_part_with_no_role_is_stored_as_a_suggested_contract():
    _doc("d1", SCHEDULE_COVER, state=doc_router.STATE_NEEDS_ENGINEER)
    assert document_kind.classify_contract("d1").kind == "contract"
    assert document_kind.stored_kind("d1") == ("contract", doc_router.STATE_SUGGESTED)


def test_a_paper_the_decision_does_not_call_a_contract_keeps_what_it_has():
    _doc(
        "d2",
        DATASHEET_COVER,
        role="CONTRACTOR_SUBMITTAL",
        kind="datasheet",
        state=doc_router.STATE_SUGGESTED,
    )
    assert (
        document_kind.classify_contract("d2") is None
    )  # a 'Contract No.' header line is not a contract
    assert document_kind.stored_kind("d2") == ("datasheet", doc_router.STATE_SUGGESTED)


def test_a_confirmed_kind_and_the_switch_off_write_nothing(monkeypatch):
    _doc("d3", SCHEDULE_COVER, kind="procedure", state=doc_router.STATE_CONFIRMED)
    assert document_kind.classify_contract("d3") is None
    assert document_kind.stored_kind("d3") == ("procedure", doc_router.STATE_CONFIRMED)
    _doc("d4", SCHEDULE_COVER)
    monkeypatch.setattr(settings, "document_kind_enabled", False)
    assert (
        document_kind.classify_contract("d4") is None
        and document_kind.stored_kind("d4") is None
    )


def _script():
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "e14_contract_role", repo / "scripts" / "e14_contract_role.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["e14_contract_role"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_the_live_step_refuses_without_the_owners_yes_and_its_undo_puts_everything_back(
    tmp_path, monkeypatch
):
    from app import live_guard

    script = _script()
    _doc("d1", SCHEDULE_COVER, state=doc_router.STATE_NEEDS_ENGINEER)
    _doc("d2", DATASHEET_COVER, kind="datasheet", state=doc_router.STATE_SUGGESTED)
    ids = tmp_path / "ids.txt"
    ids.write_text("d1\nd2\n")
    dbfile = settings.db_path
    monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: True)
    for extra in ([], ["--live"]):
        with pytest.raises(SystemExit, match="owner-yes"):
            script.main(
                [
                    "--db",
                    str(dbfile),
                    "--docs",
                    str(ids),
                    "--out",
                    str(tmp_path / "m.json"),
                    *extra,
                ]
            )
    monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: False)
    out = tmp_path / "m.json"
    assert (
        script.main(["--db", str(dbfile), "--docs", str(ids), "--out", str(out)]) == 0
    )
    db.reset_connection()
    assert document_kind.stored_kind("d1") == ("contract", doc_router.STATE_SUGGESTED)
    assert document_kind.stored_kind("d2") == (
        "datasheet",
        doc_router.STATE_SUGGESTED,
    )  # not a contract: kept
    role = (
        db.connect()
        .execute(
            "SELECT document_role FROM document_classification WHERE document_id='d2'"
        )
        .fetchone()[0]
    )
    assert role == "CONTRACT_DOCUMENT"
    assert script.main(["--db", str(dbfile), "--undo", str(out)]) == 0
    db.reset_connection()
    assert document_kind.stored_kind("d1") == (None, doc_router.STATE_NEEDS_ENGINEER)
    assert (
        db.connect()
        .execute(
            "SELECT document_role FROM document_classification WHERE document_id='d2'"
        )
        .fetchone()[0]
        is None
    )
