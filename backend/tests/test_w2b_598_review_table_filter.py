"""#598: a standards-table cell is a review check only when the submittal has a
field that answers it. Synthetic data only (invented grades and values).
Mutations M2701-M2709 prove each test."""
from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, standards, submittal_review, table_gate
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t598.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, name=None):
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',3,'2026-09-18T00:00:00Z')""",
            (doc_id, name or f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf"))
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,document_role) VALUES (?,?,?)""",
            (doc_id, "test", role))
    return doc_id


def _chunk(chunk_id, doc_id, page=1):
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,?,?,NULL,'table','t',1,?,1)""",
            (chunk_id, doc_id, "f.pdf", page, page, f"h-{chunk_id}"))


def _cell(std, chunk, row, column, value, page=1, kind="table_value"):
    return standards.create_requirement(
        standard_document_id=std, chunk_id=chunk, clause=None, page=page,
        requirement_text=f"{row} - {column}: {value}",
        source_text=f"{row} | {column} | {value}", confidence=0.5,
        structured={"requirement_type": kind, "field": column, "condition": row,
                    "raw_value": str(value), "value": float(value),
                    "operator": "<="})["id"]


def _setup(facts, standards_spec):
    """standards_spec: {std_id: [(row, column, value), ...]} on page 1."""
    sub = _doc("sub", "CONTRACTOR_SUBMITTAL")
    _chunk("fc", sub)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run, sub))
    ids = {}
    for std, cells in standards_spec.items():
        _doc(std, "COMPANY_STANDARD", f"{std}.pdf")
        _chunk(f"c-{std}", std)
        with db.connect() as conn:
            conn.execute("""INSERT INTO review_applicable_standards
                (id,review_run_id,standard_document_id,selection_method,included,
                 created_at) VALUES (?,?,?,'rule',1,?)""",
                (str(uuid.uuid4()), run, std, "2026-09-18T00:00:00Z"))
        for row, column, value in cells:
            ids[(std, row, column)] = _cell(std, f"c-{std}", row, column, value)
    for label, value in facts:
        datasheets.create_fact(submittal_document_id=sub, chunk_id="fc",
                               field_label=label, raw_value=value, page=1)
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({sub, run, *standards_spec}))
    cited = {f["requirement_id"] for f in result["findings"] if f.get("requirement_id")}
    return ids, cited, result


GRADES = [("UNS S31600", 22), ("UNS S32205", 28), ("UNS N08825", 35)]


def _table(prefix_cols=("Max hardness (HRC)",)):
    return [(row, col, v) for row, v in GRADES for col in prefix_cols]


def test_only_the_rows_for_the_submittals_grade_are_checked_and_the_rest_are_grouped():
    """Test 1."""
    ids, cited, result = _setup([("Material", "UNS S31600")], {"std-a": _table()})
    assert ids[("std-a", "UNS S31600", "Max hardness (HRC)")] in cited
    assert ids[("std-a", "UNS S32205", "Max hardness (HRC)")] not in cited
    assert ids[("std-a", "UNS N08825", "Max hardness (HRC)")] not in cited
    [line] = result["table_values_not_compared"]
    assert line["count"] == 2
    assert line["line"] == ("2 table values in 1 table of std-a.pdf not compared: "
                            "no matching field on this submittal")
    assert line["tables"][0]["examples"] == ["UNS S32205", "UNS N08825"]


def test_a_submittal_with_no_matching_field_gets_no_table_checks_and_one_line_per_standard():
    """Test 2."""
    ids, cited, result = _setup(
        [("Noise level", "85 dB(A)")],
        {"std-a": _table(), "std-b": _table(("Max yield (MPa)",))})
    assert not (set(ids.values()) & cited)
    lines = {l["standard_document_id"]: l for l in result["table_values_not_compared"]}
    assert set(lines) == {"std-a", "std-b"}
    assert lines["std-a"]["count"] == 3 and lines["std-b"]["count"] == 3


def test_the_check_count_drops_from_every_cell_to_the_matched_rows():
    """Test 3. 20 rows x 3 columns = 60 cells; the sheet names one of the rows."""
    cols = ("Max hardness (HRC)", "Max yield (MPa)", "Max strain (pct)")
    rows = [(f"UNS S{31600 + i}", c, 10 + i) for i in range(20) for c in cols]
    _, cited, result = _setup([("Material", "UNS S31605")], {"std-a": rows})
    assert result["requirements_in_scope"] == 60
    assert result["requirements_evaluated"] == 3
    assert len([f for f in result["findings"] if f.get("requirement_id")]) == 3
    assert result["table_values_not_compared"][0]["count"] == 57


