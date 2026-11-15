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
    _head, crs_rows = rows_after(sheet(data, crs_one.EVIDENCE_SHEET), "No")
    _h2, removed = rows_after(sheet(data, crs_one.REMOVED_SHEET), "No")
    return page["of"], len(crs_rows), len(removed), count_line_of(ws)


# ------------------------------------------------------------------------------------------------ one file, every point


def test_the_team_file_holds_every_point_the_page_counts_and_says_so():
    doc, rc, ai, client = world_with_both()
    page, rows, removed, line = equality(doc, scope_all())
    assert page == 4 and rows == page
    assert line.startswith(f"{page} points on the page; {rows} rows in this file")


def test_a_removed_point_is_counted_once_and_sits_on_its_own_sheet_with_who_and_why():
    doc, rc, ai, client = world_with_both()
    first = points_of(client, doc)["points"][-1]
    assert (
        decide(client, doc, first["id"], "remove", reason="Not our scope").status_code
        == 200
    )
    page, rows, removed, _ = equality(doc, scope_all())
    assert (page, removed) == (4, 1) and rows == 4
    _h, rem = rows_after(
        sheet(crs_one.build_team(doc, scope_all()), crs_one.REMOVED_SHEET), "No"
    )
    assert "Not our scope" in rem[0]


def test_the_file_is_worst_first_like_the_page():
    doc, rc, ai, client = world_with_both()
    page = points_of(client, doc)["points"]
    _h, rows = rows_after(
        sheet(crs_one.build_team(doc, scope_all()), crs_one.EVIDENCE_SHEET), "No"
    )
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1))
    assert [r[3] for r in rows] == [p["pill"] for p in page]


