"""Order 117 item 5, last part: the playbook, run-standard, finding-history,
CRS record, deliverable history/stakeholder, escalation-rule and admin lists
take an optional page and carry `total` beside their rows.

Without `limit`/`offset` every row comes back, as before. `total` is every row
the caller may read, the same on every page (rule 4). A run, finding or
deliverable on a document the caller cannot read stays a 404, and a standard
they cannot read is not counted (rule 5). Invented rows only.
"""

from __future__ import annotations

import json
import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    crs_issue,
    db,
    deliverables,
    playbooks,
    review,
    submittal_review,
)
from app.config import settings
from app.main import app

NOW = "2026-10-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "lists.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    deliverables.ensure_schema()
    crs_issue.ensure_schema()
    review.ensure_schema()
    yield
    app.dependency_overrides.pop(access.current_scope, None)
    db.reset_connection()


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def _doc(doc_id: str) -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,'/x','ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW),
        )
    return doc_id


def _run(doc_id: str) -> str:
    run_id = str(uuid.uuid4())
    outcome = json.dumps({"recommended_code": "Manual Review Required", "reason": "r"})
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,"
            "created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
            (run_id, doc_id, outcome, NOW, NOW),
        )
    return run_id


def _pages(client, path: str, key: str, size: int, whole: int) -> list:
    """Walk every page of `path`; each states the same total. Returns the rows
    joined, in the order they came."""
    joined: list = []
    sep = "&" if "?" in path else "?"
    for offset in range(0, whole, size):
        body = client.get(f"{path}{sep}limit={size}&offset={offset}").json()
        assert body["total"] == whole, (path, offset)
        assert (body["limit"], body["offset"]) == (size, offset)
        assert len(body[key]) <= size
        joined.extend(body[key])
    return joined


def _check(client, path: str, key: str, size: int = 2) -> dict:
    """The unpaged answer has every row and states it; the pages joined are
    that same list."""
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    whole = resp.json()
    assert whole["total"] == len(whole[key]) and whole["limit"] is None
    assert whole["offset"] == 0
    assert _pages(client, path, key, size, whole["total"]) == whole[key]
    return whole


