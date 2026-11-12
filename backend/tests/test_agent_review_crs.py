"""The CRS files of the AI reviewer in the app's own layout (order 13): internal and contractor. Invented data only; no model, no network."""

from __future__ import annotations

import io
import itertools

import openpyxl
import pytest

from app import agent_review_crs as C
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_layout
from app.config import settings

META = {
    "paper": "Paper A",
    "run_id": "run-1",
    "date": "2026-11-11",
    "lead_models": ["lead-m"],
    "second_models": ["second-m"],
    "usd": 0.5,
    "header": {
        "project": "Project Q",
        "document_number": "DOC-77",
        "title": "Title Z",
        "revision": "2",
        "date": "2026-01-05",
        "discipline": "instrument",
    },
}
SK = {"S-1"}
OK = {"source": "rule", "rule_label": {"tier": "AI approved"}}
NO = {
    "source": "rule",
    "rule_tier": V.RULE_NOT_APPROVED,
    "rule_unapproved_why": "values",
}


def mk(iid, verdict, ai=None, item=OK, paper_kind=None, **kw):
    base = {
        "item_id": iid,
        "source": item["source"],
        "standard": "STD-1",
        "clause": "4.1",
        "verdict": verdict,
        "decided_by": "decided by code",
        "ai_verdict": ai,
        "paper_page": 2,
        "paper_quote": "Nameplate: steel",
        "clause_quote": "Nameplates shall be steel and fixed",
        "quotes_checked": {"paper": True, "clause": True},
        "reasoning": "It is steel.",
        "model": "lead-m",
        "field": "Field " + iid.replace("-", ""),
        "field_roles": ["nameplate_material"],
    }
    if (
        verdict == "Pass"
    ):  # a PROVEN Pass is one the code compared (owner, 12 Nov 2026): the number path's result
        base["compare"] = {"decided": True, "verdict": "meets"}
    base.update(kw)
    return W.final_cap(base, item, skill_ids=SK, paper_kind=paper_kind)


def rows_of(path, sheet="CRS"):
    """The table rows of a sheet as dicts keyed by the column headings."""
    ws = openpyxl.load_workbook(path)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    top = next(i for i, r in enumerate(rows) if r[0] == "Item No")
    return [
        dict(zip(rows[top], r, strict=False))
        for r in rows[top + 1 :]
        if r[0] is not None
    ]


def fields(path, sheet="CRS"):
    return [r["Page No./Section"].split(" - ")[-1] for r in rows_of(path, sheet)]


def all_text(path):
    wb = openpyxl.load_workbook(path)
    return "\n".join(
        str(c)
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for c in row
        if c is not None
    )


def rows_of_notes(path):
    ws = openpyxl.load_workbook(path)["Notes"]
    rows = list(ws.iter_rows(values_only=True))
    return [dict(zip(rows[0], r, strict=False)) for r in rows[1:]]


def all_text_of(path, sheet):
    ws = openpyxl.load_workbook(path)[sheet]
    return "\n".join(
        str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None
    )


LINES = [
    mk("R-1", "Fail", "Fail"),  # proven Fail
    mk("R-2", "Pass", "Pass"),  # proven Pass
    mk("R-3", "Query", "Fail", why="no second opinion"),  # AI opinion, not met
    mk("R-4", "Query", "Pass", why="no second opinion"),  # AI opinion, met (held)
    mk(
        "R-5", "Fail", "Fail", item=NO
    ),  # proven by the gate but the rule is not approved: capped
    mk("R-6", "Fail", "Fail", rule_kind="advice"),  # a "should" rule
    mk(
        "S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"}
    ),  # a checklist Fail
    mk("R-7", "Query", None, reason_code="not_applicable"),
    mk("R-8", "Query", None, why="the AI did not give pass or fail"),  # a Query
]


def test_the_internal_copy_has_four_sheets_and_the_ten_columns_in_order(tmp_path):
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == [
        "CRS",
        "Not reviewed or not applicable",
        "Evidence",
        "Notes",
    ]
    assert list(rows_of(path)[0]) == [
        "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By", "Contractor's Response",
        "Final Resolution", "Standard Reference", "Priority", "Status",
    ]  # fmt: skip
    assert {r["Status"] for r in rows_of(path)} <= {
        "Pass",
        "Fail",
        "AI opinion",
        "Query",
    }


def test_the_item_rows_run_fail_ai_not_met_query_ai_met_pass(tmp_path):
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    rows = rows_of(path)
    # Fail (R-1, S-1, then the 'should' Fail R-6), AI opinion not met (R-3), Query (R-8), AI opinion met (R-4), Pass (R-2)
    assert [r["Status"] for r in rows] == [
        "Fail",
        "Fail",
        "Fail",
        "AI opinion",
        "Query",
        "AI opinion",
        "Pass",
    ]
    assert fields(path) == [
        "Field R1",
        "Field S1",
        "Field R6",
        "Field R3",
        "Field R8",
        "Field R4",
        "Field R2",
    ]
    assert [r["Item No"] for r in rows] == list(range(1, 8))
    assert "the requirement is not met" in rows[3]["COMPANY Comments"]
    assert "the requirement is met" in rows[5]["COMPANY Comments"]


