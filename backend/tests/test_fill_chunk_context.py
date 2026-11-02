"""#1606: heading chains for chunks made before CHUNKER_VERSION 8
(`scripts/fill_chunk_context.py`). Off by default, never on the live database,
and it writes only `chunks.context`, what the keyword index and the embedder
read from it: chunk text and ids, which every citation depends on, stay as they
were. Invented text only; no model.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app import db, fts_index
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "fill_chunk_context_under_test", REPO / "scripts" / "fill_chunk_context.py"
)
fill = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fill)

NOW = "2026-11-02T00:00:00Z"
PAGE_ONE = "\n".join(
    [
        "4.1 General",
        "All piping shall be designed to the governing code and shall be inspected.",
        "4.2 Pipes larger than 2 inch",
        "4.2.1 The minimum wall thickness shall be 5 mm for all such pipes in any service.",
        "4.2.2 Branch connections shall be reinforced where required by the code.",
    ]
)
REUSED = "\n".join(
    [
        "4.1 General",
        "All piping shall be designed to the governing code and shall be inspected.",
        "4.2 Pipes larger than 2 inch",
        "4.2.1 The minimum wall thickness shall be 5 mm for all such pipes in any service.",
        "A.1 Annex material",
        "A.1.1 Annex items shall be recorded by the supplier in every shipment.",
        "B.1 Other annex",
        "A.1.1 Annex items shall be recorded by the buyer in every shipment.",
    ]
)
BODY = "Branch connections shall be reinforced where required by the code."


def _doc(conn, doc_id: str, page_text: str, pagination: str | None = None) -> None:
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status,"
        " uploaded_at, pagination) VALUES (?,?,?,?,?,?,?,?)",
        (
            doc_id,
            f"{doc_id}.pdf",
            f"sha-{doc_id}",
            1,
            f"{doc_id}.pdf",
            "ready",
            NOW,
            pagination,
        ),
    )
    conn.execute(
        "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
        " VALUES (?,1,?,?,1)",
        (doc_id, page_text, len(page_text)),
    )


def _chunk(
    conn, chunk_id, doc_id, section, ordinal=0, retrievable=1, context=None, text=BODY
):
    conn.execute(
        "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
        " section, kind, text, token_count, content_hash, retrievable, context)"
        " VALUES (?,?,?,?,1,1,?,'prose',?,10,?,?,?)",
        (
            chunk_id,
            doc_id,
            f"{doc_id}.pdf",
            ordinal,
            section,
            text,
            f"h-{chunk_id}",
            retrievable,
            context,
        ),
    )


def _vector(conn, chunk_id, doc_id, model="any-model+heading-v1") -> None:
    conn.execute(
        "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model, created_at)"
        " VALUES (?,?,2,?,?,?)",
        (chunk_id, doc_id, b"\0" * 8, model, NOW),
    )


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    db.reset_connection()
    db.init_db()
    conn = db.connect()
    fts_index.ensure_schema(conn)
    with conn:
        _doc(conn, "d1", PAGE_ONE)
        _chunk(conn, "c1", "d1", "4.2.2")
    yield conn
    db.reset_connection()


def _context(conn, chunk_id):
    return conn.execute(
        "SELECT context FROM chunks WHERE id = ?", (chunk_id,)
    ).fetchone()[0]


# ----------------------------------------------------------------- the fill


def test_an_old_chunk_gets_the_chain_the_chunker_would_give_it(library):
    report = fill.fill_document(library, "d1")
    assert _context(library, "c1") == "4.2 Pipes larger than 2 inch > 4.2.2"
    assert report["filled"] == 1


def test_only_the_context_changes_never_the_text_or_the_id(library):
    columns = "id, document_id, ordinal, page_start, page_end, section, kind, text, content_hash"
    before = [
        tuple(r) for r in library.execute(f"SELECT {columns} FROM chunks ORDER BY id")
    ]
    fill.fill_document(library, "d1")
    assert [
        tuple(r) for r in library.execute(f"SELECT {columns} FROM chunks ORDER BY id")
    ] == before


def test_a_chunk_with_a_chain_already_is_left_alone(library):
    with library:
        _chunk(
            library,
            "c2",
            "d1",
            "4.2.1",
            ordinal=1,
            context="Set by the chunker > 4.2.1",
        )
    report = fill.fill_document(library, "d1")
    assert _context(library, "c2") == "Set by the chunker > 4.2.1"
    assert report["filled"] == 1


def test_a_clause_number_two_chains_share_gets_no_chain(library):
    """No context is better than the wrong one: the chunker's own rule."""
    with library:
        _doc(library, "d2", REUSED)
        _chunk(library, "c3", "d2", "A.1.1")
    report = fill.fill_document(library, "d2")
    assert _context(library, "c3") is None
    assert report["filled"] == 0 and report["no_single_chain"] == 1


def test_a_section_this_chunker_does_not_set_gets_no_chain(library):
    with library:
        _chunk(library, "c4", "d1", "9.9.9", ordinal=2)
    report = fill.fill_document(library, "d1")
    assert _context(library, "c4") is None and report["no_single_chain"] == 1


def test_a_chain_that_says_no_more_than_the_section_changes_nothing(library):
    with library:
        _chunk(library, "c5", "d1", "4.1 General", ordinal=3)
    report = fill.fill_document(library, "d1")
    assert _context(library, "c5") is None and report["chain_adds_nothing"] == 1


