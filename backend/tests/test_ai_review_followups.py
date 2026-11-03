"""Lane 6, part 3 follow-ups: the CRS top note, the sheet's evidence, honest states, the restore route, and the open-items
gate still seeing AI-removed rows. Invented rows and pages only."""

from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import access, crs_export
from app import ai_review_pass as arpass
from app import crs_ai_review_view as view
from app.config import settings
from app.main import _crs_content, _crs_issue_gate, app, number_crs_rows
from tests.test_ai_review_pass import FAIL, HELD, PAGES, REMOVE, ROW, Stub
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in
from tests.test_review_screen import world as _world  # noqa: F401


@pytest.fixture
def stored(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(
        "rv9",
        [dict(ROW), dict(FAIL)],
        pages=PAGES,
        held=HELD,
        provider=Stub([REMOVE]),
    )
    return "rv9"


def _rows():
    return [dict(ROW, priority=3), dict(FAIL, priority=1)]


def _sheet_text(wb, name):
    return "\n".join(
        str(c.value) for row in wb[name].iter_rows() for c in row if c.value
    )


def _workbook(stored_id, copy):
    findings = [
        {"document_name": "d", "page_section": "p.1", "comment": "c", "comment_by": "b"}
    ]
    rows = _rows()
    view.apply(rows, stored_id)  # the pass changes the rows; this records what it found
    meta = {"copy": copy, "ai_review": view.for_run(stored_id)}
    return openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(findings, meta)))


def test_the_top_note_counts_removed_comments_on_the_internal_copy_only(stored):
    internal = _workbook(stored, "internal")
    top = internal.worksheets[0]["A1"].value
    assert "1 comment removed by AI review, see internal sheet" in top
    assert "removed by AI review" not in str(
        _workbook(stored, "issue").worksheets[0]["A1"].value
    )


def test_the_sheet_shows_the_reason_and_the_verified_evidence_with_its_page(stored):
    text = _sheet_text(_workbook(stored, "internal"), view.SHEET)
    assert "Different tags have different MAWP" in text
    assert 'p.1: "Tag P-101B  MAWP 16 barg"' in text
    assert "tag_difference" in text


def test_a_confirmed_or_absent_row_is_never_called_removed(stored):
    rows = _rows()
    rows[0]["engineer_confirmed"] = True
    view.apply(rows, stored)
    data = view.for_run(stored)
    assert data["removed"][0]["state"] == view.STATE_KEPT and data["note"] == ""
    view.apply([dict(FAIL)], stored)  # k-rev is not in this run any more
    data = view.for_run(stored)
    assert data["removed"][0]["state"] == view.STATE_ABSENT and data["note"] == ""
    assert "removed from the CRS" != data["removed"][0]["state"]
    assert "removed by AI review" not in view.top_note({"ai_review": data}, "internal")


def test_without_an_apply_the_state_does_not_claim_the_row_was_removed(stored):
    view._APPLIED.set(None)
    assert view.for_run(stored)["removed"][0]["state"] == view.STATE_UNCHECKED


def test_the_removed_row_stays_in_the_decision_paths_rows(stored):
    seen = {}

    def build():
        rows = _rows()
        view.apply(rows, stored)
        seen["keys"] = [r["crs_row_key"] for r in rows]

    view.with_removed(build)
    assert seen["keys"] == ["k-rev", "k-fail"]
    build()
    assert seen["keys"] == ["k-fail"]


def _world_with_removal(request, monkeypatch):
    _sub, run, scope = request.getfixturevalue("_world")
    reader = access.AccessScope(user_id=None, allowed_document_ids=scope)
    number_crs_rows(run, reader)
    # a row the AI may remove (never a Fail); the world's rows are all Fails, so the fixture's first row is made a question
    first = _crs_content(run, reader, "internal")[0][0]
    monkeypatch.setattr(
        view, "source_is_fail", lambda row: False
    )  # the removal path itself; the Fail guard has its own test below
    key = first["crs_row_key"]
    finding = first.get("finding_id") or key
    item = {
        "type": "remove",
        "row_key": key,
        "proposal_id": "p1",
        "reason": "r",
        "evidence": [],
        "row_words": "w",
    }
    monkeypatch.setattr(arpass, "accepted", lambda _r: [item])
    monkeypatch.setattr(arpass, "restored_ids", lambda _r: set())
    return run, scope, reader, key, finding


def test_an_ai_removed_row_is_still_an_open_item_and_can_be_decided(
    request, monkeypatch
):
    run, scope, reader, key, finding = _world_with_removal(request, monkeypatch)
    shown = [r["crs_row_key"] for r in _crs_content(run, reader, "internal")[0]]
    assert key not in shown  # the internal CRS does not print it
    gate = _crs_issue_gate(run, reader)
    assert finding in {f["finding_id"] for f in gate["open_findings"]}
    # and the decide route finds it (404 only for a key that is in no row)
    _signed_in(monkeypatch, scope)
    response = TestClient(app).post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{finding}/decision",
        json={"decision": "accept", "reason": "checked by eye"},
    )
    assert response.status_code != 404, response.text


