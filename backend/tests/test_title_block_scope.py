"""Part of #1478, after #1549 (switch EQUIPMENT_FROM_TITLE_BLOCK_ENABLED): a title block
that names no equipment leaves the type to the engineer. The standards step still runs,
without an equipment term; a panel heading never sets the title or the type; the words
say the type is unknown, never that nothing applies. Invented data only."""

from __future__ import annotations

import pytest

from app import (
    applicability,
    classification,
    comparison,
    db,
    equipment_title_block,
    fts_index,
    subject_scope,
    submittal_fill,
    submittal_review,
)
from app.config import settings

TITLE = ["ACME PROJECT", "GENERAL NOTES", "Doc 1", "Rev 0", "Tag X-1"]
BODY = [f"Process line {i}" for i in range(5)] + ["MOTOR DATA"]
#: A pump sheet's words, in the body only.
WORDS = "impeller casing volute shaft seal impeller casing"


def _page(title=TITLE):
    tail = [f"{WORDS} {i}" for i in range(6)]
    return "\n".join(
        [*title, *BODY, *tail, "Notes", "Page 1 of 3", "Rev 0", "End", "x"]
    )


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", True)


def _add(doc_id, role, text, **meta):
    conn = db.connect()
    columns = ["document_id", "suggested_by", "document_role", *meta]
    values = [doc_id, "t", role, *meta.values()]
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, page_count, uploaded_at) VALUES (?,?,?,1,'x','ready',1,'2026-11-02')",
            (doc_id, f"{doc_id}.pdf", doc_id),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
            " VALUES (?,1,?,?,0)",
            (doc_id, text, len(text)),
        )
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
            " text, token_count, content_hash, retrievable) VALUES (?,?,'f',0,1,1,?,1,?,1)",
            (f"{doc_id}_c", doc_id, text, doc_id),
        )
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})",
            values,
        )
    fts_index.index_document(doc_id)


def _world():
    """A sheet whose title block names nothing, and a standard with the same words."""
    _add("sub", "CONTRACTOR_SUBMITTAL", _page())
    _add("std", "COMPANY_STANDARD", f"Rules for the {WORDS}.", document_number="ZZ-1")
    classification.classify_equipment_type_for_submittal("sub")
    submittal_fill.fill("sub")
    return frozenset({"sub", "std"})


def _select(allowed):
    result = applicability.select("sub", allowed_document_ids=allowed, persist=False)
    return result, {r["standard_document_id"]: r for r in result["selected"]}


def _title():
    return classification.of_document("sub").get("title")


# ---------------------------------------------------- 1: the standards step runs


def test_no_type_keeps_the_standards_that_match_the_sheet_and_says_engineer_to_confirm(
    on,
):
    result, rows = _select(_world())
    assert rows["std"]["included"] is True
    assert "equipment type: engineer to confirm" in rows["std"]["reason"]
    assert "equipment type: engineer to confirm" in result["scope_decision_not_run"]
    detail = equipment_title_block.for_submittal("sub")[0]["detail"]
    assert "matched by the sheet's own words, not by a scope check" in detail
    # still no type, stored or read: the body words did not name one
    assert classification.of_document("sub")["equipment_type"] is None


def test_the_kept_standard_is_written_as_included_on_the_run(on):
    allowed = _world()
    run_id = "run-1"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at,"
            " updated_at) VALUES (?,'sub','pending','2026-11-02','2026-11-02')",
            (run_id,),
        )
    applicability.select("sub", allowed_document_ids=allowed, review_run_id=run_id)
    row = (
        db.connect()
        .execute(
            "SELECT included, exclusion_reason FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = 'std'",
            (run_id,),
        )
        .fetchone()
    )
    assert row["included"] == 1 and row["exclusion_reason"] is None


def test_the_body_words_are_never_asked_as_a_type(on, monkeypatch):
    """No proposal: the model's scope question is not put with any term taken from the body."""
    asked = []
    monkeypatch.setattr(
        applicability,
        "_cached_scope_decision",
        lambda sid, term, *a, **k: asked.append(term) or {"decision": "UNKNOWN"},
    )
    _select(_world())
    assert asked == []


