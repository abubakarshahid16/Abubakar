"""#193 plan B4 (order 5.5): the geometry reader wired into `extract_facts`
behind `settings.geometry_reader_enabled`, OFF by default.

* OFF is the pre-B4 extraction: the geometry reader is never called and the
  facts are exactly those of a run in which it contributes nothing.
* ON adds `extraction_method='geometry'` facts with their provenance (boxes,
  source, table cell), never a second copy of a rule-reader fact, and never a
  value written over one: a disagreement is kept as a `conflict` row naming
  the rule fact it contradicts.

Synthetic PDFs only; no client document is read (CLAUDE.md rule 3).
Mutation proofs: M586-M589, M591, M596, M1022 (scripts/mutations/datasheets.py).
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from app import datasheets, db, geometry_reader, submittal_review
from app.config import settings

NOW = "2026-09-25T00:00:00Z"

#: Words at the positions a two-column form prints them. The rule readers read
#: the colon pairs; the geometry reader also reads the drawn fields.
ITEMS = [
    (50, 100, "DESIGN PRESSURE: 10 barg"),
    (50, 140, "DESIGN TEMPERATURE: 120 C"),
    (50, 180, "CASE MOUNTING"), (220, 180, "____________"),
    (50, 220, "BEARING TYPE"), (220, 220, "___BALL___"),
    (50, 260, "SPEED:"), (140, 260, "2950 rpm"),
    (50, 300, "SUCTION PRESSURE"), (220, 300, "_________ bar g"),
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "geo.sqlite")
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    # "OFF" below means every geometry path off - the table path alone is
    # on by default since 2026-09-25 (test_b4_schedule_tables.py).
    monkeypatch.setattr(settings, "geometry_table_reader_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _store(tmp_path, items=ITEMS, doc_id="doc_geo") -> str:
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for x, y, text in items:
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


def _extract(doc_id: str) -> dict:
    return datasheets.extract_facts(doc_id, allowed_document_ids=frozenset({doc_id}),
                                    replace=True)


def _current(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?"
        " AND superseded_at IS NULL ORDER BY page, field_name, extraction_method,"
        " field_value", (doc_id,))]


#: Per-write columns: a fresh id and clock on every run. Everything else is
#: what the extraction SAID and must not move with the flag off.
_VOLATILE = {"id", "created_at", "updated_at", "superseded_at"}


def _snapshot(doc_id: str) -> list[dict]:
    return [{k: v for k, v in f.items() if k not in _VOLATILE} for f in _current(doc_id)]


def _explode(*_a, **_k):
    raise AssertionError("the geometry reader ran with the flag off")


# ------------------------------------------------------------------ flag OFF

def test_the_flag_is_off_by_default():
    from app.config import Settings
    assert Settings.model_fields["geometry_reader_enabled"].default is False


def test_off_never_calls_the_geometry_reader_and_the_facts_are_identical(tmp_path, monkeypatch):
    """THE MUTATION TARGET (M586): OFF = the pre-B4 extraction, byte for byte.

    Run 1: flag ON with a geometry reader that contributes nothing - the
    rule readers alone. Run 2: flag OFF, with the geometry reader rigged to
    fail the test if it is so much as called. The two fact sets must be
    identical column for column, and the OFF result carries no geometry keys.
    """
    doc = _store(tmp_path)
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    _extract(doc)
    rules_only = _snapshot(doc)
    assert rules_only, "the rule readers read nothing - the comparison would be vacuous"

    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", _explode)
    monkeypatch.setattr(geometry_reader, "read_page_rows", _explode)
    result = _extract(doc)
    off = _snapshot(doc)
    # extractor_version is the same code hash in both runs (same source).
    assert off == rules_only
    assert not [f for f in off if f["extraction_method"] == "geometry"]
    assert "geometry_facts" not in result and "geometry_conflicts" not in result


# ------------------------------------------------------------------ flag ON

@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)


def test_on_adds_geometry_facts_with_their_provenance(tmp_path, on):
    """THE MUTATION TARGET (M587): the fields only the geometry reader reads
    become facts, each with its page, box, source and reader version."""
    doc = _store(tmp_path)
    result = _extract(doc)
    geo = [f for f in _current(doc) if f["extraction_method"] == "geometry"]
    assert geo and result["geometry_facts"] == len(geo)
    names = {f["field_name"]: f for f in geo}
    assert {"bearing type", "design pressure", "design temperature"} <= set(names)
    bearing = names["bearing type"]
    assert (bearing["field_value"], bearing["is_blank"], bearing["page"]) == ("BALL", 0, 1)
    assert bearing["source_text"] == "___BALL___"
    assert bearing["validation_state"] is None
    assert bearing["extractor_version"].startswith("datasheets+tables+geometry_reader@")
    box = json.loads(bearing["bbox"])
    assert box["source"] == "form" and box["reader"] == "geometry_reader"
    assert len(box["value_bbox"]) == 4 and len(box["label_bbox"]) == 4
    assert box["value_bbox"][0] > box["label_bbox"][2]
    pressure = names["design pressure"]
    assert (pressure["raw_value"], pressure["raw_unit"]) == ("10", "barg")


def test_a_rule_reader_fact_wins_and_is_not_duplicated(tmp_path, on):
    """THE MUTATION TARGET (M588): a field both readers read - filled or
    blank - is written ONCE, by the rule reader."""
    doc = _store(tmp_path)
    _extract(doc)
    rows = _current(doc)
    for name in ("speed", "case mounting", "suction pressure"):
        same = [f for f in rows if f["field_name"] == name]
        assert len(same) == 1, (name, [f["extraction_method"] for f in same])
        assert same[0]["extraction_method"] == "extracted"


def _row(label: str, value_text: str, *, value=None, unit=None, blank=False, marker=None,
         source="form", column_label=None, table_id=None) -> dict:
    return {"source": source, "page": 1, "label": label, "label_text": label,
            "value_text": value_text, "value": value, "unit": unit,
            "is_blank": blank, "blank_marker": marker, "condition": None, "note": None,
            "bbox": [140.0, 90.0, 190.0, 102.0],
            "label_bbox": [50.0, 90.0, 130.0, 102.0] if source == "form" else None,
            "position": "right" if source == "form" else None, "table_id": table_id,
            "row": 3 if table_id else None, "column": 2 if table_id else None,
            "column_label": column_label}


def test_a_disagreement_is_recorded_as_a_conflict_not_written_over(tmp_path, monkeypatch, on):
    """THE MUTATION TARGET (M589): a geometry reading that contradicts
    the rule reader is kept beside it as `conflict`, naming the rule fact by
    id - and the rule fact is untouched."""
    doc = _store(tmp_path)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [
        _row("SPEED", "3000 rpm", value="3000", unit="rpm")])
    result = _extract(doc)
    same = [f for f in _current(doc) if f["field_name"] == "speed"]
    rule = [f for f in same if f["extraction_method"] != "geometry"]
    geo = [f for f in same if f["extraction_method"] == "geometry"]
    assert len(rule) == 1 and len(geo) == 1
    assert rule[0]["raw_value"] == "2950" and rule[0]["validation_state"] is None
    assert geo[0]["raw_value"] == "3000"
    assert geo[0]["validation_state"] == datasheets.GEOMETRY_CONFLICT == "conflict"
    assert json.loads(geo[0]["bbox"])["conflicts_with"] == [rule[0]["id"]]
    assert result["geometry_conflicts"] == 1


def test_an_agreeing_reading_in_other_spelling_is_not_a_conflict(tmp_path, monkeypatch, on):
    """Negative for M589: the same speed spelled differently agrees."""
    doc = _store(tmp_path)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [
        _row("SPEED:", "2950.0 rpm", value="2950.0", unit="rpm")])
    result = _extract(doc)
    same = [f for f in _current(doc) if f["field_name"] == "speed"]
    assert [f["extraction_method"] for f in same] == ["extracted"]
    assert result["geometry_conflicts"] == 0 and result["geometry_facts"] == 0


def test_a_blank_against_a_value_is_a_conflict():
    fact = {"is_blank": 0, "raw_value": "10", "normalized_value": None,
            "normalized_unit": None, "field_value": "10 barg"}
    assert datasheets._geometry_agrees("", True, fact) is False
    assert datasheets._geometry_agrees("10 barg", False, fact) is True
    assert datasheets._geometry_agrees("11 barg", False, fact) is False


def test_the_readers_blank_evidence_and_table_cell_are_kept(tmp_path, monkeypatch, on):
    """THE MUTATION TARGET (M591): a drawn blank with its printed units is a
    blank with the reader's marker (the text rule alone would not call it
    blank), and a table cell keeps its column and cell."""
    printed = "________ bar g @ ________ oC"
    assert datasheets.is_blank_value(printed)[0] is False  # the override is what decides
    doc = _store(tmp_path)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [
        _row("HYDROTEST", printed, blank=True, marker="______"),
        _row("N1 Rating", "CL-150", value="CL-150", source="table",
             column_label="Rating", table_id="p1-t1")])
    _extract(doc)
    names = {f["field_name"]: f for f in _current(doc) if f["extraction_method"] == "geometry"}
    hydro = names["hydrotest"]
    assert (hydro["is_blank"], hydro["blank_marker"], hydro["raw_value"]) == (1, "______", None)
    assert hydro["field_value"] == printed
    cell = names["n1 rating"]
    assert cell["value_column"] == "Rating"
    box = json.loads(cell["bbox"])
    assert (box["source"], box["table_id"], box["row"], box["column"]) == ("table", "p1-t1", 3, 2)


def test_a_page_only_the_geometry_reader_read_is_read_into_fields(tmp_path, on):
    """THE MUTATION TARGET (M1022; owner decision 2026-09-26, honesty audit
    entry 68): a page whose only facts came from the geometry reader HAS
    recorded facts, so the ledger says it was read into fields. Under B4 it
    said "no_facts" while its facts sat in submittal_facts. An ABSENCE there
    is still an engineer's question (M595, test_b3_page_ledger.py)."""
    from app import page_ledger
    doc = _store(tmp_path, items=[(50, 220, "BEARING TYPE"), (220, 220, "___BALL___")],
                 doc_id="doc_geo_only")
    result = _extract(doc)
    assert result["geometry_facts"] >= 1
    assert result["pages_unparsed"] == 0
    row = page_ledger.rows(doc)[0]
    assert (row["facts_status"], row["facts_count"]) == ("facts", result["geometry_facts"])
    assert page_ledger.coverage(doc)["pages_not_read_into_fields"] == []