def test_the_restore_route_restores_logs_and_undoes(request, monkeypatch, stored):
    _sub, run, scope = request.getfixturevalue("_world")
    _signed_in(monkeypatch, scope)
    # a removal stored under the world's run id
    arpass.run(
        run, [dict(ROW), dict(FAIL)], pages=PAGES, held=HELD, provider=Stub([REMOVE])
    )
    client = TestClient(app)
    url = f"/api/reviews/runs/{run}/ai-review/p1/restore"
    assert client.post(url, json={}).json()["action"] == "restore"
    assert arpass.restored_ids(run) == {"p1"}
    assert client.post(url, json={"undo": True}).json()["action"] == "unrestore"
    assert arpass.restored_ids(run) == set()
    assert client.post(url.replace("/p1/", "/nope/"), json={}).status_code == 404


def test_the_restore_route_refuses_a_run_the_caller_cannot_read(request, monkeypatch):
    _sub, run, _scope = request.getfixturevalue("_world")
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(run, [dict(ROW)], pages=PAGES, held=HELD, provider=Stub([REMOVE]))
    _signed_in(monkeypatch, frozenset())
    response = TestClient(app).post(
        f"/api/reviews/runs/{run}/ai-review/p1/restore", json={}
    )
    assert response.status_code == 404
    assert arpass.restored_ids(run) == set()


def test_the_restore_route_needs_a_named_engineer(request, monkeypatch):
    _sub, run, _scope = request.getfixturevalue("_world")
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(run, [dict(ROW)], pages=PAGES, held=HELD, provider=Stub([REMOVE]))
    response = TestClient(app).post(
        f"/api/reviews/runs/{run}/ai-review/p1/restore", json={}
    )
    assert response.status_code == 401
    assert arpass.restored_ids(run) == set()


FLAG = {
    "id": "pf",
    "type": "flag",
    "row_key": "k-fail",
    "page": 2,
    "value": "10 barg",
    "reason": "The row's datasheet figure may be misread.",
    "confidence": "medium",
    "evidence": [{"page": 2, "quote": "Relief valve PSV-9901  Set pressure 10 barg"}],
}


@pytest.fixture
def flagged(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run(
        "rv10",
        [dict(ROW), dict(FAIL)],
        pages=PAGES,
        held=HELD,
        provider=Stub([FLAG, dict(REMOVE, id="p1")]),
    )
    return "rv10"


def test_a_flag_keeps_the_fail_on_the_crs_and_prints_the_code_built_text(flagged):
    rows = _rows()
    view.apply(rows, flagged)
    fail = next(r for r in rows if r["crs_row_key"] == "k-fail")
    assert fail["row_kind"] == "non_compliant"  # still there, still a Fail
    assert fail["ai_review_comment"] == (
        "AI suspects the datasheet value was misread: page 2 shows "
        '"Relief valve PSV-9901  Set pressure 10 barg"'
    )
    assert "misread." not in fail["ai_review_comment"]  # none of the AI's own words


def test_the_note_and_the_sheet_say_flagged_for_a_flag_and_removed_for_a_removal(
    flagged,
):
    data = _workbook(flagged, "internal")
    top = data.worksheets[0]["A1"].value
    assert (
        "1 comment removed by AI review, 1 comment flagged by AI review, see internal sheet"
        in top
    )
    text = _sheet_text(data, view.SHEET)
    assert "Flagged by AI review (the row stays on the CRS)" in text
    assert "flagged: the row stays on the CRS" in text
    assert "removed from the CRS" in text


def test_a_flag_alone_is_never_called_a_removal(monkeypatch):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    arpass.run("rv11", [dict(FAIL)], pages=PAGES, held=HELD, provider=Stub([FLAG]))
    view.apply([dict(FAIL)], "rv11")
    data = view.for_run("rv11")
    assert (
        data["removed"] == []
        and data["note"] == "1 comment flagged by AI review, see internal sheet"
    )


def test_apply_keeps_a_row_whose_source_finding_is_a_fail_even_if_the_row_says_otherwise(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ai_engineering_review_pass_enabled", True)
    row = dict(
        ROW,
        row_kind="needs_engineer_review",
        compliance_status="NEEDS_ENGINEER_REVIEW",
        severity="minor",
        finding_ids=["src-fail"],
    )
    arpass.run(
        "rv-real",
        [row],
        pages=PAGES,
        held=HELD,
        provider=Stub([REMOVE]),
    )
    monkeypatch.setattr(
        "app.review.get",
        lambda fid: (
            {"compliance_status": "NON_COMPLIANT"} if fid == "src-fail" else None
        ),
    )
    rows = [dict(row)]
    view.apply(rows, "rv-real")
    assert [r["crs_row_key"] for r in rows] == ["k-rev"]  # still there
    data = view.for_run("rv-real")
    assert data["removed"][0]["state"] == view.STATE_KEPT_FAIL
    assert data["note"] == ""
    # and with the source finding not a Fail, the same removal applies
    monkeypatch.setattr(
        "app.review.get", lambda fid: {"compliance_status": "NEEDS_ENGINEER_REVIEW"}
    )
    rows = [dict(row)]
    view.apply(rows, "rv-real")
    assert rows == []
