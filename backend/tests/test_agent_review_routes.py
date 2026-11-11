"""The AI reviewer's routes: the switch, the kind gate, the scope, the answers, and that a GET never writes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tests.test_agent_review_job as job_tests
from app import (
    access,
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    db,
    nothing_read,
)
from app import agent_review_items as items_mod
from app.config import settings
from app.main import app
from tests import agent_review_support as s
from tests.test_agent_review_job import (  # noqa: F401 - the same invented world
    _CACHE,
    _DOC,
    reading,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    fake = s.FakeModel()
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id
    )
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    doc, cache = s.item_doc(
        left_out=[
            {
                "rule_version_id": "x1",
                "rule_book": "INV-OTHER",
                "clause": "9.1",
                "reason": "needs_another_paper",
                "page": 3,
                "needs_paper_kind": "procedure",
                "standard_document_id": "doc_other",
            },
        ]
    )
    job_tests._DOC, job_tests._CACHE = doc, cache

    def build(_conn, _paper, _kind, *, cache=None, **_kw):
        cache.update(job_tests._CACHE)
        return job_tests._DOC

    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in doc["items"]])
    return TestClient(app, base_url="http://127.0.0.1")


def finished_run(client) -> str:
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"] if "run_id" in r.json() else r.json()["review_run_id"]
    job_id = agent_review_jobs.claim_next("w-test")
    assert agent_review_jobs.run(job_id, "w-test") == "done"
    return run_id


ROUTES = [
    ("get", "/api/reviews/agent-status"),
    ("post", "/api/reviews/agent-run"),
    ("get", "/api/reviews/runs/r1/agent/summary"),
    ("get", "/api/reviews/runs/r1/agent/lines"),
    ("get", "/api/reviews/runs/r1/agent/lines/R-coat/trace"),
    ("get", "/api/reviews/runs/r1/agent/crs?copy=internal"),
    ("get", "/api/reviews/runs/r1/rules-used"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_switch_off_every_route_is_404_feature_off_and_no_table_exists(
    tmp_path, monkeypatch, method, path
):
    s.setup_world(tmp_path, monkeypatch, on=False)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.request(
        method,
        path,
        json={"submittal_document_id": s.PAPER} if method == "post" else None,
    )
    assert (r.status_code, r.json()["detail"]) == (404, "feature_off")
    names = {
        row[0]
        for row in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert not [n for n in names if n.startswith("agent_review_")]
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM jobs WHERE stage = 'agent_review'")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "kind", ["procedure", "contract", "drawing", "calculation", "other", "unknown"]
)
def test_only_a_datasheet_is_accepted_any_other_kind_is_409_with_no_job_and_no_call(
    client, monkeypatch, kind
):
    monkeypatch.setattr(
        agent_review_kind,
        "decide",
        lambda *_a, **_k: reading(kind=kind, known=kind != "unknown"),
    )
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "kind_not_enabled"
    assert (
        r.json()["detail"]["message"]
        == "AI review is on for datasheets only (owner, 11 Nov 2026)"
    )
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM jobs WHERE stage = 'agent_review'")
        .fetchone()[0]
        == 0
    )
    from app import submittal_review

    submittal_review.ensure_schema()
    assert db.connect().execute("SELECT COUNT(*) FROM review_runs").fetchone()[0] == 0


def test_the_kind_list_is_one_constant_with_the_owners_words():
    assert agent_review_gate.AGENT_REVIEW_KINDS == ("datasheet",)
    assert agent_review_gate.kind_enabled(
        "datasheet"
    ) and not agent_review_gate.kind_enabled(None)
    assert not any(
        agent_review_gate.kind_enabled(k)
        for k in ("procedure", "contract", "test_record", "unknown", "")
    )


def test_a_datasheet_is_queued_and_a_second_start_while_it_waits_is_409(client):
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    again = client.post(
        "/api/reviews/agent-run", json={"submittal_document_id": s.PAPER}
    )
    assert again.status_code == 409
    assert client.post(
        "/api/reviews/agent-run", json={"submittal_document_id": "nope"}
    ).status_code in (404, 409)


def test_status_says_enabled_and_whether_the_lane_is_open(client, monkeypatch):
    monkeypatch.setattr(agent_review_gate, "claude_lane_open", lambda: False)
    assert client.get("/api/reviews/agent-status").json() == {
        "enabled": True,
        "claude_lane_open": False,
    }


def test_summary_lines_trace_crs_and_rules_used_after_a_review(client):
    run_id = finished_run(client)
    summary = client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()
    assert summary["paper_kind"] == "datasheet" and summary["stop_reason"] is None
    assert (
        summary["counts_by_class"]["Proven by code"] == 3
        and summary["not_reviewed"] == 1
    )
    assert summary["missing_books"] == ["INV-MISSING-9"] and summary["usd"] > 0
    lines = client.get(f"/api/reviews/runs/{run_id}/agent/lines").json()
    words = {ln["item_id"]: ln["word"] for ln in lines["lines"]}
    assert words == {
        "R-coat": "Pass",
        "R-frame": "Pass",
        "R-mark": "Fail",
        "R-colour": "Not reviewed",
    }
    assert lines["next"] is None
    paged = client.get(f"/api/reviews/runs/{run_id}/agent/lines?limit=2").json()
    assert len(paged["lines"]) == 2 and paged["next"]
    rest = client.get(
        f"/api/reviews/runs/{run_id}/agent/lines?limit=2&cursor={paged['next']}"
    ).json()
    assert {x["item_id"] for x in paged["lines"] + rest["lines"]} == set(words)
    trace = client.get(f"/api/reviews/runs/{run_id}/agent/lines/R-mark/trace").json()
    assert (
        trace["paper_quote"] == "Marking blue"
        and trace["page"] == 1
        and trace["rule_book"] == "INV-STD-100"
    )
    assert any(
        g["step"] == "decision" and g["outcome"] == "Fail" for g in trace["gate"]
    )
    assert (
        client.get(f"/api/reviews/runs/{run_id}/agent/lines/NOPE/trace").status_code
        == 404
    )
    for copy in ("internal", "contractor"):
        r = client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy={copy}")
        assert r.status_code == 200 and r.content[:2] == b"PK"
    assert (
        client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=other").status_code
        == 422
    )
    used = client.get(f"/api/reviews/runs/{run_id}/rules-used").json()
    assert used["paper_kind"] == "datasheet" and used["rule_set_changed_by"] is None
    assert {r["tier"] for r in used["asked"]} == {"AI approved"} and len(
        used["asked"]
    ) == 4
    assert used["left_out"] == [
        {"rule_book": "INV-OTHER", "clause": "9.1", "reason": "needs another paper"}
    ]
    assert used["left_out_counts"] == {"needs another paper": 1}
    assert (used["equipment_state"], used["equipment_notes"]) == (
        "usable",
        ["another equipment type: 2 rules not asked (pump 2)"],
    )
    assert (summary["equipment_state"], summary["equipment_notes"]) == (
        used["equipment_state"],
        used["equipment_notes"],
    )
    assert used["missing_books"][0]["name"] == "INV-MISSING-9"
    assert all(r["read_from"] == "text" for r in used["asked"])


def test_rules_used_books_come_from_the_coverage_file_and_are_null_without_a_row(
    client,
):
    run_id = finished_run(client)
    books = client.get(f"/api/reviews/runs/{run_id}/rules-used").json()["books"]
    assert (
        books
        == [
            {
                "rule_book": b["rule_book"],
                "requirement_sentences": None,
                "covered_sentences": None,
                "unreadable_pages": None,
                "weak_pages": None,
                "below_half": None,
            }
            for b in books
        ]
        and books
    )
    folder = Path(settings.data_dir) / "coverage"
    folder.mkdir()
    (folder / "coverage.json").write_text(
        json.dumps(
            {
                "books": {
                    s.STD: {
                        "sentences": 40,
                        "covered": 15,
                        "unreadable_pages": [3],
                        "weak_pages": [1, 2],
                    }
                }
            }
        )
    )
    got = {
        b["rule_book"]: b
        for b in client.get(f"/api/reviews/runs/{run_id}/rules-used").json()["books"]
    }
    assert got["INV-STD-100"] == {
        "rule_book": "INV-STD-100",
        "requirement_sentences": 40,
        "covered_sentences": 15,
        "unreadable_pages": 1,
        "weak_pages": 2,
        "below_half": True,
    }


def test_a_run_the_caller_may_not_read_is_a_404_like_one_that_does_not_exist(
    client, monkeypatch
):
    run_id = finished_run(client)
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="u2", allowed_document_ids=frozenset({"doc_other"})
    )
    try:
        for path in (
            f"/api/reviews/runs/{run_id}/agent/summary",
            f"/api/reviews/runs/{run_id}/agent/lines",
            f"/api/reviews/runs/{run_id}/rules-used",
            f"/api/reviews/runs/{run_id}/agent/crs?copy=internal",
            f"/api/reviews/runs/{run_id}/agent/lines/R-mark/trace",
        ):
            assert client.get(path).status_code == 404, path
        assert client.get("/api/reviews/runs/missing/agent/summary").status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert client.get(f"/api/reviews/runs/{run_id}/agent/summary").status_code == 200


def test_no_get_route_of_the_reviewer_writes(client, monkeypatch):
    run_id = finished_run(client)
    writes: list = []
    real_init = db.SchemaRetryConnection.__init__

    def authorizer(action, arg1, _a2, dbname, _src):
        if (
            action
            in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)
            and dbname != "temp"
            and not str(arg1).startswith("sqlite_")
        ):
            writes.append((action, arg1))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def guarded(self, *a, **k):
        real_init(self, *a, **k)
        self.set_authorizer(authorizer)

    monkeypatch.setattr(db.SchemaRetryConnection, "__init__", guarded)
    db.reset_connection()
    for path in (
        "/api/reviews/agent-status",
        f"/api/reviews/runs/{run_id}/agent/summary",
        f"/api/reviews/runs/{run_id}/agent/lines",
        f"/api/reviews/runs/{run_id}/agent/lines/R-mark/trace",
        f"/api/reviews/runs/{run_id}/agent/crs?copy=internal",
        f"/api/reviews/runs/{run_id}/rules-used",
    ):
        assert client.get(path).status_code == 200, path
    assert writes == []


def test_a_get_before_any_run_creates_no_table(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)  # switch on, no run, no table yet
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get("/api/reviews/runs/r1/agent/summary").status_code == 404
    assert c.get("/api/reviews/runs/r1/rules-used").status_code == 404
    names = {
        row[0]
        for row in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert not [n for n in names if n.startswith("agent_review_")]


def test_no_new_module_builds_a_line_by_model_construct_or_field_assignment():
    root = Path(__file__).resolve().parents[1] / "app"
    mine = [root / "api" / "agent_review.py", *root.glob("agent_review_*.py")]
    for path in mine:
        text = path.read_text(encoding="utf-8")
        assert "model_construct" not in text, path.name
        assert ".model_copy(update" not in text, path.name


def test_the_tables_refuse_an_unproven_pass_or_fail_themselves(client):
    finished_run(client)
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, line_json, decided_at)"
            " VALUES ('r', 'i', 'AI opinion, engineer to confirm', 'Pass', '{}', 'x')"
        )
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, rule_tier, line_json, decided_at)"
            " VALUES ('r', 'i', 'Proven by code', 'Fail', 'Not AI approved', '{}', 'x')"
        )