def test_a_page_no_reader_read_still_reads_no_facts(tmp_path, on):
    """The other side: a page with no fact from any reader is still unread -
    the fix counts recorded facts, it does not mark every page read."""
    from app import page_ledger
    doc = _store(tmp_path, items=[(50, 220, "Notes only, nothing to read here")],
                 doc_id="doc_nothing")
    result = _extract(doc)
    assert result["facts"] == 0
    assert page_ledger.rows(doc)[0]["facts_status"] == "no_facts"
    assert page_ledger.coverage(doc)["pages_not_read_into_fields"] == [1]


def test_a_non_quantity_value_keeps_the_unit_the_reader_split_off(tmp_path, monkeypatch, on):
    """THE MUTATION TARGET (M596): "<85" + "dBA" is stored as the value "<85"
    with the printed unit "dBA" - not glued back into "<85 dBA" with the
    unit lost, and never turned into a number."""
    doc = _store(tmp_path)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [
        _row("SOUND LEVEL", "<85 (dBA)", value="<85", unit="dBA")])
    _extract(doc)
    fact = next(f for f in _current(doc) if f["field_name"] == "sound level")
    assert (fact["field_value"], fact["raw_unit"], fact["raw_value"]) == ("<85", "dBA", None)
    # negative: a real quantity is handed over whole and parses as one
    assert datasheets._geometry_raw_value(_row("P", "10 barg", value="10", unit="barg")) == (
        "10 barg", None)
