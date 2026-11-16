"""The older per-review CRS files behind a switch (owner order, 16 Nov 2026).

"Old CRS download without the count line ... hide it behind a switch (off) so only the new one-CRS file is offered. Do not
delete code." The older files (`GET /api/reviews/runs/{id}/crs`, the AI review's stored `GET /api/reviews/runs/{id}/agent/crs`)
do not state "N points reviewed, N in this file". While the redesigned page is on and `old_crs_download_enabled` is off, both
refuse with one plain sentence and the page's status says they are not offered. On, the file is the same bytes as before.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app import crs_copy_words
from app.config import settings
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)


def _old_file(client, run_id: str):
    return client.get(f"/api/reviews/runs/{run_id}/crs", params={"copy": "internal"})


@pytest.fixture(autouse=True)
def ai_reviewer_on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)  # the AI review's routes answer only with their own switch on


def _cells(data: bytes) -> list:
    book = load_workbook(io.BytesIO(data))
    return [(ws.title, [[c.value for c in row] for row in ws.iter_rows()]) for ws in book.worksheets]


def _paper_with_run():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    return doc, run


def test_the_switch_is_off_by_default():
    assert type(settings).model_fields["old_crs_download_enabled"].default is False


def test_off_with_the_new_page_on_the_old_file_is_refused_with_the_sentence(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", False)
    doc, run = _paper_with_run()
    client = _client(doc)
    got = _old_file(client, run)
    assert got.status_code == 404
    assert got.json()["detail"]["message"] == crs_copy_words.OLD_FILE_OFF
    assert "spreadsheet" not in got.headers.get("content-type", "")
    agent = client.get(f"/api/reviews/runs/{run}/agent/crs", params={"copy": "internal"})
    assert agent.status_code == 404 and agent.json()["detail"]["message"] == crs_copy_words.OLD_FILE_OFF
    assert client.get("/api/reviews/page-v2").json() == {"enabled": True, "old_crs_download": False}


def test_on_the_old_file_is_served_as_before_the_same_cells_as_with_the_new_page_off(monkeypatch):
    doc, run = _paper_with_run()
    client = _client(doc)
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    before = _old_file(client, run)
    assert before.status_code == 200 and before.content[:2] == b"PK"
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    on = _old_file(client, run)
    assert on.status_code == 200
    assert on.headers["content-disposition"] == before.headers["content-disposition"]
    assert _cells(on.content) == _cells(before.content)  # every sheet, every cell: the same file as before
    assert client.get("/api/reviews/page-v2").json() == {"enabled": True, "old_crs_download": True}
    # the AI review's older file is no longer refused by the switch (this run has none: the route's own 404, not the sentence)
    agent = client.get(f"/api/reviews/runs/{run}/agent/crs", params={"copy": "internal"})
    assert crs_copy_words.OLD_FILE_OFF not in agent.text


def test_with_the_new_page_off_there_is_no_one_crs_so_the_old_file_stays(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    monkeypatch.setattr(settings, "old_crs_download_enabled", False)
    doc, run = _paper_with_run()
    client = _client(doc)
    assert _old_file(client, run).status_code == 200
    assert client.get("/api/reviews/page-v2").json() == {"enabled": False, "old_crs_download": True}


def test_a_wrong_copy_word_is_still_422_and_the_issue_copy_still_goes_through_post(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    doc, run = _paper_with_run()
    client = _client(doc)
    assert client.get(f"/api/reviews/runs/{run}/crs", params={"copy": "nope"}).status_code == 422
    assert client.get(f"/api/reviews/runs/{run}/crs", params={"copy": "issue"}).status_code == 409