def test_lines_that_are_not_item_rows_are_on_their_own_sheet_numbered_on_from_the_crs_rows(
    tmp_path,
):
    meta = {
        **META,
        "rule_labels": {
            "missing_rule_books": [{"rule_book": "Book X", "why": "cited by the paper"}]
        },
    }
    cut = mk("R-9", "Query", None, error="stop_max_tokens", reasoning="")
    path = C.write_internal([*LINES, cut], tmp_path / "i.xlsx", meta)
    other = rows_of(path, "Not reviewed or not applicable")
    assert [r["What it is"] for r in other] == [
        "Rule not yet approved", "Does not apply", "Not reviewed", "Not checked: rule book not held",
    ]  # fmt: skip
    assert [r["Item No"] for r in other] == [8, 9, 10, 11]  # the CRS sheet holds 1 to 7
    assert "Book X" in all_text(path)
    main = fields(path)
    assert not {"Field R7", "Field R5", "Field R9"} & set(
        main
    )  # not applicable, not approved, not reviewed: not item rows


def test_the_contractor_copy_holds_proven_fail_lines_only_and_nothing_else(tmp_path):
    path = C.write_contractor(LINES, tmp_path / "c.xlsx", META)
    assert openpyxl.load_workbook(path).sheetnames == [
        "CRS"
    ]  # no Evidence, no Notes, no sheet of other lines
    assert fields(path) == [
        "Field R1",
        "Field S1",
    ]  # R-1 and the checklist Fail: no Pass, no opinion, no 'should', no Query
    assert (
        "Status" not in rows_of(path)[0]
    )  # order 13: the nine company columns only; the Status column is the internal copy's
    assert list(rows_of(path)[0]) == [
        "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By", "Contractor's Response",
        "Final Resolution", "Standard Reference", "Priority",
    ]  # fmt: skip
    text = all_text(path)
    for word in (
        "AI opinion", "AI reviewer's view", "Recommendation", "lead-m", "second-m", "It is steel", "run-1", "Query",
        "recommends", "Evidence", "Notes",
    ):  # fmt: skip
        assert word not in text
    assert all(r["Comment By"] is None for r in rows_of(path))


def test_the_contractor_copy_numbers_match_the_internal_copy(tmp_path):
    internal = rows_of(C.write_internal(LINES, tmp_path / "i.xlsx", META))
    contractor = rows_of(C.write_contractor(LINES, tmp_path / "c.xlsx", META))
    by_no = {r["Item No"]: r["COMPANY Comments"] for r in internal}
    assert contractor and all(
        by_no[r["Item No"]] == r["COMPANY Comments"] for r in contractor
    )


def test_the_contractor_copy_never_takes_an_ai_opinion_or_unapproved_line_even_if_its_verdict_says_fail(
    tmp_path,
):
    """Defence beside the cap: a line forced to look like a Fail but filed as an opinion is still left out."""
    sneaky = {**mk("R-1", "Fail", "Fail"), "verdict_class": W.CLASS_OPINION}
    unapproved = {**mk("R-1", "Fail", "Fail"), "rule_tier": V.RULE_NOT_APPROVED}
    advice = {**mk("R-1", "Fail", "Fail"), "recommendation": True}
    for bad in (sneaky, unapproved, advice):
        path = C.write_contractor([bad], tmp_path / "c.xlsx", META)
        assert rows_of(path) == []


def test_the_comment_only_copy_excludes_unapproved_lines_and_pass_lines(tmp_path):
    path = C.write_comment_only(LINES, tmp_path / "o.xlsx", META)
    ids = {c for c in all_text(path).split() if c.startswith(("R-", "S-"))}
    assert not {"R-5", "R-2", "R-4", "R-7"} & ids
    assert {"R-1", "R-3", "R-6", "S-1"} <= ids


def test_a_pass_of_an_unapproved_rule_is_never_a_pass_row(tmp_path):
    """R7: a stored Pass line whose item is not approved NOW went through final_cap and cannot be a Pass row."""
    stored = {
        "item_id": "R-9",
        "source": "rule",
        "verdict": "Pass",
        "decided_by": "decided by code",
        "ai_verdict": "Pass",
    }
    capped = W.final_cap_all([stored], {"R-9": NO}, skill_ids=SK)
    path = C.write_internal(capped, tmp_path / "i.xlsx", META)
    assert [r for r in rows_of(path) if r["Status"] == "Pass"] == []
    assert rows_of(C.write_contractor(capped, tmp_path / "c.xlsx", META)) == []


@pytest.mark.parametrize(
    "writer", ["write_internal", "write_contractor", "write_comment_only"]
)
@pytest.mark.parametrize("tier", [None, "not AI approved", "nobody"])
def test_every_writer_refuses_a_pass_or_fail_without_an_approved_tier(
    writer, tier, tmp_path
):
    bad = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Fail",
        "decided_by": "decided by code",
        "tier": tier,
    }
    with pytest.raises(C.UnprovenLineRefused):
        getattr(C, writer)([bad], tmp_path / "x.xlsx", META)
    assert not (tmp_path / "x.xlsx").exists()  # nothing written
    raw = {k: v for k, v in bad.items() if k != "tier"}  # never went through final_cap
    with pytest.raises(C.UnprovenLineRefused):
        getattr(C, writer)([{**raw, "verdict": "Pass"}], tmp_path / "x.xlsx", META)


@pytest.mark.parametrize("tier", ["owner", "engineer", "AI approved"])
def test_the_approved_tiers_are_written(tier, tmp_path):
    ok = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Fail",
        "decided_by": "decided by code",
        "tier": tier,
    }
    assert C.write_internal([ok], tmp_path / "x.xlsx", META).exists()


def test_a_should_rule_says_recommends_and_is_kept_out_of_the_contractor_copy(tmp_path):
    line = mk("R-6", "Fail", "Fail", rule_kind="advice")
    status, order = WB.status_of(line)
    assert "recommends" in WB.layout_comment(line, status, order)
    assert rows_of(C.write_contractor([line], tmp_path / "c.xlsx", META)) == []


