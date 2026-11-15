"""U5 on the ONE team CRS: a Priority column, the AI's labelled reasoning, worst first, and no AI wording in the contractor file.
Invented data only."""

from __future__ import annotations

from app import crs_one, review_points
from tests.test_b1_review_points import decide, points_of, world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import on, rows_after, scope_all, sheet  # noqa: F401 - fixtures and helpers

AI_WORDS = ("reasoning", "AI reviewer", "AI opinion", "AI thinks", "AI verdict", "not proven", "Question", "Query")


def team(doc):
    data = crs_one.build_team(doc, scope_all())
    head, rows = rows_after(sheet(data), "Comment")
    ev_head, ev_rows = rows_after(sheet(data, crs_one.EVIDENCE_SHEET), "No")
    return head, rows, ev_head, ev_rows


def test_the_columns_are_in_the_order_the_owner_reads_them():
    assert crs_one.COMMENT_COLUMNS[2:4] == ("Class", "Priority")
    assert crs_one.TEAM_COLUMNS[4:6] == ("Class", "Priority")
    for cols in (crs_one.COMMENT_COLUMNS, crs_one.TEAM_COLUMNS):
        assert cols[cols.index("What the paper shows") + 1] == crs_one.REASONING_COLUMN


def test_every_point_carries_a_priority_and_a_labelled_reasoning_only_when_the_ai_gave_one():
    doc, rc, ai, client = world_with_both()
    head, rows, ev_head, ev_rows = team(doc)
    prio, reasoning = ev_head.index("Priority"), ev_head.index(crs_one.REASONING_COLUMN)
    klass = ev_head.index("Class")
    seen_fail = seen_ai = False
    for r in ev_rows:
        if r[ev_head.index("Pill")] and "proven by code" in str(r[ev_head.index("Pill")]) and r[klass] == "Not met":
            seen_fail = True
            assert r[prio] == "High" and not r[reasoning]  # a proven Fail: High, and no AI wording at all
        if r[ev_head.index("Source")] == "AI review" and r[klass] == "Questions for you":
            seen_ai = True
            assert str(r[reasoning]).startswith("The AI reviewer's reasoning (not proven by code):")
            assert r[prio] in ("High", "Medium", "Low", None)
    assert seen_fail and seen_ai
    assert all(len(str(r[reasoning] or "")) < crs_one.CELL_LIMIT for r in ev_rows)  # never cut, so no mark is needed


def test_a_comments_priority_is_the_highest_of_its_points():
    assert crs_one.highest_priority([{"priority": "Low"}, {"priority": "High"}, {"priority": ""}, {"priority": "Medium"}]) == "High"
    assert crs_one.highest_priority([{"priority": "Low"}, {"priority": "Medium"}]) == "Medium"
    assert crs_one.highest_priority([{"priority": ""}, {}]) == ""


def test_comments_are_worst_first_then_by_priority():
    doc, rc, ai, client = world_with_both()
    head, rows, _h, _r = team(doc)
    pill = head.index("Pill")
    ranks = [next((i for i, (what, _f) in review_points.RANKS.items() if str(r[pill]).startswith(what)), 9) for r in rows]
    assert ranks == sorted(ranks) or all(a <= b for a, b in zip(ranks, ranks[1:], strict=False))
    pts = [{"rank": 4, "priority": "Low", "id": "a"}, {"rank": 4, "priority": "High", "id": "b"}, {"rank": 1, "priority": "", "id": "c"}, {"rank": 4, "priority": "", "id": "d"}]
    assert [p["id"] for p in review_points.order_points(pts)] == ["c", "b", "a", "d"]


def test_the_contractor_file_has_no_ai_wording_in_any_cell():
    doc, rc, ai, client = world_with_both()
    for p in points_of(client, doc)["points"]:
        assert decide(client, doc, p["id"], "keep").status_code == 200
    ws = sheet(crs_one.build_contractor(doc, scope_all()))
    text = "\n".join(str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None)
    assert text and not any(w in text for w in AI_WORDS), [w for w in AI_WORDS if w in text]
    for sh in sheet_names(crs_one.build_contractor(doc, scope_all())):
        assert not any(w in sh for w in ("reasoning",))


def sheet_names(data: bytes):
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(data))
    for ws in wb.worksheets:
        yield "\n".join(str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None)


def test_a_comment_sits_by_its_strongest_point_not_by_its_first_and_numbers_follow():
    from app import crs_comments

    def pt(i, name, rank, priority=""):
        return {"id": i, "rank": rank, "tile": review_points.TILE_OF_RANK[rank], "name": name, "tags": [], "page": 1,
                "decision": {}, "priority": priority, "pill": "x", "firm": None}  # fmt: skip

    got = crs_comments.group([pt("1", "B", 4, "Low"), pt("2", "A", 4), pt("3", "A", 3), pt("4", "C", 4, "High")])
    assert [c["name"] for c in got] == ["A", "C", "B"]  # A holds a rank 3 point; then the questions, High before Low
    assert [c["number"] for c in got] == [1, 2, 3]
    assert [c["member_ids"] for c in got] == [["2", "3"], ["4"], ["1"]]


def test_the_completeness_cut_check_covers_the_reasoning_column():
    from app import crs_completeness, review_points_service

    doc, rc, ai, client = world_with_both()
    raw = review_points_service.export_listing(doc, scope_all())[1]
    data = crs_one.build_team(doc, scope_all())
    assert crs_completeness.cut_report(data, raw)["problems"] == []
    # a reasoning cell shortened WITHOUT its text elsewhere is a problem: change the stored full text under the file
    changed = [{**p, "ai_reasoning": (p.get("ai_reasoning") or "") + (" 480 characters of reasoning." * 17 if p.get("ai_reasoning") else "")} for p in raw]
    assert any(p.get("ai_reasoning") for p in raw)
    problems = crs_completeness.cut_report(data, changed)["problems"]
    assert any("reasoning is shortened or changed" in x for x in problems)
