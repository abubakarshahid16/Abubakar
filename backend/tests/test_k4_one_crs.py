# ruff: noqa: RUF059
"""K4: ONE complete CRS file per paper, drawn from the page's own list of points. Invented data only; the data-copy test runs only
where a copy of stored runs is present."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app import (
    access,
    crs_one,
    db,
    review_points,
    review_points_service,
)
from app.config import settings
from tests.test_b1_review_points import decide, points_of, world_with_both
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def sheet(data: bytes, name: str = "CRS"):
    return load_workbook(io.BytesIO(data))[name]


def rows_after(ws, first_header: str):
    """The table rows under the header whose first cell is `first_header`."""
    values = [list(r) for r in ws.iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(values) if r and r[0] == first_header)
    return values[start], [
        r for r in values[start + 1 :] if any(c is not None for c in r)
    ]


def count_line_of(ws) -> str:
    return next(
        r[0]
        for r in ws.iter_rows(values_only=True)
        if isinstance(r[0], str) and " points on the page; " in r[0]
    )


def scope_all():
    conn = db.connect()
    return access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in conn.execute("SELECT id FROM documents")
        ),
    )


def equality(doc, scope):
    """(points on the page, rows on the sheet CRS, rows on the sheet Removed (record), the file's own count line)."""
    page = review_points_service.assemble(doc, scope)
    data = crs_one.build_team(doc, scope)
    ws = sheet(data)
    _head, crs_rows = rows_after(ws, "No")
    _h2, removed = rows_after(sheet(data, crs_one.REMOVED_SHEET), "No")
    return page["of"], len(crs_rows), len(removed), count_line_of(ws)


# ------------------------------------------------------------------------------------------------ one file, every point


def test_the_team_file_holds_every_point_the_page_counts_and_says_so():
    doc, rc, ai, client = world_with_both()
    page, rows, removed, line = equality(doc, scope_all())
    assert page == 4 and rows + removed == page
    assert line.startswith(
        f"{page} points on the page; {rows + removed} rows in this file"
    )


def test_a_removed_point_is_counted_once_and_sits_on_its_own_sheet_with_who_and_why():
    doc, rc, ai, client = world_with_both()
    first = points_of(client, doc)["points"][-1]
    assert (
        decide(client, doc, first["id"], "remove", reason="Not our scope").status_code
        == 200
    )
    page, rows, removed, _ = equality(doc, scope_all())
    assert (page, removed) == (4, 1) and rows == 3
    _h, rem = rows_after(
        sheet(crs_one.build_team(doc, scope_all()), crs_one.REMOVED_SHEET), "No"
    )
    assert "Not our scope" in rem[0]


def test_the_file_is_worst_first_like_the_page():
    doc, rc, ai, client = world_with_both()
    page = points_of(client, doc)["points"]
    _h, rows = rows_after(sheet(crs_one.build_team(doc, scope_all())), "No")
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1))
    assert [r[2] for r in rows] == [p["pill"] for p in page]


def test_the_team_file_has_all_the_sheets():
    doc, rc, ai, client = world_with_both()
    from openpyxl import load_workbook as lw

    names = lw(io.BytesIO(crs_one.build_team(doc, scope_all()))).sheetnames
    assert names == [
        "CRS", "Removed (record)", "Does not apply", "Rule books not held", "What was not checked", "How it was reviewed",
    ]  # fmt: skip


def test_the_header_is_complete_and_a_draft_never_says_date_issued():
    doc, rc, ai, client = world_with_both()
    data = crs_one.build_team(doc, scope_all(), exported="2026-11-15 10:00 UTC")
    text = "\n".join(
        str(c)
        for r in sheet(data).iter_rows(values_only=True)
        for c in r
        if c is not None
    )
    for label in ("Paper:", "Revision:", "Kind of paper:", "Equipment type:", "Engine:", "Review date:", "Exported on:", "Decided by:",
                  "Proposed review code:", "Recorded review code:"):  # fmt: skip
        assert label in text
    assert "Date Issued" not in text and "2026-11-15 10:00 UTC" in text
    assert "Working copy, not issued" in text and "not recorded" in text