def test_the_team_file_has_all_the_sheets():
    doc, rc, ai, client = world_with_both()
    from openpyxl import load_workbook as lw

    names = lw(io.BytesIO(crs_one.build_team(doc, scope_all()))).sheetnames
    assert names == [
        "CRS", "Evidence", "Removed (record)", "Does not apply", "Rule books not held", "What was not checked", "How it was reviewed",
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
    assert cut >= 1 and action.endswith("…") and len(action) <= crs_one.CELL_LIMIT
    assert raw["action"].replace("\n", " ") in cells[-1]


def test_a_cut_never_falls_inside_a_number_or_a_clause_number():
    for tail in ("25 mm", "clause 4.2.1 applies", "rated 1.5 mm"):
        text = ("word " * 98)[:495] + tail + " end of the line " * 3
        cell, cut = crs_one._cut(text)
        assert cut
        assert cell.endswith("…") and crs_one.CUT_MARK == "…"
        body = cell[:-1].rstrip()
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
    assert len(rows) >= 1 and any("Add the tag to the sheet" in str(r[3]) for r in rows)
    assert not any(
        other["name"] in str(r)
        for r in rows
        if other["rank"] > 1 and other["name"] != proven["name"]
    )


def test_the_issued_file_is_the_same_builder_marked_issued_and_served_byte_for_byte():
    doc, rc, ai, client = world_with_both()
    assert crs_one.issued_file(doc) is None
    _data, _name, rec = crs_one.issue(rc, scope_all(), actor="Engineer A")
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
        assert rows == page, doc
        assert line.startswith(f"{page} points on the page; {rows} rows in this file")
        from app import crs_completeness as cc

        got = cc.checked_files(
            doc, scope
        )  # three counts agree, and no cell ends cut without the mark and its full text
        assert got["team"][1]["ok"] and got["contractor"][1]["ok"], (
            doc,
            got["team"][1]["sentence"],
            got["contractor"][1]["sentence"],
        )
        assert got["team"][1]["cut_problems"] == 0
        checked += 1
    db.reset_connection()
    assert checked == len(papers)


def _pt(
    rank,
    source="rule_check",
    state=None,
    text=None,
    action="The nameplate shall be steel.",
    **kw,
):
    d = {"state": state, "text": text} if state else None
    return {
        "id": f"p{rank}{source}{state}",
        "rank": rank,
        "source": source,
        "decision": d,
        "action": action,
        "page": 2,
        **kw,
    }


from app.crs_export_quality import NOTE_PARKED as PLACEHOLDER  # noqa: E402


def test_a_kept_rule_check_ai_opinion_is_withheld_and_counted_never_issued():
    """Clause (d) of the first build admitted these: a rank 3 and a rank 2 row kept with one click. Revert it and this fails."""
    rows = [
        _pt(3, state="keep", action=PLACEHOLDER),
        _pt(2, state="keep", action="The AI reviewers agree it is not met."),
        _pt(3, state="keep"),
        _pt(1, state="keep"),
    ]
    kept, withheld = crs_one.contractor_points(rows)
    assert [p["rank"] for p in kept] == [1] and withheld == 3
    assert crs_one.status_of(kept[0]) == "Fail"


def test_status_is_fail_only_for_a_proven_failure_else_the_engineers_decision_word_never_from_the_ai_rank():
    assert crs_one.status_of(_pt(1, state="keep")) == "Fail"
    for rank in (2, 3, 4):
        edited = _pt(rank, state="edit", text="Fix the nameplate material.")
        assert crs_one.status_of(edited) == "Edited"
        assert crs_one.status_of(_pt(rank, source="added")) == "Added"
        assert crs_one.status_of(_pt(rank, state="keep")) == "Kept"
        assert crs_one.status_of(_pt(rank)) == ""
        kept, _w = crs_one.contractor_points([edited])
        assert kept == [
            edited
        ]  # the engineer's own words are issued whatever the AI rank


def test_the_stored_placeholder_is_withheld_but_the_engineers_own_words_are_issued_whatever_words_they_use():
    kept, withheld = crs_one.contractor_points([_pt(3, state="edit", text=PLACEHOLDER)])
    assert kept == [] and withheld == 1
    for words in (
        "Contractor to confirm the set pressure of the relief valve.",
        "Awaiting vendor data: contractor to supply the seat leakage class.",
        "AI-generated drawings are not accepted; resubmit.",
        "Reconfirm the nameplate material.",
    ):
        edited = _pt(3, state="edit", text=words)
        assert crs_one.issuable_text(edited) == words
        assert crs_one.contractor_points([edited])[0] == [edited]
        added = _pt(4, source="added", action=words)
        assert crs_one.issuable_text(added) == words
    proven = _pt(1, state="keep", action="Contractor to confirm the rating.")
    assert crs_one.issuable_text(proven) == "Contractor to confirm the rating."
    assert crs_one.issuable_text(_pt(1, state="keep", action=PLACEHOLDER)) == ""


def test_the_withheld_reason_on_the_first_sheet_is_true_for_engineer_text_with_those_words():
    from app import crs_completeness as cc

    rows = [
        _pt(3, state="edit", text="Contractor to confirm the set pressure."),
        _pt(3, state="edit", text=PLACEHOLDER),
    ]
    mine, reasons = cc.contractor_split(rows)
    assert len(mine) == 1 and reasons == {cc.REASON_NO_WORDING: 1}


def test_no_cell_of_the_contractor_file_holds_ai_awaiting_or_confirm_text_even_with_every_point_kept():
    import re

    doc, rc, ai, client = world_with_both()
    for p in points_of(client, doc)["points"]:
        assert decide(client, doc, p["id"], "keep").status_code == 200
    data = crs_one.build_contractor(doc, scope_all())
    cells = [
        str(c)
        for r in sheet(data).iter_rows(values_only=True)
        for c in r
        if c is not None
    ]
    assert not [
        c for c in cells if re.search(r"\bAI\b|awaiting|confirm", c, re.IGNORECASE)
    ]
    _h, rows = rows_after(sheet(data), "Item No")
    assert all(r[6] in (None, "Fail", "Kept", "Edited", "Added") for r in rows)
    assert any(re.search(r"not issued: .*no engineer wording", c) for c in cells)


def test_the_sign_reply_the_archive_and_the_page_button_are_the_same_bytes():
    doc, rc, ai, client = world_with_both()
    data, name, record = crs_one.issue(rc, scope_all(), actor="Engineer A")
    assert name == crs_one.ISSUED_NAME and record["filename"] == name
    _rec, archived = crs_one.issued_file(doc)
    assert archived == data
    assert client.get(f"/api/reviews/papers/{doc}/crs?copy=contractor").content == data


def test_a_failed_archive_leaves_nothing_half_issued(monkeypatch):
    from app import crs_issue

    doc, rc, ai, client = world_with_both()

    def boom(*a, **k):
        raise crs_issue.IssueError("disk full")

    monkeypatch.setattr(crs_issue, "archive", boom)
    with pytest.raises(crs_issue.IssueError):
        crs_one.issue(rc, scope_all(), actor="Engineer A")
    monkeypatch.undo()
    assert crs_issue.issued(rc) == [] and crs_one.issued_file(doc) is None
    monkeypatch.setattr(crs_one, "build_contractor", boom)
    with pytest.raises(crs_issue.IssueError):
        crs_one.issue(rc, scope_all(), actor="Engineer A")
    assert crs_issue.issued(rc) == []


def test_the_engine_of_a_run_with_no_model_name_is_not_recorded():
    doc, rc, ai, client = world_with_both()
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET model_name = NULL WHERE id = ?", (rc,))
    _l, _raw, extra = review_points_service.export_listing(doc, scope_all())
    rule = next(r for r in crs_one._run_facts(extra) if r["what"] == "Rule check")
    assert rule["engine"] == crs_one.NOT_RECORDED


# ------------------------------------------------------------------------------------------------ completeness is a hard rule


def test_the_first_sheet_states_the_counts_from_the_one_function():
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    team = sheet(crs_one.build_team(doc, scope_all()))
    c = review_points_service.assemble(doc, scope_all())["comment_count"]
    assert cc.team_statement(4, c) in [r[0] for r in team.iter_rows(values_only=True)]
    con = sheet(crs_one.build_contractor(doc, scope_all()))
    first = [r[0] for r in con.iter_rows(values_only=True) if r[0]]
    assert any(
        c.startswith("4 points reviewed, 0 in this file, 4 not issued: ") for c in first
    )


def test_the_contractor_split_adds_up_to_the_points_with_each_reason():
    from app import crs_completeness as cc

    rows = [
        _pt(1, state="keep"),
        _pt(3, state="keep"),
        _pt(3, state="remove"),
        _pt(2),
        _pt(4, state="edit", text="Fix it."),
    ]
    mine, reasons = cc.contractor_split(rows)
    assert len(mine) + sum(reasons.values()) == len(rows) == 5
    assert reasons == {
        cc.REASON_NO_WORDING: 1,
        cc.REASON_REMOVED: 1,
        cc.REASON_NOT_PROVEN: 1,
    }


def test_all_three_counts_agree_and_the_check_is_stored_with_the_run():
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    got = cc.checked_files(doc, scope_all())
    for copy in ("team", "contractor"):
        assert got[copy][1]["ok"], got[copy][1]["sentence"]
    stored = cc.record_after_run(ai)
    assert stored and stored["team"]["ok"]
    row = (
        db.connect()
        .execute(
            "SELECT ok, page, database_lines FROM crs_completeness WHERE run_id = ?",
            (ai,),
        )
        .fetchone()
    )
    assert (row["ok"], row["page"], row["database_lines"]) == (1, 4, 4)


def test_one_row_dropped_from_the_file_refuses_the_download_and_names_it(monkeypatch):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    real = crs_one.build_team

    def short(paper, scope, *, listing_raw=None, **kw):
        listing, raw, facts = listing_raw
        return real(paper, scope, listing_raw=(listing, raw[:-1], facts), **kw)

    monkeypatch.setattr(crs_one, "build_team", short)
    with pytest.raises(cc.Incomplete) as e:
        cc.file_or_refuse(doc, scope_all(), "team")
    assert (
        "not complete" in str(e.value)
        and "Missing:" in str(e.value)
        and e.value.report["page"] == 4
    )
    got = client.get(f"/api/reviews/papers/{doc}/crs?copy=team")
    assert got.status_code == 409 and "not complete" in got.text


def test_one_line_missing_from_the_page_but_in_the_database_refuses_the_download(
    monkeypatch,
):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    real = review_points.ai_point
    monkeypatch.setattr(
        review_points,
        "ai_point",
        lambda ln, ctx: None if ln.get("item_id") == "R-3" else real(ln, ctx),
    )
    with pytest.raises(cc.Incomplete) as e:
        cc.file_or_refuse(doc, scope_all(), "team")
    assert "stored but not on the page" in str(e.value)


def test_a_contractor_file_that_loses_a_row_is_refused(monkeypatch):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    for p in points_of(client, doc)["points"]:
        if p["rank"] == 1:
            decide(client, doc, p["id"], "keep")
    real = crs_one.build_contractor

    def short(paper, scope, *, listing_raw=None, **kw):
        listing, raw, facts = listing_raw
        return real(
            paper,
            scope,
            listing_raw=(listing, [p for p in raw if p["rank"] != 1], facts),
            **kw,
        )

    monkeypatch.setattr(crs_one, "build_contractor", short)
    with pytest.raises(cc.Incomplete):
        cc.file_or_refuse(doc, scope_all(), "contractor")


def test_a_removed_cut_mark_is_found_and_the_file_is_refused(monkeypatch):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    point = points_of(client, doc)["points"][0]
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/add",
            json={"text": "word " * 200, "page": 1},
        ).status_code
        == 200
    )
    ok = cc.checked_files(doc, scope_all())["team"][1]
    assert ok["ok"] and ok["cut_cells_marked"] >= 1 and point
    monkeypatch.setattr(crs_one, "CUT_MARK", "")
    with pytest.raises(cc.Incomplete) as e:
        cc.file_or_refuse(doc, scope_all(), "team")
    assert "cut" in str(e.value)