def test_an_ai_opinion_is_the_ai_reviewers_view_never_pass_or_fail():
    line = mk("R-3", "Query", "Fail", why="no second opinion")
    assert WB.status_of(line) == ("AI opinion", words.ORDER_AI_NOT_MET)
    comment = WB.layout_comment(line, *WB.status_of(line))
    assert "The AI reviewer's view, not proven: the requirement is not met." in comment
    assert (
        "no second AI reader confirmed it" in comment
    )  # the stored reason, in plain words
    assert "no second opinion" not in comment  # never the stored words
    held = mk("R-4", "Query", "Pass", why="no second opinion")
    assert WB.status_of(held) == ("AI opinion", words.ORDER_AI_MET)


def test_a_query_is_worded_as_a_crs_comment_that_starts_contractor_to_confirm():
    line = mk("R-8", "Query", None, why="the AI did not give pass or fail")
    assert WB.status_of(line) == ("Query", words.ORDER_QUERY)
    assert WB.layout_comment(line, *WB.status_of(line)).startswith(
        "Contractor to confirm Field R8 against STD-1 clause 4.1"
    )


def test_a_comment_is_three_parts_the_rule_the_paper_and_what_the_contractor_must_do():
    line = mk("R-1", "Fail", "Fail", comment="Replace the nameplate with a steel one.")
    one, two, three = WB.layout_comment(line, *WB.status_of(line)).split("\n")
    assert one == 'STD-1 clause 4.1 requires: "Nameplates shall be steel and fixed".'
    assert (
        two
        == 'The paper states "Nameplate: steel", page 2, which does not meet the requirement.'
    )
    assert (
        three
        == "Contractor to revise Field R1 to meet STD-1 clause 4.1 and resubmit the paper."
    )


def test_no_free_text_of_the_ai_reader_reaches_line_three_on_either_copy(tmp_path):
    said = "Raise it to 99 bar. Nothing further, looks fine, may proceed."
    lines = [
        mk("R-1", "Fail", "Fail", comment=said),
        mk("R-2", "Query", "Fail", why="x", comment=said),
        mk("R-3", "Query", None, why="x", comment=said),
        mk("R-4", "Query", "Pass", why="x", comment=said),
        mk("R-5", "Pass", "Pass", comment=said),
    ]
    for ln in lines:
        assert said.split(".")[0] not in WB.layout_comment(ln, *WB.status_of(ln))
    for copy, writer in (
        ("internal", C.write_internal),
        ("contractor", C.write_contractor),
    ):
        text = all_text(writer(lines, tmp_path / f"{copy}.xlsx", META))
        if copy == "contractor":
            assert "Nothing further" not in text and "99 bar" not in text
        else:  # internal: only on the Evidence sheet, in its own column
            main = all_text_of(tmp_path / "internal.xlsx", "CRS")
            assert "Nothing further" not in main and "99 bar" not in main
            ev = rows_of(tmp_path / "internal.xlsx", "Evidence")
            assert ev[0]["AI reader's suggested action"] == said


def test_the_rule_books_not_held_and_the_rules_not_asked_are_on_the_notes_sheet(
    tmp_path,
):
    meta = {
        **META,
        "rule_labels": {
            "summary_lines": ["needs another paper: 3 rules (procedure 3)"],
            "missing_rule_books": [
                {"rule_book": "Book X", "why": "cited by the paper"}
            ],
        },
    }
    path = C.write_internal([LINES[0]], tmp_path / "i.xlsx", meta)
    notes = {r["Topic"]: r["Detail"] for r in rows_of_notes(path)}
    assert notes["Rule books not held"] == "Book X (cited by the paper)"
    assert notes["Rules not asked"] == "needs another paper: 3 rules (procedure 3)"
    assert notes["Rule books used (reviewed lines)"] == "STD-1"
    assert "Book X" not in all_text_of(path, "CRS")  # never mixed into the item rows


def test_the_notes_counts_equal_the_rows_and_the_priority_rule_is_printed(tmp_path):
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    notes = {r["Topic"]: r["Detail"] for r in rows_of_notes(path)}
    assert notes["Priority rule"] == words.PRIORITY_RULE
    statuses = [r["Status"] for r in rows_of(path)]
    for status in words.STATUSES:
        assert int(notes[f"Count: {status}"]) == statuses.count(status)
    assert int(notes["Count: rows on the CRS sheet"]) == len(statuses)
    other = rows_of(path, "Not reviewed or not applicable")
    assert int(
        notes["Count: rows on the sheet 'Not reviewed or not applicable'"]
    ) == len(other)
    for kind in words.OTHER_KINDS:
        assert int(notes[f"Count: {kind}"]) == [r["What it is"] for r in other].count(
            kind
        )
    # the one function that decides a line's place (`sheet_of`) agrees with the rows
    assert len(statuses) + len(other) == len(LINES)
    assert len(statuses) == sum(
        1
        for ln in LINES
        if C.sheet_of(ln) in (C.CRS_SHEET, C.PASSED_SHEET, C.HELD_PASS_SHEET)
    )


def test_run_facts_and_run_numbers_are_on_the_notes_sheet_of_the_internal_copy_only(
    tmp_path,
):
    internal = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    notes = {r["Topic"]: r["Detail"] for r in rows_of_notes(internal)}
    assert notes["Run id"] == "run-1" and notes["First reader models"] == "lead-m"
    assert notes["Second reader models"] == "second-m" and notes["Cost (USD)"] == 0.5
    main = all_text_of(internal, "CRS")
    for word in ("run-1", "lead-m", "second-m"):
        assert (
            word not in main
        )  # no model name and no run number in the header block or the rows


