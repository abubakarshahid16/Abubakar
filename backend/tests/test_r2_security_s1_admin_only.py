"""r2 S1: deleting a document and forcing the pipeline are ADMIN actions.

A READ grant lets a caller see a document; it did not stop them deleting it
(or forcing a re-chunk, which cascades into requirement rows). Mutations:
scripts/mutations/r2_security.py M1980.
"""

from __future__ import annotations

import pytest

from app import chunker, extract, keyword
from app.db import connect

from tests.r2_security_support import h, temp_storage, world  # noqa: F401

PIPELINE = ("extract", "chunk", "embed", "index-keyword")


def _exists(doc_id: str) -> bool:
    return connect().execute("SELECT 1 FROM documents WHERE id = ?",
                             (doc_id,)).fetchone() is not None


def test_a_reader_cannot_delete_a_document(world):
    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_sub"))
    assert r.status_code == 404
    assert _exists("doc_sub"), "a read grant deleted the document"


def test_an_anonymous_caller_cannot_delete(world):
    assert world.delete("/api/documents/doc_sub?confirm=true").status_code == 404
    assert _exists("doc_sub")


def test_an_admin_can_still_delete(world):
    r = world.delete("/api/documents/doc_sub?confirm=true&acknowledge_orphaned_findings=true",
                     headers=h("u_admin"))
    assert r.status_code == 200, r.text
    assert not _exists("doc_sub")


@pytest.mark.parametrize("stage", PIPELINE)
def test_a_reader_cannot_force_the_pipeline(world, monkeypatch, stage):
    called = []
    for mod, name in ((extract, "extract_document"), (chunker, "chunk_document"),
                      (keyword, "index_document")):
        monkeypatch.setattr(mod, name, lambda *a, **k: called.append(name) or {})
    from app import ingest
    monkeypatch.setattr(ingest, "get_worker",
                        lambda: called.append("worker") or (_ for _ in ()).throw(RuntimeError))
    r = world.post(f"/api/documents/doc_sub/{stage}", headers=h("u_sub"))
    assert r.status_code == 404, r.text
    assert called == [], f"{stage} ran for a caller with only a read grant"


@pytest.mark.parametrize("stage", PIPELINE)
def test_an_admin_reaches_the_pipeline(world, monkeypatch, stage):
    called = []
    for mod, name in ((extract, "extract_document"), (chunker, "chunk_document"),
                      (keyword, "index_document")):
        monkeypatch.setattr(mod, name, lambda *a, **k: called.append(name) or {})
    from app import ingest

    def worker():
        called.append("worker")
        raise RuntimeError("stop here")
    monkeypatch.setattr(ingest, "get_worker", worker)
    world.post(f"/api/documents/doc_sub/{stage}", headers=h("u_admin"))
    assert called, f"the admin gate also stopped the admin on {stage}"
