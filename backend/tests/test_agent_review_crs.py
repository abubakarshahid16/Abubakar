"""The CRS files of the AI reviewer in the app's own layout (order 13): internal and contractor. Invented data only; no model, no network."""

from __future__ import annotations

import io

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


def mk(iid, verdict, ai=None, item=OK, **kw):
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
    base.update(kw)
    return W.final_cap(base, item, skill_ids=SK)


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
    assert {r["Status"] for r in rows_of(path)} == {"Fail"}
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
    assert three == "Replace the nameplate with a steel one."


def test_a_number_in_the_readers_action_that_no_checked_quote_holds_is_not_printed():
    line = mk(
        "R-1", "Fail", "Fail", comment="Raise the set pressure to 99 bar and re-issue."
    )
    third = WB.layout_comment(line, *WB.status_of(line)).split("\n")[2]
    assert "99" not in third and third.startswith("Contractor to correct the paper")


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
    assert notes["Rule books used"] == "STD-1"
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
    assert block["Discipline:"] == "instrument" and block["Rule books used:"] == "STD-1"
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
    assert {next(iter(v)) for v in by_status.values()} == {
        f.fgColor.rgb for f in crs_layout.STATUS_FILLS.values()
    }


def test_every_other_sheet_is_styled_the_same_way(tmp_path):
    wb = openpyxl.load_workbook(C.write_internal(LINES, tmp_path / "i.xlsx", META))
    for name in ("Not reviewed or not applicable", "Evidence", "Notes"):
        ws = wb[name]
        assert ws["A1"].fill.fgColor.rgb == "FF1F3864" and ws["A1"].font.bold
        assert ws.freeze_panes == "A2" and ws.page_setup.orientation == "landscape"
        assert ws.print_title_rows == "$1:$1" and ws.print_area.startswith(
            f"'{name}'!$A$1:"
        )


def test_the_status_fills_are_defined_once_with_four_colours():
    assert set(crs_layout.STATUS_FILLS) == set(words.STATUSES)
    assert len({f.fgColor.rgb for f in crs_layout.STATUS_FILLS.values()}) == 4


def test_a_cell_that_starts_with_an_equals_sign_is_text_not_a_formula():
    line = mk("R-1", "Fail", "Fail", paper_quote="=1+1", field="=SUM(A1)")
    data = crs_layout.build_layout_crs(WB.layout_view([line], META, "internal"))
    ws = openpyxl.load_workbook(io.BytesIO(data))["CRS"]
    assert all(c.data_type != "f" for row in ws.iter_rows() for c in row)


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
