"""One block shape for every file (W5b-01, #525 slice 3; INTAKE_BLOCKS_ENABLED).

Needs ONE_INTAKE_ENABLED on as well. Every page of a document, whatever the
file was, becomes numbered blocks: `text` (the running text between tables) or
`table` (rows of cells), each with a hash and one citation form, "page 2,
block 1". A page with no block gets a `not_read` row that says why, and a file
that cannot be read gets one at page 0 ("could not check"), so an empty result
is never a silent pass (CLAUDE.md rule 4).

THE HASH is over the block's kind and its text with spacing, letter case, NFC
and full-width forms made equal, so a wrapped PDF line and a Word paragraph
agree. NOT NFKC: that folds 10 with a superscript 2 into 102 and a one-half sign
into 1/2 (audit F14), so the hash adds no folding of a digit, a sign or a power.
Text the pages already hold is hashed as stored, and `quality.normalise_text`
has written a unit power there as a plain digit, so m with a cubed sign is m3 on
a stored page before it gets here. It says whether two blocks hold the same
content; it decides no verdict. An empty cell does not count, because the
workbook reader drops it.

A page the file holds with no stored row is named too, not skipped. A workbook
page is its own sheet, and a Word page is its reading part, so a block's page is
the same number the stored pages use. The native citation (a
workbook's cell range, a Word heading path) stays on the chunk.

A SCAN'S TABLES come from where the recognised lines sit, never from what they
say (rule 13): consecutive rows of two or more lines, each line under exactly
one column of the row with the most lines. Anything that does not fit, or two
columns of running text, stays text. A table here is read from geometry, and no
table is better than a wrong grid: a cell wrapped onto two lines, or a line
over two columns, makes the run text.

Additive: nothing reads these rows yet, and chunks are unchanged. Local only,
no model, no socket; logs hold ids and counts, never document text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import unicodedata
from dataclasses import dataclass, field

from .config import settings

log = logging.getLogger(__name__)

KIND_TEXT, KIND_TABLE, KIND_NOT_READ = "text", "table", "not_read"

WHY_OCR_FAILED = "recognition failed on this page, so it holds no reading"
WHY_COULD_NOT_CHECK = "could not check: the file's blocks could not be read"
WHY_NOT_STORED = "in the file, but no reading of this page was stored"

#: Full-width ASCII (U+FF01..U+FF5E) to ASCII: the same character at another width.
_WIDTH = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})

#: One page's content in reading order: ("text", line) or ("table", rows).
Item = tuple[str, object]


@dataclass(frozen=True)
class Block:
    page_no: int
    seq: int
    kind: str
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)
    block_hash: str | None = None
    reason: str | None = None

    @property
    def citation(self) -> str | None:
        """The one citation form. A `not_read` row cites nothing."""
        if self.kind == KIND_NOT_READ:
            return None
        return f"page {self.page_no}, block {self.seq}"


def enabled() -> bool:
    return bool(settings.intake_blocks_enabled and settings.one_intake_enabled)


def _squeeze(text: str) -> str:
    return " ".join(str(text).split())


def _hash(kind: str, body: str) -> str:
    canon = unicodedata.normalize("NFC", body).translate(_WIDTH).casefold()
    return hashlib.sha256(f"{kind}\n{canon}".encode()).hexdigest()


def _table_body(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(_squeeze(c) for c in row if _squeeze(c)) for row in rows)


def _assemble(page_no: int, items: list[Item]) -> list[Block]:
    """Blocks of one page: text between tables joined into one block, as a PDF
    has no paragraph marks to split on and every format must agree."""
    blocks: list[Block] = []
    pending: list[str] = []

    def flush() -> None:
        body = _squeeze(" ".join(pending))
        pending.clear()
        if body:
            blocks.append(
                Block(
                    page_no,
                    len(blocks) + 1,
                    KIND_TEXT,
                    text=body,
                    block_hash=_hash(KIND_TEXT, body),
                )
            )

    for kind, value in items:
        if kind == KIND_TEXT:
            pending.append(str(value))
            continue
        flush()
        rows = [[_squeeze(c) for c in row] for row in value]
        body = _table_body(rows)
        blocks.append(
            Block(
                page_no,
                len(blocks) + 1,
                KIND_TABLE,
                text=body,
                rows=rows,
                block_hash=_hash(KIND_TABLE, body),
            )
        )
    flush()
    return blocks


def _is_table(rows: list[list[str]]) -> bool:
    from . import tables

    return (
        len(rows) >= tables.MIN_ROWS
        and tables.MIN_COLUMNS <= max(len(r) for r in rows) <= tables.MAX_COLUMNS
    )


def _row_items(rows: list[list[str]]) -> list[Item]:
    """Rows of cells (a sheet): a run of multi-cell rows is a table if it is long
    enough; anything else is text."""
    items: list[Item] = []
    run: list[list[str]] = []

    def flush() -> None:
        if run and _is_table(run):
            items.append((KIND_TABLE, list(run)))
        else:
            items.extend((KIND_TEXT, " ".join(r)) for r in run)
        run.clear()

    for row in rows:
        if len(row) >= 2:
            run.append(list(row))
            continue
        flush()
        items.append((KIND_TEXT, " ".join(row)))
    flush()
    return items


def _stored_items(text: str, raw_tables: str | None) -> list[Item]:
    """A stored page (a PDF's, a recognised scan's, an office Word's): its lines,
    the lines each table claimed giving way to that table's rows."""
    try:
        tables = list(json.loads(raw_tables).get("tables") or []) if raw_tables else []
    except (ValueError, AttributeError):
        tables = []  # an unreadable record is no tables, as the chunker reads it
    claimed = {i: t for t in tables for i in t.get("lines") or []}
    items: list[Item] = []
    placed: set[int] = set()
    for i, line in enumerate((text or "").split("\n")):
        table = claimed.get(i)
        if table is None:
            items.append((KIND_TEXT, line))
        elif id(table) not in placed:
            placed.add(id(table))
            items.append((KIND_TABLE, table["rows"]))
    return items


def _word_items(path) -> dict[int, list[Item]]:
    """A Word file's own structure, by the page numbers its stored pages use."""
    from . import docx_reader

    pages: dict[int, list[Item]] = {}
    for b in docx_reader.read_structure(path).blocks:
        if b.kind != docx_reader.KIND_TABLE:
            for line in docx_reader.block_lines(b):
                pages.setdefault(b.page, []).append((KIND_TEXT, line))
            continue
        # A table may cross real pages: each page keeps the rows that sit on it.
        where = b.row_pages or [b.page] * len(b.rows)
        by_page: dict[int, list[list[str]]] = {}
        for page, row in zip(where, b.rows, strict=True):
            by_page.setdefault(page, []).append(list(row))
        for page, rows in by_page.items():
            pages.setdefault(page, []).extend(_row_items(rows))
    return pages


def _sheet_items(path) -> dict[int, list[Item]]:
    """A workbook's rows. Its stored page text starts with the sheet's name, which
    is the page's label, not content the other formats hold."""
    from . import datasheet_inputs

    return {
        p.page_no: _row_items([list(r) for r in p.rows])
        for p in datasheet_inputs.read_xlsx(path).pages
    }


def _file_items(doc, path) -> tuple[dict[int, list[Item]] | None, str | None]:
    """(items by page, why an empty page is empty) for a file that states its own
    structure; (None, None) for one read from its stored pages."""
    from . import datasheet_inputs, intake

    if datasheet_inputs.office_kind(path) == datasheet_inputs.KIND_XLSX:
        return _sheet_items(path), intake.WHY_EMPTY_SHEET
    if doc["pagination"] == "flow":
        return _word_items(path), intake.WHY_EMPTY_WORD
    return None, None


def _file_pages(by_file: dict | None, path) -> set[int]:
    """The page numbers the file itself holds, to hold the stored rows against. A
    Word file on the datasheet reader's path has its rows stored in one batch."""
    from . import extract, intake

    if by_file is not None:
        return set(by_file)
    if intake.detect(path) != intake.KIND_PDF:
        return set()
    return set(range(1, extract.page_count(str(path)) + 1))


def build(doc_id: str) -> list[Block]:
    """Every page's blocks, read from what ingestion stored (a recognised page
    from its recognised text). A page with nothing in it says why, and so does a
    page of the file with no stored row."""
    from . import intake, stored_paths
    from .db import connect

    conn = connect()
    doc = conn.execute(
        "SELECT stored_path, pagination FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    page_rows = conn.execute(
        """SELECT p.page_no, p.needs_ocr, p.text AS native, p.tables_json,
                  o.page_no AS ocr_page, o.text AS ocr_text, o.error,
                  o.tables_json AS ocr_tables
           FROM pages p LEFT JOIN page_ocr o
             ON o.document_id = p.document_id AND o.page_no = p.page_no
           WHERE p.document_id = ? ORDER BY p.page_no""",
        (doc_id,),
    ).fetchall()
    path = stored_paths.local(doc["stored_path"])
    by_file, why_empty = _file_items(doc, path)
    out: list[Block] = []
    for r in page_rows:
        if by_file is not None:
            items = by_file.get(r["page_no"], [])
        elif r["ocr_text"]:
            items = _stored_items(r["ocr_text"], r["ocr_tables"])
        else:
            items = _stored_items(r["native"], r["tables_json"])
        blocks = _assemble(r["page_no"], items)
        if blocks:
            out.extend(blocks)
            continue
        if r["error"]:
            why = WHY_OCR_FAILED
        elif r["needs_ocr"] and r["ocr_page"] is None:
            why = intake.WHY_SCANNED
        else:
            why = why_empty or intake.WHY_BLANK_PDF
        out.append(Block(r["page_no"], 1, KIND_NOT_READ, reason=why))
    missing = _file_pages(by_file, path) - {r["page_no"] for r in page_rows}
    out.extend(Block(n, 1, KIND_NOT_READ, reason=WHY_NOT_STORED) for n in missing)
    return sorted(out, key=lambda b: (b.page_no, b.seq))


def refresh(doc_id: str) -> int | None:
    """Store a document's blocks in place of its earlier ones; the row count, or
    None when the switch is off. A document held out of the index holds no
    blocks. A file that cannot be read stores 'could not check' and never stops
    ingestion, because nothing reads the blocks yet."""
    from . import states
    from .db import connect

    if not enabled():
        return None
    conn = connect()
    doc = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if doc is None:
        return None
    blocks: list[Block] = []
    if doc["status"] != states.STORED_NOT_INDEXED:
        try:
            blocks = build(doc_id)
        except Exception as exc:  # noqa: BLE001 - named below; a read must not stop ingestion
            log.warning("intake blocks: %s not read (%s)", doc_id, type(exc).__name__)
            blocks = [Block(0, 1, KIND_NOT_READ, reason=WHY_COULD_NOT_CHECK)]
    with conn:
        conn.execute("DELETE FROM intake_blocks WHERE document_id = ?", (doc_id,))
        conn.executemany(
            "INSERT INTO intake_blocks (document_id, page_no, seq, kind, text,"
            " rows_json, block_hash, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    doc_id,
                    b.page_no,
                    b.seq,
                    b.kind,
                    b.text,
                    json.dumps(b.rows, ensure_ascii=False) if b.rows else None,
                    b.block_hash,
                    b.reason,
                )
                for b in blocks
            ],
        )
    return len(blocks)


