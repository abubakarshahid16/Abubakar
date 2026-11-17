"""Owner's decision on PR #1872: the AI's "does not apply" lines without proof are NOT main questions. They are their own short section,
"AI thinks these do not apply, tick to confirm", grouped, each line ticked (one engineer decision, who and when; "Confirm all" is the same
tick on each; a tick can be undone), counted apart on the team file, never on the contractor copy, and still to decide until ticked.
Every check reads the route as served or the file as built. Invented values only."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    access,
    agent_review_not_applicable,
    crs_completeness,
    crs_one,
    review_points_service,
)
from app.main import app
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, points_of
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _submittal,
    temp_db,
)
from tests.test_ftu17_first_time_user import on  # noqa: F401 - the same switches
from tests.test_k4_one_crs import rows_after, scope_all

NA = agent_review_not_applicable


def _na(iid: str, field: str) -> dict:
    return mk(iid, "Query", None, reason_code="not_applicable", field=field)


def _world():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(
        doc,
        [
            _na("R-21", "Field A"),
            _na("R-22", "Field B"),
            mk("R-23", "Query", "Fail", field="Field C"),
        ],
    )
    client = _client(doc, "doc_std")
    ids = [p["id"] for p in points_of(client, doc)["points"] if p["tile"] == NA.TILE]
    assert len(ids) == 2
    return doc, client, ids


def _confirm(client, doc, ids):
    return client.post(
        f"/api/reviews/papers/{doc}/points/not-applicable/confirm",
        json={"point_ids": ids},
    )


def _texts(ws) -> list[str]:
    return [str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None]


def test_the_section_is_counted_apart_and_still_to_decide_until_ticked():
    doc, client, ids = _world()
    listing = points_of(client, doc)
    got = listing["counts"]["not_applicable_to_confirm"]
    assert (got["total"], got["confirmed"], got["open"]) == (2, 0, 2)
    assert (
        listing["counts"]["tiles"]["questions"]["total"] == 0
    )  # never mixed into the main questions
    assert (
        listing["decided"] == 0 and listing["proposed_code"]["undecided"] == 3
    )  # the open count the proposed code reads
    assert all(
        c["member_ids"] and not set(c["member_ids"]) & set(ids)
        for c in listing["comments"]
    )


def test_a_single_tick_confirm_all_and_undo_each_record_one_decision_who_and_when():
    doc, client, ids = _world()
    one = _confirm(client, doc, ids[:1])
    assert one.status_code == 200, one.text
    p = next(x for x in one.json()["points"] if x["id"] == ids[0])
    assert p["decision"]["state"] == "keep" and p["decision"]["words"] == NA.CONFIRMED
    assert p["decision"]["by"] and p["decision"]["at"]
    assert one.json()["counts"]["not_applicable_to_confirm"]["confirmed"] == 1
    every = _confirm(client, doc, ids)  # "Confirm all": the same tick on each
    assert (
        every.status_code == 200
        and every.json()["counts"]["not_applicable_to_confirm"]["open"] == 0
    )
    assert (
        every.json()["decided"] == every.json()["of"] - 1
    )  # only the AI "not met" is left
    back = client.post(
        f"/api/reviews/papers/{doc}/points/not-applicable/undo",
        json={"point_id": ids[0]},
    )
    assert back.status_code == 200, back.text
    p = next(x for x in back.json()["points"] if x["id"] == ids[0])
    assert p["decision"]["state"] is None
    left = back.json()["counts"]["not_applicable_to_confirm"]
    assert (left["confirmed"], left["open"]) == (1, 1) and back.json()["proposed_code"][
        "undecided"
    ] == 2
    nothing = client.post(
        f"/api/reviews/papers/{doc}/points/not-applicable/undo",
        json={"point_id": ids[0]},
    )
    assert nothing.status_code == 422  # nothing left to undo


def test_the_routes_need_an_identified_engineer_and_only_take_the_sections_lines():
    doc, client, ids = _world()
    other = next(
        p["id"] for p in points_of(client, doc)["points"] if p["tile"] != NA.TILE
    )
    assert _confirm(client, doc, [ids[0], other]).status_code == 422  # all-or-nothing
    assert (
        points_of(client, doc)["counts"]["not_applicable_to_confirm"]["confirmed"] == 0
    )
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({doc})
    )
    anon = TestClient(app)
    assert _confirm(anon, doc, ids).status_code in (401, 403)
    assert anon.post(
        f"/api/reviews/papers/{doc}/points/not-applicable/undo",
        json={"point_id": ids[0]},
    ).status_code in (401, 403)


def test_the_team_file_lists_them_on_their_own_sheet_counted_apart_and_the_contractor_never_sees_them():
    doc, client, ids = _world()
    _confirm(client, doc, ids[:1])
    team = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    )
    head, rows = rows_after(team[crs_one.NA_SHEET], "No on the sheet Evidence")
    assert len(rows) == 2
    confirmed = [r[head.index("Confirmed")] for r in rows]
    assert (
        sum(str(c).startswith(NA.CONFIRMED) for c in confirmed) == 1
        and NA.OPEN in confirmed
    )
    said = NA.count_line(2, 1)[:-1]
    assert any(said in t for t in _texts(team[crs_one.TEAM_SHEET]))
    assert any(NA.TITLE in t for t in _texts(team[crs_one.NA_SHEET]))
    _h, comment_rows = rows_after(team[crs_one.TEAM_SHEET], "Comment")
    assert not [
        r
        for r in comment_rows
        if r and any(f in str(c) for c in r for f in ("Field A", "Field B"))
    ]
    contractor = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "contractor"))
    )
    text = " ".join(_texts(contractor["CRS"]))
    assert "Field A" not in text and "Field B" not in text and "AI thinks" not in text
    assert (
        "1 does not apply" in text
    )  # the confirmed line is accounted in the contractor's count line, in its words


def test_the_completeness_check_counts_the_section():
    doc, client, _ids = _world()
    got = client.get(f"/api/reviews/papers/{doc}/crs/check").json()
    assert (
        got["team"]["ok"] is True
        and got["team"]["page"] == got["team"]["rows_in_file"] == 3
    )
    wb = load_workbook(io.BytesIO(crs_one.build_team(doc, scope_all())))
    ws = wb[crs_one.NA_SHEET]
    head_row = next(
        i
        for i, r in enumerate(ws.iter_rows(values_only=True), start=1)
        if r and r[0] == "No on the sheet Evidence"
    )
    ws.delete_rows(head_row + 1)  # one line of the section lost from its sheet
    buf = io.BytesIO()
    wb.save(buf)
    _listing, raw, _facts = review_points_service.export_listing(doc, scope_all())
    missing = crs_completeness._comment_accounting(buf.getvalue(), raw)
    assert any(crs_one.NA_SHEET in m for m in missing), missing
