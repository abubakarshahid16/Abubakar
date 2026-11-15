# ruff: noqa: RUF059
"""B5: how the one CRS sheet and "How it was reviewed" read the nine-role record, and the writer's lock. Invented data only."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import access, crs_completeness, crs_one, db, nine_sheet, review_points_service
from app.config import settings
from app.nine_contract import ROLE_NAMES, ReviewRecord, RoleRecord
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def role(n, state="ran", why=None, engine="claude", usd=0.5, produced=None):
    return RoleRecord(
        role_no=n, role=ROLE_NAMES[n], state=state, why=why, engine=engine, models=("m1",) if engine != "code" else (), calls=2,
        usd=usd, produced=produced or {},
    )  # fmt: skip


def record(**over):
    roles = [
        role(n, engine="code", usd=None) if n in (7, 8) else role(n)
        for n in range(1, 10)
    ]
    for n, r in over.items():
        roles[int(n[1:]) - 1] = r
    return ReviewRecord("run1", "doc1", "automatic", tuple(roles), (), None)


def test_a_run_with_no_record_says_not_recorded_and_invents_nothing():
    assert (
        nine_sheet.roles_line(None)
        == "Roles: not recorded (reviewed before the role record)"
    )
    assert nine_sheet.how_rows(None) == [] and nine_sheet.not_checked_rows(None) == []


def test_a_role_that_did_not_run_is_named_with_its_reason_on_the_first_line():
    rec = record(
        r2=role(2, "not_run", "none held for this project", engine=None),
        r9=role(9, "ran_partly", "comments worded by code"),
    )
    line = nine_sheet.roles_line(rec)
    assert line.startswith("Roles run: 8 of 9") and "9 Writer (partly)" in line
    assert "not run: 2 Project context: none held for this project" in line


def test_how_rows_say_cost_not_known_never_zero_and_hold_counts_only():
    rec = record(
        r4=role(
            4, usd=None, produced={"raw_findings": 12, "contradictions": ["a", "b"]}
        )
    )
    rows = dict(nine_sheet.how_rows(rec))
    four = rows["Role 4 Reviewer"]
    assert (
        "cost (USD) not known" in four
        and "raw findings: 12" in four
        and "contradictions: 2" in four
    )
    assert "cost (USD) 0.50" in rows["Role 1 Reader"]
    assert (
        "Role 7 Code" in rows and "cost" not in rows["Role 7 Code"]
    )  # a code role has no cost word


def test_not_checked_rows_name_roles_not_run_and_what_was_not_read_by_reason():
    rec = record(
        r2=role(2, "not_run", "held, not on the list shown", engine=None),
        r3=role(
            3,
            "ran_partly",
            "reading budget",
            produced={"chapters_not_read.over the reading budget": 3},
        ),
    )
    rows = nine_sheet.not_checked_rows(rec)
    assert [
        "Role 2 Project context did not run",
        None,
        "held, not on the list shown",
    ] in rows
    assert ["Role 3 Librarian: chapters not read", 3, "over the reading budget"] in rows


def test_the_writer_keeps_a_wording_only_when_the_lock_finds_every_fact():
    rows = [
        {
            "key": "c1",
            "comment": "Design pressure 10 bar is below the 12 bar required (cl. 4.1).",
            "standard_reference": "STD-1 cl. 4.1",
            "page_section": "2",
            "row_kind": "non_compliant",
        }
    ]
    kept, dropped = nine_sheet.apply_wordings(
        rows,
        {
            "c1": "The design pressure of 10 bar is below the 12 bar required by clause 4.1."
        },
    )
    assert "c1" in kept and dropped == {}
    kept, dropped = nine_sheet.apply_wordings(
        rows,
        {
            "c1": "The design pressure of 15 bar is below the 12 bar required by clause 4.1."
        },
    )
    assert kept == {} and sum(dropped.values()) == 1
    kept, dropped = nine_sheet.apply_wordings(rows, {"zzz": "anything"})
    assert dropped == {"no such comment": 1}


def _make_record(run_id, *, not_run=None):
    from app import nine_record

    nine_record.start_run(run_id)
    for n in range(1, 10):
        if n == not_run:
            continue  # stays "not run: not reached"
        nine_record.role_start(run_id, n, "code")
        nine_record.role_end(run_id, n, "ran", produced={"x": 1}, engine="code")


def test_load_record_is_the_stored_record_and_a_run_without_rows_is_none():
    doc, rc, ai, client = world_with_both()
    assert nine_sheet.load_record(db.connect(), ai) is None
    _make_record(ai, not_run=2)
    rec = nine_sheet.load_record(db.connect(), ai)
    assert [r.role_no for r in rec.roles] == list(range(1, 10)) and rec.roles[
        1
    ].state == "not_run"
    assert rec.roles[1].why == "not reached"


def scope_all():
    return access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )


def text_of(data):
    return "\n".join(
        str(c)
        for ws in load_workbook(io.BytesIO(data))
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c is not None
    )


def test_the_first_sheet_and_how_it_was_reviewed_read_the_record_and_completeness_stays_n_equals_n():
    doc, rc, ai, client = world_with_both()
    old = text_of(crs_one.build_team(doc, scope_all()))
    assert "Roles: not recorded (reviewed before the role record)" in old
    _make_record(ai, not_run=2)
    data = crs_one.build_team(doc, scope_all())
    text = text_of(data)
    assert "not run: 2 Project context: not reached" in text
    assert "Role 4 Reviewer" in text and "Role 2 Project context did not run" in text
    got = crs_completeness.checked_files(doc, scope_all())
    assert (
        got["team"][1]["ok"] and got["contractor"][1]["ok"]
    )  # N points = N lines = N rows with a nine-role record present


# ------------------------------------------------------------------------------------------------ findings behind a nine-role line


def _stub_line(world_ai, item, underlying, members, verdicts=None):
    """Give one stored AI line the keys B4's `decide_all` writes."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT line_json FROM agent_review_line WHERE run_id = ? AND item_id = ?",
            (world_ai, item),
        ).fetchone()
        line = json.loads(row["line_json"])
        line.update(
            nine_underlying=underlying,
            nine_members=members,
            **({"nine_member_verdicts": verdicts} if verdicts else {}),
        )
        conn.execute(
            "UPDATE agent_review_line SET line_json = ? WHERE run_id = ? AND item_id = ?",
            (json.dumps(line), world_ai, item),
        )


