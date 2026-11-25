"""Picture reading as an upload-worker stage, never inside a review (#1905). The Claude transport is a FAKE that counts and records what would
leave: no network. Invented values only."""

from __future__ import annotations

import pymupdf
import pytest

from app import claude_spend, db, ocr, page_ledger, picture_stage, vision_reader
from app import reasoning_provider as rp
from app.aim_review import unread as U
from app.aim_review.paper import load_paper
from app.config import settings
from tests.test_aim_method_helpers import _doc, open_aim_db
from tests.test_chat_pr1_model_lane import KEY

MODEL = "claude-sonnet-5"
LONG = "Design pressure of the invented test item is stated here in full words."
TEXT = (
    "Invented printed words that a person can read on this page of the invented sheet."
)
DOC = "doc_stage"


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


class Wire:
    """The fake transport: records every request body, answers with `reply`, or raises `error`."""

    def __init__(self, reply: str = TEXT, error: Exception | None = None):
        self.bodies, self.reply, self.error = [], reply, error

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(body)
        if self.error:
            raise self.error
        return {"model": MODEL, "stop_reason": "end_turn", "content": [{"type": "text", "text": self.reply}],
                "usage": {"input_tokens": 1500, "output_tokens": 40}}  # fmt: skip


def _claude(monkeypatch, wire):
    monkeypatch.setattr(
        vision_reader,
        "provider",
        lambda: (rp.ClaudeProvider(MODEL, transport=wire), None),
    )


def _stored(conn, tmp_path, pages=3, blank=(2,)):
    """A held PDF of `pages` pages; the pages in `blank` have no text and no scan flag."""
    path = tmp_path / "sheet.pdf"
    pdf = pymupdf.open()
    for _ in range(pages):
        pdf.new_page()
    pdf.save(str(path))
    pdf.close()
    with conn:
        _doc(
            conn,
            DOC,
            "invented.pdf",
            "CONTRACTOR_SUBMITTAL",
            {n: ("" if n in blank else LONG) for n in range(1, pages + 1)},
        )
        conn.execute(
            "UPDATE documents SET stored_path = ?, page_count = ? WHERE id = ?",
            (str(path), pages, DOC),
        )
    return DOC


def test_a_page_with_no_text_is_read_stored_as_recognised_text_and_counts_as_read_in_the_ledger(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path)
    wire = Wire()
    _claude(monkeypatch, wire)
    assert picture_stage.wanted(doc) is True
    counts = picture_stage.run(doc)
    assert counts[picture_stage.READ] == 1 and len(wire.bodies) == 1
    blocks = wire.bodies[0]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count(
        "image"
    ) == 1  # ONE page image, nothing else of any document
    row = aim_db.execute(
        "SELECT text, engine FROM page_ocr WHERE document_id = ? AND page_no = 2",
        (doc,),
    ).fetchone()
    assert row["text"] == TEXT and row["engine"] == picture_stage.ENGINE
    page_ledger.refresh(doc)
    ledger = aim_db.execute(
        "SELECT ocr_status FROM page_ledger WHERE document_id = ? AND page_no = 2",
        (doc,),
    ).fetchone()
    assert (
        ledger["ocr_status"] == "done"
    )  # the page counts as read because text came back
    paper = load_paper(aim_db, doc)
    assert paper.pages[2] == TEXT and paper.sources[2] == "recognised_text"
    paper = U.with_unread(aim_db, doc, paper, load_paper)
    assert paper.unread == []
    assert (
        picture_stage.wanted(doc) is False
    )  # asked once: the page has its record and its text


def test_a_failed_reading_is_recorded_said_on_the_page_and_never_counted_as_read(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path)
    _claude(monkeypatch, Wire(error=RuntimeError("the transport is down")))
    counts = picture_stage.run(doc)
    assert counts[picture_stage.REFUSED] == 1 and counts[picture_stage.READ] == 0
    assert (
        aim_db.execute(
            "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ?", (doc,)
        ).fetchone()["c"]
        == 0
    )
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [("page 2", U.REFUSED)]
    assert (
        "refused" in U.sentence("page 2", U.REFUSED)
        and picture_stage.wanted(doc) is False
    )  # not asked again in a loop


def test_a_picture_that_holds_no_text_stays_not_read(aim_db, tmp_path, monkeypatch):
    doc = _stored(aim_db, tmp_path)
    _claude(monkeypatch, Wire(reply="[no text]"))
    assert picture_stage.run(doc)[picture_stage.NO_TEXT] == 1
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.NO_TEXT_AFTER)
    ]


def test_nothing_is_asked_when_the_page_image_reader_is_not_switched_to_claude(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path)
    monkeypatch.setattr(
        vision_reader, "provider", lambda: (None, "the page-image reader is local")
    )
    assert picture_stage.wanted(doc) is False
    assert sum(picture_stage.run(doc).values()) == 0
    assert picture_stage.recorded(aim_db, doc) == {}


