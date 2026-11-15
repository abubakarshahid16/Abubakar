# ruff: noqa: RUF059
"""B5: how the one CRS sheet and "How it was reviewed" read the nine-role record, and the writer's lock. Invented data only."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import access, crs_completeness, crs_one, db, nine_sheet
from app.config import settings
from app.nine_contract import ROLE_NAMES, ReviewRecord, RoleRecord
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

DDL = (
    "CREATE TABLE IF NOT EXISTS agent_review_role (run_id TEXT, role_no INTEGER, role TEXT, state TEXT, why TEXT, engine TEXT,"
    " models_json TEXT, calls INTEGER, usd REAL, started_at TEXT, finished_at TEXT, produced_json TEXT, PRIMARY KEY (run_id, role_no))",
    "CREATE TABLE IF NOT EXISTS agent_review_role_call (run_id TEXT, role_no INTEGER, call_id TEXT, step TEXT, engine TEXT, model TEXT,"
    " request_sha256 TEXT, state TEXT, error_code TEXT, usd REAL, sent_at TEXT, PRIMARY KEY (run_id, call_id))",
    "CREATE TABLE IF NOT EXISTS agent_review_role_read (run_id TEXT, role_no INTEGER, call_id TEXT, seq INTEGER, document_id TEXT,"
    " document_kind TEXT, pages_json TEXT, chapter_id TEXT, part_no INTEGER, part_of INTEGER, chars INTEGER, text_sha256 TEXT,"
    " pictures INTEGER, PRIMARY KEY (run_id, call_id, seq))",
)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
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


def test_a_table_with_fewer_than_nine_rows_says_the_missing_roles_were_not_reached():
    doc, rc, ai, client = world_with_both()
    with db.connect() as conn:
        for ddl in DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO agent_review_role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ai, 1, "Reader", "ran", None, "claude", "[]", 1, 0.1, "t", "t", "{}"),
        )
    line = nine_sheet.roles_line(nine_sheet.load_record(db.connect(), ai))
    assert (
        line.startswith("Roles run: 1 of 9")
        and "2 Project context: not reached" in line
    )


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
            produced={"chapters_not_read": {"over the reading budget": 3}},
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
    with db.connect() as conn:
        for ddl in DDL:
            conn.execute(ddl)
        for n in range(1, 10):
            state, why = (
                ("not_run", "none held for this project")
                if n == not_run
                else ("ran", None)
            )
            conn.execute(
                "INSERT INTO agent_review_role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    n,
                    ROLE_NAMES[n],
                    state,
                    why,
                    "claude",
                    json.dumps(["m1"]),
                    1,
                    None if n == 4 else 0.25,
                    "t0",
                    "t1",
                    json.dumps({"x": 1}),
                ),
            )
        conn.execute(
            "INSERT INTO agent_review_role_read VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                1,
                "c1",
                0,
                "doc_x",
                "paper",
                "[1,2]",
                None,
                None,
                None,
                90,
                "ab" * 32,
                2,
            ),
        )


def test_load_record_round_trips_and_a_run_without_tables_is_none():
    doc, rc, ai, client = world_with_both()
    assert nine_sheet.load_record(db.connect(), ai) is None
    _make_record(ai, not_run=2)
    rec = nine_sheet.load_record(db.connect(), ai)
    assert [r.role_no for r in rec.roles] == list(range(1, 10)) and rec.roles[
        1
    ].state == "not_run"
    assert rec.roles[0].reads[0].pictures == 2 and rec.roles[3].usd is None


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
    assert "not run: 2 Project context: none held for this project" in text
    assert (
        "Role 4 Reviewer" in text
        and "cost (USD) not known" in text
        and "Role 2 Project context did not run" in text
    )
    got = crs_completeness.checked_files(doc, scope_all())
    assert (
        got["team"][1]["ok"] and got["contractor"][1]["ok"]
    )  # N points = N lines = N rows with a nine-role record present