def test_a_table_the_submittal_cannot_select_by_row_is_matched_by_its_column_field():
    """The column is the handle only when no row matches by its key."""
    _, cited, result = _setup(
        [("Hardness", "21 HRC")], {"std-a": _table(("Max hardness (HRC)",))})
    assert result["requirements_evaluated"] == 3
    assert result["table_values_not_compared"] == []


def test_a_matching_row_stops_the_column_from_pulling_in_every_other_row():
    _, cited, result = _setup(
        [("Material", "UNS S31600"), ("Hardness", "21 HRC")],
        {"std-a": _table(("Max hardness (HRC)",))})
    assert result["requirements_evaluated"] == 1


def test_a_definition_never_becomes_a_check():
    """Test 4a, through a real run, with a control that is compared."""
    sub_facts = [("Noise level", "95 dB(A)")]
    sub = None
    ids, cited, result = _setup(sub_facts, {"std-a": []})
    # The control and the definition are written to the same standard.
    std = "std-a"
    control = standards.create_requirement(
        standard_document_id=std, chunk_id="c-std-a", clause="5.1", page=1,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).", confidence=0.9,
        structured={"requirement_type": "numeric_limit", "operator": "<=",
                    "value": 90, "unit": "dB(A)", "raw_value": "90",
                    "raw_unit": "dB(A)", "field": "noise level",
                    "subject": "the noise level"})["id"]
    definition = standards.create_requirement(
        standard_document_id=std, chunk_id="c-std-a", clause="3.1", page=1,
        requirement_text="Noise level: the level shall not exceed 90 dB(A) as defined.",
        source_text="Noise level: the level shall not exceed 90 dB(A) as defined.",
        confidence=0.9,
        structured={"requirement_type": "definition", "operator": "<=",
                    "value": 90, "unit": "dB(A)", "raw_value": "90",
                    "raw_unit": "dB(A)", "field": "noise level",
                    "subject": "the noise level"})["id"]
    run = next(iter({f["review_run_id"] for f in result["findings"]}), None)
    with db.connect() as conn:
        run = conn.execute("SELECT id FROM review_runs").fetchone()["id"]
        subm = conn.execute("SELECT submittal_document_id s FROM review_runs").fetchone()["s"]
    again = comparison.run_comparison(
        run, allowed_document_ids=frozenset({subm, std}))
    cited = {f["requirement_id"] for f in again["findings"]}
    assert control in cited
    assert definition not in cited
    assert again["requirements_excluded"] == {"definition": 1}


def test_unconfirmed_garbled_text_is_never_a_check_but_a_confirmed_row_is():
    cells = [
        {"id": "ok", "requirement_type": "numeric_limit"},
        {"id": "bad", "requirement_type": "numeric_limit", "quality_reason": "text_quality"},
        {"id": "bad2", "requirement_type": "table_value",
         "needs_verification_reason": "text_quality", "condition": "UNS S31600",
         "standard_document_id": "s", "chunk_id": "c"},
        {"id": "human", "requirement_type": "numeric_limit",
         "quality_reason": "text_quality", "confirmed_by": "eng"},
    ]
    out = table_gate.gate(cells, [{"field_label": "Material", "field_value": "UNS S31600"}])
    assert [r["id"] for r in out["kept"]] == ["ok", "human"]
    assert out["excluded"] == {"text_quality": 2}


def test_matching_is_by_normalised_words_not_by_a_list():
    values = [("Material", "uns  s31600"), ("Size", "DN 50")]
    cells = [
        {"id": "a", "requirement_type": "table_value", "condition": "UNS S31600",
         "field": "x", "standard_document_id": "s", "chunk_id": "c"},
        {"id": "b", "requirement_type": "table_value", "condition": "DN 50",
         "field": "x", "standard_document_id": "s", "chunk_id": "c"},
        {"id": "c", "requirement_type": "table_value", "condition": "DN 80",
         "field": "x", "standard_document_id": "s", "chunk_id": "c"},
    ]
    facts = [{"field_label": k, "field_value": v} for k, v in values]
    assert [r["id"] for r in table_gate.gate(cells, facts)["kept"]] == ["a", "b"]


def test_a_table_row_is_never_filtered_because_the_matcher_pairs_it_by_subject():
    cell = {"id": "r", "requirement_type": "table_row", "subject": "design pressure",
            "standard_document_id": "s", "chunk_id": "c", "condition": "x"}
    assert table_gate.gate([cell], [])["kept"] == [cell]
