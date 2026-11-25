# ruff: noqa: F811
"""Pages local recognition cannot read are read as PICTURES by Claude, through the one approved path only (#1905). The Claude transport is
a FAKE that counts and records what would leave: no network. Invented values only."""

from __future__ import annotations

import pymupdf
import pytest

from app import claude_spend, db, vision_reader
from app import reasoning_provider as rp
from app.aim_review import picture_pages as P
from app.aim_review import unread as U
from app.aim_review.paper import FROM_PICTURE, Paper
from app.config import settings
from tests.test_aim_method_helpers import _doc
from tests.test_chat import temp_storage  # noqa: F401 - fixture
from tests.test_chat_pr1_model_lane import KEY

MODEL = "claude-sonnet-5"
TEXT = (
    "Invented printed words that a person can read on this page of the invented sheet."
)


@pytest.fixture(autouse=True)
def _lane(temp_storage, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / tmp_path.name)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def blank_pdf(tmp_path, pages: int) -> str:
    path = tmp_path / "sheet.pdf"
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return str(path)


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


def paper(*unread_pages: int, why=U.NO_TEXT_AFTER) -> Paper:
    p = Paper(paper_id="doc_u1", pages={1: TEXT})
    p.unread = [{"where": f"page {n}", "why": why} for n in unread_pages]
    return p


def provider(wire: Wire):
    return rp.ClaudeProvider(MODEL, transport=wire)


def test_a_page_with_no_text_after_recognition_is_read_as_a_picture_and_counts_as_read(
    tmp_path,
):
    wire = Wire()
    got = P.read("doc_u1", paper(2), blank_pdf(tmp_path, 3), provider(wire))
    assert got.pages[2] == TEXT and got.sources[2] == FROM_PICTURE and got.unread == []
    assert len(wire.bodies) == 1
    blocks = wire.bodies[0]["messages"][0]["content"]
    assert [b["type"] for b in blocks].count(
        "image"
    ) == 1  # ONE page image, nothing else of any document


def test_only_the_papers_own_unread_pages_are_asked_never_a_page_that_has_text_or_is_still_waiting(
    tmp_path,
):
    wire = Wire()
    p = paper(2)
    p.unread.append(
        {"where": "page 3", "why": U.WAITING}
    )  # local recognition may still read it, for free
    got = P.read("doc_u1", p, blank_pdf(tmp_path, 3), provider(wire))
    assert len(wire.bodies) == 1 and [i["where"] for i in got.unread] == ["page 3"]


def test_nothing_is_asked_when_the_page_image_reader_is_not_switched_to_claude(
    tmp_path, monkeypatch
):
    wire = Wire()
    monkeypatch.setattr(
        vision_reader, "provider", lambda: (None, "the page-image reader is local")
    )
    got = P.read("doc_u1", paper(2), blank_pdf(tmp_path, 3))
    assert wire.bodies == [] and [i["where"] for i in got.unread] == ["page 2"]
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "vision_reader_engine", "ollama")
    monkeypatch.undo()  # the real provider() under per_task with the vision engine local is closed: asked below
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "vision_reader_engine", "ollama")
    assert vision_reader.provider()[0] is None


def test_a_picture_that_holds_no_text_stays_not_read(tmp_path):
    wire = Wire(reply="[no text]")
    got = P.read("doc_u1", paper(2), blank_pdf(tmp_path, 3), provider(wire))
    assert [i["where"] for i in got.unread] == ["page 2"] and 2 not in got.pages


def test_a_refusal_never_raises_and_leaves_the_pages_unread_with_the_reason(tmp_path):
    wire = Wire(error=RuntimeError("the transport is down"))
    got = P.read("doc_u1", paper(2, 3), blank_pdf(tmp_path, 4), provider(wire))
    assert [(i["where"], i["why"]) for i in got.unread] == [
        ("page 2", U.REFUSED),
        ("page 3", U.REFUSED),
    ]
    assert (
        len(wire.bodies) == 1
    )  # it stopped at the first refusal: no later page was sent
    assert "refused" in U.sentence("page 2", U.REFUSED)


def test_at_most_the_limit_of_pages_is_asked_and_the_rest_say_so(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "MAX_PAGES", 2)
    wire = Wire()
    got = P.read("doc_u1", paper(2, 3, 4, 5), blank_pdf(tmp_path, 6), provider(wire))
    assert len(wire.bodies) == 2 and [(i["where"], i["why"]) for i in got.unread] == [
        ("page 4", U.CAPPED),
        ("page 5", U.CAPPED),
    ]


def test_the_runs_approved_list_decides_the_paper_is_not_sent_unless_it_is_on_it(
    tmp_path, monkeypatch
):
    """The gate asks before every call: with the list enforced and the paper not on it, nothing leaves (transport never called)."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    wire = Wire()
    got = P.read("doc_u1", paper(2), blank_pdf(tmp_path, 3), provider(wire))
    assert wire.bodies == [] and [(i["where"], i["why"]) for i in got.unread] == [
        ("page 2", U.REFUSED)
    ]


def test_the_same_page_read_again_is_served_from_the_answer_cache_at_no_cost(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    stored(
        {1: (TEXT, 0)}
    )  # the paper is a held document: only then is an answer about it kept for later
    wire = Wire()
    path = blank_pdf(tmp_path, 3)
    P.read("doc_u1", paper(2), path, provider(wire))
    P.read("doc_u1", paper(2), path, provider(wire))
    assert (
        len(wire.bodies) == 1
        and [e["finish_reason"] for e in claude_spend.entries()][-1] == "cache_hit"
    )


# ---- the plan's sentence before the start


def stored(pages: dict[int, tuple[str, int]]):
    conn = db.connect()
    with conn:
        _doc(
            conn,
            "doc_u1",
            "invented.pdf",
            "CONTRACTOR_SUBMITTAL",
            {n: t for n, (t, _f) in pages.items()},
        )
        for n, (_t, flag) in pages.items():
            conn.execute(
                "UPDATE pages SET needs_ocr = ? WHERE document_id = 'doc_u1' AND page_no = ?",
                (flag, n),
            )
    return conn


def test_the_plan_says_how_many_pages_will_be_read_as_pictures_and_the_most_it_can_cost():
    conn = stored(
        {1: (TEXT, 0), 2: ("", 0), 3: ("", 0)}
    )  # two pages with no text that no local recognition will take
    note = P.plan_note(conn, "doc_u1")
    assert note is not None and note.startswith(
        "2 pages of this paper will be read as pictures by Claude, up to USD "
    )
    assert float(note.split("USD ")[1].rstrip(".")) > 0


def test_a_page_still_waiting_for_local_recognition_is_not_counted_and_a_text_paper_says_nothing():
    conn = stored(
        {1: (TEXT, 0), 2: ("", 1)}
    )  # flagged for recognition, not yet read: it may be read for free
    assert P.plan_note(conn, "doc_u1") is None


def test_a_page_local_recognition_came_back_empty_on_is_counted():
    conn = stored({1: (TEXT, 0), 2: ("", 1)})
    with conn:
        conn.execute(
            "INSERT INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, box_count, seconds, recognised_at, batch_no)"
            " VALUES ('doc_u1', 2, '', 0, 'e', 'm', 150, 0, 0, 'x', 0)"
        )
    assert P.plan_note(conn, "doc_u1").startswith(
        "1 page of this paper will be read as a picture"[:20]
    )


def test_the_plan_says_nothing_when_the_reader_is_not_switched_to_claude(monkeypatch):
    conn = stored({1: (TEXT, 0), 2: ("", 0)})
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert P.plan_note(conn, "doc_u1") is None