def test_the_count_check_script_agrees_and_exits_one_on_a_difference(
    monkeypatch, capsys
):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crs_count_check",
        Path(__file__).resolve().parents[2] / "scripts" / "crs_count_check.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    doc, rc, ai, client = world_with_both()
    assert script.main([ai]) == 0
    assert "points on the page      4" in capsys.readouterr().out
    real = crs_one.build_team

    def short(paper, scope, *, listing_raw=None, **kw):
        listing, raw, facts = listing_raw
        return real(paper, scope, listing_raw=(listing, raw[:-1], facts), **kw)

    monkeypatch.setattr(crs_one, "build_team", short)
    assert script.main([ai]) == 1
    assert "DIFFERENT" in capsys.readouterr().out
    assert script.main(["no-such-run"]) == 2


# ------------------------------------------------------------------------------------------------ P2: one comment per field


def _fp(i, rank, name="Design pressure", clause="4.1", page=1, state=None, **kw):
    tile = review_points.TILE_OF_RANK[rank]
    return {
        "id": f"ai:r:{i}", "rank": rank, "tile": tile, "name": name, "clause": clause, "page": page, "rule_book": "STD-1",
        "tags": [], "source": "ai_review", "decision": {"state": state} if state else {"state": None}, "pill": f"pill{rank}",
        "firm": "one reader", "action": "x", **kw,
    }  # fmt: skip


