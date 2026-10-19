"""Order 139 part 2, spec b: ONE SOURCE for the screen and the file.

`GET /api/reviews/runs/{id}/summary` sends, per finding, the CRS row it lands
on (`crs_group`), that row's place in the sheet's order (`crs_order`) and its
action line (`crs_action`), computed by the same grouping the CRS file uses
(`crs_mapping.crs_groups`, through `build_crs_rows`). The screen groups and
orders by these and never by a rule of its own. Proven end to end on a seeded
run: the summary's partition of finding ids by `crs_group` is exactly the
internal CRS rows' `finding_ids`, in the file's order.

Synthetic sheet only (invented fields and clauses).
"""
from __future__ import annotations

from collections import defaultdict

from fastapi.testclient import TestClient

from app import access, crs_mapping, main
from app.api import run_summary
from app.main import app
from tests.test_139_crs_numbers_merge import FIELD, _add_blanks
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401


def _summary(run) -> dict:
    response = TestClient(app).get(f"/api/reviews/runs/{run}/summary")
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_sends_group_order_action(world):  # noqa: F811
    _sub, run, _scope = world
    ids = _add_blanks(run, ("4.1", "6.2", "7.7"))
    body = _summary(run)
    assert body["crs_grouping"] is True
    rows = {r["finding_id"]: r for r in body["rows"]}
    groups = {rows[i]["crs_group"] for i in ids}
    assert len(groups) == 1 and next(iter(groups)).startswith("field:")
    assert {rows[i]["crs_action"] for i in ids} == {f"Contractor to provide {FIELD}."}
    assert len({rows[i]["crs_order"] for i in ids}) == 1
    # The breach (the world's one comment) is a row of its own, first.
    [breach] = [r for r in body["rows"] if r["finding_id"] not in ids]
    assert breach["crs_group"].startswith("req:") and breach["crs_action"] is None
    assert breach["crs_order"] == 0 and rows[ids[0]]["crs_order"] == 1


def test_summary_groups_equal_the_files_rows(world):  # noqa: F811
    _sub, run, scope = world
    _add_blanks(run, ("4.1", "6.2"))
    _add_blanks(run, ("9.9", "2.4"), field="Set pressure")
    body = _summary(run)
    by_group: dict[str, set[str]] = defaultdict(set)
    order: dict[str, int] = {}
    for r in body["rows"]:
        if r["crs_group"]:
            by_group[r["crs_group"]].add(r["finding_id"])
            order[r["crs_group"]] = r["crs_order"]
    summary_rows = [by_group[g] for g in sorted(by_group, key=order.__getitem__)]
    file_rows, *_ = main._crs_content(
        run, access.AccessScope(user_id=None, allowed_document_ids=scope))
    finding_rows = [set(r["finding_ids"]) for r in file_rows if r.get("finding_ids")]
    assert summary_rows == finding_rows and len(finding_rows) == 3
    assert sorted(order.values()) == list(range(len(finding_rows)))


def test_counts_route_sends_no_groups(world, monkeypatch):  # noqa: F811
    """`/counts` (up to 200 runs) never pays for the grouping."""
    _sub, run, _scope = world

    def refuse(*_a, **_k):
        raise AssertionError("the counts route computed the CRS grouping")

    monkeypatch.setattr(run_summary, "crs_fields", refuse)
    response = TestClient(app).get(f"/api/reviews/runs/counts?ids={run}")
    assert response.status_code == 200, response.text
    assert run in response.json()["counts"]
    assert all(r.get("crs_group") is None for r in run_summary._tiers(run, None)[0]["rows"])


def test_summary_without_grouping_says_so(world, monkeypatch):  # noqa: F811
    """If the grouping cannot be computed the tiers still answer, and the
    summary says `crs_grouping: false` - the screen then shows one row per
    finding and says so, never a grouping of its own."""
    _sub, run, _scope = world

    def broken(*_a, **_k):
        raise RuntimeError("grouping broke")

    monkeypatch.setattr(crs_mapping, "build_crs_rows", broken)
    body = _summary(run)
    assert body["crs_grouping"] is False
    assert body["rows"] and all(r["crs_group"] is None for r in body["rows"])


def test_a_question_the_file_puts_in_its_review_notes_is_sent_as_a_note(world):  # noqa: F811
    """Covers #1177's screen gap: a standard's engineer-to-check finding the
    file lists in its Review notes (here an unread page) is `crs_note`, so the
    screen shows it as a note and never as a comment row to decide."""
    from app import db
    _sub, run, _scope = world
    [question] = _add_blanks(run, ("8.8",), field="Set pressure")
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET compliance_status = 'NEEDS_ENGINEER_REVIEW',"
                     " reason_code = 'UNREAD_PAGES', ai_rationale = 'UNREAD_PAGES: page 2' WHERE id = ?",
                     (question,))
    rows = {r["finding_id"]: r for r in _summary(run)["rows"]}
    assert rows[question]["crs_note"] is True and rows[question]["crs_group"] is None
    assert all(r["crs_note"] is None for fid, r in rows.items() if fid != question)
