"""B6B E1: a chunk's semantic vector is computed from its clause heading + body.

The keyword index and the reranker already read "heading + body"; the embedder
read the body alone, so a one-line chunk was embedded without the heading that
says what it is about. E1 changes ONLY the embedder's input:

  * the stored chunk text (what a citation quotes) is untouched;
  * chunk boundaries, pages, clause labels and permissions are untouched;
  * the body is never cut to make room for the heading - when heading + body
    would pass the model's 512-token limit, the body alone is embedded.

Synthetic text only. Needs the staged e5 model (the conftest guard refuses a
run without it). Mutations M797-M799.
"""
from __future__ import annotations

import numpy as np
import pytest

from app import db
from app.config import settings
from app.embedder import PASSAGE_INPUT_VERSION, PASSAGE_PREFIX, Embedder, EmbedderConfig
from app.ingest import IngestionWorker

NOW = "2026-09-26T00:00:00Z"
HEADING = "4.7 Widget Bracket Loads"
BODY = "Loads from the extreme case shall also be established."


@pytest.fixture(scope="module")
def embedder():
    return Embedder.instance(EmbedderConfig())


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "e1.sqlite")
    db.reset_connection()
    db.init_db()
    yield tmp_path
    db.reset_connection()


def _cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ------------------------------------------------------------ the input text

def test_the_heading_comes_first_then_the_body(embedder):
    assert embedder.passage_input(HEADING, BODY) == f"{HEADING}\n{BODY}"


def test_a_chunk_without_a_heading_is_embedded_from_its_body(embedder):
    assert embedder.passage_input(None, BODY) == BODY
    assert embedder.passage_input("   ", BODY) == BODY


def test_the_body_is_never_cut_to_make_room_for_the_heading(embedder):
    """A body that fits the model alone, but not with the heading in front:
    the heading is dropped, never the body's tail (the evidence)."""
    words = []
    while not embedder.tokenizer.encode(PASSAGE_PREFIX + " ".join(words + ["valve"])).overflowing:
        words.append("valve")
    body = " ".join(words)          # the longest body that still fits alone
    assert not embedder.tokenizer.encode(PASSAGE_PREFIX + body).overflowing
    long_heading = "9.9 " + " ".join(["Heading"] * 20)
    assert embedder.tokenizer.encode(PASSAGE_PREFIX + long_heading + "\n" + body).overflowing
    assert embedder.passage_input(long_heading, body) == body


# ------------------------------------------------------ the stored vector

def test_ingestion_stores_the_heading_aware_vector_and_leaves_the_text_alone(world, embedder):
    """THE E1 TEST: the vector ingestion stores is the one computed from
    heading + body, not from the body alone - and the chunk's stored text,
    which citations quote, is exactly the body it was."""
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('doc_e1','e1.pdf','sha-e1',1,'/nonexistent','ready',1,?)""", (NOW,))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES ('doc_e1-c1','doc_e1','e1.pdf',1,1,1,?,'prose',?,12,'h-e1',1)""",
                     (HEADING, BODY))
    assert IngestionWorker().embed_pending("doc_e1") == 1

    row = db.connect().execute(
        "SELECT v.vector, v.model, c.text, c.section FROM chunk_vectors v"
        " JOIN chunks c ON c.id = v.chunk_id WHERE v.chunk_id = 'doc_e1-c1'").fetchone()
    stored = np.frombuffer(row["vector"], dtype="float32")
    # One text per call, as ingestion embedded this one-chunk document: the
    # quantized model's output moves slightly with batch padding.
    with_heading = embedder.embed_passages([f"{HEADING}\n{BODY}"])[0]
    body_only = embedder.embed_passages([BODY])[0]
    # the two candidate inputs must be distinguishable, or this proves nothing
    assert _cos(with_heading, body_only) < 0.995
    assert _cos(stored, with_heading) > 0.9999
    assert _cos(stored, body_only) < 0.995
    # provenance: which input produced this vector
    assert row["model"].endswith("+" + PASSAGE_INPUT_VERSION)
    # the evidence a citation quotes is unchanged
    assert row["text"] == BODY and row["section"] == HEADING