def test_points_of_one_field_make_one_comment_listing_every_clause_and_page():
    from app import crs_comments

    pts = [
        _fp(1, 3, clause="4.1", page=1),
        _fp(2, 3, clause="4.2", page=2),
        _fp(3, 3, clause="4.1", page=3),
        _fp(4, 4, name="Other"),
    ]
    got = crs_comments.group(pts)
    assert [c["n_points"] for c in got] == [3, 1]
    assert got[0]["pages"] == [1, 2, 3] and {
        (k["clause"], k["page"]) for k in got[0]["clauses"]
    } >= {("4.1", 1), ("4.2", 2), ("4.1", 3)}
    assert sorted(i for c in got for i in c["member_ids"]) == sorted(
        p["id"] for p in pts
    )  # nothing is dropped


def test_the_strongest_status_wins_and_a_weaker_one_never_does():
    from app import crs_comments

    c = crs_comments.group([_fp(1, 4), _fp(2, 3), _fp(3, 4)])[0]
    assert c["rank"] == 3 and c["pill"] == "pill3"
    c = crs_comments.group([_fp(1, 5), _fp(2, 4)])[0]
    assert c["rank"] == 4  # a Query is stronger than a Met
    c = crs_comments.group([_fp(1, 7), _fp(2, 7)])[0]
    assert c["rank"] == 7  # merging never raises a class
    c = crs_comments.group([_fp(1, 1), _fp(2, 3)])[0]
    assert c["rank"] == 1 and c["pill"] == "pill1"  # a proven Fail keeps its own class


