"""Structured rows and columns for chunks already identified as tables.

WHAT THIS REUSES, AND THE ONE THING IT CANNOT

`chunks.kind` is a persisted column and `chunker.py` already classifies table
runs (`_table_run_length`, `Block("table", ...)`, `RETRIEVABLE_KINDS`). That
signal is real and populated - measured on the live corpus: 134 table chunks
against 6,349 prose. So this module never re-finds tables in a PDF. It asks
`WHERE kind = 'table'` which chunks are tables, and on which pages.

WHAT IT CANNOT REUSE IS THE CHUNK TEXT. Extraction flattens a table to one cell
per line with no delimiters and no column geometry. A real example, from
`civil-Design-and-Construction.pdf` page 59:

    1252\\n562\\nof abutment\\n0\\n0\\n0\\n...\\nStrength I\\n1565\\n758\\n0\\n...

Which number belongs to which column is simply not in that string, and the
OCR-damaged labels beside it ("Senvice", "Brioge") make a positional guess
worse than useless. Reconstructing rows from it would be inventing structure,
which is the one thing this phase's honesty constraint forbids.

So the chunk decides WHERE a table is; the stored PDF is re-read for that page
to recover WHAT SHAPE it has. That is not a second table detector - nothing
here decides whether a region is a table, and a page the chunker never called a
table is never looked at.

AND IT OFTEN FAILS, WHICH IS REPORTED RATHER THAN PAPERED OVER. Measured across
the live corpus: of 98 pages holding table chunks, 33 yielded recoverable
geometry and 65 did not - a 34% parse rate. The 65 are scanned or drawn without
ruling lines, and there is nothing in them to recover. Each is recorded as
UNPARSED with a reason, and unparsed tables lower a standard's completeness.
A requirement set built from the sentences and none of the tables looks
complete and is missing the numbers an engineer checks against; the completeness
figure is what stops that looking like success.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .db import connect

#: A recovered table must have at least this many rows and columns before it is
#: called a table. A 1xN strip is a run of text that happened to sit inside
#: ruling lines, and reading it as a header plus values invents a relationship.
MIN_ROWS = 2
MIN_COLUMNS = 2

#: A recovered shape whose cells are mostly one or two characters long is
#: CHARACTER FRAGMENTATION, not a table.
#:
#: This gate exists because of a measurement, not a hypothesis. Running the
#: geometry recovery over the live corpus reported 29 of 98 pages "parsed", and
#: reading those 29 showed things like
#:
#:     ['DE', 'F', 'I', 'N', 'IT', 'I', 'O', 'N']
#:
#: which is the single word DEFINITION cut into eight columns by the vertical
#: white space between its letters. A scanned page has no ruling lines, so the
#: detector latches onto letter spacing and returns a grid of fragments. Every
#: one of those 29 was of that kind: the true usable rate on this corpus is
#: zero, and the 29 was an artefact of counting shapes rather than reading them.
#:
#: Accepting them would put "F" and "IT" into a requirement as a field name and
#: a value. An unparsed table costs a reader one honest gap; an invented one
#: costs them a wrong number they have no reason to doubt.
MAX_FRAGMENT_RATIO = 0.5
FRAGMENT_LENGTH = 2

#: A second fragmentation signature, and the one that catches what the ratio
#: misses. Page 449 of the differential-equations text recovers as
#:
#:     ['T', 'H', 'E', 'O', 'R', 'E', ...]   (51 columns)
#:
#: which is the word THEOREM, and page 120 recovers 46 columns of two- and
#: three-letter pieces that the length ratio lets through because the pieces
#: are long enough individually.
#:
#: No engineering table has fifty columns. A noise-criterion table has a
#: frequency band per column and perhaps a dozen; a permissible-exposure table
#: has two or three. Twenty-five is well above anything legitimate and well
#: below the fragmentation cases, both of which were read before this number
#: was chosen.
MAX_COLUMNS = 25


def _is_fragmented(rows: list[list[str]]) -> bool:
    """True when the recovered cells look like split letters rather than data."""
    cells = [cell for row in rows for cell in row if cell]
    if not cells:
        return True
    fragments = sum(1 for cell in cells if len(cell) <= FRAGMENT_LENGTH)
    return (fragments / len(cells)) > MAX_FRAGMENT_RATIO


@dataclass(frozen=True)
class TableParse:
    """One table chunk, parsed or explicitly not.

    `unparsed_reason` is the whole point of this class. A table that could not
    be read is a FACT to report, not an absence to skip over.
    """

    chunk_id: str
    document_id: str
    page: int
    #: Row-major, header first when one was recovered. Empty when unparsed.
    rows: list[list[str]] = field(default_factory=list)
    #: The header row, when the recovered table has one.
    columns: list[str] = field(default_factory=list)
    unparsed_reason: str | None = None

    @property
    def parsed(self) -> bool:
        return self.unparsed_reason is None

    def as_api(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "page": self.page,
            "columns": self.columns,
            "rows": self.rows,
            "parsed": self.parsed,
            "unparsed_reason": self.unparsed_reason,
        }


def _clean(cell: object) -> str:
    """A cell as text. `None` from the extractor is an EMPTY cell, not "None"."""
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def parse_page_tables(stored_path: str, page_no: int) -> list[list[list[str]]]:
    """Every table shape recoverable from one page of a stored PDF.

    Isolated in its own function so the geometry library is called in exactly
    one place and a page that makes PyMuPDF raise is a page with no tables
    rather than an ingestion failure - this runs over documents an outside
    contractor supplied.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pymupdf is a hard dependency elsewhere
        return []
    try:
        with pymupdf.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            found = doc[page_no - 1].find_tables()
            out: list[list[list[str]]] = []
            for table in found.tables:
                rows = [[_clean(cell) for cell in row] for row in table.extract()]
                rows = [row for row in rows if any(cell for cell in row)]
                width = max(len(r) for r in rows)
                if len(rows) < MIN_ROWS or width < MIN_COLUMNS:
                    continue
                if width > MAX_COLUMNS or _is_fragmented(rows):
                    # Split letters, not data. See MAX_FRAGMENT_RATIO.
                    continue
                out.append(rows)
            return out
    except Exception:  # noqa: BLE001 - an unreadable page is not a crash
        return []


