"""#436: deleting a document erases its text and filename from the rows that
outlive it (owner decision 8 Oct).

Before: chat answers, their payload passages, report snapshots, the filename
copies in `report_documents` and `watch_events` all kept the document's words
after `DELETE /api/documents/{id}`.

Now the delete rewrites them in its own transaction; a report keeps its row,
its snapshot hash is recomputed, and an audit row records old and new hash.
Names and text are invented sentinels.
"""
from __future__ import annotations

import json

from app import document_refs, reports
from app.db import connect

from tests.r2_security_support import h, temp_storage, world  # noqa: F401

FILE = "SUBMITTAL-A-001.pdf"
QUOTE = "SENTINEL-QUOTE relief valve set at 12 barg"
OTHER = "OTHER-SENTINEL standard passage"


def _seed() -> dict:
    """A conversation that quotes doc_sub and doc_std, a report over it, a
    watch-folder row, and one unrelated answer that cites doc_std only."""
    now = "2026-01-01T00:00:00Z"
    sub = {"chunk_id": "c1", "document_id": "doc_sub", "filename": FILE,
           "page_start": 4, "page_end": 4, "text": QUOTE, "section": "SENTINEL-SECTION"}
    std = {"chunk_id": "c2", "document_id": "doc_std", "filename": "STD-A-001.pdf",
           "page_start": 2, "page_end": 2, "text": OTHER}
    snapshot = {"answer": f"The set pressure is 12 barg ({FILE} p.4).",
                "question": f"what does {FILE} say?",
                "passages": [{**sub, "cited": True}, {**std, "cited": True}],
                "documents": [{"document_id": "doc_sub", "filename": FILE},
                              {"document_id": "doc_std", "filename": "STD-A-001.pdf"}]}
    body = reports._canonical(snapshot)
    with connect() as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at)"
                     " VALUES ('cv1', ?, ?, ?)", (f"Ask about {FILE}", now, now))
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " resolved_question, created_at) VALUES ('m1','cv1',1,'user',?,?,?)",
                     (f"what does {FILE} say?", f"what does {FILE} say?", now))
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " answer_type, payload, created_at) VALUES"
                     " ('m2','cv1',2,'assistant',?,'generated',?,?)",
                     (snapshot["answer"], json.dumps({"passages": [sub, std], "cited": [1, 2]}), now))
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " answer_type, payload, created_at) VALUES"
                     " ('m3','cv1',3,'assistant','Only the standard says so.','generated',?,?)",
                     (json.dumps({"passages": [std], "cited": [1]}), now))
        conn.execute(
            "INSERT INTO reports (id, created_at, message_id, conversation_id, auth_mode,"
            " scope_document_ids, question, resolved_question, snapshot_json,"
            " snapshot_sha256, config_version, renderer, template_version, report_sha256,"
            " size_bytes, page_count) VALUES ('rpt1', ?, 'm2', 'cv1', 'required', '[]',"
            " ?, ?, ?, ?, 'c', 'r', 't', 'x', 1, 1)",
            (now, snapshot["question"], snapshot["question"], body.decode("utf-8"),
             reports._sha(body)))
        for doc, name in (("doc_sub", FILE), ("doc_std", "STD-A-001.pdf")):
            conn.execute("INSERT INTO report_documents (report_id, document_id, filename,"
                         " sha256) VALUES ('rpt1', ?, ?, 'h')", (doc, name))
        conn.execute("INSERT INTO watch_events (filename, source_path, sha256, observed_at,"
                     " outcome, document_id) VALUES (?, ?, 'h', ?, 'ingested', 'doc_sub')",
                     (FILE, f"/drop/{FILE}", now))
    return {"old_sha": reports._sha(body)}


def _every_text_cell() -> str:
    conn = connect()
    out = []
    for table in ("messages", "conversations", "reports", "report_documents", "watch_events"):
        for row in conn.execute(f"SELECT * FROM {table}"):
            out += [str(v) for v in tuple(row) if v is not None]
    return "\n".join(out)


def test_a_delete_leaves_no_copy_of_the_documents_text_or_name(world):
    seeded = _seed()
    assert QUOTE in _every_text_cell() and FILE in _every_text_cell()

    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_admin"))
    assert r.status_code == 200, r.text

    left = _every_text_cell()
    for leaked in (QUOTE, FILE, "SENTINEL-SECTION", "12 barg"):
        assert leaked not in left, f"{leaked!r} survived the delete"
    assert OTHER in left, "the other document's passage must stay"
    assert connect().execute("SELECT text FROM messages WHERE id='m3'").fetchone()[0] \
        == "Only the standard says so.", "an answer that never cited it is untouched"

    payload = json.loads(connect().execute(
        "SELECT payload FROM messages WHERE id='m2'").fetchone()[0])
    sub, std = payload["passages"]
    assert sub["document_id"] == "doc_sub" and sub["chunk_id"] == "c1"
    assert sub["page_start"] == 4, "ids and page numbers stay"
    assert sub["text"] == document_refs.ERASED
    assert std["text"] == OTHER

    report = connect().execute("SELECT * FROM reports WHERE id='rpt1'").fetchone()
    assert report is not None, "the record that a report was issued stays"
    assert reports._sha(report["snapshot_json"].encode("utf-8")) == report["snapshot_sha256"]
    assert report["snapshot_sha256"] != seeded["old_sha"]
    (audit,) = connect().execute(
        "SELECT resource_id, detail FROM audit_events WHERE action='report.redacted'").fetchall()
    assert audit["resource_id"] == "rpt1"
    assert f"old={seeded['old_sha']}" in audit["detail"]
    assert f"new={report['snapshot_sha256']}" in audit["detail"]
    assert FILE not in audit["detail"]

    counts = r.json()["rows_removed"]
    assert counts["erased_reports"] == 1 and counts["erased_messages"] >= 2


def test_a_refused_delete_erases_nothing(world, monkeypatch):
    """The erase runs inside the delete's transaction: no delete, no erase."""
    _seed()
    r = world.delete("/api/documents/doc_sub", headers=h("u_admin"))   # no confirm
    assert r.status_code == 400
    assert QUOTE in _every_text_cell() and FILE in _every_text_cell()


def test_scrub_keeps_ids_and_numbers_and_cuts_the_filename_elsewhere():
    value = {"a": [{"document_id": "d", "chunk_id": "c", "page": 3, "text": "x",
                    "nested": {"quote": "y"}}],
             "note": "see F.pdf p.3", "keep": "nothing to do"}
    out = document_refs._scrub(value, "d", "F.pdf")
    item = out["a"][0]
    assert item["chunk_id"] == "c" and item["page"] == 3
    assert item["text"] == item["nested"]["quote"] == document_refs.ERASED
    assert out["note"] == f"see {document_refs.ERASED} p.3"
    assert out["keep"] == "nothing to do"
