"""#1503 remainder, behind CRS_EXPORT_QUALITY_STRICT_ENABLED (needs the #1509 switch):
what the stored runs still showed after #1509. Duplicate rows on the internal
copy (rows with no page on one clause), a comment that was only
the "not yet proven" flag going blank, spellings of a material standard the prefix
table missed, and the screen not showing the Internal sheet.

Invented rows only; no document text.
"""

from __future__ import annotations

import collections
import io

import openpyxl
import pytest

from app import crs_export, review_audit_rows, schemas
from app import crs_export_quality as q
from app.config import settings
from app.rule_trust import UNPROVEN_REASON

ON = {"review_run_id": "run-1", "export_quality": True}


def row(comment="Datasheet check: Set pressure is above the limit.", **kw):
    base = {
        "document_name": "DS-1.pdf",
        "page_section": "p.2 - Set pressure",
        "comment": comment,
        "comment_by": "AI Review",
        "standard_reference": "STD-1 4.1.2",
        "row_kind": "datasheet_check",
        "engineer_confirmed": False,
        "priority": 3,
        "reasoning": "Read: Set pressure = 12 (p.2).",
    }
    base.update(kw)
    return base


def tick(comment, **kw):
    return row(comment, row_kind="safety_tick", rule_trust="automatic", **kw)


def view(rows, copy="internal"):
    return crs_export.build_crs_view(rows, {**ON, "copy": copy})


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(settings, "crs_export_quality_strict_enabled", True)


def test_the_switch_is_off_by_default_and_off_leaves_these_rows_apart():
    assert settings.crs_export_quality_strict_enabled is False
    blank = [row("A", page_section=""), row("B", page_section="")]
    assert len(view(blank)["rows"]) == 2
    assert q.standard_kind("ANSI B16.5") == q.KIND_DESIGN
    assert not view([row("A")]).get("internal_preview")


def test_it_needs_the_export_quality_switch(strict):
    off = {"review_run_id": "run-1", "export_quality": False, "copy": "internal"}
    blank = [row("A", page_section=""), row("B", page_section="")]
    assert len(crs_export.build_crs_view(blank, off)["rows"]) == 2


def test_two_safety_ticks_on_one_key_stay_two_rows_with_their_own_refs(strict):
    # A merged tick keeps the first reference: confirming it would leave the other
    # under a confirmed row, and a guess must never look confirmed.
    for section in ("p.2 - Set pressure", ""):
        v = view(
            [
                tick("Tick A.", page_section=section),
                tick("Tick B.", page_section=section),
            ]
        )
        assert [r["comment"] for r in v["rows"]] == ["Tick A.", "Tick B."]
        assert len({r["row_ref"] for r in v["rows"]}) == 2
        assert v["rows_merged"] == 0


def test_a_tick_never_joins_a_row_that_is_not_a_tick(strict):
    # A "meets" tick inside a failing row would hide the failing row's colour.
    v = view([tick("Tick A."), row("Fails.", priority=1)])
    assert sorted(r["row_kind"] for r in v["rows"]) == [
        "datasheet_check",
        "safety_tick",
    ]


def test_an_issued_tick_and_a_carried_comment_stay_their_own_rows(strict):
    issued = [
        tick("A", crs_ref="CRS-X-001", crs_status="Open"),
        tick("B", crs_ref="CRS-X-002", crs_status="Open"),
    ]
    assert len(view(issued)["rows"]) == 2
    carried = [
        row("A", row_kind="carried_forward", page_section=""),
        row("B", row_kind="carried_forward", page_section=""),
    ]
    assert len(view(carried)["rows"]) == 2


def test_a_confirmed_row_stays_apart_from_an_unconfirmed_one(strict):
    rows = [
        row("A", page_section="", engineer_confirmed=True),
        row("B", page_section=""),
    ]
    assert len(view(rows)["rows"]) == 2


def test_rows_with_no_page_on_one_clause_are_one_row(strict):
    v = view([row("A", page_section=""), row("B", page_section="  ")])
    assert len(v["rows"]) == 1
    assert v["rows"][0]["comment"] == "A\n\nB"
    assert v["rows"][0]["page_section"] == "page not found (not identified)"


def test_rows_with_no_page_stay_apart_when_their_reason_differs(strict):
    rows = [
        row("A", page_section=""),
        row("B", page_section="", row_kind="standard_not_cited"),
    ]
    cells = {r["page_section"] for r in view(rows)["rows"]}
    assert cells == {
        "page not found (not identified)",
        "page not found (needs other document)",
    }


def test_a_row_with_no_standard_has_no_key(strict):
    rows = [
        row("A", page_section="", standard_reference=""),
        row("B", page_section="", standard_reference=""),
    ]
    assert len(view(rows)["rows"]) == 2


def test_rows_on_another_clause_or_document_stay_apart(strict):
    rows = [
        row("A", page_section=""),
        row("B", page_section="", standard_reference="STD-1 4.1.3"),
        row("C", page_section="", document_name="DS-2.pdf"),
    ]
    assert len(view(rows)["rows"]) == 3


def test_a_merge_past_the_limit_loses_no_word(strict):
    first, second = "First row sentence. " * 12, "Second row sentence. " * 12
    entry = view([row(first.strip()), row(second.strip())])["rows"][0]
    assert len(entry["comment"]) <= q.COMMENT_LIMIT
    whole = entry["comment"] + entry["ai_review_comment"]
    assert whole.count("First row sentence.") == 12
    assert whole.count("Second row sentence.") == 12