def test_a_chunk_search_may_not_use_is_not_touched(library):
    with library:
        _chunk(library, "c6", "d1", "4.2.1", ordinal=4, retrievable=0)
    fill.fill_document(library, "d1")
    assert _context(library, "c6") is None


def test_a_document_that_states_its_own_structure_is_skipped(library):
    with library:
        _doc(library, "d3", PAGE_ONE, pagination="flow")
        _chunk(library, "c7", "d3", "4.2.2")
    report = fill.fill_document(library, "d3")
    assert report["skipped"] is True and _context(library, "c7") is None


def test_a_second_run_finds_nothing_to_do(library):
    fill.fill_document(library, "d1")
    assert fill.fill_document(library, "d1")["filled"] == 0


# ------------------------------------------- what reads the chain afterwards


def test_the_keyword_index_finds_the_clause_by_the_heading_above_it(library):
    with library:
        fts_index._index_rows(library, "d1")
    query = "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH 'larger'"
    assert library.execute(query).fetchall() == []
    assert fill.fill_document(library, "d1", embed=False)["filled"] == 1
    assert [r[0] for r in library.execute(query)] == ["c1"]


def test_a_filled_chunk_loses_its_old_vector_so_it_is_embedded_from_the_chain(library):
    with library:
        _vector(library, "c1", "d1")
    fill.fill_document(library, "d1", embed=True)
    assert library.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 0


def test_a_chunk_that_gained_nothing_keeps_its_vector(library):
    with library:
        _chunk(library, "c8", "d1", "9.9.9", ordinal=5)
        _vector(library, "c8", "d1")
    fill.fill_document(library, "d1", embed=True)
    assert (
        library.execute(
            "SELECT COUNT(*) FROM chunk_vectors WHERE chunk_id = 'c8'"
        ).fetchone()[0]
        == 1
    )


def test_without_embedding_the_old_vector_stays_searchable(library):
    with library:
        _vector(library, "c1", "d1")
    fill.fill_document(library, "d1", embed=False)
    assert library.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 1


# --------------------------------------------------- the switch, default off


@pytest.mark.parametrize("value", ["", "off", None])
def test_the_setting_is_off_by_default_and_nothing_is_written(
    value, monkeypatch, tmp_path
):
    if value is None:
        monkeypatch.delenv(fill.SETTING, raising=False)
    else:
        monkeypatch.setenv(fill.SETTING, value)
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(b"")
    assert fill.main(["--db", str(copy)]) == 2
    assert copy.read_bytes() == b""


def test_the_live_database_is_refused_even_with_the_setting_on(monkeypatch, tmp_path):
    monkeypatch.setenv(fill.SETTING, "on")
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    assert fill.main(["--db", str(live)]) == 2
    assert live.read_bytes() == b""


def test_a_missing_database_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(fill.SETTING, "on")
    assert fill.main(["--db", str(tmp_path / "missing.sqlite")]) == 2
    assert not (tmp_path / "missing.sqlite").exists()


def test_the_run_fills_every_document_and_reports_counts_only(
    library, monkeypatch, capsys
):
    monkeypatch.setenv(fill.SETTING, "on")
    monkeypatch.setattr(fill, "_point_at_copy", lambda path: library)
    assert fill.main(["--db", str(settings.db_path)]) == 0
    out = capsys.readouterr().out
    assert _context(library, "c1") == "4.2 Pipes larger than 2 inch > 4.2.2"
    assert '"filled": 1' in out
    for word in ("Pipes", "Branch", "d1.pdf"):
        assert word not in out


def test_vectors_are_left_alone_unless_embedding_is_asked_for(library, monkeypatch):
    """The measured best: re-embedding from the chain lost recall on the bed."""
    monkeypatch.setenv(fill.SETTING, "on")
    monkeypatch.setattr(fill, "_point_at_copy", lambda path: library)
    seen = []
    monkeypatch.setattr(fill, "_embed_pending", lambda doc_id: seen.append(doc_id) or 0)
    with library:
        _vector(library, "c1", "d1")
    assert fill.main(["--db", str(settings.db_path)]) == 0
    assert seen == []
    assert library.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 1
    assert fill.main(["--db", str(settings.db_path), "--embed"]) == 0
    assert seen == ["d1"]


def test_asking_for_embedding_drops_the_vector_of_a_chunk_that_gains_a_chain(
    library, monkeypatch
):
    monkeypatch.setenv(fill.SETTING, "on")
    monkeypatch.setattr(fill, "_point_at_copy", lambda path: library)
    monkeypatch.setattr(fill, "_embed_pending", lambda doc_id: 0)
    with library:
        _vector(library, "c1", "d1")
    assert fill.main(["--db", str(settings.db_path), "--embed"]) == 0
    assert library.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 0


def test_vectors_only_writes_no_chain_and_upgrades_vectors(library, monkeypatch):
    monkeypatch.setenv(fill.SETTING, "on")
    monkeypatch.setattr(fill, "_point_at_copy", lambda path: library)
    seen = []
    monkeypatch.setattr(fill, "_embed_pending", lambda doc_id: seen.append(doc_id) or 0)
    assert fill.main(["--db", str(settings.db_path), "--vectors-only"]) == 0
    assert _context(library, "c1") is None and seen == ["d1"]