def test_switch_off_the_same_sheet_keeps_nothing_by_similar_words():
    allowed = _world()
    assert classification.of_document("sub")["equipment_type"] == "Motor"
    _result, rows = _select(allowed)
    assert rows["std"]["included"] is False
    assert "kept_without_type" not in rows["std"]


def test_a_type_the_title_block_names_keeps_nothing_by_similar_words(on):
    _add(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        _page(["ACME", "CENTRIFUGAL PUMP DATA SHEET", "Doc 1", "Rev 0", "Tag P-1"]),
    )
    _add("std", "COMPANY_STANDARD", f"Rules for the {WORDS}.", document_number="ZZ-1")
    classification.classify_equipment_type_for_submittal("sub")
    _result, rows = _select(frozenset({"sub", "std"}))
    assert "std" not in rows or rows["std"]["included"] is False


# ---------------------------------------------------- 2: a panel heading


def test_a_panel_heading_never_sets_the_title(on):
    _world()
    assert not _title()


def test_a_panel_heading_inside_the_title_block_never_sets_the_title(on):
    _add(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        _page(["ACME", "MOTOR DATA", "Doc 1", "Rev 0", "Tag X-1"]),
    )
    submittal_fill.fill("sub")
    assert not _title()


def test_a_title_block_data_sheet_line_still_sets_the_title(on):
    _add(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        _page(["ACME", "ATMOSPHERIC TANK DATA SHEET", "Doc 1", "Rev 0", "Tag T-1"]),
    )
    submittal_fill.fill("sub")
    assert _title() == "ATMOSPHERIC TANK DATA SHEET"


def test_a_data_sheet_line_below_the_title_block_never_sets_the_title(on):
    lines = ["ACME", "Doc 1", "Rev 0", "Tag X-1", "Sheet 1"]
    lines += [f"Line {i}" for i in range(5)] + ["MOTOR DATA SHEET"]
    lines += [f"Value {i}" for i in range(12)]
    _add("sub", "CONTRACTOR_SUBMITTAL", "\n".join(lines))
    submittal_fill.fill("sub")
    assert not _title()


def test_switch_off_a_panel_heading_still_sets_the_title_as_before():
    _world()
    assert _title() == "MOTOR DATA"


@pytest.mark.parametrize("switch", [True, False])
def test_a_stored_title_never_reads_as_the_equipment_with_the_switch_on(
    monkeypatch, switch
):
    """A title stored before the switch was on (an older ingest) is not read either."""
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", switch)
    found, source, _doubt = subject_scope.read_equipment(
        {"equipment_type": None, "title": "MOTOR DATA"}, [], subject_scope.vocabulary()
    )
    assert (found, source) == ((set(), None) if switch else ({"motor"}, "title"))


# ---------------------------------------------------- 3: the words


def _coverage(allowed):
    return comparison.completeness_for_run(
        "sub", allowed_document_ids=allowed, findings=[]
    )


def test_the_plain_reason_says_the_type_is_unknown_never_no_applicable_standard(on):
    coverage = _coverage(_world())
    technical = comparison._insufficient_reason(coverage)
    plain = comparison.plain_reason("Manual", technical, coverage, None, [])
    assert "No applicable standard" not in plain
    assert "equipment type is unknown" in plain and "engineer to confirm" in plain


def test_the_technical_reason_says_the_type_is_unknown(on):
    technical = comparison._insufficient_reason(_coverage(_world()))
    assert "no requirement of an applicable standard" not in technical
    assert "equipment type is unknown" in technical


def test_switch_off_the_words_are_as_before():
    coverage = _coverage(_world())
    technical = comparison._insufficient_reason(coverage)
    assert technical.startswith("no requirement of an applicable standard")
    assert "No applicable standard asks" in comparison.plain_reason(
        "Manual", technical, coverage, None, []
    )
    assert equipment_title_block.for_submittal("sub") == []