def parse_document_tables(
    document_id: str, *, allowed_document_ids: frozenset[str],
) -> list[TableParse]:
    """Every table chunk of one document, parsed or marked unparsed.

    Scoped like every other read: an empty grant set resolves to `1 = 0`, never
    to "no restriction".
    """
    if not allowed_document_ids:
        return []
    marks = ",".join("?" for _ in allowed_document_ids)
    rows = connect().execute(
        f"""SELECT c.id, c.document_id, c.page_start, d.stored_path
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.document_id IN ({marks}) AND c.document_id = ?
              AND c.kind = 'table'
            ORDER BY c.page_start, c.ordinal""",
        [*sorted(allowed_document_ids), document_id],
    ).fetchall()

    out: list[TableParse] = []
    # One PDF open per PAGE would be wasteful on a document with forty table
    # chunks, so pages are parsed once and shared by every chunk on them.
    by_page: dict[int, list[list[list[str]]]] = {}
    for row in rows:
        page = row["page_start"]
        if page not in by_page:
            by_page[page] = parse_page_tables(row["stored_path"], page)
        tables = by_page[page]
        if not tables:
            out.append(TableParse(
                chunk_id=row["id"], document_id=row["document_id"], page=page,
                # Named precisely. The page IS a table - the chunker said so -
                # and what is missing is the ruling geometry a parser needs.
                # "no table here" would contradict the chunker and send the
                # reader looking for the wrong problem.
                unparsed_reason="no recoverable table geometry on this page",
            ))
            continue
        # The largest table on the page, by cell count. A page with a real
        # table and a stray two-cell artefact should yield the real one, and
        # the chunk cannot tell us which it belongs to.
        best = max(tables, key=lambda t: sum(len(r) for r in t))
        header = best[0] if best else []
        out.append(TableParse(
            chunk_id=row["id"], document_id=row["document_id"], page=page,
            rows=best, columns=header,
        ))
    return out


def completeness(parses: list[TableParse]) -> dict:
    """How much of a standard's tabular content was actually read.

    A RATE WITH ITS DENOMINATOR, always. `rates.py` already refuses a rate from
    a near-zero denominator elsewhere in this system for the same reason: "34%"
    over three tables is noise presented as a measurement.

    `parsed_fraction` is None when there are no tables at all - which is not
    0% and must not render as a failure. A standard with no tables has nothing
    missing.
    """
    total = len(parses)
    parsed = sum(1 for p in parses if p.parsed)
    return {
        "tables_total": total,
        "tables_parsed": parsed,
        "tables_unparsed": total - parsed,
        "parsed_fraction": (round(parsed / total, 3) if total else None),
    }
