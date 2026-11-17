# ruff: noqa: F811, E731
"""Order 14, piece D: the paper history route and the saved-checklists route (scope-narrowed; earlier runs keep their routes)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import aim_review_store as store
from app import db, settings_ext  # noqa: F401
from app.config import settings
from app.main import app
from tests.test_p3_review_jobs import _doc, _user, temp_storage  # noqa: F401 - fixture

PAPER = "doc_inv_paper"
OTHER = "doc_inv_other_paper"
NOW = "2026-11-18T10:00:00Z"


def _run(
    run_id: str, paper: str, status: str, created: str, *, ai: bool = False
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at, completed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                paper,
                status,
                created,
                created,
                created,
                created if status == "completed" else None,
            ),
        )
        if ai:
            from app import agent_review_schema

            agent_review_schema.create_tables(conn)
            conn.execute(
                "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at) VALUES (?, ?, 'datasheet', 'test', 'x')",
                (run_id, paper),
            )
            for i in range(3):
                conn.execute(
                    "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, line_json, reason, decided_at) VALUES (?, ?, 'Query for the engineer', 'Query', '{}', '', 'x')",
                    (run_id, f"I{i}"),
                )


def _general(
    run_id: str, paper: str, created: str, status: str = "done", n_lines: int = 2
) -> None:
    _run(run_id, paper, "completed", created)
    with db.connect() as conn:
        store.start_run(conn, run_id, paper, created)
        lines = [
            {"item_id": f"C{i}", "label": "Question", "comment": "invented"}
            for i in range(n_lines)
        ]
        store.finish_run(conn, run_id, {"status": status, "lines": lines}, created)


@pytest.fixture
def world(temp_storage, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    _doc(PAPER, "CONTRACTOR_SUBMITTAL", "invented paper text")
    _doc(OTHER, "CONTRACTOR_SUBMITTAL", "another invented paper")
    store.ensure_schema()
    admin = _user("adm", [PAPER, OTHER], admin=True)
    eng = _user("eng", [PAPER])
    narrow = _user("narrow", [OTHER])
    return {"admin": admin, "eng": eng, "narrow": narrow}


def _get(path, headers):
    return TestClient(app).get(path, headers=headers)


def test_history_lists_general_and_earlier_runs_newest_first(world):
    _run("rc_old", PAPER, "completed", "2026-11-01T10:00:00Z")
    _run("ai_old", PAPER, "completed", "2026-11-02T10:00:00Z", ai=True)
    _general("gen_new", PAPER, "2026-11-18T10:00:00Z")
    r = _get(f"/api/reviews/papers/{PAPER}/history", world["eng"])
    assert r.status_code == 200
    body = r.json()
    assert (
        body["paper_document_id"] == PAPER
        and body["boundary"] == "reviews of this paper you may read"
    )
    assert [x["run_id"] for x in body["runs"]] == ["gen_new", "ai_old", "rc_old"]
    by = {x["run_id"]: x for x in body["runs"]}
    assert (
        by["gen_new"]["version"] == "general"
        and by["gen_new"]["part"] == "general review"
        and by["gen_new"]["points"] == 2
    )
    assert (
        by["ai_old"]["version"] == "earlier version"
        and by["ai_old"]["part"] == "AI review"
        and by["ai_old"]["points"] == 3
    )
    assert (
        by["rc_old"]["version"] == "earlier version"
        and by["rc_old"]["part"] == "rule check"
    )
    assert by["rc_old"]["points"] is None  # no stored count: null, never 0


def test_earlier_runs_keep_their_existing_download_routes(world):
    _run("rc_old", PAPER, "completed", "2026-11-01T10:00:00Z")
    _run("ai_old", PAPER, "completed", "2026-11-02T10:00:00Z", ai=True)
    body = _get(f"/api/reviews/papers/{PAPER}/history", world["eng"]).json()
    by = {x["run_id"]: x for x in body["runs"]}
    assert [f["url"] for f in by["rc_old"]["files"]] == [
        "/api/reviews/runs/rc_old/crs?copy=internal"
    ]
    assert [f["url"] for f in by["ai_old"]["files"]] == [
        "/api/reviews/runs/ai_old/agent/crs?copy=internal",
        "/api/reviews/runs/ai_old/agent/crs?copy=contractor",
    ]
    assert all(f["label"] for r in body["runs"] for f in r["files"])


def test_no_older_file_is_linked_when_the_app_does_not_offer_them(world, monkeypatch):
    from app import crs_copy_words

    _run("rc_old", PAPER, "completed", "2026-11-01T10:00:00Z")
    monkeypatch.setattr(crs_copy_words, "old_file_offered", lambda: False)
    body = _get(f"/api/reviews/papers/{PAPER}/history", world["eng"]).json()
    assert body["runs"][0]["files"] == []


def test_a_run_that_did_not_finish_has_no_file(world):
    _run("rc_run", PAPER, "running", "2026-11-01T10:00:00Z")
    _general("gen_stop", PAPER, "2026-11-18T10:00:00Z", status="stopped")
    by = {
        x["run_id"]: x
        for x in _get(f"/api/reviews/papers/{PAPER}/history", world["eng"]).json()[
            "runs"
        ]
    }
    assert by["rc_run"]["files"] == [] and by["gen_stop"]["files"] == []
    assert by["gen_stop"]["status"] == "stopped"


def test_history_is_scope_narrowed_a_paper_outside_the_scope_is_404(world):
    _general("gen_a", PAPER, NOW)
    outside = _get(f"/api/reviews/papers/{PAPER}/history", world["narrow"])
    unknown = _get("/api/reviews/papers/doc_does_not_exist/history", world["narrow"])
    assert outside.status_code == 404 and unknown.status_code == 404
    strip = lambda r: {
        k: v for k, v in r.json()["detail"].items() if k != "document_id"
    }
    assert strip(outside) == strip(unknown)  # indistinguishable: no existence oracle
    assert "gen_a" not in outside.text


def test_a_caller_sees_only_runs_of_the_paper_asked_for(world):
    _general("gen_a", PAPER, NOW)
    _general("gen_b", OTHER, NOW)
    _run("rc_b", OTHER, "completed", NOW)
    ids = [
        x["run_id"]
        for x in _get(f"/api/reviews/papers/{PAPER}/history", world["admin"]).json()[
            "runs"
        ]
    ]
    assert ids == ["gen_a"]


def test_history_with_the_function_directly_never_widens_the_scope(world):
    """Intersection, never union: the module itself refuses a paper that is not in the allowed set."""
    from app import aim_review_history

    conn = db.connect()
    assert aim_review_history.history(conn, PAPER, frozenset({OTHER})) is None
    assert aim_review_history.history(conn, PAPER, frozenset()) is None
    assert aim_review_history.history(conn, PAPER, frozenset({PAPER}))["runs"] == []


def test_history_of_an_unreviewed_paper_is_an_empty_list(world):
    body = _get(f"/api/reviews/papers/{PAPER}/history", world["eng"]).json()
    assert body["runs"] == []


def test_history_rejects_an_unknown_parameter(world):
    assert (
        _get(f"/api/reviews/papers/{PAPER}/history?x=1", world["eng"]).status_code
        == 422
    )


def test_the_checklists_route_is_for_an_admin_only(world):
    s = store.DbChecklistStore(db.connect())
    s.put(
        "datasheet__inv",
        {
            "built_from": store.BUILT_FROM,
            "identity": {"kind": "datasheet", "subject_key": "inv"},
            "books": ["doc_b"],
            "items": [{"id": "C1"}],
        },
        run_id="gen_1",
        usd=0.5,
    )
    ok = _get("/api/reviews/general/checklists", world["admin"])
    assert ok.status_code == 200
    rows = ok.json()["checklists"]
    assert (
        len(rows) == 1
        and rows[0]["key"] == "datasheet__inv"
        and rows[0]["items"] == 1
        and rows[0]["books"] == ["doc_b"]
    )
    assert "body" not in rows[0]
    assert _get("/api/reviews/general/checklists", world["eng"]).status_code in (
        401,
        403,
        404,
    )
    assert _get("/api/reviews/general/checklists", {}).status_code in (401, 403, 404)
