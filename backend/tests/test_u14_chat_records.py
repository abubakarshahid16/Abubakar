"""Chat answers questions about the app's RECORDS by code, on both engines (lead-4, 26 Nov 2026, G7): which reviews are signed, a
paper's review counts with its engine and rough-draft label, and a list of papers by kind. Each answer has its count and boundary,
is drawn only from the reader's read set (rule 5), and no model is asked. A records question it cannot answer says so, never an
essay. Invented papers and values only. (Technical queries: `test_u14_chat_records_tq.py`.)"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_records as R
from app import db
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - the fixture
from tests.test_chat_claude_first import _on, _scripted, _text

pytestmark = pytest.mark.usefixtures("temp_storage")


def _doc(
    doc_id: str, filename: str, kind: str | None, role: str = "CONTRACTOR_SUBMITTAL"
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?, ?, ?, 1, ?, 'ready', '2026-11-25T00:00:00Z')",
            (doc_id, filename, (doc_id * 8)[:64], f"/nowhere/{doc_id}"),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, title, suggested_by) VALUES (?, ?, ?, 'test')",
            (doc_id, role, filename.rsplit(".", 1)[0]),
        )
        if kind:
            conn.execute(
                "INSERT INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, ?, 'routed', '2026-11-25T00:00:00Z')",
                (doc_id, kind),
            )


def _entry(
    run: str,
    doc: str,
    name: str,
    *,
    signed: bool,
    engine: str = "claude",
    newer: str | None = None,
) -> dict:
    words = (
        "Claude"
        if engine == "claude"
        else "Local model: rough draft, not scored as reliable"
    )
    return {
        "review_run_id": run, "submittal_document_id": doc, "submittal_filename": name, "status": "completed",
        "completed_at": "2026-11-20T10:00:00Z", "engine": engine, "engine_words": words, "face": True,
        "general_signoff": "signed" if signed else "not_signed", "equipment_tags": ["invented widget"],
        "general_counts": {"points": 12, "comments": 5, "confirmations": 2}, "newer_note": newer,
    }  # fmt: skip


@pytest.fixture
def records(monkeypatch):
    """Two reviewed papers the reader may read (one signed, one a local rough draft) and one they may not."""
    from app import aim_review_runs

    monkeypatch.setattr(settings, "chat_database_tools_enabled", True)
    rows = [
        _entry("run-invented-a-0001", "doc_a", "INV-WIDGET-A.pdf", signed=True),
        _entry(
            "run-invented-b-0002",
            "doc_b",
            "INV-PUMPLET-B.pdf",
            signed=False,
            engine="local",
        ),
        _entry("run-invented-c-0003", "doc_c", "INV-SECRET-C.pdf", signed=True),
    ]

    def entries(conn, allowed, document_id=None, *, newest_only=False):
        return [e for e in rows if e["submittal_document_id"] in allowed]

    monkeypatch.setattr(aim_review_runs, "entries", entries)
    return frozenset({"doc_a", "doc_b"})  # doc_c: the reader may not read it


@pytest.mark.parametrize(
    "question, kind",
    [
        ("which reviews are signed", R.SIGNED),
        ("Which reviews have been signed off?", R.SIGNED),
        ("how many comments on the valve review", R.PAPER_REVIEW),
        ("show me the latest review of the pump", R.PAPER_REVIEW),
        ("list the queries waiting for evidence", R.WAITING_EVIDENCE),
        ("Which TQs are still waiting for their evidence?", R.WAITING_EVIDENCE),
        ("list the datasheets", R.LIST_KIND),
        ("how many datasheets do we have", R.LIST_KIND),
        ("which TQs are open", R.UNANSWERED),
        ("what is the operating pressure in the datasheet", None),
        ("what is the design pressure", None),
        ("review these papers", None),
        ("which standards apply to the valve", None),
        ("list the standards", None),
    ],
)
def test_which_questions_are_records_questions(records, question, kind):
    assert R.kind_of(question) == kind


def test_with_the_switch_off_no_records_question_is_answered_not_even_the_list_by_kind(monkeypatch):
    """Review of #1926: off, Chat goes on exactly as before for EVERY records question, the list by kind included (it had no
    document id to withhold and took over questions about picked papers)."""
    monkeypatch.setattr(settings, "chat_database_tools_enabled", False)
    for q in (
        "which reviews are signed",
        "how many comments on the valve review",
        "list the queries waiting for evidence",
        "list the datasheets",
        "what do the procedures say about hydrotest pressure",
    ):
        assert R.kind_of(q) is None, q  # Chat goes on exactly as before


def test_signed_reviews_are_counted_with_their_boundary_and_only_readable_papers(
    records,
):
    text = R.signed_reviews(records)
    assert text.startswith(
        "1 of 2 finished reviews is signed, of the papers you may read."
    )
    assert "INV-WIDGET-A.pdf" in text and "run-inve" in text and "5 comments" in text
    assert "SECRET" not in text  # rule 5: a paper outside the read set is never named


def test_a_papers_review_gives_its_counts_engine_and_signed_state(records):
    text = R.paper_review("how many comments on the widget review", records)
    assert (
        "INV-WIDGET-A.pdf (invented widget)" in text
        and "(Claude)" in text
        and "signed by an engineer" in text
    )
    assert (
        "12 points, 5 comments, 2 to confirm" in text
        and "of the papers you may read" in text
    )


def test_a_local_review_is_named_a_rough_draft(records):
    text = R.paper_review("how many comments on the pumplet review", records)
    assert (
        "rough draft, not scored as reliable" in text
        and "AI, to be checked (not signed)" in text
    )


def test_a_paper_outside_the_read_set_is_never_answered(records):
    text = R.paper_review("how many comments on the secret review", records)
    assert text.startswith(R.CANNOT) and "SECRET" not in text


def test_the_datasheets_are_listed_by_kind_not_counted_as_submittals():
    _doc("doc_d1", "INV-DS-1.pdf", "datasheet")
    _doc("doc_d2", "INV-DS-2.pdf", "datasheet")
    _doc("doc_p1", "INV-PROC-1.pdf", "procedure")
    _doc("doc_x", "INV-SUBMITTAL-NOKIND.pdf", None)
    _doc("doc_hidden", "INV-DS-HIDDEN.pdf", "datasheet")
    text = R.papers_by_kind(
        "list the datasheets", frozenset({"doc_d1", "doc_d2", "doc_p1", "doc_x"})
    )
    assert text.startswith("2 datasheets, of the papers you may read")
    assert "INV-DS-1" in text and "INV-DS-2" in text and "INV-PROC-1" not in text
    assert "1 of the papers you may read have no kind recorded yet" in text
    assert "HIDDEN" not in text  # rule 5


def test_chat_answers_a_records_question_by_code_on_the_local_engine_and_on_claude(
    records, monkeypatch, tmp_path
):
    for doc, name in (
        ("doc_a", "INV-WIDGET-A.pdf"),
        ("doc_b", "INV-PUMPLET-B.pdf"),
        ("doc_c", "INV-SECRET-C.pdf"),
    ):
        _doc(
            doc, name, "datasheet"
        )  # with sign-in off the reader may read every paper (the API's own read set)
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("A model essay.")], calls)
    client = TestClient(app)
    for model in ("local", "claude"):
        convo = client.post("/api/conversations").json()["id"]
        got = client.post(
            f"/api/conversations/{convo}/ask",
            json={"question": "which reviews are signed", "model": model},
        ).json()
        assert got["answer_type"] == "metadata" and got["answer"].startswith(
            "2 of 3 finished reviews are signed, of the papers you may read."
        )  # unrestricted
        assert got["used_line"].startswith(
            "Read from the app's records, not from document text"
        )
    assert calls == []  # no model was asked, and nothing reached Claude


def test_a_records_question_it_cannot_answer_says_so_never_an_essay(
    records, monkeypatch, tmp_path
):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("A model essay.")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    got = client.post(
        f"/api/conversations/{convo}/ask",
        json={"question": "which TQs are open", "model": "local"},
    ).json()
    assert got["answer"].startswith(R.CANNOT) and calls == []


def test_the_coverage_line_counts_the_passages_an_answer_quotes():
    """Found on the practice copy (26 Nov 2026): an extract answer quoting one selected paper said "Passages read from 0 of 10"."""
    from app import chat_coverage

    for doc, name in (("doc_q1", "INV-Q1.pdf"), ("doc_q2", "INV-Q2.pdf")):
        _doc(doc, name, "datasheet")
    result = {"passages": [], "answer_passages": [{"document_id": "doc_q1"}]}
    got = chat_coverage.attach(
        result,
        "what is the invented value",
        frozenset({"doc_q1", "doc_q2"}),
        chat_coverage.sources_of(result),
    )
    assert got["paper_coverage"]["read"] == 1 and got["paper_coverage"][
        "sentence"
    ].startswith("Passages read from 1 of 2")
