"""The vector cache, and the properties that make it safe to trust.

Re-reading every vector blob from SQLite per query was the only component of
retrieval measured to grow with the corpus:

    2,670 -> 4,780 retrievable chunks
    vector load    39.1 ms -> 82.6 ms   x2.11
    matmul         48.1 ms -> 50.7 ms   x1.05

A cache that returns a stale matrix is worse than a slow one, so the tests
that matter here are the INVALIDATION ones: each asserts a change the
signature must notice, and each was confirmed to fail against a signature
that omitted its term.
"""

import numpy as np
import pytest

from app import db, keyword, vectorcache
from app.config import settings
from app.db import connect
from app.embedder import EMBEDDING_DIM, embedding_tag


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    vectorcache.invalidate()
    yield
    vectorcache.invalidate()
    db.reset_connection()


def _add_vector(conn, document_id, chunk_id, retrievable=1, seed=1.0):
    conn.execute(
        "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
        " page_end, kind, text, token_count, content_hash, retrievable)"
        " VALUES (?, ?, 'a.pdf', 0, 1, 1, 'prose', ?, 4, ?, ?)",
        (chunk_id, document_id, f"text for {chunk_id}", chunk_id, retrievable),
    )
    vec = np.full(EMBEDDING_DIM, seed, dtype=np.float32)
    conn.execute(
        "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model,"
        " created_at) VALUES (?, ?, ?, ?, ?, '2026-09-04T00:00:00Z')",
        (chunk_id, document_id, EMBEDDING_DIM, vec.tobytes(), embedding_tag()),
    )


@pytest.fixture
def corpus():
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, uploaded_at) VALUES ('d1', 'a.pdf', 'x', 1, 'p', 'ready', '2026-09-04T00:00:00Z')"
        )
        for i in range(4):
            _add_vector(conn, "d1", f"d1:c{i}", seed=float(i + 1))
    vectorcache.invalidate()
    return conn


# ------------------------------------------------------- it is really a cache


def test_the_matrix_matches_a_direct_read(corpus):
    m = vectorcache.load()
    direct = vectorcache._read_from_db()
    assert m.ids == direct.ids
    assert np.array_equal(np.asarray(m.matrix), direct.matrix)
    assert [m.documents[i] for i in m.doc_index] == [direct.documents[i] for i in direct.doc_index]


def test_the_matrix_is_memory_mapped_not_heap_allocated(corpus):
    """The point of the file is that these are pages the OS can evict and
    share. A heap copy would pass every other test here while giving that up,
    on a machine that demos at 92% RAM."""
    matrix = vectorcache.load().matrix
    assert isinstance(matrix, np.memmap), f"got {type(matrix).__name__}, not a mapping"


def test_the_FIRST_load_is_mapped_too(corpus):
    """The build path used to return the heap array it had just assembled, so
    the process that ingests - the one under the most memory pressure - was the
    only one that never got the mapping. An earlier version of the test above
    hid this by invalidating first, which is why this one does not."""
    vectorcache.invalidate()
    data_path, meta_path = vectorcache._paths(vectorcache.generation())
    data_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    matrix = vectorcache.load().matrix    # a genuine cold build
    assert isinstance(matrix, np.memmap), (
        f"the build path returned {type(matrix).__name__}, not a mapping")


def test_a_second_load_does_not_re_read_the_blobs(corpus, monkeypatch):
    """Guard the guard: if the cache silently fell through to the direct read
    it would still return correct results, and every other test would pass."""
    vectorcache.load()
    calls = []
    real = vectorcache._read_from_db
    monkeypatch.setattr(vectorcache, "_read_from_db",
                        lambda t=None: (calls.append(1), real(t))[1])
    vectorcache.load()
    assert calls == [], "the cache re-read the blobs from SQLite"


# --------------------------------------------------------------- INVALIDATION


def test_an_added_vector_invalidates(corpus):
    before = vectorcache.load().ids
    with corpus:
        _add_vector(corpus, "d1", "d1:new", seed=9.0)
    after = vectorcache.load().ids
    assert len(after) == len(before) + 1
    assert "d1:new" in after


def test_a_deleted_vector_invalidates(corpus):
    before = vectorcache.load().ids
    with corpus:
        corpus.execute("DELETE FROM chunk_vectors WHERE chunk_id = 'd1:c0'")
    after = vectorcache.load().ids
    assert "d1:c0" not in after
    assert len(after) == len(before) - 1


def test_excluding_a_chunk_invalidates(corpus):
    with corpus:
        corpus.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'd1:c1'")
    after = vectorcache.load().ids
    assert "d1:c1" not in after, "an excluded chunk stayed in the dense matrix"


def test_one_chunk_excluded_as_another_is_restored_invalidates(corpus):
    """The case a count-only signature cannot see: the number of excluded
    chunks is unchanged, so only a signature sensitive to WHICH rows are
    excluded catches it. Confirmed to fail with the SUM(rowid) term removed."""
    with corpus:
        corpus.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'd1:c1'")
    first = vectorcache.load().ids
    assert "d1:c1" not in first

    with corpus:
        corpus.execute("UPDATE chunks SET retrievable = 1 WHERE id = 'd1:c1'")
        corpus.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'd1:c2'")
    second = vectorcache.load().ids
    assert "d1:c1" in second, "restored chunk never came back"
    assert "d1:c2" not in second, "newly excluded chunk stayed in the matrix"


def test_a_rechunk_that_keeps_the_count_invalidates(corpus):
    """Replacing every vector leaves COUNT(*) identical, so the max-rowid term
    is what catches it. Confirmed to fail without that term."""
    before = vectorcache.load().ids
    with corpus:
        corpus.execute("DELETE FROM chunk_vectors")
        corpus.execute("DELETE FROM chunks")
        for i in range(4):
            _add_vector(corpus, "d1", f"d1:r{i}", seed=float(100 + i))
    after = vectorcache.load().ids
    assert len(after) == len(before)
    assert after != before, "the cache served vectors for chunks that no longer exist"


# ------------------------------------------------------------------- fallback


def test_search_still_works_when_the_cache_cannot_be_built(corpus, monkeypatch):
    """Retrieval must never depend on the cache."""
    def boom(*a, **k):
        raise OSError("cache directory is not writable")
    monkeypatch.setattr(vectorcache, "load", boom)
    q = np.full(EMBEDDING_DIM, 1.0, dtype=np.float32) / np.sqrt(EMBEDDING_DIM)
    hits = vectorcache.search(q, 10, frozenset({"d1"}))
    assert sorted(h["chunk_id"] for h in hits) == [f"d1:c{i}" for i in range(4)]


def test_a_truncated_cache_file_is_rebuilt_not_mapped(corpus):
    """A crash mid-write must not leave a short file that maps as though it
    were complete."""
    vectorcache.load()
    data_path, _ = vectorcache._paths(vectorcache.generation())
    # the mapping has to be released before the file can be rewritten - which
    # is exactly what a process that crashed mid-write would have done
    vectorcache.invalidate()
    data_path.write_bytes(data_path.read_bytes()[: EMBEDDING_DIM * 4])
    m = vectorcache.load()
    assert len(m.ids) == 4
    assert m.matrix.shape == (4, EMBEDDING_DIM)
