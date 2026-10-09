"""#659: re-chunking a standard keeps its requirements (detach before the
delete, re-point after the insert, supersede what cannot be re-pointed).

INVENTED text. Mutations: M4961-M4968, `python scripts/mutation_check.py --phase 4961`.
"""
from __future__ import annotations

import uuid

from app import db
from app.chunker import chunk_document
from tests.test_b38_orphan_guard import (  # noqa: F401 - temp_storage is autouse
    NOW, _finding_citing, _requirement, _standard, temp_storage)

SENTENCE = ("The noise level of rotating equipment shall not exceed 90 dB(A) at one metre "
            "from the equipment surface under rated operating conditions.")


def _row(req_id):
    return dict(db.connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?", (req_id,)).fetchone())


def _audit_detail():
    rows = db.connect().execute(
        "SELECT detail FROM audit_events WHERE action = 'requirements.rechunked'").fetchall()
    return [r["detail"] for r in rows]


def _on_an_old_chunk(std, *, text, requirement_type=None, confirmed=False, superseded=False):
    """A requirement pointing at a chunk whose id will NOT exist after a re-chunk."""
    req = _requirement(std)
    old = f"old-{uuid.uuid4().hex[:8]}"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,kind,text,"
            "token_count,content_hash,retrievable) VALUES (?,?,?,?,1,1,'prose',?,5,?,0)",
            (old, std, "std.pdf", 90, "old chunk text", f"h-{old}"))
        user = None
        if confirmed:
            user = str(uuid.uuid4())
            conn.execute("INSERT INTO users (id,email,display_name,password_hash,created_at)"
                         " VALUES (?,?,'E','x',?)", (user, f"{user}@example.test", NOW))
        conn.execute(
            "UPDATE standard_requirements SET chunk_id = ?, requirement_text = ?,"
            " requirement_type = ?, confirmed_by = ?, superseded_at = ? WHERE id = ?",
            (old, text, requirement_type, user, NOW if superseded else None, req))
    return req


def test_a_requirement_on_an_unchanged_chunk_keeps_its_link_through_a_re_chunk():
    std = _standard()
    req = _requirement(std)
    chunk_before = _row(req)["chunk_id"]
    chunk_document(std, force=True)
    row = _row(req)
    assert row["chunk_id"] == chunk_before and row["superseded_at"] is None
    assert "same_chunk=1" in _audit_detail()[0]


def test_a_requirement_whose_chunk_changed_is_repointed_to_the_chunk_that_holds_its_sentence():
    std = _standard()
    req = _on_an_old_chunk(std, text=SENTENCE)
    chunk_document(std, force=True)
    row = _row(req)
    new_ids = {r["id"] for r in db.connect().execute("SELECT id FROM chunks WHERE document_id = ?", (std,))}
    assert row["chunk_id"] in new_ids and row["superseded_at"] is None
    assert "repointed=1" in _audit_detail()[0]


def test_an_unconfirmed_requirement_with_no_chunk_to_go_to_is_superseded_not_deleted():
    std = _standard()
    req = _on_an_old_chunk(std, text="A sentence that is nowhere in the new chunks of this standard at all.")
    _finding_citing(std, req)
    chunk_document(std, force=True)
    row = _row(req)                                  # still there
    assert row["superseded_at"] is not None and row["chunk_id"] is None
    assert row["superseded_by_run"].startswith("xrun_rechunk_")
    assert db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE requirement_id = ?", (req,)).fetchone()[0] == 1
    assert "superseded=1" in _audit_detail()[0] and "findings_citing_superseded=1" in _audit_detail()[0]


def test_a_confirmed_requirement_is_never_superseded_by_a_re_chunk():
    std = _standard()
    req = _on_an_old_chunk(std, text="A confirmed sentence that is nowhere in the new chunks at all.",
                           confirmed=True)
    chunk_document(std, force=True)
    row = _row(req)
    assert row["superseded_at"] is None and row["confirmed_by"] is not None
    assert row["chunk_id"] is None                  # honest: no chunk to resolve to
    assert "confirmed_unlinked=1" in _audit_detail()[0]


def test_a_table_cell_that_loses_its_chunk_is_superseded_for_the_next_extraction_to_rewrite():
    std = _standard()
    req = _on_an_old_chunk(std, text="Fan - Speed: 900", requirement_type="table_value")
    chunk_document(std, force=True)
    assert _row(req)["superseded_at"] is not None


def test_a_requirement_already_superseded_stays_as_history():
    std = _standard()
    req = _on_an_old_chunk(std, text="An old sentence that is gone from every chunk of the standard.",
                           superseded=True)
    chunk_document(std, force=True)
    row = _row(req)
    assert row["superseded_at"] == NOW and row["superseded_by_run"] is None     # untouched
    assert "history_unlinked=1" in _audit_detail()[0]


def test_a_standard_with_no_requirements_re_chunks_and_writes_no_record():
    std = _standard()
    chunk_document(std, force=True)
    assert _audit_detail() == []