def test_the_evidence_sheet_has_one_row_per_item_with_the_same_item_no(tmp_path):
    lines = [*LINES, mk("R-9", "Query", None, error="stop_max_tokens", reasoning="")]
    path = C.write_internal(lines, tmp_path / "i.xlsx", META)
    evidence = rows_of(path, "Evidence")
    shown = rows_of(path) + rows_of(path, "Not reviewed or not applicable")
    assert [e["Item No"] for e in evidence] == [r["Item No"] for r in shown]
    first = evidence[0]
    assert (
        first["Item id (internal)"] == "R-1" and first["AI reasoning"] == "It is steel."
    )
    assert first["Paper quote"] == "Nameplate: steel" and first[
        "Clause quote"
    ].startswith("Nameplates shall")
    assert (
        first["Paper quote check"] == "verified"
        and first["Clause quote check"] == "verified"
    )
    assert (
        first["Second reader"] == "not asked"
        and first["AI calls (models)"] == "first reader lead-m"
    )
    assert first["Reason code"] is None
    asked = mk(
        "R-A",
        "Fail",
        "Fail",
        second_opinion={"agree": False, "model": "second-m"},
        reason_code="not_met",
    )
    ev = rows_of(C.write_internal([asked], tmp_path / "j.xlsx", META), "Evidence")[0]
    assert ev["Second reader"] == "asked: disagreed" and ev["Reason code"] == "not_met"
    assert ev["AI calls (models)"] == "first reader lead-m; second reader second-m"
    unverified = mk(
        "R-B", "Query", "Pass", quotes_checked={"paper": False, "clause": True}, why="x"
    )
    ev = rows_of(C.write_internal([unverified], tmp_path / "k.xlsx", META), "Evidence")[
        0
    ]
    assert (
        ev["Paper quote check"] == "not verified"
        and ev["Clause quote check"] == "verified"
    )


def test_the_header_block_holds_what_the_app_has_and_the_generated_by_sentence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "crs_company_name", "")
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    top = list(
        openpyxl.load_workbook(path)["CRS"].iter_rows(max_row=12, values_only=True)
    )
    block = {r[0]: r[2] for r in top if r[0] and r[2] is not None}
    assert block["Project:"] == "Project Q" and block["Document number:"] == "DOC-77"
    assert (
        block["Document title:"] == "Title Z"
        and block["Revision:"] == "2"
        and block["Date:"] == "2026-01-05"
    )
    assert (
        block["Discipline:"] == "instrument"
        and block["Rule books used (reviewed lines):"] == "STD-1"
    )
    assert "Generated by AI, to be confirmed by a COMPANY engineer" in [
        r[0] for r in top
    ]
    monkeypatch.setattr(settings, "crs_company_name", "ACME Ltd")
    path = C.write_contractor(LINES, tmp_path / "c.xlsx", META)
    assert "Generated by AI, to be confirmed by a ACME Ltd engineer" in all_text(path)


def test_a_value_the_app_does_not_hold_is_blank_never_invented(tmp_path):
    path = C.write_internal(
        LINES, tmp_path / "i.xlsx", {**META, "header": {"project": "P"}}
    )
    top = {
        r[0]: r[2]
        for r in openpyxl.load_workbook(path)["CRS"].iter_rows(
            max_row=12, values_only=True
        )
        if r[0]
    }
    assert top["Project:"] == "P"
    for label in (
        "Document number:",
        "Document title:",
        "Revision:",
        "Date:",
        "Discipline:",
    ):
        assert top[label] in (None, "")  # blank: no "None", no "0", no guess


def test_comment_by_is_the_ai_reviewer_and_the_discipline_when_known(tmp_path):
    rows = rows_of(C.write_internal(LINES, tmp_path / "i.xlsx", META))
    assert {r["Comment By"] for r in rows} == {"AI reviewer, instrument"}
    rows = rows_of(C.write_internal(LINES, tmp_path / "j.xlsx", {**META, "header": {}}))
    assert {r["Comment By"] for r in rows} == {"AI reviewer"}


@pytest.mark.parametrize(
    ("line", "priority"),
    [
        (mk("R-1", "Fail", "Fail"), "High"),
        (mk("S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"}), "High"),
        (
            mk("R-3", "Query", "Fail", why="x"),
            "High",
        ),  # AI opinion not met, mandatory rule
        (
            mk("R-3", "Query", "Fail", why="x", rule_kind="advice"),
            "Medium",
        ),  # a 'should'
        (
            mk(
                "S-1",
                "Query",
                "Fail",
                item={"source": "skill", "item_id": "S-1"},
                why="x",
            ),
            "Medium",
        ),  # a checklist item
        (mk("R-8", "Query", None, why="x"), "Medium"),  # Query, mandatory
        (mk("R-8", "Query", None, why="x", rule_kind="advice"), "Low"),
        (mk("R-4", "Query", "Pass", why="x"), None),  # AI opinion met
        (mk("R-2", "Pass", "Pass"), None),
    ],
)
def test_the_priority_rule(line, priority, tmp_path):
    row = rows_of(C.write_internal([line], tmp_path / "i.xlsx", META))[0]
    assert row["Priority"] == priority


