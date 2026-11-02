"""#1606: give chunks made before CHUNKER_VERSION 8 their heading chain, on a copy.

A chunk's `section` is its nearest heading; `chunks.context` is the whole chain
above it, and the keyword index, the embedder and the reranker already read it.
Only chunks chunked since version 8 have one, and `reindex_chunking.py` is the
only way to give it to the rest, which rebuilds every chunk of the document and
can change them. This writes the chain and nothing else: chunk text, ids, pages
and everything cited from them stay as they are.

The chain is the chunker's own (`segment_document(paths_out=...)`), keyed by
section, under the chunker's own rule: a section two chains share gets none. A
chain that says no more than the section is not written. Font-set headings are
not read: this opens no stored file, so only text-detected headings give a chain.
A document that states its own structure (Word, a workbook) is skipped.

Then the document's keyword rows are rewritten; the reranker reads the chain from
the chunk. Vectors stay as they are BY DEFAULT, because that is what measured best
on `scripts/retrieval_bed.py` (2 Nov, 974 cases): chains in the keyword index and
reranker lifted recall@5 from 939 to 944, and re-embedding as well left it at 938.
`--embed` is there to repeat that measurement: a chunk that gained a chain loses its
old vector, as `chunk_document` does, and the worker's `embed_pending` embeds it and
upgrades every other vector of the document that is not current. A vector left as
it is stays searchable (`LEGACY_PASSAGE_INPUT_VERSIONS`), but re-processing the
document later embeds it from the chain.

OFF unless CHUNK_CONTEXT_FILL=on, and the live database is refused whatever the
setting says: nothing under `backend/app` changes, so with this unused the search
is byte-identical. Filling the live database is the owner's decision. Prints
counts only. Local models only; no Claude, no network.

    CHUNK_CONTEXT_FILL=on python scripts/fill_chunk_context.py --db COPY [--embed]
    CHUNK_CONTEXT_FILL=on python scripts/fill_chunk_context.py --db COPY --vectors-only
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import chunker, fts_index, live_guard, sheet_chunks  # noqa: E402
from app.config import settings  # noqa: E402

SETTING = "CHUNK_CONTEXT_FILL"


class Refused(Exception):
    """A safeguard said no; the message names no document."""


def heading_paths(conn: sqlite3.Connection, doc_id: str) -> dict[str, str | None]:
    """The chains `chunk_document` would record, from the stored pages."""
    pages, raw_tables, _rows = chunker._load_pages(conn, doc_id)
    if not pages:
        return {}
    doc = conn.execute(
        "SELECT page_count FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    kinds = chunker.classify_document_pages(pages, doc["page_count"] or len(pages))
    running = chunker.detect_running_lines(pages)
    masked = chunker.mask_tables(pages, chunker._decode_tables(raw_tables), running)
    paths: dict[str, str | None] = {}
    chunker.segment_document(masked, running, kinds, paths, None)
    return paths


def fill_document(conn: sqlite3.Connection, doc_id: str, embed: bool = False) -> dict:
    """Write the chains of one document's old chunks. Counts only come back."""
    report: Counter = Counter(
        {"filled": 0, "no_single_chain": 0, "chain_adds_nothing": 0}
    )
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if sheet_chunks.structured(doc):
        return {**report, "skipped": True}
    paths = heading_paths(conn, doc_id)
    gained: list[tuple[str, str]] = []
    for row in conn.execute(
        "SELECT id, section FROM chunks WHERE document_id = ? AND retrievable = 1"
        " AND context IS NULL AND section IS NOT NULL",
        (doc_id,),
    ).fetchall():
        path = paths.get(row["section"])
        if not path:
            report["no_single_chain"] += 1
        elif path == row["section"]:
            report["chain_adds_nothing"] += 1
        else:
            gained.append((path, row["id"]))
    report["filled"] = len(gained)
    if gained:
        with conn:
            conn.executemany("UPDATE chunks SET context = ? WHERE id = ?", gained)
            fts_index._index_rows(conn, doc_id)
            if embed:
                conn.executemany(
                    "DELETE FROM chunk_vectors WHERE chunk_id = ? AND document_id = ?",
                    [(chunk_id, doc_id) for _path, chunk_id in gained],
                )
    return {**report, "skipped": False}


def _embed_pending(doc_id: str) -> int:
    from app.ingest import IngestionWorker

    return IngestionWorker().embed_pending(doc_id)


def _point_at_copy(path: Path) -> sqlite3.Connection:
    """The whole app on the copy, with its own derived files beside it."""
    settings.db_path = path.resolve()
    settings.data_dir = path.resolve().parent
    from app.db import connect, init_db

    init_db()
    fts_index.ensure_schema(connect())
    return connect()


def run(path: Path, embed: bool, vectors_only: bool) -> dict:
    conn = _point_at_copy(path)
    totals: Counter = Counter()
    doc_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM documents WHERE status = 'ready' ORDER BY id"
        )
    ]
    for number, doc_id in enumerate(doc_ids, start=1):
        if not vectors_only:
            report = fill_document(conn, doc_id, embed=embed)
            totals["documents_skipped"] += int(report.pop("skipped"))
            totals.update(report)
        if embed or vectors_only:
            totals["vectors_written"] += _embed_pending(doc_id)
        if number % 25 == 0:
            print(f"{number} of {len(doc_ids)} documents", file=sys.stderr, flush=True)
    totals["documents"] = len(doc_ids)
    return dict(totals)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", required=True)
    parser.add_argument(
        "--embed",
        action="store_true",
        help="also embed from the chain; measured worse, kept to repeat the measurement",
    )
    parser.add_argument(
        "--vectors-only",
        action="store_true",
        help="no chains: upgrade vectors, to tell the two effects apart",
    )
    args = parser.parse_args(argv)
    path = Path(args.db).expanduser()
    try:
        if (os.environ.get(SETTING) or "").strip() != "on":
            raise Refused(f"off; set {SETTING}=on to run this on a copy")
        if live_guard.is_live_shaped(path):
            raise Refused("refusing the live database; make a copy and pass that")
        if not path.exists():
            raise Refused(f"no database at {path}")
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            run(path, embed=args.embed, vectors_only=args.vectors_only),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
