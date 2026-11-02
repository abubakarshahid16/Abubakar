"""#1494 follow-up (live I-06 review): the words of a running review's progress.

A procedure (or any non-datasheet) review never says "datasheet": the line
names the CONFIRMED kind, or says "document" (a suggested kind is a guess). A
Word file has no pages: its reading units are "part N of M". Invented
documents only; no model runs.
"""

from __future__ import annotations

from app import db, job_progress, review_jobs, submittal_review
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    W,
    _enqueue,
    _job,
    temp_storage,
    world,
)


def _kind(doc_id: str, kind: str, state: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, routed_at)"
            " VALUES (?, ?, ?, '2026-11-01T00:00:00Z')",
            (doc_id, kind, state),
        )


def _labels_seen(w, monkeypatch) -> list[str]:
    _run_id, job_id = _enqueue(w)
    review_jobs.claim_next(W)
    seen: list[str] = []

    def reading(*args, **kwargs):
        seen.append(_job(job_id)["progress_label"])
        for number in (1, 2):
            job_progress.page(number, 2)
            seen.append(_job(job_id)["progress_label"])

    monkeypatch.setattr(submittal_review, "ensure_facts_extracted", reading)
    assert review_jobs.run(job_id, W) == "done"
    return seen


def test_a_confirmed_procedure_review_says_procedure_never_datasheet(
    world,  # noqa: F811
    monkeypatch,
):
    _kind(world["sub"], "procedure", "confirmed")
    seen = _labels_seen(world, monkeypatch)
    assert seen == [
        "reading the procedure",
        "reading the procedure, page 1 of 2",
        "reading the procedure, page 2 of 2",
    ]
    assert review_jobs.step_label(2, ("procedure", "page")) == (
        "comparing requirements with the procedure"
    )


def test_a_suggested_or_missing_kind_says_document_not_a_guess(world, monkeypatch):  # noqa: F811
    _kind(world["sub"], "procedure", "suggested")
    assert review_jobs.document_words(world["sub"]) == ("document", "page")
    with db.connect() as conn:
        conn.execute("DELETE FROM document_kinds")
    seen = _labels_seen(world, monkeypatch)
    assert all("datasheet" not in s for s in seen)
    assert seen[1] == "reading the document, page 1 of 2"


def test_a_confirmed_datasheet_still_says_datasheet(world):  # noqa: F811
    _kind(world["sub"], "datasheet", "confirmed")
    assert review_jobs.document_words(world["sub"]) == ("datasheet", "page")


def test_a_word_file_is_read_in_parts_not_pages(world, monkeypatch):  # noqa: F811
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET pagination = 'flow' WHERE id = ?", (world["sub"],)
        )
    seen = _labels_seen(world, monkeypatch)
    assert seen[1:] == [
        "reading the document, part 1 of 2",
        "reading the document, part 2 of 2",
    ]
