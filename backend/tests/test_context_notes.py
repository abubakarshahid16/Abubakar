"""Context notes (CHUNKER_VERSION 8): every chunk knows WHERE it sits.

A chunk's `section` is only its nearest heading - for a numbered requirement,
only its number. So "4.2.2 Branch connections shall be reinforced" under
"4.2 Pipes larger than 2 inch" carried nothing that said "larger than 2 inch",
and a question about a 6 inch pipe had nothing to match it on. Measured on the
owner's corpus (2026-09-29, counts only): of 66 answers that used a similar
clause with a different number, 43 never had the right clause in the top 5.

Now each chunk records its heading CHAIN in `chunks.context`
("4.2 Pipes larger than 2 inch > 4.2.2"), used ONLY to index it: the keyword
index, the embedder and the reranker read it; the chunk's text - what every
answer and CRS row quotes - is never changed.

Synthetic text only. Mutations M1400-M1405.
"""
from __future__ import annotations

import numpy as np
import pytest

from app import chunker as ch
from app import db, keyword, vector_store, vectorcache
from app.config import settings
from app.embedder import (
    LEGACY_PASSAGE_INPUT_VERSIONS,
    PASSAGE_INPUT_VERSION,
    Embedder,
    EmbedderConfig,
    embedding_tag,
    searchable_tags,
)
from app.ingest import IngestionWorker
from app.search import Candidate
from tests.test_chunking_quality import _InlinePool, corpus  # noqa: F401 - fixture

NOW = "2026-09-30T00:00:00Z"

PIPING = "\n".join([
    "4.1 General",
    "All piping shall be designed to the governing code and shall be inspected.",
    "4.2 Pipes larger than 2 inch",
    "4.2.1 The minimum wall thickness shall be 5 mm for all such pipes in any service.",
    "4.2.2 Branch connections shall be reinforced where required by the code.",
    "4.3 Pipes 2 inch and smaller",
    "4.3.1 The minimum wall thickness shall be 3 mm for all such pipes in any service.",
])


def _paths(text: str) -> tuple[list, dict]:
    paths: dict = {}
    blocks, _ = ch.segment_document([(1, text)], set(), paths_out=paths)
    return blocks, paths


# ------------------------------------------------------------ the chain

def test_a_numbered_clause_knows_the_titled_heading_above_it():
    """THE CASE: 4.2.2 never carried "larger than 2 inch" - not in its text
    (the heading was carried into 4.2.1 only) and not in its section."""
    blocks, paths = _paths(PIPING)
    sibling = next(b for b in blocks if b.section == "4.2.2")
    assert "larger than 2 inch" not in sibling.text      # the gap being closed
    assert paths["4.2.2"] == "4.2 Pipes larger than 2 inch > 4.2.2"


def test_a_new_heading_at_the_same_depth_replaces_the_old_one():
    _, paths = _paths(PIPING)
    assert paths["4.3.1"] == "4.3 Pipes 2 inch and smaller > 4.3.1"
    assert "larger" not in paths["4.3.1"]


def test_a_clause_is_never_filed_under_a_heading_it_is_not_numbered_under():
    """Depth alone was not enough: "4.4" after "8.2" was filed under "8
    Thermally sprayed metallic coatings" - found by the full suite, where the
    reranker read the wrong chain and a right answer was refused."""
    text = "\n".join([
        "8 Thermally sprayed metallic coatings",
        "8.2 Coating materials",
        "Zinc shall have a maximum operating temperature of 120 C in service here.",
        "4.4 Ambient conditions",
        "No coating shall be applied if the relative humidity is more than 85 %.",
    ])
    _, paths = _paths(text)
    assert paths["4.4 Ambient conditions"] == "4.4 Ambient conditions"


def test_the_chain_ends_with_the_section_itself():
    _, paths = _paths(PIPING)
    for section, chain in paths.items():
        assert chain.endswith(" ".join(section.split())), (section, chain)


def test_a_section_two_different_chains_set_gets_no_context():
    """A clause number reused under another heading (an annex): no context
    is better than the wrong one."""
    text = PIPING + "\n" + "\n".join([
        "5.1 Valves",
        "Valves shall be tested to the governing code before installation on site.",
        "5.2 Isolation valves",
        "4.2.2 Seats shall be tested at the maximum differential pressure stated.",
    ])
    _, paths = _paths(text)
    assert paths["4.2.2"] is None
    assert paths["4.2.1"] == "4.2 Pipes larger than 2 inch > 4.2.1"


# ------------------------------------------------- through the real chunker

def test_every_stored_chunk_context_ends_with_its_section_and_text_is_untouched(corpus):  # noqa: F811
    """End to end on the synthetic corpus: contexts are written, each ends
    with its chunk's own section, and no context leaks into chunk text."""
    rows = [c for d in corpus.values() for c in d["chunks"]]
    with_context = [c for c in rows if c["context"]]
    assert with_context, "the chunker wrote no context at all"
    for c in with_context:
        assert c["context"].endswith(" ".join(c["section"].split())), c["id"]
        if " > " in c["context"]:
            assert c["context"] not in c["text"]