def stored(doc_id: str) -> list[Block]:
    """A document's stored blocks in page order."""
    from .db import connect

    return [
        Block(
            r["page_no"],
            r["seq"],
            r["kind"],
            r["text"],
            json.loads(r["rows_json"]) if r["rows_json"] else [],
            r["block_hash"],
            r["reason"],
        )
        for r in connect().execute(
            "SELECT * FROM intake_blocks WHERE document_id = ? ORDER BY page_no, seq",
            (doc_id,),
        )
    ]


# ---------------------------------------------------------------- a scan's tables


def _grid(run: list[list[tuple]]) -> list[list[str]] | None:
    """Rows of (y, x, text, line, right) on the columns of the run's widest row;
    None when a line does not sit under exactly one column, each its own."""
    columns = [(it[1], it[4]) for it in max(run, key=len)]
    grid = []
    for row in run:
        cells = [""] * len(columns)
        for _y, x0, text, _line, x1 in row:
            hit = [i for i, (c0, c1) in enumerate(columns) if x0 < c1 and c0 < x1]
            if len(hit) != 1 or cells[hit[0]]:
                return None
            cells[hit[0]] = text
        grid.append(cells)
    return grid


def _table_of(run: list[list[tuple]]) -> dict | None:
    from . import ocr, tables

    if len(run) < tables.MIN_ROWS or len(max(run, key=len)) > tables.MAX_COLUMNS:
        return None
    grid = _grid(run)
    if grid is None or tables._is_fragmented(grid):
        return None
    words = [len(it[2].split()) for row in run for it in row]
    if statistics.median(words) >= ocr._MIN_COLUMN_WORDS:
        return None  # columns of running text, as `ocr._reading_order` reads them
    lines = sorted(it[3] for row in run for it in row)
    return {"bbox": None, "rows": grid, "lines": lines}


