"""A result file must be able to say what it ran against.

INSTANCE NINE of "the verification that verified nothing". The stored field
was `data.get("corpus")` - a static string copied out of the questions file,
stamped on every result regardless of what was ingested. The 4,346 ms result
claims "3 documents: NORSOK, book1, book2" whether or not a fourth 1,400-page
document was present.

The consequence was not cosmetic: a reported "superlinear latency growth from
3 to 4 documents" could not be checked against the record, because no record
said which corpus it ran on. It had to be re-measured from scratch, and the
growth turned out not to exist - the change was machine state across a
40-minute gap.

These tests assert the replacement reads the DATABASE and cannot be influenced
by what the question set claims.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from app import db, keyword  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import connect  # noqa: E402

run_eval = pytest.importorskip("run_eval")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _add_document(doc_id, filename, chunks=2):
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, uploaded_at, chunk_count) VALUES (?, ?, ?, 1, 'p', 'ready',"
            " '2026-09-04T00:00:00Z', ?)",
            (doc_id, filename, doc_id, chunks),
        )
        for i in range(chunks):
            conn.execute(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
                " page_end, kind, text, token_count, content_hash, retrievable)"
                " VALUES (?, ?, ?, ?, 1, 1, 'prose', 'body text here', 3, ?, 1)",
                (f"{doc_id}:c{i}", doc_id, filename, i, f"{doc_id}:c{i}"),
            )


def test_the_stamp_counts_what_is_actually_in_the_database():
    _add_document("d1", "one.pdf", chunks=3)
    _add_document("d2", "two.pdf", chunks=5)
    observed = run_eval.observed_corpus()
    assert observed["documents"] == 2
    assert observed["chunks"] == 8
    assert observed["retrievable"] == 8
    assert sorted(observed["filenames"]) == ["one.pdf", "two.pdf"]


def test_adding_a_document_changes_the_stamp():
    """The property the old field lacked entirely: it never moved."""
    _add_document("d1", "one.pdf")
    before = run_eval.observed_corpus()
    _add_document("d2", "two.pdf")
    after = run_eval.observed_corpus()
    assert after["documents"] == before["documents"] + 1
    assert after["document_ids_sha256"] != before["document_ids_sha256"], (
        "the document-set hash did not change when a document was added"
    )
    assert after["chunks"] > before["chunks"]


def test_excluded_chunks_are_reported_separately():
    """A retrievable count that silently included excluded chunks would
    overstate what the run could actually reach."""
    _add_document("d1", "one.pdf", chunks=4)
    conn = connect()
    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'd1:c0'")
    observed = run_eval.observed_corpus()
    assert observed["chunks"] == 4
    assert observed["retrievable"] == 3
    assert observed["excluded"] == 1


def test_the_questions_file_cannot_influence_the_stamp():
    """The whole defect in one test. The old field WAS the questions file's
    claim; the new one must be unable to see it."""
    _add_document("d1", "one.pdf", chunks=2)
    observed = run_eval.observed_corpus()
    blob = repr(observed)
    assert "3 documents" not in blob
    assert observed["documents"] == 1, (
        "the stamp reported something other than the one document present"
    )


def test_machine_state_records_free_memory_and_model_residency():
    """Latency on this machine moved 1,434-4,291 ms on an unchanged corpus,
    correlating with free memory at r = 0.977. A latency figure without this
    is not reproducible."""
    state = run_eval.machine_state()
    assert "ram_percent_used" in state
    assert "ram_available_gib" in state
    assert 0 <= state["ram_percent_used"] <= 100
    # None is allowed - the daemon may not be running - but the KEY must exist,
    # so a reader can tell "not resident" from "never asked"
    assert "answer_model_resident" in state


def test_machine_state_never_raises_even_if_probing_fails(monkeypatch):
    """Provenance must not be able to fail a measurement run."""
    import builtins

    real_import = builtins.__import__

    def refuse(name, *a, **k):
        if name in ("psutil", "httpx"):
            raise ImportError(f"{name} unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", refuse)
    state = run_eval.machine_state()
    assert isinstance(state, dict)
    assert "memory_error" in state or "ram_percent_used" in state
