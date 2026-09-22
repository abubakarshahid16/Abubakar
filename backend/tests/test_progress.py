"""Progress: reported by the work, never inferred from a clock.

A Tier 2 answer takes 20-75 s on this hardware and the screen showed one
spinner for all of it, which reads as broken. The fix is only worth having if
what it shows is TRUE - so these tests are mostly about what it must refuse to
claim: no stage it did not reach, no percentage, and nothing about the
documents.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import progress
from app.main import app


@pytest.fixture(autouse=True)
def clean():
    progress.clear()
    yield
    progress.clear()


def test_a_stage_appears_only_after_the_work_reports_it():
    """The whole point. A client that polls early gets the stage the work is
    actually in, not the one a timer would guess it should be in."""
    progress.start("r1")
    assert progress.read("r1")["stage"] == "retrieving"

    progress.stage("r1", "generating", "3 sources")
    state = progress.read("r1")
    assert state["stage"] == "generating"
    assert state["detail"] == "3 sources"
    # reranking and reading are NOT in the history: they did not happen.
    assert [h["stage"] for h in state["history"]] == ["retrieving", "generating"]


def test_an_unknown_stage_is_refused_rather_than_displayed():
    """A typo must be an error, not a label nobody notices on screen."""
    progress.start("r1")
    with pytest.raises(ValueError, match="unknown stage"):
        progress.stage("r1", "thinking-really-hard")


def test_the_history_records_when_each_transition_happened():
    progress.start("r1")
    time.sleep(0.02)
    progress.stage("r1", "reranking")
    history = progress.read("r1")["history"]
    assert [h["stage"] for h in history] == ["retrieving", "reranking"]
    assert history[0]["at_seconds"] == 0.0
    assert history[1]["at_seconds"] > 0


def test_there_is_no_percentage_anywhere():
    """The length of a generation is unknown until it ends, so a bar would be
    an invention. A stage, a count and a clock are all true."""
    progress.start("r1")
    progress.stage("r1", "reading", "3 passages")
    state = progress.read("r1")
    assert set(state) == {"stage", "detail", "seconds", "history"}
    assert "percent" not in str(state) and "%" not in str(state)


def test_an_unknown_id_is_404_not_an_empty_state():
    """An expired or never-created entry is not 'stage: retrieving at 0s' -
    that would put a spinner on screen for work that is not happening."""
    r = TestClient(app).get("/api/progress/never-existed")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"


def test_progress_carries_no_document_content():
    """It is unauthenticated. A detail string may count passages and must
    never quote one."""
    progress.start("r1")
    progress.stage("r1", "reading", "3 passages")
    body = TestClient(app).get("/api/progress/r1").text
    assert "passages" in body
    for leak in ("NORSOK", "coating", ".pdf", "shall"):
        assert leak not in body


def test_no_progress_id_means_no_bookkeeping_and_no_error():
    """The id is optional. Without one the work behaves exactly as before."""
    progress.start(None)
    progress.stage(None, "reranking")
    progress.finish(None)
    assert progress.read("") is None


def test_entries_expire_so_an_abandoned_request_is_forgotten(monkeypatch):
    monkeypatch.setattr(progress, "TTL_SECONDS", 0)
    progress.start("old")
    progress.start("new")  # start() evicts on the way in
    assert progress.read("old") is None


def test_the_map_is_capped_so_it_cannot_grow_without_bound(monkeypatch):
    monkeypatch.setattr(progress, "MAX_ENTRIES", 5)
    for i in range(20):
        progress.start(f"r{i}")
    with progress._lock:
        assert len(progress._entries) <= 5


def test_a_real_ask_reports_every_stage_it_passed_through(monkeypatch):
    """End to end through the route, with the model stubbed.

    Asserts the ORDER of what happened, which is the only thing that makes the
    screen's stage list honest.
    """
    import pymupdf

    from app import answer as answer_mod
    from app import chat, db, keyword
    from app.config import settings

    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate([
        "5.3.2 Vibration Limits",
        "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at",
        "the bearing housing of pump P-101A during continuous operation.",
    ]):
        page.insert_text((72, 100 + i * 16), line)
    path = settings.data_dir / "spec.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()

    client = TestClient(app)
    with open(path, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": ("spec.pdf", fh, "application/pdf")}
                             ).json()["document"]["id"]
    from app.ingest import IngestionWorker
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: {
        "response": "The limit is 3.0 mm/s RMS [S1].", "done_reason": "stop"})

    conv = chat.create_conversation()
    ticket = "live-ticket"
    r = client.post(f"/api/conversations/{conv['id']}/ask",
                    json={"question": "what are the vibration limits",
                          "tier": "generated", "progress_id": ticket})
    assert r.status_code == 200, r.text

    state = progress.read(ticket)
    assert state is not None, "the record was dropped before the client could read it"
    stages = [h["stage"] for h in state["history"]]
    assert stages[0] == "retrieving"
    assert "reading" in stages
    assert stages[-1] == "done", f"the record never closed: {stages}"
    # Monotonic: a stage is never reported before the one it follows.
    assert state["history"] == sorted(state["history"], key=lambda h: h["at_seconds"])


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    from app import db, keyword
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()
