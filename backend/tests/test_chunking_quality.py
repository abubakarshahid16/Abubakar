"""Chunking quality on SAES-style specifications (brief 2026-09-27, audit F1,
F2, F4, F5, F8, F10). Synthetic documents only - see synthetic_saes_spec.py.

The owner's live corpus measured: 3,761 chunks dropped by the quality gate
(paint data rows such as ": 4:1 by Volume"), 22% of retrievable chunks under
30 tokens, 35% starting mid-sentence, 95 table chunks in 275 documents and 315
duplicate chunk hashes. Each test below pins one cause. Mutations M1220-M1249.
"""

from __future__ import annotations

import json
import re

import pytest

from app import chunker as ch
from app import db, extract
from app.config import settings
from app.quality import assess
from tests.synthetic_saes_spec import build_corpus

# ======================================================================
# End-to-end fixture: the synthetic corpus through the REAL extract + chunk.
# ======================================================================


class _InlinePool:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *a, **k):
        import concurrent.futures as cf
        f = cf.Future()
        f.set_result(fn(*a, **k))
        return f


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """{pdf name: (document id, chunk rows)} plus the connection, built once."""
    from app import upload

    tmp = tmp_path_factory.mktemp("saes")
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "data_dir", tmp)
    mp.setattr(settings, "upload_dir", tmp / "uploads")
    mp.setattr(settings, "db_path", tmp / "t.sqlite")
    mp.setattr(extract.cf, "ProcessPoolExecutor", _InlinePool)
    db.reset_connection()
    db.init_db()
    out = {}
    for pdf in build_corpus(tmp / "pdf"):
        with open(pdf, "rb") as fh:
            row, _job, _dup = upload.ingest(fh, pdf.name)
        extract.extract_document(row["id"])
        result = ch.chunk_document(row["id"])
        rows = [dict(r) for r in db.connect().execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal", (row["id"],))]
        out[pdf.name] = {"id": row["id"], "chunks": rows, "result": result}
    yield out
    db.reset_connection()
    mp.undo()


def _retrievable(corpus, name=None):
    docs = [corpus[name]] if name else corpus.values()
    return [c for d in docs for c in d["chunks"] if c["retrievable"]]


_LIST_ITEM = re.compile(r"^(?:[a-z][).]|\(?[ivx]+[).]|[-•])\s")


def _mid_sentence(text: str) -> bool:
    t = text.lstrip()
    return bool(t) and t[0].islower() and not _LIST_ITEM.match(t)


# ======================================================================
# P0-1: the quality gate keeps data rows and short requirements
# ======================================================================

@pytest.mark.parametrize("text", [
    ": 4:1 by Volume",
    ": 35°C (Mixed) 4.5 Approved Color/s : Yellow (RAL 1023)",
    ": CS = Abrasive blast Sa 3",
    "Approved Color/s : Yellow (RAL 1023)",
    "Pot Life : 2 hours at 35°C",
    "Shall be 2H.",
])
def test_gate_keeps_data_rows_and_short_requirements(text):
    """Every one of these was `no_clause(longest=N<3)` - the rule that
    dropped 3,761 real chunks from the owner's corpus."""
    assert assess(text, "prose")["ok"], assess(text, "prose")


@pytest.mark.parametrize("text", [
    "eabeb2terfcb 1t a 2 1t ea1s 1s(1s b)",
    "a 1 b 2 c 3 d",
    ". . . . . . . . . . 12",
    "Page 3 of 26",
    "---- ==== ////",
])
def test_gate_still_rejects_junk(text):
    assert not assess(text, "prose")["ok"]


def test_a_recovered_table_is_judged_as_a_table():
    text = "| Coats | DFT (um) |\n| 1 | 75 |\n| 2 | 100 |"
    assert assess(text, "table")["ok"]


def test_no_data_sheet_row_is_excluded_on_the_synthetic_corpus(corpus):
    """End to end: every paint-system value is in a retrievable chunk."""
    retrievable = "\n".join(c["text"] for c in _retrievable(corpus, "saes_h_901v.pdf"))
    for value in ("4:1 by Volume", "3:1 by Volume", "35°C (Mixed)", "Yellow (RAL 1023)",
                  "CS = Abrasive blast Sa 3", "Single pack"):
        assert value in retrievable, value
    gated = [c for d in corpus.values() for c in d["chunks"]
             if c["kind"] in ("prose", "table") and not c["retrievable"]
             and (c["quality_flags"] or "").startswith("no_clause")]
    assert all(len(c["text"].split()) <= 3 for c in gated), [c["text"] for c in gated]


# ======================================================================
# Data-sheet rows are data, not headings
# ======================================================================

_SHEET = "\n".join([
    "APCS-1A",
    "Epoxy Primer / Epoxy Topcoat System",
    "1 General",
    "1.1 Generic Type : Two-component polyamide cured epoxy",
    "4 Mixing and Curing",
    "4.1 Mixing Ratio",
    ": 4:1 by Volume",
    "4.3 Pot Life",
    ": 4 hours at 25°C, 2 hours at",
    ": 35°C (Mixed)",
    "4.5 Approved Color/s : Yellow (RAL 1023)",
])


def test_data_sheet_rows_become_one_table_block_under_the_sheet_title():
    pages = [(1, "1 Scope\nThis standard lists the approved coating systems and their data."),
             (2, _SHEET)]
    blocks, _ = ch.segment_document(pages, running=set())
    tables = [b for b in blocks if b.kind == "table"]
    assert len(tables) == 1
    block = tables[0]
    assert "4.1 Mixing Ratio : 4:1 by Volume" in block.rows
    assert "4.3 Pot Life : 4 hours at 25°C, 2 hours at : 35°C (Mixed)" in block.rows
    assert block.lead[0] == "APCS-1A"
    # no field label became a clause
    assert not any(b.section and "Mixing Ratio" in b.section for b in blocks)


def test_a_prose_colon_is_not_a_data_row():
    lines = ["Note: the system shall be applied by airless spray to all surfaces."]
    assert ch._field_run(lines, 0) == ([], 0)


# ======================================================================
# P0-2: ruled tables, read by geometry
# ======================================================================

def test_extraction_stores_ruled_tables_beside_the_page_text(corpus):
    conn = db.connect()
    doc = corpus["saes_l_910.pdf"]["id"]
    rows = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, text, tables_json FROM pages WHERE document_id = ?", (doc,))}
    table = json.loads(rows[1]["tables_json"])["tables"][0]
    assert ["Seawater", '1/2" - 12"', "UNS S32760", "40S", "0.0"] in table["rows"]
    lines = rows[1]["text"].split("\n")
    assert {lines[i] for i in table["lines"]} >= {"Seawater", "UNS S32760", "0.0"}
    # a page without ruling stores nothing, and the page text is unchanged
    assert rows[2]["tables_json"] is None
    assert "UNS S32760" in rows[1]["text"]


def test_a_table_is_one_table_chunk_with_its_header_and_no_fake_clause(corpus):
    chunks = corpus["saes_l_910.pdf"]["chunks"]
    tables = [c for c in chunks if c["kind"] == "table" and "Pipe Material" in c["text"]]
    assert len(tables) == 1
    text = tables[0]["text"]
    assert "| Service | Size range | Material | Schedule | CA (mm) |" in text
    assert '| Seawater | 1/2" - 12" | UNS S32760 | 40S | 0.0 |' in text
    assert tables[0]["section"] == "4.1 Pipe" and tables[0]["retrievable"]
    # the row values never became clause headings ...
    assert not any((c["section"] or "").startswith(("3.0", "1.5", "0.0")) for c in chunks)
    # ... and never appear a second time as shredded prose
    assert not any("UNS S32760" in c["text"] for c in chunks if c["kind"] == "prose")


def test_a_long_table_is_split_on_rows_with_the_header_repeated(corpus):
    pieces = [c for c in corpus["saes_h_900.pdf"]["chunks"]
              if c["kind"] == "table" and "Coating Systems" in c["text"]]
    assert len(pieces) >= 3
    header = "| System | Primer | Primer DFT (um) | Total DFT (um) | Max temp (C) |"
    for c in pieces:
        lines = c["text"].split("\n")
        assert lines[0] == "Table 3 - Coating Systems" and lines[1] == header
        assert c["token_count"] <= settings.chunk_max_tokens
    rows = [ln for c in pieces for ln in c["text"].split("\n")[2:]]
    systems = [ln.split("|")[1].strip() for ln in rows]
    # every row exactly once, across the page break, none lost or repeated
    assert systems == [f"CS-{k:02d}" for k in range(1, 45)]
    # the piece holding a page-5 row cites page 5
    assert any(c["page_end"] > c["page_start"] or c["page_start"] == 5 for c in pieces
               if "CS-44" in c["text"])


def test_a_table_continued_on_the_next_page_is_one_table():
    """The '(continued)' part joins its first part rather than starting a new
    table with a caption that is not the table's name."""
    header = ["System", "DFT"]
    t1 = {"rows": [header, ["CS-01", "100"], ["CS-02", "120"]], "lines": [1, 2, 3, 4, 5, 6]}
    t2 = {"rows": [header, ["CS-03", "140"]], "lines": [1, 2, 3, 4]}
    pages = [(1, "Table 3 - Coating Systems\nSystem\nDFT\nCS-01\n100\nCS-02\n120"),
             (2, "Table 3 - Coating Systems (continued)\nSystem\nDFT\nCS-03\n140")]
    masked = ch.mask_tables(pages, {1: [t1], 2: [t2]}, set())
    blocks, _ = ch.segment_document(masked, running=set())
    tables = [b for b in blocks if b.kind == "table"]
    assert len(tables) == 1
    assert tables[0].rows == ["| CS-01 | 100 |", "| CS-02 | 120 |", "| CS-03 | 140 |"]
    assert tables[0].row_pages == [1, 1, 2]
    assert tables[0].lead == ["Table 3 - Coating Systems", "| System | DFT |"]


def test_a_ruled_header_box_on_every_page_is_furniture_not_a_table(corpus):
    """The coating standard draws a box round its running header; the table
    finder reads it as a table on every page. It must not be published."""
    chunks = corpus["saes_h_900.pdf"]["chunks"]
    assert not any("Document Responsibility" in c["text"] for c in chunks)
    assert not any("Next Planned Update" in c["text"] for c in chunks)


# ======================================================================
# P0-3: fragments and mid-sentence starts
# ======================================================================

def test_a_sentence_across_a_page_break_is_one_sentence_and_its_word_is_rejoined():
    blocks = [
        ch.Block("prose", "Bolting shall be supplied clean. Bolting shall be hot-dip galvan-",
                 3, 3, "4.1 General"),
        ch.Block("prose", "ized after threading and inspected. The zinc shall be even.",
                 4, 4, "4.1 General"),
    ]
    chunks = ch.build_chunks(blocks)
    assert len(chunks) == 1
    assert "hot-dip galvanized after threading" in chunks[0].text
    assert (chunks[0].page_start, chunks[0].page_end) == (3, 4)
    assert not any(_mid_sentence(c.text) for c in chunks)


def test_a_colon_or_abbreviation_does_not_start_a_new_unit():
    assert ch.sentences("Apply as follows: the primer first. Then the topcoat.") == [
        "Apply as follows: the primer first.", "Then the topcoat."]
    assert ch.sentences("Use e.g. the approved list. Keep records.") == [
        "Use e.g. the approved list.", "Keep records."]


def test_a_runt_under_forty_tokens_joins_its_section_neighbour():
    big = ch.Block("prose", "word " * 150, 1, 1, "4.1 General", 150)
    small_text = ("The coating shall be cured for at least seven days before any immersion "
                  "test, and the cure shall be recorded by the inspector on the daily report.")
    small = ch.Block("prose", small_text, 1, 1, "4.1 General", ch.count_tokens(small_text))
    assert 25 <= small.tokens < 40
    merged = ch._merge_runts([big, small])
    assert len(merged) == 1 and small_text in merged[0].text


def test_a_runt_never_joins_another_clause():
    big = ch.Block("prose", "word " * 150, 1, 1, "4.1 General", 150)
    small = ch.Block("prose", "Nuts shall be heavy hex.", 1, 1, "4.2.2", 7)
    assert len(ch._merge_runts([big, small])) == 2


def test_corpus_targets_tiny_and_mid_sentence_chunks(corpus):
    """Brief targets on the synthetic corpus: under 5% of retrievable chunks
    below 30 tokens, under 5% starting mid-sentence."""
    chunks = _retrievable(corpus)
    tiny = [c for c in chunks if c["token_count"] < 30]
    mid = [c for c in chunks if _mid_sentence(c["text"])]
    assert len(tiny) / len(chunks) < 0.05, [c["text"] for c in tiny]
    assert not mid, [c["text"][:60] for c in mid]
    assert max(c["token_count"] for c in chunks) <= settings.chunk_max_tokens


# ======================================================================
# F2 / task 4: running lines are furniture, table values are not
# ======================================================================

_WORDS = ("pump", "valve", "flange", "gasket", "nozzle", "casing", "shaft", "seal",
          "bearing", "coupling", "impeller", "baseplate", "guard", "lining", "vent", "drain")


def _body(p: int, n: int = 14) -> list[str]:
    """Body lines that differ in WORDS from page to page, not only in digits -
    a line differing only in its digits is exactly what a running line is."""
    return [f"The {_WORDS[(p + k) % 16]} and the {_WORDS[(p * 3 + k * 5) % 16]} "
            f"shall suit the {_WORDS[(p * 7 + k) % 16]}." for k in range(n)]


def _book(n_pages=8, last_values=("69", "222", "200")):
    pages = []
    for p in range(1, n_pages + 1):
        body = _body(p)
        pages.append((p, "\n".join(["SAES-H-900", "Issue Date: 12 March 2024", *body,
                                   *last_values, str(p)])))
    return pages


def test_bare_numbers_at_the_foot_of_a_page_survive_unless_they_are_the_page_number():
    pages = _book()
    running = ch.detect_running_lines(pages)
    cleaned, removed = ch.strip_running_lines(pages[5][1], running, 6)
    lines = cleaned.splitlines()
    assert lines[-3:] == ["69", "222", "200"]  # the table's last row
    assert "6" not in lines                    # the page number
    assert "SAES-H-900" not in lines and removed == 3


def test_a_page_top_heading_sharing_a_masked_shape_is_kept():
    pages = [(p, "\n".join([f"A.{p} Coating system no. {p}", *_body(p)]))
             for p in range(1, 8)]
    running = ch.detect_running_lines(pages)
    cleaned, _ = ch.strip_running_lines(pages[3][1], running, 4)
    assert cleaned.splitlines()[0] == "A.4 Coating system no. 4"


def test_a_header_block_longer_than_the_edge_window_is_removed_whole():
    furniture = ["Document Responsibility: Paints Committee", "SAES-H-900",
                 "Issue Date: 12 March 2024", "Next Planned Update: 12 March 2029",
                 "Protective Coating Requirements", "Company General Use"]
    pages = [(p, "\n".join([*furniture, f"Page {p} of 9", *_body(p, 15)]))
             for p in range(1, 8)]
    running = ch.detect_running_lines(pages)
    cleaned, removed = ch.strip_running_lines(pages[2][1], running, 3)
    assert removed == 7
    assert cleaned.splitlines() == _body(3, 15)


# ======================================================================
# F4 / task 5: a numbering gap keeps later clauses
# ======================================================================

def test_a_missing_sibling_does_not_disable_the_rest_of_the_group():
    allowed = ch.plausible_heading_numbers(["4", "4.1", "4.3", "4.4", "4.5", "4.6"])
    assert {"4.1", "4.3", "4.4", "4.5", "4.6"} <= allowed


def test_a_far_jump_is_still_refused_unless_its_children_vouch_for_it():
    allowed = ch.plausible_heading_numbers(["9.1", "9.2", "9.3", "9.33", "9.35"])
    assert "9.33" not in allowed and "9.35" not in allowed
    vouched = ch.plausible_heading_numbers(["9.1", "9.2", "9.9", "9.9.1"])
    assert "9.9" in vouched


def test_corpus_clauses_after_a_gap_keep_their_labels(corpus):
    sections = {c["section"] for c in corpus["saes_h_900.pdf"]["chunks"]}
    assert {"4.3 Surface Preparation", "4.4 Application", "4.5 Inspection",
            "4.6 Repairs"} <= sections


# ======================================================================
# F5 / F8 / task 6: headings after a table, long numbered requirements
# ======================================================================

def test_a_table_run_stops_at_the_heading_after_it():
    page = "\n".join(["5.2 Heat Treatment", "Post weld heat treatment is as follows.",
                      "1", "19", "595 - 650", "1", "3", "16", "595 - 720", "1",
                      "6.1 Surface Preparation",
                      "Surfaces shall be blast cleaned to Sa 2.5 before coating."])
    blocks, _ = ch.segment_document([(1, "5.1 Welding\nWelds shall be ground."), (2, page)],
                                    running=set())
    last = blocks[-1]
    assert last.section == "6.1 Surface Preparation"
    assert "blast cleaned" in last.text


def test_a_long_numbered_requirement_is_its_own_clause():
    page = "\n".join([
        "4.2 Bolting",
        "Bolting shall be supplied with certificates.",
        "4.2.1 Stud bolts for flanges in hydrocarbon service shall be ASTM A193 Grade B7 with a",
        "minimum yield strength of 725 MPa.",
        "4.2.2 Nuts shall be heavy hex ASTM A194 Grade 2H.",
    ])
    blocks, _ = ch.segment_document([(1, "4 Materials\n4.1 Pipe\nPipe shall be seamless."),
                                     (2, page)], running=set())
    by_section = {b.section: b.text for b in blocks}
    assert "4.2.1" in by_section and "725 MPa" in by_section["4.2.1"]
    assert by_section["4.2.1"].startswith("4.2.1 Stud bolts")


def test_a_wrapped_requirement_whose_first_line_looks_like_a_title_keeps_its_text():
    page = "\n".join([
        "4.2 Bolting",
        "Bolting shall be supplied with certificates.",
        "4.2.1 Stud bolts for flanges in hydrocarbon service",
        "shall be ASTM A193 Grade B7.",
    ])
    blocks, _ = ch.segment_document([(1, "4.1 Pipe\nPipe shall be seamless."), (2, page)],
                                    running=set())
    block = next(b for b in blocks if b.section == "4.2.1")
    assert block.text.startswith("4.2.1 Stud bolts for flanges")


# ======================================================================
# F10 / task 7: line-break hyphens
# ======================================================================

@pytest.mark.parametrize("raw,expected", [
    ("hot-dip galvan-\nized", "hot-dip galvanized"),
    ("tempera-\nture", "temperature"),
    ("carbon-\nsteel", "carbon-steel"),
    ("API-\n5L", "API-\n5L"),
])
def test_line_break_hyphens_are_repaired_conservatively(raw, expected):
    assert ch.dehyphenate(raw) == expected


def test_the_documents_own_spelling_decides_an_unknown_split():
    vocab = frozenset({"fireproof"})
    assert ch.dehyphenate("fire-\nproof", vocab) == "fireproof"
    assert ch.dehyphenate("fire-\nproof") == "fire-proof"
    # and a compound the document prints whole keeps its hyphen
    assert ch.dehyphenate("pre-\nqualified", frozenset({"pre-qualified"})) == "pre-qualified"


# ======================================================================
# Task 8: duplicates kept once for search, page kept for citation
# ======================================================================

def test_identical_chunks_in_one_section_are_kept_once(corpus):
    doc = corpus["saes_h_901v.pdf"]
    notes = [c for c in doc["chunks"] if c["text"].startswith("Note: The system")]
    assert len(notes) == len({c["page_start"] for c in notes}) >= 3
    assert sum(c["retrievable"] for c in notes) == 1
    ledger = db.connect().execute(
        "SELECT page_start, rule FROM exclusions WHERE document_id = ? AND rule = ?",
        (doc["id"], "duplicate_chunk")).fetchall()
    # every copy's page is still on record
    assert {r["page_start"] for r in ledger} == {c["page_start"] for c in notes
                                                 if not c["retrievable"]}


def test_the_same_text_under_two_clauses_is_two_citations():
    a = ch.Block("prose", "Not used.", 1, 1, "4.1 General")
    b = ch.Block("prose", "Not used.", 2, 2, "4.2 Bolting")
    c = ch.Block("prose", "Not used.", 3, 3, "4.2 Bolting")
    assert ch.duplicate_of([a, b, c]) == {2: 1}


# ======================================================================
# Versioning: old chunks are detected stale
# ======================================================================

def test_extracted_tables_are_part_of_the_chunk_signature():
    pages = [(1, "text")]
    assert ch._chunk_signature("s", pages) != ch._chunk_signature("s", pages, {1: '{"v":"1"}'})


def test_chunks_from_the_previous_chunker_are_stale(corpus, monkeypatch):
    conn = db.connect()
    doc = corpus["saes_l_910.pdf"]["id"]
    assert not ch.is_stale(conn, doc)
    monkeypatch.setattr(ch, "CHUNKER_VERSION", str(int(ch.CHUNKER_VERSION) - 1))
    old = ch._chunk_signature(
        conn.execute("SELECT sha256 FROM documents WHERE id = ?", (doc,)).fetchone()[0],
        *ch._load_pages(conn, doc)[:2])
    monkeypatch.undo()
    stored = conn.execute("SELECT chunk_signature FROM documents WHERE id = ?",
                          (doc,)).fetchone()[0]
    assert old != stored
