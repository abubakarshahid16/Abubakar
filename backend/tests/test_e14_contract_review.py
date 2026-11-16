"""Order 14 lane E: the contract-review wrapper's dry-run parts (no app started, no network, invented data)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
_SPEC = importlib.util.spec_from_file_location(
    "e14_contract_review", REPO / "scripts" / "e14_contract_review.py"
)
w = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(w)  # type: ignore[union-attr]


def test_the_stub_keeps_every_body_and_answers_nothing(tmp_path):
    stub = w.StubSender(tmp_path)
    reply = stub(
        "https://example.invalid/v1/messages",
        headers={},
        body={"messages": [{"x": "MARK1"}]},
        timeout=1,
    )
    assert json.loads(reply["content"][0]["text"]) == {} and stub.calls == 1
    assert w.marker_counts(tmp_path, {"d1": "MARK1", "d2": "MARK2"}) == {
        "d1": 1,
        "d2": 0,
    }


def test_the_dry_run_blocks_every_send_of_the_reader_transport(tmp_path, monkeypatch):
    from app import reader_transport as rt

    for name in ("transport", "stream", "list_models", "_gated", "batch_create", "batch_retrieve", "batch_cancel",
                 "batch_results", "httpx"):  # fmt: skip
        monkeypatch.setattr(rt, name, getattr(rt, name))  # restored after the test
    stub = w.StubSender(tmp_path)
    w._block_every_send(stub)
    assert rt.transport() is stub
    for name in ("stream", "list_models", "_gated", "batch_create"):
        try:
            getattr(rt, name)("https://example.invalid", headers={}, timeout=1)
        except RuntimeError as exc:
            assert "no network" in str(exc)
        else:
            raise AssertionError(name)
    try:
        rt.httpx.Client()
    except RuntimeError as exc:
        assert "no network" in str(exc)
    else:
        raise AssertionError("httpx.Client")


def test_the_plan_and_the_start_carry_the_project_papers(tmp_path, monkeypatch):
    seen = []

    def fake_call(self, method, path, body=None, timeout=120.0):
        seen.append((method, path, body))
        return 200, b'{"documents": {"leaving": []}}'

    monkeypatch.setattr(w.trial.Http, "call", fake_call)
    call = w._with_projects(["doc_p1", "doc_p2"], tmp_path)
    call(None, "GET", "/api/reviews/plan?submittal_document_id=x&engine=claude")
    call(None, "POST", "/api/reviews/start", {"submittal_document_id": "x"})
    assert seen[0][1].endswith(
        "&project_document_ids=doc_p1&project_document_ids=doc_p2"
    )
    assert seen[1][2]["project_document_ids"] == ["doc_p1", "doc_p2"]
    assert (tmp_path / "plan.json").exists()


def test_the_kind_and_markers_go_into_the_copy_only(tmp_path, monkeypatch):
    from app.config import settings

    db = tmp_path / "copy.sqlite"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE document_kinds (document_id TEXT PRIMARY KEY, kind TEXT, state TEXT, evidence TEXT, router_version TEXT,"
        " routed_at TEXT, confirmed_by TEXT, confirmed_at TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "INSERT INTO pages VALUES ('p', 1, 'one'), ('p', 2, 'two'), ('o', 1, 'other');"
    )
    c.commit()
    c.close()
    monkeypatch.setattr(settings, "db_path", db)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    w._prepare_copy("contract", "p", {"o": "MARKO"})
    c = sqlite3.connect(db)
    assert c.execute(
        "SELECT kind, state FROM document_kinds WHERE document_id='p'"
    ).fetchone() == ("contract", "confirmed")
    assert (
        "MARKO"
        in c.execute("SELECT text FROM pages WHERE document_id='o'").fetchone()[0]
    )
    assert (
        c.execute(
            "SELECT text FROM pages WHERE document_id='p' AND page_no=2"
        ).fetchone()[0]
        == "two"
    )