def test_a_contradiction_is_never_merged_silently():
    from app import crs_comments

    c = crs_comments.group([_fp(1, 5), _fp(2, 3)])[0]
    assert (
        c["disagree"]
        and c["rank"] == 4
        and "disagree" in c["pill"]
        and c["n_points"] == 2
    )
    assert not crs_comments.group([_fp(1, 5), _fp(2, 6)])[0]["disagree"]


def test_a_point_with_no_field_groups_by_clause_else_stands_alone():
    from app import crs_comments

    a = _fp(1, 4, name=None, clause="9.9")
    b = _fp(2, 4, name=None, clause="9.9")
    c = _fp(3, 4, name=None, clause=None, rule_book=None)
    d = _fp(4, 4, name=None, clause=None, rule_book=None)
    assert [x["n_points"] for x in crs_comments.group([a, b, c, d])] == [2, 1, 1]


def test_the_page_and_the_file_show_the_same_comments_and_every_point_stays_on_evidence():
    doc, rc, ai, client = world_with_both()
    page = points_of(client, doc)
    data = crs_one.build_team(doc, scope_all())
    _h, rows = rows_after(sheet(data), "Comment")
    assert [(r[0], r[4]) for r in rows] == [
        (c["number"], c["n_points"]) for c in page["comments"]
    ]
    assert page["comment_count"] == len(rows)
    _h, evidence = rows_after(sheet(data, crs_one.EVIDENCE_SHEET), "No")
    assert len(evidence) == page["of"] and {r[1] for r in evidence} <= {
        c["number"] for c in page["comments"]
    } | {"removed"}


def test_a_comment_that_loses_a_point_from_its_count_is_refused(monkeypatch):
    from app import crs_comments, crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    real = crs_comments.group

    def lossy(points):
        out = real(points)
        out[0] = {**out[0], "n_points": out[0]["n_points"] + 1}
        return out

    import types

    # the builder's own grouping drifts (a point's count lost); the check reads the grouping function itself
    monkeypatch.setattr(
        crs_one,
        "comments",
        types.SimpleNamespace(group=lossy, DISAGREE=crs_comments.DISAGREE),
    )
    with pytest.raises(cc.Incomplete) as e:
        cc.file_or_refuse(doc, scope_all(), "team")
    assert "do not add up" in str(e.value)


# ------------------------------------------------------------------------------------------------ R61


