"""Order 14 lane C: the answer-key scorer reads the TEAM file (`crs_one.build_team`), takes a procedure playbook row's element role
from the element's own lead, parses page cells that go on with a section path, and scores two ways with a cause for every miss.

Invented keys and invented workbooks only: no client key row, no paper text. The playbook titles come from the app's own playbook
files (data the run holds), never from a paper.
"""

from __future__ import annotations

import openpyxl
import pytest
from tools import answer_key_score as aks

from app import crs_one, playbooks, procedure_playbook_rows

KEY_HEAD = ["Row", "Standard Reference", "Field role", "Paper page", "Scored as"]


def _key(tmp_path, rows, name="key.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(KEY_HEAD)
    for i, r in enumerate(rows, start=1):
        ws.append([i, r.get("std", ""), r.get("role", ""), r.get("page", ""), r["kind"]])
    path = tmp_path / name
    wb.save(path)
    return path


def _point(no, comment, pill, cls, field, page, book="", clause=None, action="", reason=""):
    cells = dict.fromkeys(crs_one.TEAM_COLUMNS)
    cells.update({"No": no, "Comment": comment, "Source": "Rule check", "Pill": pill, "Class": cls, "Field or item": field, "Page": page,
                  "Rule book": book, "Clause": clause, "What the contractor must do": action, "Reason": reason})  # fmt: skip
    return [cells[c] for c in crs_one.TEAM_COLUMNS]


def _team(tmp_path, points, held=(), name="team.xlsx"):
    """A workbook in the team file's layout: a header block and the comment table on CRS, the per-point table on Evidence."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = crs_one.TEAM_SHEET
    ws.append(["Comment Resolution Sheet"])
    ws.append(["Paper:", None, "INVENTED PAPER"])
    ws.append([])
    ws.append(list(crs_one.COMMENT_COLUMNS))
    for p in points:  # one comment per point here; the comment table must NOT be read again
        row = dict(zip(crs_one.TEAM_COLUMNS, p))
        if str(row["Comment"]).isdigit():
            ws.append([int(row["Comment"]), row["Pill"], row["Class"], None, row["Field or item"], 1, row["Page"], row["Rule book"]])
    ev = wb.create_sheet(crs_one.EVIDENCE_SHEET)
    ev.append(["Every point the page counts, one row each."])
    ev.append([])
    ev.append(list(crs_one.TEAM_COLUMNS))
    for p in points:
        ev.append(p)
    hs = wb.create_sheet(crs_one.HELD_SHEET)
    hs.append([f"{len(held)} rule book(s) not held."])
    hs.append([])
    hs.append(["Rule book", "What it means"])
    for b in held:
        hs.append([b, crs_one.HELD_MEANS])
    path = tmp_path / name
    wb.save(path)
    return path


def _lead(playbook_id: str, element_id: str) -> str:
    """The lead a playbook row prints, built from the app's own playbook (its title and the element's title)."""
    found, _ = playbooks.available()
    pb = found[playbook_id]
    e = next(x for x in pb.elements if x.id == element_id)
    return f"{procedure_playbook_rows.element_lead(pb.title, e.title)} ({e.standard} {e.clause})"


def test_the_scorer_reads_the_team_columns_the_builder_writes():
    for name in (aks.TEAM_FIELD, aks.TEAM_PAGE, aks.TEAM_PILL, aks.TEAM_CLASS, aks.TEAM_COMMENT, aks.TEAM_BOOK, aks.TEAM_CLAUSE):
        assert name in crs_one.TEAM_COLUMNS
    assert "Page" not in crs_one.COMMENT_COLUMNS  # the comment table ("Pages") is never taken for the per-point table
    assert aks.HELD_SHEET == crs_one.HELD_SHEET


def test_the_team_file_is_read_point_by_point_with_its_kind_from_class_and_pill(tmp_path):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2"},
        {"kind": "complies", "role": "body_material", "page": "1"},
        {"kind": "problem", "role": "design_pressure", "page": "3"},
    ]
    points = [
        _point(1, "1", "Question", "Questions for you", "Set pressure", "2"),
        _point(2, "removed", "Question", "Questions for you", "Design pressure", "3"),  # an engineer removed it: not read
        _point(3, "Nothing to change", "Met · proven by code", "Met", "Body material", "1"),  # set aside, still a pass line
        _point(4, "2", "Met · one reader", "Met", "Design pressure", "3"),  # the AI's own met: no comment, no pass
        _point(5, "3", "Does not apply", "Does not apply", "Design pressure", "3"),
    ]
    res = aks.score_files(_key(tmp_path, key), _team(tmp_path, points))
    assert res["layout"] == aks.LAYOUT_TEAM
    assert res["problems_found"] == [2] and res["complies_confirmed"] == [3]
    assert res["comment_lines"] == 1 and res["pass_lines"] == 1  # the CRS sheet's comment table was not read a second time
    assert res["missed"] == {"not asked": [4]}  # the removed point, the AI's own met and the does-not-apply point raise nothing


def test_before_the_fix_the_team_file_gave_no_line(tmp_path):
    """The layout the scorer could not read (no "Item No" header): every line is read now, none was before."""
    points = [_point(1, "1", "Not met · proven by code", "Not met", "Set pressure", "2", "XS-1", "4.2")]
    lines, layout = aks.read_crs_layout(_team(tmp_path, points))
    assert layout == aks.LAYOUT_TEAM and len(lines) == 1
    ln = lines[0]
    assert (ln.status, ln.pages, ln.clause, ln.is_pass) == ("fail", frozenset({2}), ("XS1", "4.2"), False)


def test_a_two_reader_verdict_of_the_team_file_is_its_own_kind(tmp_path):
    points = [
        _point(1, "1", "Not met · two readers agree", "Not met", "Set pressure", "2"),
        _point(2, "Nothing to change", "Met · two readers agree", "Met", "Body material", "1"),
    ]
    lines, _ = aks.read_crs_layout(_team(tmp_path, points))
    assert [(ln.status, ln.ai_kind) for ln in lines] == [("ai verdict", "not met"), ("ai verdict", "met")]


def test_a_playbook_row_carries_its_elements_role_from_the_lead_it_prints(tmp_path):
    lead = _lead("hazop_procedure", "H01")
    key = [{"kind": "problem", "role": "hazop_procedure:H01", "page": "2"}]
    on = [_point(1, "1", "Question", "Questions for you", "1 > para 1-4", "2", action=f"{lead}: section found at page 2.")]
    res = aks.score_files(_key(tmp_path, key), _team(tmp_path, on))
    assert res["problems_found"] == [2]
    # the same section path without the element's lead names no element: not found
    off = [_point(1, "1", "Question", "Questions for you", "1 > para 1-4", "2", action="Section found at page 2.")]
    res = aks.score_files(_key(tmp_path, key), _team(tmp_path, off, name="t2.xlsx"))
    assert res["problems_found"] == []


def test_every_element_lead_names_its_own_element_only():
    found, _ = playbooks.available()
    for pb in found.values():
        for e in pb.elements:
            assert aks.element_roles(f"x {_lead(pb.id, e.id)}: y") == frozenset({f"{pb.id}:{e.id}"})


def test_the_playbook_comment_starts_with_the_lead_the_scorer_reads():
    found, _ = playbooks.available()
    pb = found["hazop_procedure"]
    e = pb.elements[0]
    entry = {"title": e.title, "source": {"standard": e.standard, "clause": e.clause}, "state": playbooks.STANDARD_NOT_HELD,
             "reason": "invented reason"}  # fmt: skip
    text = procedure_playbook_rows._comment(pb, {"playbook": {"notice": None}}, entry)
    assert text.startswith(_lead(pb.id, e.id) + ":")
    assert aks.element_roles(text) == frozenset({f"{pb.id}:{e.id}"})


def test_an_old_layout_line_takes_the_element_role_too(tmp_path):
    lead = _lead("sil_procedure", "S08")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Standard Reference", "Status"])
    ws.append(["R-1", "doc_x", "p.8 - 4 > 4.5 > para 1-3", f"{lead}: Section not found.", "XS-1 11.9", "Query"])
    path = tmp_path / "old.xlsx"
    wb.save(path)
    key = [{"kind": "problem", "role": "sil_procedure:S08", "page": "8"}]
    assert aks.score_files(_key(tmp_path, key), path)["problems_found"] == [2]


@pytest.mark.parametrize(
    "cell, pages",
    [
        ("p.2 - 1 > para 1-4", {2}),  # the section path's numbers are not pages (was: nothing, "2 - 1" read as a range)
        ("page 2", {2}),  # was: nothing
        ("pages 2 and 4", {2, 4}),
        ("p.1-4 - Set pressure", {1, 2, 3, 4}),
        ("p.2, 7 - 4 > 4.3 > para 1-3", {2, 7}),
        ("p.3", {3}),
        ("page not found (not read) - Not read from the datasheet (5 pages) - Cdtp", set()),
        ("1 > para 1-4", set()),
    ],
)
def test_a_page_cell_gives_its_own_pages_and_never_a_section_paths_numbers(cell, pages):
    assert aks.line_pages(cell, "") == frozenset(pages)


@pytest.mark.parametrize("cell, pages", [("8", {8}), ("2, 7", {2, 7}), ("1-3", {1, 2, 3}), ("not recorded", set()), ("", set())])
def test_a_page_only_cell_of_the_team_file(cell, pages):
    assert aks.page_cell_pages(cell) == frozenset(pages)


def test_two_ways_and_one_cause_for_every_row_not_found(tmp_path):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2", "std": "XS-1 4.2"},  # found
        {"kind": "problem", "role": "cdtp", "page": "absent", "std": "NH-9 6.1"},  # its book is not held
        {"kind": "problem", "role": "design_pressure", "page": "5", "std": "XS-1 7.1"},  # raised on page 6 only
        {"kind": "problem", "role": "body_material", "page": "4", "std": "XS-1 8.2"},  # clause raised under another field
        {"kind": "problem", "role": "orifice_area", "page": "9", "std": "XS-1 9.9"},  # nothing
        {"kind": "complies", "role": "inlet_size", "page": "3", "std": "XS-1 3.3"},  # left as a question
    ]
    points = [
        _point(1, "1", "Question", "Questions for you", "Set pressure", "2", "XS-1", "4.2"),
        _point(2, "2", "Question", "Questions for you", "Design pressure", "6", "XS-1", "7.1"),
        _point(3, "3", "Not met · one reader", "Not met", "Some other field", "4", "XS-1", "8.2"),
        _point(4, "4", "Question", "Questions for you", "Inlet size", "3", "XS-1", "3.3"),
        _point(5, "5", "Question", "Questions for you", "Not on the key", "12", reason="Book missing: NH-9 (clause not named by the reviewer)"),
    ]
    res = aks.score_files(_key(tmp_path, key), _team(tmp_path, points))
    s = aks.summary(res)
    assert s["two_ways"]["problems_found_of_all"] == "1 of 5"
    assert s["two_ways"]["problems_found_where_rule_held"] == "1 of 4"
    assert s["two_ways"]["books_the_file_says_not_held"] == ["NH9"]
    assert res["missed"] == {"book not held": [3], "misread": [4], "wrong label": [5], "not asked": [6], "left as a question": [7]}
    assert s["comment_lines_answering_no_key_row"] == 3  # design pressure on page 6, "Some other field", "Not on the key"


def test_the_held_sheet_alone_says_a_book_is_not_held(tmp_path):
    key = [{"kind": "problem", "role": "cdtp", "page": "absent", "std": "NH-9 6.1"}]
    path = _team(tmp_path, [_point(1, "1", "Question", "Questions for you", "Set pressure", "2")], held=("NH-9",))
    res = aks.score_files(_key(tmp_path, key), path)
    assert res["missed"] == {"book not held": [2]} and res["two_ways"]["not_held_books"] == ["NH9"]
    # without the listing the same row is simply not asked: the scorer never guesses a book is missing
    res = aks.score_files(_key(tmp_path, key), _team(tmp_path, [_point(1, "1", "Question", "Questions for you", "Set pressure", "2")], name="t3.xlsx"))
    assert res["missed"] == {"not asked": [2]}