def test_how_it_was_reviewed_counts_pages_engine_and_rules():
    doc, rc, ai, client = world_with_both()
    ws = sheet(crs_one.build_team(doc, scope_all()), crs_one.HOW_SHEET)
    text = "\n".join(
        str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None
    )
    assert (
        "AI review: engine" in text
        and "AI review: rules asked" in text
        and "run id" in text
    )


# ------------------------------------------------------------------------------------------------ no unmarked cut


def test_a_long_cell_ends_with_the_mark_and_the_whole_text_is_in_the_full_text_column():
    doc, rc, ai, client = world_with_both()
    point = points_of(client, doc)["points"][0]
    raw = next(
        p
        for p in review_points_service.export_listing(doc, scope_all())[1]
        if p["id"] == point["id"]
    )
    raw = {**raw, "action": "The valve shall be 25 mm " * 40 + "rated 150 lb 1.5 mm"}
    cells, cut = crs_one.row_of(1, raw)
    action = cells[crs_one.TEAM_COLUMNS.index("What the contractor must do")]
    assert (
        cut >= 1
        and action.endswith(crs_one.CUT_MARK)
        and len(action) <= crs_one.CELL_LIMIT
    )
    assert raw["action"].replace("\n", " ") in cells[-1]


def test_a_cut_never_falls_inside_a_number_or_a_clause_number():
    for tail in ("25 mm", "clause 4.2.1 applies", "rated 1.5 mm"):
        text = ("word " * 98)[:495] + tail + " end of the line " * 3
        cell, cut = crs_one._cut(text)
        assert cut
        body = cell[: -len(crs_one.CUT_MARK)].rstrip()
        assert (
            not body[-1].isdigit() or " " in body[-12:]
        )  # never a bare number at the cut


def test_a_short_cell_is_not_cut_and_has_no_full_text():
    cell, cut = crs_one._cut("short text")
    assert (cell, cut) == ("short text", False)


# ------------------------------------------------------------------------------------------------ the contractor file


def test_a_contractor_file_with_no_row_says_why_in_words_with_counts():
    doc, rc, ai, client = world_with_both()
    ws = sheet(crs_one.build_contractor(doc, scope_all()))
    text = "\n".join(
        str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None
    )
    assert (
        "This review has none" in text
        and "4 points" in text
        and "0 row(s) in this copy" in text
    )
    assert "working copy, not issued" in text.lower()


def test_the_contractor_file_holds_a_kept_proven_fail_and_the_engineers_own_words_only():
    doc, rc, ai, client = world_with_both()
    listing = points_of(client, doc)
    proven = next(p for p in listing["points"] if p["rank"] == 1)
    other = next(
        p for p in listing["points"] if p["rank"] != 1 and p["source"] == "ai_review"
    )
    assert decide(client, doc, proven["id"], "keep").status_code == 200
    assert decide(client, doc, other["id"], "keep").status_code == 200
    got = client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Add the tag to the sheet", "page": 1},
    )
    assert got.status_code == 200, got.text
    _h, rows = rows_after(sheet(crs_one.build_contractor(doc, scope_all())), "Item No")
    assert len(rows) == 2 and any("Add the tag to the sheet" in str(r[3]) for r in rows)
    assert not any(
        other["name"] in str(r)
        for r in rows
        if other["rank"] > 1 and other["name"] != proven["name"]
    )


def test_the_issued_file_is_the_same_builder_marked_issued_and_served_byte_for_byte():
    doc, rc, ai, client = world_with_both()
    assert crs_one.issued_file(doc) is None
    rec = crs_one.archive_issued(rc, scope_all(), actor="Engineer A")
    assert rec["filename"] == crs_one.ISSUED_NAME
    record, data = crs_one.issued_file(doc)
    text = "\n".join(
        str(c)
        for r in sheet(data).iter_rows(values_only=True)
        for c in r
        if c is not None
    )
    assert "Issued" in text and "Working copy, not issued" not in text
    got = client.get(f"/api/reviews/papers/{doc}/crs?copy=contractor")
    assert got.status_code == 200 and got.content == data


# ------------------------------------------------------------------------------------------------ route and switch


def test_the_route_serves_both_files_and_is_off_with_the_switch(monkeypatch):
    doc, rc, ai, client = world_with_both()
    for copy in ("team", "contractor"):
        got = client.get(f"/api/reviews/papers/{doc}/crs?copy={copy}")
        assert got.status_code == 200 and got.content[:2] == b"PK"
    assert client.get(f"/api/reviews/papers/{doc}/crs?copy=nope").status_code == 422
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    assert client.get(f"/api/reviews/papers/{doc}/crs?copy=team").status_code == 404