def test_the_main_sheet_is_styled_by_code(tmp_path):
    path = C.write_internal(LINES, tmp_path / "i.xlsx", META)
    ws = openpyxl.load_workbook(path)["CRS"]
    header = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Item No")
    for col in range(1, 11):
        cell = ws.cell(header, col)
        assert (
            cell.font.bold
            and cell.fill.fill_type == "solid"
            and cell.fill.fgColor.rgb == "FF1F3864"
        )
        assert cell.alignment.wrap_text and cell.border.left.style == "thin"
    for r in range(header + 1, ws.max_row + 1):
        for col in range(1, 11):
            assert (
                ws.cell(r, col).border.top.style == "thin"
                and ws.cell(r, col).alignment.wrap_text
            )
    assert ws.freeze_panes == f"A{header + 1}"
    assert (
        ws.page_setup.orientation == "landscape"
        and ws.page_setup.fitToWidth == 1
        and ws.page_setup.fitToHeight == 0
    )
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_title_rows == f"${header}:${header}"
    assert ws.print_area == f"'CRS'!$A$1:$J${ws.max_row}"
    widths = [ws.column_dimensions[c].width for c in "ABCDEFGHIJ"]
    assert (
        widths == list(crs_layout.LAYOUT_WIDTHS) and len(set(widths)) > 4
    )  # set per column, not one width
    by_status = {}
    for r in range(header + 1, ws.max_row + 1):
        by_status.setdefault(ws.cell(r, 10).value, set()).add(
            ws.cell(r, 1).fill.fgColor.rgb
        )
    assert all(len(v) == 1 for v in by_status.values())  # one colour per Status
    assert (
        {next(iter(v)) for v in by_status.values()}
        == {crs_layout.STATUS_FILLS[st].fgColor.rgb for st in by_status}
    )  # each Status present has exactly its own fill (the fifth, "AI verdict", has its own test in test_agent_two_reader.py)


def test_every_other_sheet_is_styled_the_same_way(tmp_path):
    wb = openpyxl.load_workbook(C.write_internal(LINES, tmp_path / "i.xlsx", META))
    for name in ("Not reviewed or not applicable", "Evidence", "Notes"):
        ws = wb[name]
        assert ws["A1"].fill.fgColor.rgb == "FF1F3864" and ws["A1"].font.bold
        assert ws.freeze_panes == "A2" and ws.page_setup.orientation == "landscape"
        assert ws.print_title_rows == "$1:$1" and ws.print_area.startswith(
            f"'{name}'!$A$1:"
        )


def test_the_status_fills_are_defined_once_with_five_colours():
    assert set(crs_layout.STATUS_FILLS) == set(words.STATUSES)
    fills = {name: f.fgColor.rgb for name, f in crs_layout.STATUS_FILLS.items()}
    assert len(fills) == 5
    # every pair of Statuses has two different fills
    for first, second in itertools.combinations(fills, 2):
        assert fills[first] != fills[second], (first, second)


def test_a_cell_that_starts_with_an_equals_sign_is_text_not_a_formula():
    """The drawing code stores every string as text, whatever the caller hands over (a second defence beside `_cell`)."""
    view = WB.layout_view([mk("R-1", "Fail", "Fail")], META, "internal")
    view["rows"] = [["=1+1"] * 10]
    view["header"] = [("Project:", "=SUM(A1)")]
    view["evidence"]["rows"][0][2] = "=HYPERLINK(1)"
    ws = openpyxl.load_workbook(io.BytesIO(crs_layout.build_layout_crs(view)))
    assert all(
        c.data_type != "f"
        for sheet in ws.worksheets
        for row in sheet.iter_rows()
        for c in row
    )
    assert any(
        c.value == "=1+1" for row in ws["CRS"].iter_rows() for c in row
    )  # the text is kept as it came


def test_run_counts_are_counts_only_with_a_denominator():
    counts = C.run_counts(LINES)
    assert counts["lines"] == 9 and counts["lines_with_a_verdict"].endswith(" of 9")
    assert (
        counts["unapproved_lines"] == 1 and counts["proven_fail"] == 3
    )  # R-1, R-6 (advice), S-1
    assert sum(counts["sheet_rows"].values()) == 9


def test_a_not_reviewed_line_is_not_an_item_row_in_any_copy(tmp_path):
    nr = mk("R-N", "Query", None, error="stop_max_tokens", reasoning="")
    assert nr["verdict_class"] == W.CLASS_NOT_REVIEWED
    held = mk(
        "R-H", "Query", "Pass", error="timeout"
    )  # an AI Pass with a failed call is not reviewed, not a held Pass
    assert held["verdict_class"] == W.CLASS_NOT_REVIEWED
    lines = [nr, held, mk("R-1", "Fail", "Fail")]
    internal = C.write_internal(lines, tmp_path / "i.xlsx", META)
    assert [r["Status"] for r in rows_of(internal)] == ["Fail"]
    other = rows_of(internal, "Not reviewed or not applicable")
    assert [r["What it is"] for r in other] == ["Not reviewed", "Not reviewed"]
    assert "cut off" in other[0]["Reason"]  # plain words, never the stored code
    assert len(rows_of(C.write_contractor(lines, tmp_path / "c.xlsx", META))) == 1
    assert len(rows_of(C.write_comment_only(lines, tmp_path / "o.xlsx", META))) == 1


def test_a_not_reviewed_line_of_an_unapproved_rule_is_only_on_the_other_sheet(tmp_path):
    cut = mk("R-U", "Query", "Pass", item=NO, error="stop_max_tokens")
    assert cut["verdict_class"] == W.CLASS_NOT_REVIEWED
    raw = {
        **mk("R-Q", "Query", None),
        "error": "timeout",
    }  # a line whose class was never recomputed
    raw.pop("verdict_class")
    internal = C.write_internal(
        [cut, raw, mk("R-1", "Fail", "Fail")], tmp_path / "i.xlsx", META
    )
    assert [r["Status"] for r in rows_of(internal)] == ["Fail"]
    assert [
        r["What it is"] for r in rows_of(internal, "Not reviewed or not applicable")
    ] == ["Not reviewed", "Not reviewed"]