def test_a_name_that_is_not_a_field_never_makes_a_comment():
    from app import crs_comments

    assert not any(
        crs_comments.is_field(n)
        for n in (
            "",
            "  ",
            "p.22",
            "P. 8",
            "page 3",
            PLACEHOLDER,
            "Section 4 Scope",
            "3.2 Materials",
        )
    )
    assert all(
        crs_comments.is_field(n)
        for n in ("Design pressure", "Gas (H2 and CO2 content)", "2 inch nozzle")
    )
    pts = [
        _fp(i, 3, name=n, clause=f"{i}.1", rule_book=f"B{i}")
        for i, n in enumerate(["p.22", "p.22", PLACEHOLDER, PLACEHOLDER, "", ""], 1)
    ]
    got = crs_comments.group(pts)
    assert [c["n_points"] for c in got] == [
        1
    ] * 6  # different clauses of different books never merge on a non-field


def test_no_comment_merges_points_of_different_clauses_unless_they_share_a_real_field():
    from app import crs_comments

    pts = [
        _fp(1, 3, name="p.5", clause="1.1"),
        _fp(2, 3, name="p.5", clause="2.2"),
        _fp(3, 3, name="Real field", clause="1.1"),
        _fp(4, 3, name="Real field", clause="2.2"),
    ]
    for c in crs_comments.group(pts):
        members = [p for p in pts if p["id"] in c["member_ids"]]
        if len({p["clause"] for p in members}) > 1:
            assert (
                crs_comments.is_field(members[0]["name"])
                and len({p["name"] for p in members}) == 1
            )
    assert [c["n_points"] for c in crs_comments.group(pts)] == [1, 1, 2]
    same_clause = crs_comments.group(
        [_fp(1, 4, name="", clause="7.7"), _fp(2, 4, name="", clause="7.7")]
    )
    assert [c["n_points"] for c in same_clause] == [2]


def test_the_field_is_what_review_points_split_tags_says(monkeypatch):
    from app import crs_comments

    seen = []

    def stub(name):
        seen.append(name)
        return {
            "Fluid (A (x, y) & B (z))": "Fluid",
            "Gas (H2 and CO2 content)": "Gas (H2 and CO2 content)",
        }.get(name, name), []

    monkeypatch.setattr(review_points, "split_tags", stub)
    pts = [
        _fp(1, 3, name="Fluid (A (x, y) & B (z))"),
        _fp(2, 3, name="Fluid"),
        _fp(3, 3, name="Gas (H2 and CO2 content)"),
        _fp(4, 3, name="Gas"),
    ]
    got = crs_comments.group(pts)
    assert (
        [c["n_points"] for c in got] == [2, 1, 1]
    )  # the nested-tag name is the field "Fluid"; a bracket that is part of the name stays whole
    assert "Fluid (A (x, y) & B (z))" in seen


def test_the_page_says_when_the_three_counts_differ_and_names_the_missing_point(
    monkeypatch,
):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    assert cc.record_after_run(ai)["team"]["ok"]
    assert points_of(client, doc)["completeness"]["ok"] is True
    real = review_points.build
    monkeypatch.setattr(review_points, "build", lambda a, r, d: real(a, r, d)[:-1])
    got = cc.record_after_run(ai)
    assert not got["team"]["ok"]
    page = points_of(client, doc)["completeness"]
    assert page["ok"] is False and page["page"] == 3 and page["database"] == 4
    assert page["missing"] and all(
        "stored but not on the page" in m for m in page["missing"][:1]
    )


def test_a_point_on_the_page_that_is_not_in_the_database_is_named(monkeypatch):
    from app import crs_completeness as cc

    doc, rc, ai, client = world_with_both()
    real = cc.database_lines

    def short(paper, scope, facts):
        out = real(paper, scope, facts)
        gone = next(i for i in out["ids"] if i.startswith("ai:"))
        out["ids"].pop(gone)
        out["total"] -= 1
        return out

    monkeypatch.setattr(cc, "database_lines", short)
    with pytest.raises(cc.Incomplete) as e:
        cc.file_or_refuse(doc, scope_all(), "team")
    assert "is on the page but not in the database" in str(e.value)