# ------------------------------------------------------------------------------------------------ reader columns


def test_reader_columns_come_from_the_stored_line_and_one_reader_is_said_once():
    doc, rc, ai, client = world_with_both()
    ai_points = [
        p
        for p in review_points_service.export_listing(doc, scope_all())[1]
        if p["source"] == "ai_review"
    ]
    assert ai_points
    firsts = {crs_one.readers_of(p) for p in ai_points}
    assert all(f[0] and f[0] != crs_one.NOT_RECORDED for f in firsts)
    assert any(f[1] == "one reader" for f in firsts)
    rc_point = next(
        p
        for p in review_points_service.export_listing(doc, scope_all())[1]
        if p["source"] == "rule_check"
    )
    assert crs_one.readers_of(rc_point)[0] == "the rule check (code)"


# ------------------------------------------------------------------------------------------------ the stored class wins


def test_the_stored_class_wins_over_the_line_json_label():
    line = {
        "item_id": "R-1",
        "verdict_class": "Proven by code",
        "verdict_label": "Pass",
        "verdict": "Query",
    }
    row = {"verdict_class": "AI opinion, engineer to confirm", "word": "AI thinks: met"}
    got = review_points.stored_class_wins(line, row)
    assert (
        got["verdict_class"] == "AI opinion, engineer to confirm"
        and got["verdict_label"] == "AI thinks: met"
    )
    assert review_points.rank_of_ai_line(got)[0] != 4
    assert (
        review_points.rank_of_ai_line(line)[0] == 4
    )  # without the fix: the old reading, shown as a Question
    assert (
        review_points.stored_class_wins(line, {"verdict_class": None, "word": None})
        == line
    )


def test_a_real_proven_fail_keeps_its_class():
    line = {
        "item_id": "R-1",
        "verdict_class": "Proven by code",
        "verdict_label": "Fail",
        "verdict": "Fail",
    }
    row = {"verdict_class": "Proven by code", "word": "Fail"}
    assert (
        review_points.rank_of_ai_line(review_points.stored_class_wins(line, row))[0]
        == review_points.rank_of_ai_line(line)[0]
    )


# ------------------------------------------------------------------------------------------------ every stored run of a data copy

DATA_COPY = Path(
    os.environ.get(
        "K4_DATA_COPY", str(Path.home() / "project/mirror/proof/order13/K1/k4/data")
    )
)


@pytest.mark.skipif(
    not (DATA_COPY / "rag_intelligence.sqlite").is_file(), reason="no data copy here"
)
def test_every_stored_run_of_the_data_copy_has_equal_counts(monkeypatch, tmp_path):
    """N points on the page == N rows in the team file, for every paper that has a finished run (read only)."""
    monkeypatch.setattr(settings, "data_dir", DATA_COPY)
    monkeypatch.setattr(settings, "upload_dir", DATA_COPY / "uploads")
    monkeypatch.setattr(settings, "db_path", DATA_COPY / "rag_intelligence.sqlite")
    monkeypatch.setattr(settings, "startup_warmup", False)
    db.reset_connection()
    conn = db.connect()
    papers = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT submittal_document_id FROM review_runs WHERE status IN ('completed','done')"
        )
    ]
    scope = scope_all()
    checked = 0
    for doc in papers:
        page, rows, removed, line = equality(doc, scope)
        assert rows + removed == page, doc
        assert line.startswith(
            f"{page} points on the page; {rows + removed} rows in this file"
        )
        checked += 1
    db.reset_connection()
    assert checked == len(papers)


def test_a_kept_not_met_point_of_the_rule_check_is_in_the_contractor_file_like_the_issue_copy():
    doc, rc, ai, client = world_with_both()
    rc_point = next(
        p
        for p in points_of(client, doc)["points"]
        if p["source"] == "rule_check" and p["rank"] in (1, 2, 3)
    )
    assert decide(client, doc, rc_point["id"], "keep").status_code == 200
    _h, rows = rows_after(sheet(crs_one.build_contractor(doc, scope_all())), "Item No")
    assert len(rows) == 1
