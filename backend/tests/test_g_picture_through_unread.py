"""Picture reading as the general review reaches it: through `unread.with_unread` (the review's own call), not `picture_pages.read` alone.
Reviewer's blocker (u8 privacy round, blocker 3): the call used the wrong arguments, raised at once and was swallowed, so no page was
ever read. A FAKE Claude transport; invented values only."""

from __future__ import annotations

import logging

import pytest

from app import claude_approved, review_engine, review_shown, vision_reader
from app import reasoning_provider as rp
from app.aim_review import picture_pages as P
from app.aim_review import unread as U
from app.aim_review.paper import FROM_PICTURE, load_paper
from app.config import settings
from tests.test_aim_method_helpers import _doc, open_aim_db
from tests.test_chat_pr1_model_lane import KEY
from tests.test_g_picture_pages import MODEL, TEXT, Wire, blank_pdf

LONG = "Design pressure of the invented test item is stated here in full words."
RUN = "aim_run_invented"


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _lane(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _stored_paper(conn, tmp_path, doc="doc_u1"):
    """A held PDF of two pages: page 1 has text, page 2 is a picture with no text and no scan flag."""
    with conn:
        _doc(conn, doc, "invented.pdf", "CONTRACTOR_SUBMITTAL", {1: LONG, 2: ""})
        conn.execute(
            "UPDATE documents SET stored_path = ?, page_count = 2 WHERE id = ?",
            (blank_pdf(tmp_path, 2), doc),
        )
    return doc


def _review(conn, doc):
    return U.with_unread(conn, doc, load_paper(conn, doc), load_paper)


def _claude(monkeypatch, wire):
    monkeypatch.setattr(
        vision_reader,
        "provider",
        lambda: (rp.ClaudeProvider(MODEL, transport=wire), None),
    )


def test_the_review_reads_a_picture_page_through_unread_and_counts_it_as_read(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored_paper(aim_db, tmp_path)
    wire = Wire()
    _claude(monkeypatch, wire)
    paper = _review(aim_db, doc)
    assert (
        paper.pages[2] == TEXT
        and paper.sources[2] == FROM_PICTURE
        and paper.unread == []
    )
    assert len(wire.bodies) == 1  # one page image went, nothing else


def test_a_picture_reading_that_raises_is_logged_and_the_page_says_it_failed_never_read_and_never_hidden(
    aim_db, tmp_path, monkeypatch, caplog
):
    doc = _stored_paper(aim_db, tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("broken reading")

    monkeypatch.setattr(P, "read", boom)
    with caplog.at_level(logging.WARNING):
        paper = _review(aim_db, doc)
    assert [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.PICTURE_FAILED)
    ]
    assert 2 not in paper.pages or paper.pages[2] != TEXT
    assert "its picture reading failed" in U.sentence("page 2", U.PICTURE_FAILED)
    assert "picture reading failed" in caplog.text


def test_a_refusal_inside_the_transport_is_said_on_the_page(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored_paper(aim_db, tmp_path)
    _claude(monkeypatch, Wire(error=RuntimeError("down")))
    assert [(i["where"], i["why"]) for i in _review(aim_db, doc).unread] == [
        ("page 2", U.REFUSED)
    ]


def test_local_only_sends_nothing_and_the_page_stays_not_read(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored_paper(aim_db, tmp_path)
    wire = Wire()
    _claude(monkeypatch, wire)
    with review_engine.barring():
        paper = _review(aim_db, doc)
    assert wire.bodies == [] and [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.REFUSED)
    ]


def test_the_runs_stored_list_decides_a_paper_not_on_it_is_not_sent_and_one_on_it_is(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored_paper(aim_db, tmp_path)
    wire = Wire()
    _claude(monkeypatch, wire)
    with aim_db:
        review_shown.record_in(
            aim_db, RUN, ["doc_other"], "2026-11-25T00:00:00Z"
        )  # a list that does not name this paper
    with claude_approved.reviewing(RUN):
        paper = _review(aim_db, doc)
    assert wire.bodies == [] and [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.REFUSED)
    ]
    with aim_db:
        review_shown.record_in(
            aim_db, RUN, [doc], "2026-11-25T00:00:00Z"
        )  # the paper is on the list: control, it goes
    with claude_approved.reviewing(RUN):
        paper = _review(aim_db, doc)
    assert len(wire.bodies) == 1 and paper.pages[2] == TEXT


def test_with_the_page_image_reader_not_on_claude_nothing_is_asked(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored_paper(aim_db, tmp_path)
    wire = Wire()
    monkeypatch.setattr(
        vision_reader, "provider", lambda: (None, "the page-image reader is local")
    )
    paper = _review(aim_db, doc)
    assert wire.bodies == [] and [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.NO_TEXT)
    ]