# ---------------------------------------------------------------- the banned-words test


def _every_kind_of_line():
    stored = "Provide the S-EQ-04 value (reason not_met); the gate and the guard said so. Keep the sheet clean."
    return [
        *LINES,
        mk("R-10", "Fail", "Fail", comment=stored),
        mk("R-11", "Query", "Pass", why=V.SILENCE_WHY, reason_code="sheet_silent"),
        mk(
            "R-12",
            "Query",
            None,
            why="second opinion disagreed; first verdict RED",
            comment=stored,
        ),
        mk("R-13", "Query", "Fail", why="something nobody wrote a phrase for yet"),
        mk(
            "R-14",
            "Query",
            "Pass",
            why=V.DISAGREE_WHY,
            paper_quote="Valve tag: by contractor",
            reason_code="met",
        ),
        mk("R-15", "Query", None, reason_code="needs_drawing_or_calc", why="x"),
        mk(
            "R-16",
            "Query",
            "Pass",
            reason_code="value_deferred",
            why="x",
            paper_quote="340 psig (By Contractor)",
        ),
        mk("R-17", "Query", None, error="stop_max_tokens", reasoning=""),
        mk("R-18", "Query", None, reason_code="not_applicable", comment=stored),
    ]


def test_no_code_word_on_any_cell_of_the_main_sheet_in_either_copy(tmp_path):
    """The words a reader sees hold no item id, no reason code, no model name and none of gate, lane, guard, tier,
    verdict class, quote check (`crs_ai_words.BANNED`). Run on every kind of line, with stored texts full of code words."""
    lines = _every_kind_of_line()
    for name, path in (
        ("internal", C.write_internal(lines, tmp_path / "i.xlsx", META)),
        ("contractor", C.write_contractor(lines, tmp_path / "c.xlsx", META)),
    ):
        wb = openpyxl.load_workbook(path)
        for sheet in wb.sheetnames:
            if sheet in ("Evidence", "Notes"):
                continue  # the working sheets may carry the codes
            for row in wb[sheet].iter_rows():
                for cell in row:
                    hit = words.BANNED.search(str(cell.value or ""))
                    assert not hit, (
                        f"{name} {sheet}!{cell.coordinate} holds {hit.group(0)!r}: {cell.value!r}"
                    )
    # and the test would catch one: the Evidence sheet does hold the codes
    assert words.BANNED.search(
        all_text_of(C.write_internal(lines, tmp_path / "e.xlsx", META), "Evidence")
    )


# ---------------------------------------------------------------- review R27 (order 13): fixes and their tests


def _line2(line):
    return WB.layout_comment(line, *WB.status_of(line)).split("\n")[1]


def _reason_constants():
    from app import agent_review_absence as absence

    consts = {
        v
        for k, v in vars(V).items()
        if k.endswith("_WHY") and isinstance(v, str) and not k.startswith("CLASS_")
    }
    return sorted(consts | set(absence.ABSENCE_WHY.values()) | set(words.WHY_PHRASES))


def test_the_paper_does_not_state_is_printed_only_for_the_absence_proof():
    """R27 blocking 1: brute force over every reason constant. A silent line whose stored reason is any of them never says the
    paper does not state it, and prints its own reason in plain words; the absence check's own proof still does."""
    for reason in _reason_constants():
        for item in (OK, {"source": "skill", "item_id": "S-1"}):
            line = mk(
                "R-1",
                "Query",
                "Fail",
                item=item,
                reason_code="absent",
                why=reason,
                pages_searched=[1, 2],
                paper_quote=None,
                quotes_checked={"paper": False, "clause": True},
            )
            line2 = _line2(line)
            assert "does not state" not in line2, (reason, line2)
            assert "The AI reviewer did not find Field R1 in the paper" in line2
            assert (
                words.why_phrase(reason) in line2 or line["not_proven_reason"] != reason
            ), (reason, line2)
    proven = mk("R-1", "Fail", "Fail", decided_by="AI verdict, absence checked by code", reason_code="absent",
                paper_quote=None, quotes_checked={"paper": False, "clause": True}, pages_searched=[1, 2], paper_kind="datasheet")  # fmt: skip
    assert WB.status_of(proven) == ("Fail", words.ORDER_FAIL)
    assert _line2(proven) == "The paper does not state Field R1 (pages searched: 1, 2)."


def test_a_silent_line_with_a_verified_quote_does_not_say_the_paper_is_silent():
    line = mk(
        "R-1",
        "Query",
        None,
        reason_code="sheet_silent",
        silence_query=True,
        why=V.SILENCE_WHY,
    )
    assert "does not state" not in _line2(
        line
    ) and 'The paper states "Nameplate: steel"' in _line2(line)


@pytest.mark.parametrize("verdict", ["Fail", "Query", "Pass"])
@pytest.mark.parametrize("ai", ["Fail", "Pass", None])
def test_line_three_always_agrees_with_the_status(verdict, ai):
    """R27 blocking 2: the reader's "no action ... meets the rule" never reaches a line that asks for action, in either copy."""
    said = "No action required, the nameplate is steel and meets the rule."
    line = mk("R-1", verdict, ai, comment=said, why="x" if verdict == "Query" else None)
    got = WB.status_of(line)
    if got is None:
        return
    third = WB.layout_comment(line, *got).split("\n")[2]
    if got[0] in ("Fail", "Query") or (
        got[0] == "AI opinion" and got[1] == words.ORDER_AI_NOT_MET
    ):
        assert "No action" not in third and "meets the rule" not in third, (
            verdict,
            ai,
            third,
        )
        assert third.startswith("Contractor to")
    else:
        assert third.startswith("No action")


