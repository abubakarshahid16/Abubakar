"""#1495: a review that read nothing ends failed 'nothing read', never completed."""
from __future__ import annotations

import json

import pytest

from app import db, review_jobs
from app.config import settings
from tests import test_p3_review_jobs as p3
from tests.test_p3_review_jobs import temp_storage, _doc, _user, _run_row, _job  # noqa: F401

W = p3.W


def _world(text):
    std = _doc("std_api", "COMPANY_STANDARD", "Equipment noise level shall not exceed 90 dB(A).")
    sub = _doc("sub_x", "CONTRACTOR_SUBMITTAL", text)
    _user("adm", [std, sub], admin=True)
    return sub, frozenset({std, sub})


def _go(sub, scope):
    run_id, job_id = review_jobs.enqueue(sub, allowed_document_ids=scope, requested_by="adm")
    assert review_jobs.claim_next(W) == job_id
    return run_id, job_id, review_jobs.run(job_id, W)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "nothing_read_fails_enabled", True)


def _unread(sub):
    with db.connect() as conn:  # the file is missing and no page text came back
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (sub,))


def test_missing_file_nothing_read_fails_the_run(on):
    sub, scope = _world("x")
    _unread(sub)
    run_id, job_id, state = _go(sub, scope)
    assert state == "poisoned"
    run = _run_row(run_id)
    assert run["status"] == "failed"
    error = json.loads(run["outcome_json"])["error"]
    assert "nothing read" in error and "0 values" in error
    assert _job(job_id)["error_code"] == "NothingRead"
    assert p3._findings(run_id) == 0


def test_prose_with_page_text_and_no_fields_is_not_failed(on):
    sub, scope = _world("Welding procedure: the operator shall clean the joint before welding.")
    run_id, _, state = _go(sub, scope)
    assert state == "done"
    assert _run_row(run_id)["status"] == "completed"


def test_normal_datasheet_unchanged(on):
    from app import datasheets
    sub, scope = _world("Noise level 95 dB(A)")
    datasheets.create_fact(submittal_document_id=sub, chunk_id=f"{sub}-c1",
                           field_label="Noise level", raw_value="95", unit="dB(A)", page=1)
    _, _, state = _go(sub, scope)
    assert state == "done"


def test_switch_off_is_unchanged():
    sub, scope = _world("x")
    _unread(sub)
    assert settings.nothing_read_fails_enabled is False
    run_id, _, state = _go(sub, scope)
    assert state == "done"
    assert _run_row(run_id)["status"] == "completed"