def ocr_row_part(native: list, texts: list, boxes: list, text: str) -> tuple:
    """What `ocr.recognise_batch` adds to a page's row: the grid of a page with no
    text layer. Switch off: nothing, so the row is what it was."""
    if not enabled():
        return ()
    scanned = not any(t.strip() for _, _, t in native)
    return (ocr_tables(texts, boxes, text) if scanned else None,)


def ocr_rows_apart(doc_id: str, rows: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    """A recognition batch's rows as they always were, and its grids to store:
    (grid, document, page) for a row that carries one (`ocr_row_part`)."""
    grids = [(r[10], doc_id, r[0]) for r in rows if len(r) > 10]
    return [r[:10] for r in rows], grids


def store_ocr_grids(conn, grids: list[tuple]) -> None:
    """Replaces what the row's insert left NULL. A switched-off batch has no grids."""
    if grids:
        conn.executemany(
            "UPDATE page_ocr SET tables_json = ? WHERE document_id = ? AND page_no = ?",
            grids,
        )


def ocr_tables(texts: list[str], boxes: list, text: str) -> str | None:
    """`pages.tables_json`-shaped tables of a recognised page, from where its lines
    sit; None when it has none. `text` is the page text as stored: its line numbers
    are what a table claims, so if normalising moved them no table is stored."""
    from . import ocr
    from .extract import TABLE_READER_VERSION

    if len(texts) != len(boxes) or text.count("\n") != len(texts) - 1:
        return None
    stored_lines = text.split("\n")
    items = []
    try:
        for i, box in enumerate(boxes):
            y0, x0 = ocr._box_origin(box)
            items.append((y0, x0, stored_lines[i], i, max(float(pt[0]) for pt in box)))
    except (TypeError, ValueError, IndexError):
        return None  # a box of an odd shape: no table, and the page keeps its text
    found, run = [], []
    for row in [*ocr._rows(items), []]:
        if len(row) >= 2:
            run.append(row)
            continue
        table = _table_of(run)
        if table:
            found.append(table)
        run = []
    if not found:
        return None
    return json.dumps(
        {"v": TABLE_READER_VERSION, "tables": found},
        ensure_ascii=False,
        separators=(",", ":"),
    )