FALLBACK = "The AI reviewer holds no verified quote from the paper for this point."
PAPER_CLAIMS = (
    "the paper gives",
    "the paper does not",
    "is missing",
    "not shown",
    "not given",
    "no value",
)


def test_the_fallback_is_a_statement_about_the_reviewer_and_makes_no_claim_about_the_paper():
    """R27b B1: brute force over the stored shapes that reach the fallback (no verified quote, any verdict, any reason): line 2 holds
    none of the paper claims unless the line carries the code's absence proof, and never the empty 'it could not be confirmed'."""
    reasons = ["", "zz_unknown reason", *_reason_constants()]
    for verdict, ai in (
        ("Query", None),
        ("Query", "Fail"),
        ("Query", "Pass"),
        ("Fail", "Fail"),
    ):
        for code in (None, "other", "unclear_clause", "met", "not_met"):
            for reason in reasons:
                line = mk("R-1", verdict, ai, reason_code=code, why=reason or None, paper_quote=None,
                          quotes_checked={"paper": False, "clause": True}, decided_by="engineer")  # fmt: skip
                got = WB.status_of(line)
                if got is None:
                    continue
                line2 = WB.layout_comment(line, *got).split("\n")[1].lower()
                assert "not confirmed: it could not be confirmed" not in line2, (
                    verdict,
                    ai,
                    code,
                    reason,
                    line2,
                )
                if "does not state" in line2:
                    continue
                assert not any(c in line2 for c in PAPER_CLAIMS), (
                    verdict,
                    ai,
                    code,
                    reason,
                    line2,
                )
    bare = mk(
        "R-1",
        "Query",
        None,
        paper_quote=None,
        quotes_checked={"paper": False, "clause": True},
    )
    assert WB.layout_comment(bare, *WB.status_of(bare)).split("\n")[1] == FALLBACK


def test_no_phrase_of_the_table_is_a_tautology_of_its_own_label():
    assert words.UNKNOWN_WHY == "it could not be confirmed"
    for text, phrase in words.WHY_PHRASES.items():
        assert (
            phrase != words.UNKNOWN_WHY
            and phrase.strip(". ")
            and len(phrase.split()) >= 4
        ), text
        assert (
            f"Not confirmed: {phrase}".lower()
            != "not confirmed: it could not be confirmed"
        )


def test_the_contractor_header_lists_only_the_books_of_the_rows_shown(tmp_path):
    lines = [
        mk("R-1", "Fail", "Fail"),
        mk("R-2", "Query", "Fail", why="x", standard="OPINION-BOOK"),
        mk(
            "R-3",
            "Query",
            None,
            error="stop_max_tokens",
            reasoning="",
            standard="NOTREVIEWED-BOOK",
        ),
        mk("R-4", "Fail", "Fail", item=NO, standard="UNAPPROVED-BOOK"),
    ]
    contractor = C.write_contractor(lines, tmp_path / "c.xlsx", META)
    top = {
        r[0]: r[2]
        for r in openpyxl.load_workbook(contractor)["CRS"].iter_rows(
            max_row=14, values_only=True
        )
        if r[0]
    }
    assert top["Rule books used (rows shown):"] == "STD-1"
    assert all(
        b not in all_text(contractor)
        for b in ("OPINION-BOOK", "NOTREVIEWED-BOOK", "UNAPPROVED-BOOK")
    )
    none = C.write_contractor([lines[1]], tmp_path / "n.xlsx", META)
    top = {
        r[0]: r[2]
        for r in openpyxl.load_workbook(none)["CRS"].iter_rows(
            max_row=14, values_only=True
        )
        if r[0]
    }
    assert top["Rule books used (rows shown):"] in (None, "")
    internal = C.write_internal(lines, tmp_path / "i.xlsx", META)
    top = {
        r[0]: r[2]
        for r in openpyxl.load_workbook(internal)["CRS"].iter_rows(
            max_row=14, values_only=True
        )
        if r[0]
    }
    assert "NOTREVIEWED-BOOK" not in top["Rule books used (reviewed lines):"]
    assert "OPINION-BOOK" in top["Rule books used (reviewed lines):"]


def test_status_is_keyed_on_the_class_not_the_raw_verdict():
    sneaky = {
        **mk("R-1", "Fail", "Fail"),
        "verdict_class": W.CLASS_OPINION,
        "verdict_label": W.THINKS_NOT_MET,
    }
    assert WB.status_of(sneaky)[0] == "AI opinion"
    sneaky_pass = {**mk("R-2", "Pass", "Pass"), "verdict_class": W.CLASS_QUERY}
    assert WB.status_of(sneaky_pass)[0] != "Pass"


def test_every_other_sheet_reason_starts_with_a_capital_and_keeps_ai_upper_case(
    tmp_path,
):
    nr = mk("R-N", "Query", None, error="stop_max_tokens", reasoning="")
    reason = rows_of(
        C.write_internal([nr], tmp_path / "i.xlsx", META),
        "Not reviewed or not applicable",
    )[0]["Reason"]
    assert reason == "The AI reviewer's answer was cut off."