def test_a_joined_line_says_how_many_findings_it_stands_for_and_lists_its_members():
    doc, rc, ai, client = world_with_both()
    _make_record(ai)
    _stub_line(ai, "R-1", 3, ["c1", "c1", "c2"], ["not met", "not met", "met"])
    data = crs_one.build_team(doc, scope_all())
    text = text_of(data)
    assert "this line stands for 3 findings" in text
    assert "c1, finding 1: not met" in text and "c2, finding 3: met" in text
    assert "from 3 findings of the reviewer" in text  # the first-sheet sentence
    pts = review_points_service.assemble(doc, scope_all())["points"]
    assert [p["underlying"] for p in pts if p.get("underlying")] == [3]


def test_a_line_that_stands_for_one_finding_says_nothing_extra():
    doc, rc, ai, client = world_with_both()
    _make_record(ai)
    _stub_line(ai, "R-1", 1, ["c1"])
    text = text_of(crs_one.build_team(doc, scope_all()))
    assert (
        "this line stands for" not in text and "from 1 findings of the reviewer" in text
    )


def test_the_fourth_check_refuses_the_file_when_a_finding_is_missing_from_the_lines():
    from app import nine_record

    doc, rc, ai, client = world_with_both()
    _make_record(ai)
    _stub_line(ai, "R-1", 3, ["a", "b", "c"])
    nine_record.role_end(ai, 4, "ran", produced={"findings_kept": 3}, engine="claude")
    got = crs_completeness.checked_files(doc, scope_all())
    assert got["team"][1]["ok"] and got["contractor"][1]["ok"]
    nine_record.role_end(
        ai, 4, "ran", produced={"findings_kept": 4}, engine="claude"
    )  # the join kept one more than the lines hold
    refused = crs_completeness.checked_files(doc, scope_all())["team"][1]
    assert (
        not refused["ok"]
        and "a finding is missing from the lines" in refused["sentence"]
    )
    with pytest.raises(crs_completeness.Incomplete):
        crs_completeness.file_or_refuse(doc, scope_all(), "team")


def test_a_role_with_its_switch_off_a_role_with_no_call_and_a_role_that_produced_nothing_are_worded_plainly():
    rec = record(
        r2=role(2, engine="code", usd=None, produced={"related_papers": 0, "windows": 0, "not_available": 5}),
        r3=role(3, usd=None, produced={"books": 3, "chapters_chosen": 24}),
        r9=role(9, usd=None, produced={"sheet_by": "code", "ai_wording": "not_used_in_this_version"}),
    )
    rows = dict(nine_sheet.how_rows(RoleRecordsWithZeroCalls(rec)))
    assert rows["Role 9 Writer"].startswith("off (its switch is off)") and "Claude" not in rows["Role 9 Writer"]
    assert "ran and produced nothing (not available 5)" in rows["Role 2 Project context"]
    three = rows["Role 3 Librarian"]
    assert "Claude" not in three.split(";")[1] and "no model call was made" in three and "produced nothing" not in three
    assert "produced nothing" not in rows["Role 1 Reader"] and "Claude" in rows["Role 1 Reader"]  # a role with calls keeps its words


def RoleRecordsWithZeroCalls(rec):
    """The same record with 0 calls for roles 2, 3 and 9 (the test helper's roles have 2 calls each)."""
    from dataclasses import replace

    roles = tuple(replace(r, calls=0) if r.role_no in (2, 3, 9) else r for r in rec.roles)
    return replace(rec, roles=roles)
