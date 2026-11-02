"""#1503 CRS export quality: seven rules, each tested on a small invented sheet
with the switch ON, and the switch OFF leaves the sheet as it was.

Invented rows only; no document text.
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl

from app import crs_export
from app import crs_export_quality as q
from app.config import settings

ON = {"review_run_id": "run-1", "export_quality": True}
OFF = {"review_run_id": "run-1", "export_quality": False}


def row(comment="Datasheet check: Set pressure is above the limit.", **kw):
    base = {
        "document_name": "DS-1.pdf",
        "page_section": "p.2 - Set pressure",
        "comment": comment,
        "comment_by": "AI Review",
        "standard_reference": "SAES-J-600 4.1.2 (p.5)",
        "row_kind": "datasheet_check",
        "engineer_confirmed": False,
        "priority": 3,
        "reasoning": "Read: Set pressure = 12 (p.2).",
        "rule_trust": "automatic rule not yet proven",
    }
    base.update(kw)
    return base


def view(rows, meta=ON, copy="internal"):
    return crs_export.build_crs_view(rows, {**meta, "copy": copy})


def sheet(rows, meta=ON, copy="internal"):
    data = crs_export.build_crs(rows, {**meta, "copy": copy})
    return openpyxl.load_workbook(io.BytesIO(data))


# 1 -----------------------------------------------------------------------


def test_a_later_draft_on_the_same_section_and_clause_joins_the_first_row():
    rows = [
        row("First finding."),
        row("Second finding.", priority=2),
        row("Other", page_section="p.3 - X"),
    ]
    v = view(rows)
    assert len(v["rows"]) == 2
    assert (
        "First finding." in v["rows"][0]["comment"]
        and "Second finding." in v["rows"][0]["comment"]
    )
    assert v["rows"][0]["priority_label"] == "Missing value"  # the stronger rank wins
    assert v["rows_merged"] == 1
    off = view(rows, OFF)
    assert len(off["rows"]) == 3


def test_a_numbered_issued_a_tick_and_a_carried_comment_are_never_merged():
    issued = [
        row("A", crs_ref="CRS-X-001", crs_status="Open"),
        row("B", crs_ref="CRS-X-002", crs_status="Open"),
    ]
    assert len(view(issued)["rows"]) == 2
    ticks = [row("A", row_kind="safety_tick"), row("B", row_kind="safety_tick")]
    assert len(view(ticks)["rows"]) == 2
    carried = [
        row("A", row_kind="carried_forward"),
        row("B", row_kind="carried_forward"),
    ]
    assert len(view(carried)["rows"]) == 2


def test_a_draft_and_a_confirmed_row_are_not_merged_into_one_comment():
    rows = [row("A", engineer_confirmed=True), row("B", engineer_confirmed=False)]
    assert len(view(rows)["rows"]) == 2


# 2 -----------------------------------------------------------------------


def test_a_row_with_no_comment_is_dropped_and_counted_in_the_review_notes():
    rows = [row("A comment."), row("", page_section="p.4 - Y")]
    v = view(rows)
    assert len(v["rows"]) == 1
    assert {
        "note": "Rows dropped: no comment",
        "standard": "",
        "count": 1,
        "detail": "rows with no comment text are not exported",
    } in v["review_notes"]
    assert (
        len(view(rows, OFF)["rows"]) == 2
    )  # off: printed with the placeholder as before


# 3 -----------------------------------------------------------------------


def test_every_row_names_a_page_or_says_page_not_found_with_a_reason():
    rows = [
        row(
            "a",
            page_section="Not read from the datasheet (5 pages) - Cdtp",
            standard_reference="A 1",
        ),
        row(
            "b",
            page_section="",
            row_kind="standard_not_cited",
            standard_reference="B 1",
        ),
        row("c", page_section="Rated capacity", standard_reference="C 1"),
        row("d", page_section="p.1 - Fluid", standard_reference="D 1"),
    ]
    pages = [r["page_section"] for r in view(rows)["rows"]]
    assert pages[0].startswith("page not found (not read)")
    assert pages[1] == "page not found (needs other document)"
    assert pages[2].startswith("page not found (not identified)")
    assert pages[3] == "p.1 - Fluid"
    assert [r["page_section"] for r in view(rows, OFF)["rows"]][1] == ""


# 4 -----------------------------------------------------------------------


def test_a_long_comment_is_cut_at_350_and_the_rest_goes_to_the_ai_column():
    text = ". ".join(f"Sentence number {i} says something" for i in range(30)) + "."
    v = view([row(text)])
    entry = v["rows"][0]
    assert len(entry["comment"]) <= 350
    assert text.startswith(entry["comment"])
    rest = entry["ai_review_comment"].split("Continued from the comment: ", 1)[1]
    assert (
        entry["comment"] + " " + rest
    ).split() == text.split()  # nothing lost, nothing added
    assert len(view([row(text)], OFF)["rows"][0]["comment"]) > 350


def test_the_client_copy_has_no_internal_sheet_and_no_internal_words():
    rows = [
        row(
            "Finding. (the rule is not yet proven: it is neither engineer-approved nor an AI-compiled "
            "rule whose family is proven on an answer key and passes code's second check; an "
            "engineer decides)",
            engineer_confirmed=True,
        )
    ]
    client = sheet(rows, copy="issue")
    assert "Internal" not in client.sheetnames
    cells = " ".join(
        str(c.value or "")
        for ws in client.worksheets
        for r in ws.iter_rows()
        for c in r
    ).lower()
    for phrase in ("not yet proven", "reasoning (internal)", "rule trust (internal)"):
        assert phrase not in cells
    internal = sheet(rows)
    assert "Internal" in internal.sheetnames
    inner = " ".join(
        str(c.value or "") for r in internal["Internal"].iter_rows() for c in r
    )
    assert "Read: Set pressure" in inner and "not yet proven" in inner
    main = " ".join(
        str(c.value or "") for r in internal["CRS"].iter_rows() for c in r
    ).lower()
    assert "not yet proven" not in main and "reasoning (internal)" not in main


def test_the_client_copy_gets_the_ai_column_only_when_a_comment_overflowed():
    short = view([row("Short.", engineer_confirmed=True)], copy="issue")
    assert crs_export.AI_COLUMN not in short["columns"]
    long = view([row("word " * 120, engineer_confirmed=True)], copy="issue")
    assert crs_export.AI_COLUMN in long["columns"]
    assert all(len(r["comment"]) <= 350 for r in long["rows"])


# 5 + 6 -------------------------------------------------------------------


STANDARDS = [
    {
        "standard": "SAES-A-1",
        "status": crs_export.STATUS_APPLIED,
        "method": "m",
        "reason": "r",
        "evidence": "",
    },
    {
        "standard": "SAES-B-1",
        "status": crs_export.STATUS_CONSIDERED,
        "method": "m",
        "reason": "r",
        "evidence": "",
    },
    {
        "standard": "IEC 61511",
        "status": q.not_in_library_status("IEC 61511"),
        "method": "",
        "reason": "",
        "evidence": "",
    },
]


def test_the_standards_sheet_lists_applied_and_not_in_library_only():
    meta = {**ON, "applicable_standards": STANDARDS}
    v = view([row()], meta)
    assert [s["standard"] for s in v["applicable_standards"]] == [
        "SAES-A-1",
        "IEC 61511",
    ]
    wb = sheet([row()], meta)
    shown = [r[0].value for r in wb["Applicable standards"].iter_rows(min_row=2)]
    assert shown == ["SAES-A-1", "IEC 61511"]
    inner = [r[0].value for r in wb["Internal"].iter_rows() if r[0].value]
    assert "SAES-B-1" in inner
    assert any(
        n["note"] == "Standards considered, not applied" and n["count"] == 1
        for n in v["review_notes"]
    )
    assert (
        len(
            view([row()], {**OFF, "applicable_standards": STANDARDS})[
                "applicable_standards"
            ]
        )
        == 3
    )
    client = sheet([row(engineer_confirmed=True)], meta, copy="issue")
    assert "Internal" not in client.sheetnames
    assert [
        r[0].value for r in client["Applicable standards"].iter_rows(min_row=2)
    ] == ["SAES-A-1", "IEC 61511"]


def test_not_in_library_is_split_by_a_prefix_table_not_by_document():
    assert q.standard_kind("IEC 61511") == q.KIND_DESIGN
    assert q.standard_kind("API 521") == q.KIND_DESIGN
    assert q.standard_kind("ISO 10418") == q.KIND_DESIGN
    assert q.standard_kind("ASME B31.3") == q.KIND_DESIGN
    assert q.standard_kind("ASTM A193") == q.KIND_MATERIAL
    assert q.standard_kind("ASTM F 1554") == q.KIND_MATERIAL
    assert q.standard_kind("ASME B16.20") == q.KIND_MATERIAL
    assert q.standard_kind("ASME SA-516") == q.KIND_MATERIAL
    assert q.standard_kind("32-SAMSS-004") == q.KIND_PURCHASING
    assert (
        q.standard_kind("never seen XYZ 9") == q.KIND_DESIGN
    )  # unknown keeps "upload required"
    assert "upload required" in q.not_in_library_status("IEC 61511")
    assert "upload" not in q.not_in_library_status("ASTM A193")
    assert "upload" not in q.not_in_library_status("01-SAMSS-016")


# 7 -----------------------------------------------------------------------


def test_priority_is_only_ever_one_of_the_fixed_words():
    ranks = {
        1: "Fail",
        2: "Missing value",
        3: "Engineer to check",
        4: "Engineer to check",
        5: "Engineer to check",
        None: "Engineer to check",
    }
    for rank, word in ranks.items():
        assert q.priority_label(rank) == word
    rows = [
        row(f"c{i}", page_section=f"p.{i} - f", priority=p)
        for i, p in enumerate([1, 2, 3, 4, None])
    ]
    labels = [r["priority_label"] for r in view(rows)["rows"]]
    assert set(labels) <= set(q.PRIORITY_WORDS)
    off = [r["priority_label"] for r in view(rows, OFF)["rows"]]
    assert "" in off  # the old sheet printed a blank for a row with no rank


def test_switch_off_leaves_the_sheet_as_it_was():
    rows = [row("A"), row("B")]
    v = view(rows, OFF)
    assert len(v["rows"]) == 2 and v.get("export_quality", False) is False
    assert v["columns"][-3:] == [
        crs_export.AI_COLUMN,
        crs_export.REASONING_COLUMN,
        crs_export.TRUST_COLUMN,
    ]
    assert "Internal" not in sheet(rows, OFF).sheetnames


def test_the_setting_is_off_by_default():
    from app.config import Settings

    assert Settings.model_fields["crs_export_quality_enabled"].default is False


def test_the_ai_column_name_has_one_meaning():
    assert q.AI_COLUMN == crs_export.AI_COLUMN


def test_an_equipment_tag_is_not_a_page():
    assert not q.has_page("P101 - Fluid")
    assert not q.has_page("Pump P2 outlet")
    assert q.has_page("p.2 - Fluid") and q.has_page("pp. 3-4") and q.has_page("page 5")
    assert q.page_cell("P101 - Fluid").startswith("page not found (not identified)")


def test_a_cut_never_parts_a_number_from_its_unit_or_a_clause_word_from_its_id():
    text = (
        "x" * 20
        + " "
        + "word " * 63
        + "10 mm and clause 4.1.2 applies here for the rest of the text."
    )
    for limit in range(300, 340):
        head, rest = q.split_comment(text, limit)
        assert head + " " + rest == text or (head + rest).split() == text.split()
        assert not head.endswith("10") and not head.endswith("clause")
        assert not rest.startswith(("mm", "4.1.2"))


def test_the_requested_action_stays_in_the_client_comment():
    middle = " ".join(
        f"Detail sentence number {i} is long enough to fill space." for i in range(12)
    )
    text = f"Set pressure is above the limit. {middle} Contractor to correct the datasheet."
    head, rest = q.shorten(text, 350)
    assert len(head) <= 350 and head.endswith("Contractor to correct the datasheet.")
    assert head.startswith("Set pressure is above the limit.")
    assert sorted((head + " " + rest).split()) == sorted(text.split())
    v = view([row(text, engineer_confirmed=True)], copy="issue")
    assert v["rows"][0]["comment"].endswith("Contractor to correct the datasheet.")


def test_a_fail_merged_into_an_engineers_row_shows_fail():
    rows = [
        row("Engineer note.", row_kind="engineer_comment", priority=4),
        row("Value out of limit.", priority=1),
    ]
    v = view(rows)
    assert len(v["rows"]) == 1 and v["rows"][0]["priority_label"] == "Fail"
    assert v["rows"][0]["row_kind"] == "engineer_comment"


def test_switch_off_workbook_is_the_workbook_main_made():
    """Every column width, merge, row height, alignment, font, fill and cell
    value of both copies on a small fixture, as origin/main's `crs_export`
    wrote them (`crs_off_layout.json`, generated once from main's code)."""
    import json
    from pathlib import Path

    from tests.crs_off_layout import build_all

    expected = json.loads((Path(__file__).parent / "crs_off_layout.json").read_text())
    got = json.loads(json.dumps(build_all({"export_quality": False})))
    for copy in ("internal", "issue"):
        assert got[copy]["sheets"] == expected[copy]["sheets"]
        for sheet in expected[copy]["sheets"]:
            for part in ("widths", "merged", "heights", "max", "cells"):
                assert got[copy][sheet][part] == expected[copy][sheet][part], (
                    copy,
                    sheet,
                    part,
                )


# #1591 --------------------------------------------------------------------


_NOT_READ = (
    "Not read from the datasheet (5 pages) - Invented size (T-1, T-2 and 1 more)"
)


def _cells(monkeypatch, rows, switch=True):
    monkeypatch.setattr(settings, "crs_page_cell_field_enabled", switch)
    return [r["page_section"] for r in view(rows)["rows"]]


def test_a_row_with_no_page_says_its_section_or_field_never_not_found(monkeypatch):
    rows = [
        row("a", page_section=_NOT_READ, standard_reference="A 1"),
        row(
            "b",
            page_section="",
            row_kind="standard_not_cited",
            standard_reference="STD 9",
        ),
        row(
            "c",
            page_section="Not read from the datasheet",
            standard_reference="C 1",
        ),
        row("d", page_section="Invented section", standard_reference="D 1"),
        row("e", page_section="", standard_reference="E 1"),
        row(
            "f",
            page_section="",
            row_kind="standard_not_applicable",
            standard_reference="F 1",
        ),
        row(
            "g",
            page_section="Invented part",
            row_kind="requires_other_document",
            standard_reference="G 1",
        ),
        row("h", page_section="", standard_reference=""),
    ]
    assert _cells(monkeypatch, rows) == [
        "Field: Invented size (T-1, T-2 and 1 more) - no value read from the datasheet"
        " (5 pages), so no page",
        "Whole submittal: STD 9 is not cited, so no page",
        "no value read from the datasheet, so no page",
        "Section: Invented section: no verified quote, so no page",
        "About E 1: no verified quote, so no page",
        "Whole submittal: about F 1: no verified quote, so no page",
        "Section: Invented part: another document is needed, so no page",
        "No section or field recorded: no verified quote, so no page",
    ]


def test_the_not_read_lead_is_what_the_page_words_write():
    """`field_first` reads the cell `where` writes; a change of words must fail here."""
    from app import crs_page_words

    cell = crs_page_words.where([], "", "Invented size", ["T-1"], set(), False)
    assert cell.startswith(crs_page_words.NOT_READ_LEAD)
    assert crs_page_words.field_first(cell).startswith("Field: Invented size (T-1) - ")
    assert crs_page_words.field_first("p.1 - Invented size") is None


def test_a_cell_with_no_page_never_gets_a_page_number(monkeypatch):
    """A page comes only from a verified quote: words that merely mention a number, or a
    comment that says where wording was seen, never put a page in the cell."""
    rows = [
        row(
            page_section=_NOT_READ,
            comment="Invented size: wording for it appears on pages 1, 2, 3.",
            standard_reference="A 1",
        ),
        row(
            page_section="",
            row_kind="standard_not_cited",
            comment="Not cited; see page 7 of the standard.",
            standard_reference="STD 9",
        ),
    ]
    for cell in _cells(monkeypatch, rows):
        assert not q.has_page(cell)
        assert "1, 2, 3" not in cell and "7" not in cell


def test_a_row_with_a_page_keeps_it_with_the_switch_on(monkeypatch):
    rows = [
        row("a", page_section="p.2 - Invented size", standard_reference="A 1"),
        row(
            "b",
            page_section="Invented size: A value was read on pages 1, 2, not tied to this"
            " row; engineer to confirm",
            standard_reference="B 1",
        ),
    ]
    cells = _cells(monkeypatch, rows)
    assert cells[0] == "p.2 - Invented size"
    assert cells[1].startswith("Invented size: A value was read on pages 1, 2")
    assert not any(q.NO_PAGE in c for c in cells)


def test_switch_off_the_page_cell_is_as_before(monkeypatch):
    rows = [
        row("a", page_section=_NOT_READ, standard_reference="A 1"),
        row(
            "b",
            page_section="",
            row_kind="standard_not_cited",
            standard_reference="B 1",
        ),
    ]
    assert _cells(monkeypatch, rows, switch=False) == [
        f"page not found (not read) - {_NOT_READ}",
        "page not found (needs other document)",
    ]


def test_the_page_cell_setting_is_off_by_default():
    from app.config import Settings

    assert Settings.model_fields["crs_page_cell_field_enabled"].default is False


def test_the_check_script_accepts_the_field_cell():
    """`scripts/crs_export_quality_check.py` counts a cell with neither form as no page."""
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "crs_export_quality_check.py"
    ).read_text(encoding="utf-8")
    assert f'"{q.NO_PAGE}" not in p' in source