def test_a_scorer_reads_both_layouts_by_header_name_and_says_which(tmp_path):
    from tools import answer_key_score as aks

    lines = [
        mk("R-1", "Fail", "Fail", paper_quote="x y z"),
        mk("R-2", "Pass", "Pass"),
        mk("R-3", "Query", "Fail", why="x"),  # AI opinion not met: a comment
        mk("R-4", "Query", "Pass", why="x"),  # AI opinion met: neither
    ]
    got, layout = aks.read_crs_layout(
        C.write_internal(lines, tmp_path / "i.xlsx", META)
    )
    assert layout == aks.LAYOUT_NEW
    assert (
        sum(1 for x in got if x.is_pass) == 1 and len(got) == 3
    )  # one Pass, Fail + AI opinion (not met) comments
    old = openpyxl.Workbook()
    ws = old.active
    ws.title = "CRS"
    ws.append(
        ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Verdict"]
    )
    ws.append(["R-1", "P", "p.1 - Field", "text", "Pass, decided by code"])
    old.save(tmp_path / "old.xlsx")
    got, layout = aks.read_crs_layout(tmp_path / "old.xlsx")
    assert layout == aks.LAYOUT_OLD and [x.is_pass for x in got] == [True]


# ---------------------------------------------------------------- part A: a checklist line's own item wording


@pytest.fixture
def skills(monkeypatch):
    """A fake checklist loaded through the app's one loader (`agent_skills.load_skill`)."""
    from app import agent_skills

    def load(kind):
        if kind != agent_skills.KINDS[0]:
            raise agent_skills.SkillError("none")
        return {
            "items": [
                {
                    "id": "1",
                    "expected": "The nameplate is steel and S-EQ-04 is fixed.",
                }
            ]
        }

    WB._WORDING.clear()
    monkeypatch.setattr(agent_skills, "load_skill", load)
    yield
    WB._WORDING.clear()


def test_a_checklist_lines_part_one_is_the_item_wording_by_item_id(skills):
    line = mk("S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"})
    assert (
        WB.checklist_wording("S-1") == "The nameplate is steel and is fixed."
    )  # a code word is scrubbed
    one = WB.layout_comment(line, *WB.status_of(line)).split("\n")[0]
    assert one == 'STD-1 clause 4.1 requires: "The nameplate is steel and is fixed.".'
    assert not words.has_banned(one)


def test_a_checklist_line_falls_back_to_todays_text_and_the_notes_sheet_says_so(
    tmp_path, monkeypatch
):
    from app import agent_skills

    WB._WORDING.clear()
    monkeypatch.setattr(
        agent_skills,
        "load_skill",
        lambda kind: (_ for _ in ()).throw(agent_skills.SkillError("gone")),
    )
    line = mk("S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"})
    assert WB.checklist_wording("S-1") == ""
    one = WB.layout_comment(line, *WB.status_of(line)).split("\n")[0]
    assert (
        one == 'STD-1 clause 4.1 requires: "Nameplates shall be steel and fixed".'
    )  # the verified clause quote, as before
    path = C.write_internal([line], tmp_path / "i.xlsx", META)
    notes = {r["Topic"]: r["Detail"] for r in rows_of_notes(path)}
    assert notes["Checklist wording"].startswith("not available on this machine")
    assert WB._WORDING == []  # a failed load is never remembered


def test_a_rule_line_never_reads_the_checklist(skills):
    line = mk("R-1", "Fail", "Fail")
    assert WB.layout_comment(line, *WB.status_of(line)).startswith(
        'STD-1 clause 4.1 requires: "Nameplates shall'
    )


def test_the_notes_sheet_says_where_the_checklist_wording_came_from(skills, tmp_path):
    line = mk("S-1", "Fail", "Fail", item={"source": "skill", "item_id": "S-1"})
    notes = {
        r["Topic"]: r["Detail"]
        for r in rows_of_notes(C.write_internal([line], tmp_path / "i.xlsx", META))
    }
    assert notes["Checklist wording"] == "from the checklist data"


def test_no_cell_of_the_contractor_copy_names_an_internal_judgement_a_model_or_a_run(
    tmp_path,
):
    """Every cell of every sheet of the contractor copy, on every kind of line; plain styling (no fill encodes a Status)."""
    path = C.write_contractor(_every_kind_of_line(), tmp_path / "c.xlsx", META)
    wb = openpyxl.load_workbook(path)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                text = str(cell.value or "")
                for bad in (
                    "AI opinion",
                    "AI verdict",
                    "AI reviewer's view",
                    "not proven",
                    "Query",
                    "run-1",
                    "lead-m",
                    "second-m",
                ):
                    assert bad not in text, (cell.coordinate, bad)
                assert not words.has_banned(text), (cell.coordinate, text)
                assert (
                    cell.value is None
                    or cell.fill.fill_type is None
                    or cell.row <= 1
                    or cell.fill.fgColor.rgb in ("FF1F3864", "00000000")
                )
    ws = wb["CRS"]
    body = [
        c
        for r in ws.iter_rows(min_row=14)
        for c in r
        if c.value is not None and c.row > 14
    ]
    assert all(c.fill.fill_type is None for c in body)  # plain: no Status colour


def test_the_second_reading_row_is_on_notes_exactly_once_when_the_step_stopped_and_never_when_it_did_not():
    def rows(meta):
        view = WB.layout_view([mk("R-1", "Fail", "Fail")], meta, "internal")
        return [r for r in view["notes"]["rows"] if r[0] == "Second reading of pages"]

    stopped = {
        **META,
        "order12_counts": {
            "page_reread_stopped": "The second reading of pages stopped early: 3 lines were not re-read"
        },
    }
    assert len(rows(stopped)) == 1
    assert rows(META) == [] and rows({**META, "order12_counts": {}}) == []
