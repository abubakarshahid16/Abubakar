"""B4: equipment schedules (a nozzle table) read by the geometry TABLE path.

FOUND ON A REAL SUBMITTAL (owner-approved cloud test, 2026-09-25): a vessel
datasheet's nozzle schedule - one row per nozzle across Mark / Size / Unit /
Rating / Type / Facing / Service - produced NO facts. The label/value readers
paired it into nonsense ("raised face -> <the nozzle's service>") and the value gate
rightly rejected every pair: 44 recovered, 0 kept. The geometry reader's table
path read all 20 nozzles correctly, but only behind GEOMETRY_READER_ENABLED,
whose FORM path also mis-pairs pump-sheet fields. And its table path turned
the page-1 revision block into "facts" (people's names under a service-order
label).

So, and only this:
  * GEOMETRY_TABLE_READER_ENABLED runs the table path alone - ON by default
    (owner decision 2026-09-25);
  * a table carrying the revision header's words is dropped whole.

Synthetic PDFs only - no client document is read (CLAUDE.md rule 3).
Mutations M780-M785 (scripts/mutations/datasheets.py).
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from app import datasheets, db, row_noise, submittal_review
from app.config import Settings, settings

NOW = "2026-09-25T00:00:00Z"

#: A made-up schedule: every value invented for this test.
SCHEDULE_HEAD = ["Mark", "Size", "Rating", "Facing", "Service"]
SCHEDULE_ROWS = [["Z1", "6", "CL-300", "RTJ", "Feed Inlet"],
                 ["Z2", "3", "CL-300", "RTJ", "Gas Outlet"],
                 ["Z3", "2", "CL-150", "RF", "Drain"]]
#: A made-up revision history: the shape every datasheet's first page carries.
REVISION_HEAD = ["Rev", "Description", "Prepared", "Checked"]
#: Lettered revisions, as real blocks use: "A Prepared -> A. Author" then
#: passes every PER-ROW rule (a digit-keyed "0 Prepared" is already dropped as
#: a fragment), which is exactly how the real block reached the facts.
REVISION_ROWS = [["A", "Issued for Review", "A. Author", "B. Checker"],
                 ["B", "Issued for Design", "A. Author", "B. Checker"]]
#: A two-column form the geometry FORM reader reads (a drawn blank field).
FORM = [(50, 520, "CASE MOUNTING"), (220, 520, "____________"),
        (50, 560, "BEARING TYPE"), (220, 560, "___BALL___")]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "sched.sqlite")
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _grid(page, x0, y0, widths, head, rows, row_h=20):
    """A fully ruled table: header row, then data rows."""
    lines = [head, *rows]
    x1 = x0 + sum(widths)
    for i in range(len(lines) + 1):
        page.draw_line((x0, y0 + i * row_h), (x1, y0 + i * row_h), width=0.6)
    x = x0
    for w in [0, *widths]:
        x += w
        page.draw_line((x, y0), (x, y0 + len(lines) * row_h), width=0.6)
    for r, cells in enumerate(lines):
        x = x0
        for w, text in zip(widths, cells, strict=True):
            page.insert_text((x + 3, y0 + r * row_h + 14), text, fontsize=8)
            x += w


def _store(tmp_path, *, schedule=True, revision=True, form=True, doc_id="doc_sched") -> str:
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    if revision:
        _grid(page, 40, 60, [40, 180, 110, 110], REVISION_HEAD, REVISION_ROWS)
    if schedule:
        _grid(page, 40, 260, [60, 50, 80, 60, 180], SCHEDULE_HEAD, SCHEDULE_ROWS)
    if form:
        for x, y, text in FORM:
            page.insert_text((x, y), text, fontsize=10)
    pdf.save(str(path))
    text = pdf[0].get_text()
    pdf.close()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
                     (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), NOW))
        conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                     " VALUES (?,1,?,?,0,0)", (doc_id, text, len(text)))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)""",
                     (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    return doc_id


def _geometry(doc_id: str) -> list[dict]:
    datasheets.extract_facts(doc_id, allowed_document_ids=frozenset({doc_id}), replace=True)
    return [dict(r) for r in db.connect().execute(
        "SELECT field_name, field_value, bbox FROM submittal_facts"
        " WHERE submittal_document_id = ? AND superseded_at IS NULL"
        " AND extraction_method = 'geometry' ORDER BY field_name", (doc_id,))]


def _values(facts) -> dict[str, str]:
    return {f["field_name"]: f["field_value"] for f in facts}


def _all_current(doc_id: str) -> dict[str, str]:
    """Every current fact, whichever reader wrote it. A geometry reading that
    AGREES with a rule-reader fact is not written twice (the rule reader
    wins), so a schedule is judged on the union."""
    return _values(dict(r) for r in db.connect().execute(
        "SELECT field_name, field_value FROM submittal_facts"
        " WHERE submittal_document_id = ? AND superseded_at IS NULL", (doc_id,)))


# ------------------------------------------------------------------ the flag

def test_the_table_flag_is_on_by_default():
    """Owner decision 2026-09-25: schedules are read unless switched off."""
    assert Settings.model_fields["geometry_table_reader_enabled"].default is True


def test_off_the_schedule_yields_no_geometry_fact(tmp_path):
    assert _geometry(_store(tmp_path)) == []


# ------------------------------------------------------------ the schedule

def test_on_every_schedule_cell_is_a_fact_under_its_column(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", True)
    doc = _store(tmp_path, revision=False, form=False)
    assert _geometry(doc), "the table path wrote nothing"
    got = _all_current(doc)
    for mark, size, rating, facing, service in SCHEDULE_ROWS:
        key = mark.lower()
        assert got.get(f"{key} size") == size, got
        assert got.get(f"{key} rating") == rating, got
        assert got.get(f"{key} facing") == facing, got
        assert got.get(f"{key} service") == service, got


def test_table_only_mode_writes_no_form_reading(tmp_path, monkeypatch):
    """The form path mis-pairs real pump sheets, so the table flag must not
    bring it in: every geometry fact comes from a table cell."""
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", True)
    facts = _geometry(_store(tmp_path, revision=False))
    assert facts, "nothing read - the check below would be vacuous"
    sources = {json.loads(f["bbox"])["source"] for f in facts}
    assert sources == {"table"}, sources


def test_the_full_flag_still_brings_the_form_reading(tmp_path, monkeypatch):
    """The control for the test above: the page DOES carry a form reading, so
    its absence under the table flag is the filter, not an empty page."""
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    facts = _geometry(_store(tmp_path, revision=False))
    assert "form" in {json.loads(f["bbox"])["source"] for f in facts}


# ------------------------------------------------------------ the revision block

def test_a_revision_table_is_dropped_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", True)
    facts = _geometry(_store(tmp_path, form=False))
    text = " ".join(f"{f['field_name']} {f['field_value']}" for f in facts).lower()
    for name in ("a. author", "b. checker", "issued for"):
        assert name not in text, (name, text)
    # ... and the schedule beside it is untouched
    assert _values(facts).get("z1 service") == "Feed Inlet"


def test_a_revision_table_is_dropped_under_the_full_flag_too(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    text = " ".join(f"{f['field_name']} {f['field_value']}"
                    for f in _geometry(_store(tmp_path, form=False))).lower()
    assert "a. author" not in text and "b. checker" not in text


def test_one_revision_word_does_not_make_a_revision_table():
    """"Checked" alone can be a field; two distinct header words are needed."""
    one = [{"table_id": "t1", "label": "Checked", "label_text": "Checked",
            "value_text": "yes"}]
    two = [{"table_id": "t1", "label": "Prepared", "label_text": "Prepared",
            "value_text": "A"},
           {"table_id": "t1", "label": "Checked", "label_text": "Checked",
            "value_text": "B"}]
    assert row_noise.revision_table_ids(one) == set()
    assert row_noise.revision_table_ids(two) == {"t1"}
    # form rows (no table id) are never grouped into a table
    assert row_noise.revision_table_ids([{**r, "table_id": None} for r in two]) == set()


def test_a_cell_the_rule_reader_already_read_is_not_written_twice(tmp_path, monkeypatch):
    """The rule reader reads the size column itself; in table-only mode the
    agreeing geometry reading must be dropped, as under the full flag."""
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", True)
    doc = _store(tmp_path, revision=False, form=False)
    geometry = _values(_geometry(doc))
    assert _all_current(doc).get("z1 size") == "6"
    assert "z1 size" not in geometry, geometry