def test_playbooks_page_and_the_unusable_files_come_back_on_every_page(
    tmp_path, monkeypatch
):
    folder = tmp_path / "playbooks"
    folder.mkdir()
    for path in sorted(playbooks.PLAYBOOK_DIR.glob("*.json")):
        shutil.copy(path, folder / path.name)
    (folder / "zz_broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(playbooks, "PLAYBOOK_DIR", folder)
    client = _client()
    whole = _check(client, "/api/playbooks", "playbooks", size=1)
    assert whole["total"] >= 2
    assert [u["file"] for u in whole["unusable"]] == ["zz_broken.json"]
    one = client.get("/api/playbooks?limit=1&offset=1").json()
    assert one["unusable"] == whole["unusable"]


def test_run_standards_page_count_only_readable_standards_and_hide_the_run():
    sub = _doc("sub_a")
    stds = [_doc(f"std_{i}") for i in range(5)]
    run = _run(sub)
    with db.connect() as conn:
        for i, std in enumerate(stds):
            conn.execute(
                "INSERT INTO review_applicable_standards (id,review_run_id,"
                "standard_document_id,selection_reason,selection_method,included,"
                "created_at) VALUES (?,?,?,?,'rule',?,?)",
                (f"ras-{i}", run, std, "invented", 0 if i == 4 else 1, f"{NOW}{i}"),
            )
    # the caller may read the submittal and four of the five standards
    client = _client(sub, *stds[1:])
    path = f"/api/reviews/runs/{run}/standards"
    included = _check(client, path, "standards")
    assert included["total"] == 3  # std_0 unreadable, std_4 excluded
    everything = _check(client, f"{path}?include_excluded=true", "standards")
    assert everything["total"] == 4
    assert "std_0" not in {s["standard_document_id"] for s in everything["standards"]}
    assert client.get(f"{path}?limit=1").json()["missing_references"] == []
    assert _client(*stds).get(path).status_code == 404


def test_finding_history_pages_and_a_hidden_finding_stays_hidden():
    sub = _doc("sub_f")
    finding = review.create(
        {
            "document_id": sub,
            "category": "technical_query",
            "severity": "minor",
            "requirement": "r",
            "finding": "f",
            "required_action": "a",
        },
        created_by="eng",
    )
    with db.connect() as conn:
        for i in range(4):
            review._event(conn, finding["id"], "comment", {"n": i}, "eng", NOW)
    client = _client(sub)
    path = f"/api/reviews/findings/{finding['id']}/history"
    whole = _check(client, path, "events")
    assert whole["total"] >= 4
    assert _client("other").get(path).status_code == 404


def test_crs_decisions_and_issued_copies_page_and_a_hidden_run_stays_hidden():
    sub = _doc("sub_c")
    run = _run(sub)
    for page in range(1, 6):
        crs_issue.decide_page(
            run, page, unread=[1, 2, 3, 4, 5], reason="checked by eye", actor="eng"
        )
    for i in range(3):
        crs_issue.archive(run, f"book {i}".encode(), f"copy-{i}.xlsx", actor="eng")
    client = _client(sub)
    decisions = _check(client, f"/api/reviews/runs/{run}/crs/decisions", "decisions")
    assert decisions["total"] == 5
    copies = _check(client, f"/api/reviews/runs/{run}/crs/issued", "copies")
    assert copies["total"] == 3
    hidden = _client("other")
    for tail in ("decisions", "issued"):
        assert hidden.get(f"/api/reviews/runs/{run}/crs/{tail}").status_code == 404


def test_deliverable_history_and_stakeholders_page_and_a_hidden_one_stays_hidden():
    doc = _doc("doc_d")
    item = deliverables.create(
        {
            "wbs_code": "1.1",
            "title": "Item",
            "deliverable_type": "report",
            "document_id": doc,
        },
        created_by=None,
    )
    for rev in ("1", "2", "3"):
        deliverables.update(item["id"], {"revision": rev}, actor_user_id=None)
    with db.connect() as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,is_active,"
                "created_at) VALUES (?,?,?,'x',1,?)",
                (f"u{i}", f"u{i}@example.invalid", f"User {i}", NOW),
            )
    client = _client(doc)
    put = client.put(
        f"/api/deliverables/{item['id']}/stakeholders",
        json={
            "assignments": [{"user_id": f"u{i}", "role": "reviewer"} for i in range(5)]
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["total"] == 5 and len(put.json()["stakeholders"]) == 5
    history = _check(client, f"/api/deliverables/{item['id']}/history", "events")
    assert history["total"] >= 4
    people = _check(
        client, f"/api/deliverables/{item['id']}/stakeholders", "stakeholders"
    )
    assert people["total"] == 5
    hidden = _client("other")
    for tail in ("history", "stakeholders"):
        assert hidden.get(f"/api/deliverables/{item['id']}/{tail}").status_code == 404


def test_escalation_rules_and_admin_lists_page_with_their_total():
    with db.connect() as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO roles (id,name,description,kind,created_at)"
                " VALUES (?,?,'','discipline',?)",
                (f"r{i}", f"Discipline {i}", NOW),
            )
    client = _client()
    rules = _check(client, "/api/management/escalation-rules", "rules", size=1)
    assert rules["total"] >= 1
    disciplines = _check(client, "/api/admin/disciplines", "disciplines")
    assert disciplines["total"] >= 3
    tables = _check(client, "/api/admin/db/tables", "tables", size=10)
    assert tables["total"] > 10


def test_a_bad_page_is_refused():
    client = _client()
    for path in (
        "/api/playbooks",
        "/api/management/escalation-rules",
        "/api/admin/disciplines",
        "/api/admin/db/tables",
    ):
        for query in ("limit=0", "limit=1001", "offset=-1"):
            assert client.get(f"{path}?{query}").status_code == 422, (path, query)