# ----------------------------------------------------- index, rerank, embed

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ctx.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('doc_ctx','spec.pdf','sha-ctx',1,'/nonexistent','ready',1,?)""", (NOW,))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable,context)
            VALUES ('ctx-c1','doc_ctx','spec.pdf',1,1,1,'4.2.2','prose',?,14,'h-ctx',1,?)""",
                     ("4.2.2 Branch connections shall be reinforced where required.",
                      "4.2 Pipes larger than 2 inch > 4.2.2"))
    yield tmp_path
    db.reset_connection()


def test_the_keyword_index_finds_a_clause_by_the_heading_above_it(world):
    conn = db.connect()
    with conn:
        keyword._index_rows(conn, "doc_ctx")
    hit = conn.execute(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH 'larger'").fetchall()
    assert [r[0] for r in hit] == ["ctx-c1"]
    # index-only: the stored text is unchanged
    text = conn.execute("SELECT text FROM chunks WHERE id = 'ctx-c1'").fetchone()[0]
    assert "larger" not in text


def test_the_reranker_reads_the_chain_not_just_the_number():
    c = Candidate(chunk_id="x", document_id="d", filename="f.pdf", section="4.2.2",
                  page_start=1, page_end=1, text="Branch connections shall be reinforced.",
                  context="4.2 Pipes larger than 2 inch > 4.2.2")
    assert c.searchable_text.startswith("4.2 Pipes larger than 2 inch > 4.2.2\n")
    bare = Candidate(chunk_id="y", document_id="d", filename="f.pdf", section="4.2.2",
                     page_start=1, page_end=1, text="Branch connections.")
    assert bare.searchable_text == "4.2.2\nBranch connections."


@pytest.fixture(scope="module")
def embedder():
    return Embedder.instance(EmbedderConfig())


def _cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_the_stored_vector_is_computed_from_the_chain(world, embedder):
    assert IngestionWorker().embed_pending("doc_ctx") == 1
    row = db.connect().execute(
        "SELECT v.vector, v.model FROM chunk_vectors v WHERE v.chunk_id = 'ctx-c1'").fetchone()
    stored = np.frombuffer(row["vector"], dtype="float32")
    body = "4.2.2 Branch connections shall be reinforced where required."
    with_chain = embedder.embed_passages(["4.2 Pipes larger than 2 inch > 4.2.2\n" + body])[0]
    with_section = embedder.embed_passages(["4.2.2\n" + body])[0]
    assert _cos(with_chain, with_section) < 0.995      # distinguishable, or this proves nothing
    assert _cos(stored, with_chain) > 0.9999
    assert row["model"].endswith("+" + PASSAGE_INPUT_VERSION)


# ------------------------------------------ deployment: nothing goes dark

def _legacy_vector(embedder) -> None:
    legacy = embedding_tag().rsplit("+", 1)[0] + "+" + LEGACY_PASSAGE_INPUT_VERSIONS[0]
    vec = embedder.embed_passages(["4.2.2\nBranch connections."])[0].astype("float32")
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunk_vectors
            (chunk_id, document_id, dim, vector, model, created_at)
            VALUES ('ctx-c1','doc_ctx',?,?,?,?)""", (int(vec.shape[0]), vec.tobytes(), legacy, NOW))


def test_a_heading_v1_vector_stays_searchable_after_deployment(world, embedder):
    """Deploying context-v1 must not switch dense search off for every
    document until it is re-processed: the same model's older input format
    is still searched, and counted current on System Health."""
    _legacy_vector(embedder)
    assert len(searchable_tags()) == 2
    m = vectorcache._read_from_db()
    assert m.ids == ["ctx-c1"]
    status = vector_store.status(include_counts=True)
    assert status["current_vectors"] == 1 and status["stale_vectors"] == 0


def test_processing_a_document_upgrades_its_heading_v1_vectors(world, embedder):
    _legacy_vector(embedder)
    assert IngestionWorker().embed_pending("doc_ctx") == 1
    model = db.connect().execute(
        "SELECT model FROM chunk_vectors WHERE chunk_id = 'ctx-c1'").fetchone()[0]
    assert model == embedding_tag()


def test_another_model_is_never_legacy(world):
    """Only an input format of the SAME model is searchable; a vector from
    another model lives in another space and stays stale."""
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunk_vectors
            (chunk_id, document_id, dim, vector, model, created_at)
            VALUES ('ctx-c1','doc_ctx',384,?, 'other-model.onnx+heading-v1', ?)""",
                     (np.zeros(384, dtype="float32").tobytes(), NOW))
    assert vectorcache._read_from_db().ids == []


# ------------------------------------------------------------ versioning

def test_chunks_made_before_context_notes_are_detected_stale():
    """The chain only exists once a document is re-chunked, so a chunk from
    an older chunker must read as stale. `is_stale` compares signatures that
    carry CHUNKER_VERSION; a test that only compared the version with itself
    minus one (test_chunking_quality) passed whatever the number was - M1240
    was vacuous (status-honesty-audit entry 83). This pins the floor."""
    # 9 since the reading audit (2026-09-30) changed data-sheet, contents-page
    # and short-document running-line chunking, which must also read as stale.
    assert int(ch.CHUNKER_VERSION) >= 9
