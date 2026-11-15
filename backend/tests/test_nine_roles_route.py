"""The role record route: behind the switch, scope-checked, a document the caller may not read counted and never named."""

# ruff: noqa: F811
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db, nine_record
from app.api import nine_roles
from app.nine_contract import ReadEntry

from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

app = FastAPI()  # the route alone: the real app registers it only with the switch on (see the subprocess tests below)
app.include_router(nine_roles.router)

SECRET_TITLE = "unreadable-secret-name.pdf"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(nine_roles, "switch_on", lambda: True)


def _record(world):
    run_id = "run-nine"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?, 'running', 't', 't')",
            (run_id, world["sub"]),
        )
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('hidden',?,?,1,'h.pdf','ready',1,'t')",
            (SECRET_TITLE, "h" * 64),
        )
    nine_record.start_run(run_id)
    reads = [
        ReadEntry(
            4, "c1", world["sub"], "paper", (1,), None, None, None, 10, "a" * 64, 0
        ),
        ReadEntry(4, "c1", "hidden", "rule_book", (4,), "4", 1, 1, 20, "b" * 64, 0),
    ]
    nine_record.call_sent(
        run_id,
        4,
        "c1",
        step="nine_reviewer",
        engine="claude",
        model="m",
        request_sha256="d" * 64,
        reads=reads,
    )
    nine_record.call_end(run_id, "c1", "answered", usd=0.12)
    nine_record.role_end(run_id, 4, "ran", produced={"findings": 3})
    return run_id


def test_the_route_is_off_while_the_switch_is_off(world):
    run_id = _record(world)
    r = TestClient(app).get(f"/api/reviews/runs/{run_id}/roles", headers=world["admin"])
    assert r.status_code == 404 and "feature_off" in r.text


def test_the_record_is_shown_with_the_unreadable_document_counted_and_never_named(
    world, on
):
    run_id = _record(world)
    r = TestClient(app).get(f"/api/reviews/runs/{run_id}/roles", headers=world["admin"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        len(body["roles"]) == 9
        and body["roles"][3]["state"] == "ran"
        and body["roles"][3]["usd"] == 0.12
    )
    role = body["roles"][3]
    assert [x["title"] for x in role["reads"]] == ["sub_pump.pdf"] and role[
        "not_readable"
    ] == 1
    assert (
        SECRET_TITLE not in r.text and "hidden" not in r.text
    )  # counted, never named, not even by id
    assert (
        body["roles"][0]["state"] == "not_run"
        and "Roles run: 1 of 9" in body["roles_line"]
    )
    assert body["boundary"] == "documents you may read"


def test_a_run_the_caller_may_not_read_and_a_run_with_no_role_rows_are_404(world, on):
    client = TestClient(app)
    assert (
        client.get("/api/reviews/runs/nope/roles", headers=world["admin"]).status_code
        == 404
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('old', ?, 'completed','t','t')",
            (world["sub"],),
        )
    r = client.get("/api/reviews/runs/old/roles", headers=world["admin"])
    assert r.status_code == 404 and "no role record" in json.dumps(r.json())


def test_the_shown_list_count_counts_only_what_the_caller_may_read(world, on):
    from app import review_shown

    run_id = _record(world)
    with db.connect() as conn, conn:
        review_shown.record_in(
            conn, run_id, [world["sub"], world["std"], "hidden"], "t"
        )
    body = (
        TestClient(app)
        .get(f"/api/reviews/runs/{run_id}/roles", headers=world["admin"])
        .json()
    )
    assert (
        body["documents_on_the_shown_list"] == 2
        and body["boundary"] == "documents you may read"
    )


def _modules_after_import(switch_on: bool) -> dict:
    import json
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import json, sys\n"
        "from app.config import settings\n"
        f"object.__setattr__(settings, 'agent_review_nine_roles_enabled', {switch_on})\n"
        "import app.main as m\n"
        "names = sorted(n for n in sys.modules if n.startswith('app.') and n.split('.')[-1].startswith('nine_'))\n"
        "paths = m.app.openapi()['paths']\n"
        "print(json.dumps({'modules': names, 'route': any(p.endswith('/roles') and 'reviews/runs' in p for p in paths)}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_with_the_switch_off_no_nine_module_is_imported_and_the_route_does_not_exist():
    got = _modules_after_import(False)
    assert got == {"modules": [], "route": False}


def test_with_the_switch_on_the_route_is_registered_and_the_nine_modules_load():
    got = _modules_after_import(True)
    assert (
        got["route"]
        and "app.nine_record" in got["modules"]
        and "app.api.nine_roles" in got["modules"]
    )