FLAG_ONLY = f" ({UNPROVEN_REASON})"


def test_a_comment_that_was_only_the_flag_is_no_comment(strict):
    v = view([row(FLAG_ONLY), row("Has words.", standard_reference="STD-2 1")])
    assert [r["comment"] for r in v["rows"]] == ["Has words."]
    assert v["rows_dropped_no_comment"] == 1
    assert any(n["note"] == "Rows dropped: no comment" for n in v["review_notes"])


def test_a_confirmed_flag_only_row_prints_the_sentence_not_a_blank(strict):
    v = view([row(FLAG_ONLY, engineer_confirmed=True)])
    assert v["rows"][0]["comment"] == crs_export.EMPTY_COMMENT_TEXT
    assert v["rows"][0]["comment_missing"] is True


def test_the_client_copy_counts_a_flag_only_row_where_the_screen_says_it(strict):
    rows = [
        row(FLAG_ONLY, engineer_confirmed=True),
        row("Has words.", engineer_confirmed=True, standard_reference="STD-2 1"),
    ]
    meta = {**ON, "copy": "issue", "title": "t"}
    v = crs_export.build_crs_view(rows, meta)
    assert len(v["rows"]) == 1
    assert "Has words." in v["rows"][0]["comment"]
    # What the route serves, and the count `CrsPreviewSheet` prints.
    assert schemas.CrsPreview(**v).rows_withheld_no_text == 1
    # Counted once: the audit report still adds up.
    assert v["rows_dropped_no_comment"] == 0
    assert review_audit_rows.crs_reconciliation(rows, meta)["adds_up"] is True


def test_a_flag_only_row_adds_to_the_rows_already_withheld(strict):
    rows = [
        row(FLAG_ONLY, engineer_confirmed=True),
        row("", engineer_confirmed=True, standard_reference="STD-2 1"),
    ]
    assert view(rows, copy="issue")["rows_withheld_no_text"] == 2


def test_a_comment_with_words_and_the_flag_keeps_its_words(strict):
    v = view([row("Has words." + FLAG_ONLY)])
    assert v["rows"][0]["comment"] == "Has words."
    assert v["rows_dropped_no_comment"] == 0


@pytest.mark.parametrize(
    "reference",
    [
        "ASME-B16-47",
        "ASME-B16.5",
        "ANSI B16.5",
        "ASME/ANSI B16.34",
        "ANSI/ASME B36.10",
        "ASME-SA-193",
        "ANSI/ASME SA-105",
        "A193 Gr B7",
        "A 216 Grade WCC",
        "B633, Gr. 5",
    ],
)
def test_more_spellings_of_a_material_or_product_spec(strict, reference):
    assert q.standard_kind(reference) == q.KIND_MATERIAL


@pytest.mark.parametrize(
    "reference",
    [
        "ASME B31.3",
        "ASME-B31-3",
        "ANSI B31.3",
        "B31.3",
        "API 521",
        "IEC 61511",
        # a letter and a number alone are not a material context
        "A193",
        "B633",
        "A100 Rev 2",
        "B2000 Greenfield design basis",
        "AB-123",
    ],
)
def test_a_design_standard_stays_a_design_standard(strict, reference):
    assert q.standard_kind(reference) == q.KIND_DESIGN


def test_the_screen_gets_the_internal_sheet_the_file_has(strict):
    standards = [
        {"standard": "STD-9.pdf", "status": crs_export.STATUS_CONSIDERED, "reason": "r"}
    ]
    meta = {**ON, "copy": "internal", "applicable_standards": standards}
    v = crs_export.build_crs_view([row("A", rule_trust="automatic")], meta)
    inner = v["internal_preview"]
    assert inner["rows"][0]["reasoning"] == "Read: Set pressure = 12 (p.2)."
    assert inner["rows"][0]["rule_trust"] == "automatic"
    assert inner["considered"][0]["standard"] == "STD-9.pdf"
    fields = schemas.CrsPreview.model_fields
    assert "internal_preview" in fields


def test_the_client_screen_has_no_internal_sheet(strict):
    assert not view([row("A", engineer_confirmed=True)], copy="issue").get(
        "internal_preview"
    )


def test_a_synthetic_sheet_has_no_duplicate_and_no_blank_comment(strict):
    rows = [
        tick("Tick A.", standard_reference="STD-5 1"),
        row("No page A.", page_section=""),
        row("No page B.", page_section=""),
        row(FLAG_ONLY, standard_reference="STD-3 1"),
        row("Words.", standard_reference="STD-4 1"),
    ]
    data = crs_export.build_crs(rows, {**ON, "copy": "internal"})
    ws = openpyxl.load_workbook(io.BytesIO(data))["CRS"]
    head = [c.value for c in ws[crs_export.COLUMN_HEADER_ROW]]
    page, comment, ref = (
        head.index("Page No./Section"),
        head.index("COMPANY Comments"),
        head.index("Standard Reference"),
    )
    cells = [
        [c.value for c in cells]
        for cells in ws.iter_rows(min_row=crs_export.FIRST_DATA_ROW)
        if cells[1].value
    ]
    keys = collections.Counter((c[1], c[page], c[ref]) for c in cells)
    assert max(keys.values()) == 1
    assert all(str(c[comment] or "").strip() for c in cells)