def test_a_page_still_waiting_for_local_recognition_is_not_a_target_and_holds_the_stage_back(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path, pages=3, blank=(2, 3))
    with aim_db:
        aim_db.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = ? AND page_no = 2",
            (doc,),
        )
    _claude(monkeypatch, Wire())
    assert picture_stage.targets(aim_db, doc) == [3]
    assert (
        picture_stage.wanted(doc) is False
    )  # local recognition still has a page to read: it goes first


def test_the_gate_asks_before_every_call_a_document_not_on_the_approved_list_is_not_sent(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    wire = Wire()
    _claude(monkeypatch, wire)
    counts = picture_stage.run(doc)
    assert wire.bodies == [] and counts[picture_stage.REFUSED] == 1


def test_at_most_the_limit_of_pages_is_read_in_one_pass_and_the_rest_say_so(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path, pages=5, blank=(1, 2, 3, 4, 5))
    monkeypatch.setattr(picture_stage, "MAX_PAGES", 2)
    wire = Wire()
    _claude(monkeypatch, wire)
    counts = picture_stage.run(doc)
    assert (
        len(wire.bodies) == 2
        and counts[picture_stage.READ] == 2
        and counts[picture_stage.CAPPED] == 3
    )
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 3", U.CAPPED),
        ("page 4", U.CAPPED),
        ("page 5", U.CAPPED),
    ]


def test_a_review_never_reads_a_picture_it_only_names_the_pages_not_read(
    aim_db, tmp_path, monkeypatch
):
    doc = _stored(aim_db, tmp_path)
    monkeypatch.setattr(
        picture_stage,
        "_transcribe",
        lambda *a, **k: pytest.fail("a review must not read a picture"),
    )
    monkeypatch.setattr(
        ocr,
        "recognise_document",
        lambda *a, **k: pytest.fail("a review must not run recognition"),
    )
    paper = U.with_unread(
        aim_db, doc, load_paper(aim_db, doc), lambda *a: pytest.fail("no reload")
    )
    assert [(i["where"], i["why"]) for i in paper.unread] == [("page 2", U.NO_TEXT)]


def test_the_ingest_worker_runs_the_stage_after_local_recognition_and_before_embedding():
    """The hook is in the worker's PARTIALLY_SEARCHABLE branch, once recognition has nothing pending and before the embedding step."""
    import inspect

    from app import ingest

    src = inspect.getsource(ingest.IngestionWorker.process)
    assert (
        src.index("ocr.pending_pages(doc_id)")
        < src.index("picture_stage.wanted(doc_id)")
        < src.index("self._needs_embedding(doc_id)")
    )
    assert (
        "self._set_state(doc_id, states.CHUNKING)"
        in src[src.index("picture_stage.wanted(doc_id)") :]
    )


def test_the_same_page_read_again_is_never_asked_twice(aim_db, tmp_path, monkeypatch):
    doc = _stored(aim_db, tmp_path)
    wire = Wire()
    _claude(monkeypatch, wire)
    picture_stage.run(doc)
    picture_stage.run(doc)
    assert (
        len(wire.bodies) == 1
        and [e["finish_reason"] for e in claude_spend.entries()][-1] != "cache_hit"
    )
    assert db.connect() is not None


def test_the_worker_reads_the_picture_page_re_chunks_it_and_the_document_stays_answerable(
    tmp_path, monkeypatch
):
    """The whole stage through the real ingest worker: upload, the stage reads the blank page, its words reach a chunk."""
    from fastapi.testclient import TestClient

    from app import states
    from app.ingest import IngestionWorker
    from app.main import app
    from tests.test_ocr import _InlinePool  # noqa: F401 - the same stand-in the OCR stage tests use

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w.sqlite")
    db.reset_connection()
    db.init_db()
    pdf = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    doc.new_page()  # no text, no scan
    page = doc.new_page()
    page.insert_text((72, 100), "Section 3.0 Application", fontsize=13)
    page.insert_text(
        (72, 130), "The quick brown fox jumps over the lazy dog. " * 5, fontsize=9
    )
    doc.save(str(pdf))
    doc.close()
    with open(pdf, "rb") as fh:
        doc_id = (
            TestClient(app)
            .post(
                "/api/documents", files={"file": ("mixed.pdf", fh, "application/pdf")}
            )
            .json()["document"]["id"]
        )
    _claude(
        monkeypatch,
        Wire(
            reply="Picture words: the relief valve set pressure is twelve bar gauge on this sheet."
        ),
    )
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(
        ocr,
        "recognise_batch",
        lambda sp, sha, pages: [
            (p, "", None, None, 0, 0, 0.0, 0, "", None) for p in pages
        ],
    )  # local recognition finds nothing
    IngestionWorker().process(doc_id)
    conn = db.connect()
    row = conn.execute(
        "SELECT status, error_message FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["status"] != states.FAILED, row["error_message"]
    read = conn.execute(
        "SELECT text, engine FROM page_ocr WHERE document_id = ? AND engine = ?",
        (doc_id, picture_stage.ENGINE),
    ).fetchall()
    assert [r["text"] for r in read] == [
        "Picture words: the relief valve set pressure is twelve bar gauge on this sheet."
    ]
    assert (
        conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE document_id = ? AND text LIKE '%relief valve set pressure%'",
            (doc_id,),
        ).fetchone()["c"]
        > 0
    )
