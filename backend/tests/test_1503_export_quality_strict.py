"""#1503 remainder, behind CRS_EXPORT_QUALITY_STRICT_ENABLED (needs the #1509 switch):
what the stored runs still showed after #1509. Duplicate rows on the internal
copy (safety ticks, and rows with no page on one clause), a comment that was only
the "not yet proven" flag going blank, spellings of a material standard the prefix
table missed, and the screen not showing the Internal sheet.

Invented rows only; no document text.
"""

from __future__ import annotations

import collections
import io

import openpyxl
import pytest

from app import crs_export, schemas
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
    assert len(view([tick("A"), tick("B")])["rows"]) == 2
    blank = [row("A", page_section=""), row("B", page_section="")]
    assert len(view(blank)["rows"]) == 2
    assert q.standard_kind("ANSI B16.5") == q.KIND_DESIGN
    assert not view([row("A")]).get("internal_preview")


def test_it_needs_the_export_quality_switch(strict):
    off = {"review_run_id": "run-1", "export_quality": False, "copy": "internal"}
    assert len(crs_export.build_crs_view([tick("A"), tick("B")], off)["rows"]) == 2


def test_two_safety_ticks_on_one_key_are_one_row_with_both_sentences(strict):
    v = view([tick("Tick A."), tick("Tick B.")])
    assert len(v["rows"]) == 1
    assert v["rows"][0]["comment"] == "Tick A.\n\nTick B."
    assert v["rows"][0]["row_kind"] == "safety_tick"
    assert v["rows_merged"] == 1


def test_the_review_note_says_a_merged_tick_is_still_ticked_one_by_one(strict):
    detail = next(
        n["detail"]
        for n in view([tick("Tick A."), tick("Tick B.")])["review_notes"]
        if n["note"] == "Rows merged into an earlier row"
    )
    assert "ticked one by one" in detail
    plain = next(
        n["detail"]
        for n in view([row("A"), row("B")])["review_notes"]
        if n["note"] == "Rows merged into an earlier row"
    )
    assert "ticked" not in plain


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


def test_a_ticked_row_stays_apart_from_one_not_yet_ticked(strict):
    rows = [tick("A", engineer_confirmed=True), tick("B")]
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
    first, second = "First tick sentence. " * 12, "Second tick sentence. " * 12
    entry = view([tick(first.strip()), tick(second.strip())])["rows"][0]
    assert len(entry["comment"]) <= q.COMMENT_LIMIT
    whole = entry["comment"] + entry["ai_review_comment"]
    assert whole.count("First tick sentence.") == 12
    assert whole.count("Second tick sentence.") == 12


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


def test_the_client_copy_leaves_a_flag_only_row_out(strict):
    rows = [
        row(FLAG_ONLY, engineer_confirmed=True),
        row("Has words.", engineer_confirmed=True, standard_reference="STD-2 1"),
    ]
    v = view(rows, copy="issue")
    assert len(v["rows"]) == 1
    assert "Has words." in v["rows"][0]["comment"]
    assert v["rows_dropped_no_comment"] == 1


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
        "A193",
        "A 216",
        "B633",
    ],
)
def test_more_spellings_of_a_material_or_product_spec(strict, reference):
    assert q.standard_kind(reference) == q.KIND_MATERIAL


@pytest.mark.parametrize(
    "reference",
    ["ASME B31.3", "ASME-B31-3", "ANSI B31.3", "B31.3", "API 521", "IEC 61511"],
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
        tick("Tick A."),
        tick("Tick B."),
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
    # a tick and a draft on one clause and page are two rows on purpose
    assert max(keys.values()) == 1
    assert all(str(c[comment] or "").strip() for c in cells)
