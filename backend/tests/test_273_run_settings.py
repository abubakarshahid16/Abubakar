"""Order 273.4: a review run stores the model and the settings it ran with, read from the running process."""

from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    auth,
    config,
    datasheets,
    db,
    fts_index,
    review_jobs,
    run_settings,
    standards,
    submittal_review,
)
from app.config import settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"
W = "w-test"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "p3.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "job_max_running", 1)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    fts_index.ensure_schema()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id, role, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,'/x','ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES (?,?,?)",
            (doc_id, "test", role),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'1',"
            "'prose',?,1,?,1)",
            (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )
    fts_index.index_document(doc_id)
    return doc_id


def _user(user_id, docs, admin=False):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,'x',1,?)",
            (user_id, f"{user_id}@x", user_id, NOW),
        )
        rid = f"r-{user_id}"
        conn.execute(
            "INSERT INTO roles (id,name,description,kind,created_at) VALUES (?,?,'',?,?)",
            (rid, rid, "discipline", NOW),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
            (user_id, rid, NOW),
        )
        if admin:
            conn.execute(
                "INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                " VALUES ('role_admin','admin','','capability',?)",
                (NOW,),
            )
            adm = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()[
                "id"
            ]
            conn.execute(
                "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
                (user_id, adm, NOW),
            )
        for d in docs:
            conn.execute(
                "INSERT INTO document_role_access (document_id,role_id,granted_at)"
                " VALUES (?,?,?)",
                (d, rid, NOW),
            )
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


@pytest.fixture
def world():
    std = _doc(
        "std_api",
        "COMPANY_STANDARD",
        "Equipment noise level shall not exceed 90 dB(A).",
    )
    sub = _doc(
        "sub_pump",
        "CONTRACTOR_SUBMITTAL",
        "Pump shall comply with API 610. Noise level 95 dB(A)",
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_number = 'API 610' WHERE document_id = ?",
            (std,),
        )
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    datasheets.create_fact(
        submittal_document_id=sub,
        chunk_id=f"{sub}-c1",
        field_label="Noise level",
        raw_value="95",
        unit="dB(A)",
        page=1,
    )
    admin = _user("adm", [std, sub], admin=True)
    return {"std": std, "sub": sub, "admin": admin, "scope": frozenset({std, sub})}


def _enqueue(w, user="adm"):
    return review_jobs.enqueue(
        w["sub"], allowed_document_ids=w["scope"], requested_by=user
    )


def _row(run_id):
    return dict(
        db.connect()
        .execute("SELECT * FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )


SWITCHES = (
    "geometry_reader_enabled",
    "geometry_table_reader_enabled",
    "datasheet_reader_mode",
    "match_ask_max_per_run",
    "vision_reader_engine",
    "reasoning_provider",
)


def test_the_reader_switches_are_in_the_version_a_run_is_stamped_with(monkeypatch):
    for name in SWITCHES:
        assert name in config.ANSWER_AFFECTING_SETTINGS, name
    before = config.config_version()
    monkeypatch.setattr(
        settings, "geometry_reader_enabled", not settings.geometry_reader_enabled
    )
    assert config.config_version() != before


def test_a_claimed_run_stores_the_values_the_process_holds(world, monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)
    run_id, job_id = _enqueue(world)
    assert _row(run_id)["run_settings"] is None  # queued: nothing has run yet
    assert review_jobs.claim_next(W) == job_id
    row = _row(run_id)
    stored = json.loads(row["run_settings"])
    assert stored["settings"] == {
        k: getattr(settings, k) for k in config.ANSWER_AFFECTING_SETTINGS
    }
    assert stored["settings"]["geometry_reader_enabled"] is True
    assert row["config_version"] == stored["config_version"] == config.config_version()
    assert row["model_name"] == settings.ai_task_model


def test_the_finished_run_adds_the_reader_that_read_the_sheet(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    datasheets.record_reader_summary(
        world["sub"],
        "v1",
        {
            "engine": "ollama",
            "model": "qwen-test",
            "pages": 3,
            "pages_read": 3,
            "secret_note": "x",
        },
    )
    assert review_jobs.run(job_id, W) == "done"
    stored = run_settings.of_run(db.connect(), run_id)
    assert stored["reader"] == {
        "engine": "ollama",
        "model": "qwen-test",
        "pages": 3,
        "pages_read": 3,
    }
    assert "secret_note" not in json.dumps(stored)


def test_the_summary_route_returns_what_the_run_stored(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    r = TestClient(app, base_url="http://localhost").get(
        f"/api/reviews/runs/{run_id}/summary", headers=world["admin"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    shown = body["how_reviewed"]["run_settings"]
    assert shown["config_version"] == config.config_version()
    assert (
        shown["settings"]["geometry_reader_enabled"] is settings.geometry_reader_enabled
    )
    assert shown["model_name"] == settings.ai_task_model


def test_a_run_started_before_this_change_shows_no_settings_never_invented(world):
    run_id, _job = _enqueue(world)
    assert run_settings.of_run(db.connect(), run_id) is None


def test_a_run_opened_directly_stores_the_settings_too(world, monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    run_id = submittal_review.create_review_run(
        submittal_document_id=world["sub"], allowed_document_ids=world["scope"]
    )
    row = _row(run_id)
    stored = json.loads(row["run_settings"])
    assert stored["settings"]["geometry_reader_enabled"] is True
    assert row["config_version"] == config.config_version() == stored["config_version"]
    assert row["model_name"] == settings.ai_task_model
