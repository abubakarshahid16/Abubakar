"""#805 plan change 6: a signer's ticks in a returned checklist become decisions in the rulebook. The workbook here is
invented and written by this test, in the shape the local generator writes. No real rule is approved by any test."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import openpyxl
import pytest

from app import rulebook_v2, standards_compiler
from app.config import settings
from tests.test_805_rulebook_v2 import (
    ENGINEER,
    PSV,
    _compile,
    _conn,
    _edition_page,
    _rows,
    _rule,
    _version,
    lane,  # noqa: F401 - autouse
    switched_on,  # noqa: F401 - autouse
)
from tests.test_805_rulebook_v2 import _person as _plain_person
from tests.test_1584_standards_compiler import FakeBatches

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import import_rule_approvals as importer

COLUMNS = [
    "ID",
    *importer.READ_COLUMNS,
    importer.C_CHECK,
    importer.C_TICK,
    importer.C_COMMENT,
]
EMAIL = f"{ENGINEER}@example.test"


def _grant_admin(user_id):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, kind, created_at) VALUES ('role-admin', 'admin', 'invented', 'capability', '2026-11-02')"
        )
        role = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()[0]
        conn.execute(
            "INSERT INTO user_roles (user_id, role_id, granted_at) VALUES (?, ?, '2026-11-02')",
            (user_id, role),
        )


def _person(user_id=ENGINEER, active=1):
    """A signer who holds the admin role, so these tests may sign as owner."""
    _plain_person(user_id, active)
    _grant_admin(user_id)
    return user_id


def _cell_rows():
    rows = []
    for link in _rows(
        "SELECT c.compiled_row_id, v.rule_id, v.version_no, p.quote, s.id AS snapshot FROM rulebook_compiled_row c"
        " JOIN rulebook_version v ON v.id = c.rule_version_id"
        " JOIN rulebook_provenance p ON p.rule_version_id = v.id"
        " JOIN rulebook_snapshot s ON s.compile_run_id = c.compile_run_id ORDER BY c.rowid"
    ):
        row = {
            "ID": link["compiled_row_id"],
            "What to check": "invented thing: invented field",
            "Limit": "<= 25",
            "Unit": "bar",
            "When it applies": "If: invented\nwrapped line",
            "Clause": "4.1",
            "Page": "1",
            importer.C_QUOTE: link["quote"],
            importer.C_RULE: link["rule_id"],
            importer.C_VERSION: str(link["version_no"]),
            importer.C_SNAPSHOT: link["snapshot"],
        }
        row[importer.C_CHECK] = importer.row_check(row)
        rows.append(row)
    return rows


def _workbook(path, rows, *, tick=None, comment=None, stamp=None, equipment=PSV):
    """The returned file: cover, then rows with the tick column filled in as a person would."""
    triples = [
        (r[importer.C_RULE], r[importer.C_VERSION], r[importer.C_SNAPSHOT])
        for r in rows
        if r[importer.C_RULE]
    ]
    book = openpyxl.Workbook()
    cover = book.active
    cover.title = "Cover"
    cover.append(["File type", "standard"])
    cover.append([importer.COVER_TYPE, equipment])
    cover.append(
        [importer.COVER_STAMP, stamp or rulebook_v2.checklist_stamp(PSV, triples)]
    )
    sheet = book.create_sheet("Rules")
    sheet.append(COLUMNS)
    for row in rows:
        cells = {
            **row,
            importer.C_TICK: tick,
            importer.C_COMMENT: comment,
        }
        sheet.append([cells.get(c) for c in COLUMNS])
    book.save(path)
    return path


def _ticked(tmp_path, tick=importer.OK, **kw):
    return _workbook(tmp_path / "returned.xlsx", _cell_rows(), tick=tick, **kw)


def _run(path, signed_by=EMAIL, tier="owner"):
    said = []
    code = importer.run(settings.db_path, path, signed_by, tier, emit=said.append)
    return code, json.loads(said[0])


def _approvals():
    return _rows("SELECT * FROM rulebook_approval")


def test_a_tick_is_recorded_with_who_when_tier_and_type_and_only_then_the_rule_comes_out(
    tmp_path,
):
    _person()
    _compile()
    assert rulebook_v2.approved_rules(_conn(), PSV) == []
    code, said = _run(_ticked(tmp_path))
    assert code == 0 and said["approved"] == 1 and said["tier"] == "owner"
    (row,) = _approvals()
    assert row["approver_id"] == ENGINEER and row["tier"] == "owner"
    assert row["decided_at"] and row["equipment_type"] == PSV
    assert len(row["source_sha256"]) == 64
    (rule,) = rulebook_v2.approved_rules(_conn(), PSV)
    assert rule["approval"]["tier"] == "owner"
    assert rulebook_v2.approved_rules(_conn(), "An Invented Pump") == []
    assert _rows(
        "SELECT actor FROM rulebook_event WHERE entity = 'rulebook_approval'"
    ) == [{"actor": ENGINEER}]


@pytest.mark.parametrize("tier", ["owner", "engineer"])
def test_the_tier_is_the_flags_never_inferred(tmp_path, tier):
    _person()
    _compile()
    _run(_ticked(tmp_path), tier=tier)
    assert _approvals()[0]["tier"] == tier


@pytest.mark.parametrize(
    "argv",
    [
        ["--db", "x", "--file", "y", "--signed-by", "z"],
        ["--db", "x", "--file", "y", "--tier", "owner"],
        ["--db", "x", "--file", "y", "--signed-by", "z", "--tier", "system"],
    ],
)
def test_the_command_will_not_run_without_a_named_signer_and_tier(argv):
    with pytest.raises(SystemExit):
        importer.main(argv)


def test_an_empty_tick_is_no_approval_even_with_a_comment(tmp_path):
    _person()
    _compile()
    code, said = _run(_ticked(tmp_path, tick=None, comment="looked at it"))
    assert code == 0 and said["approved"] == 0
    assert said["empty_ticks_not_recorded"] == said["rows_in_file"] == 1
    assert _approvals() == []
    assert rulebook_v2.approved_rules(_conn(), PSV) == []


@pytest.mark.parametrize("tick", [importer.WRONG, importer.NOT_APPLICABLE])
def test_wrong_or_not_applicable_is_no_approval_and_withdraws_an_earlier_one(
    tmp_path, tick
):
    _person()
    _compile()
    _run(_ticked(tmp_path))
    assert len(rulebook_v2.approved_rules(_conn(), PSV)) == 1
    code, said = _run(_workbook(tmp_path / "second.xlsx", _cell_rows(), tick=tick))
    assert code == 0 and said["rejected"] == 1
    assert rulebook_v2.approved_rules(_conn(), PSV) == []
    assert _approvals()[-1]["note"] == tick


def test_the_import_records_what_the_tick_signed_and_a_later_change_shows(tmp_path):
    _person()
    _compile()
    path = _ticked(tmp_path)
    assert _run(path)[0] == 0
    conn = _conn()
    rule = rulebook_v2.approved_rules(conn, PSV)[0]
    assert rule["signed_matches"] is True
    row = conn.execute("SELECT signed_content FROM rulebook_approval").fetchone()[0]
    assert json.loads(row)["check_op"] is None
    from app import rule_typed_check

    rule_typed_check.ensure_columns(conn)
    with conn:
        conn.execute(
            "UPDATE compiled_rules SET check_op = 'is_not', check_state = 'verified'"
        )
    assert rulebook_v2.approved_rules(conn, PSV)[0]["signed_matches"] is False


def test_importing_the_same_file_again_adds_nothing(tmp_path):
    _person()
    _compile()
    path = _ticked(tmp_path)
    _run(path)
    code, said = _run(path)
    assert code == 0 and said["approved"] == 0 and said["already_recorded"] == 1
    assert len(_approvals()) == 1


def test_a_stale_file_is_refused_lists_the_rows_and_writes_nothing(tmp_path):
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    made = _cell_rows()
    path = _workbook(tmp_path / "old.xlsx", made, tick=importer.OK)
    _compile(
        doc="ed-2",
        pages=_edition_page("30"),
        edition="2026",
        rules=[
            _rule(
                limit="30",
                quote="The relief flange pressure shall not exceed 30 bar for gas service.",
            )
        ],
    )
    code, said = _run(path)
    assert code == importer.EXIT_STALE and said["rows_superseded"] == [
        made[0][importer.C_RULE]
    ]
    assert _approvals() == []


def test_a_new_compile_of_the_same_standard_makes_the_file_stale(tmp_path):
    _person()
    _compile()
    path = _ticked(tmp_path)
    with _conn() as conn:
        conn.execute("UPDATE compile_runs SET prompt_version = 'older'")
    standards_compiler.compile_standard(
        _conn(),
        "std-zz",
        "SAES-Z-900",
        client=FakeBatches([_rule()]),
        sleep=lambda _s: None,
    )
    from app import rulebook_v2_ingest

    rulebook_v2_ingest.ingest_latest(_conn(), "std-zz")
    code, said = _run(path)
    assert code == importer.EXIT_STALE and said["snapshots_no_longer_newest"]
    assert _approvals() == []


def test_a_changed_stamp_or_equipment_type_is_refused(tmp_path):
    _person()
    _compile()
    rows = _cell_rows()
    forged = _workbook(tmp_path / "a.xlsx", rows, tick=importer.OK, stamp="rb2-other")
    assert _run(forged)[0] == importer.EXIT_STALE
    other = _workbook(
        tmp_path / "b.xlsx", rows, tick=importer.OK, equipment="An Invented Pump"
    )
    assert _run(other)[0] == importer.EXIT_STALE
    assert _approvals() == []


@pytest.mark.parametrize(
    ("column", "words"),
    [
        ("Limit", "<= 2500"),
        ("Unit", "psi"),
        ("What to check", "another thing"),
        ("When it applies", ""),
        (importer.C_QUOTE, "Other invented words on another page."),
    ],
)
def test_a_row_whose_words_were_edited_is_refused(tmp_path, column, words):
    _person()
    _compile()
    rows = _cell_rows()
    rows[0][column] = words
    code, said = _run(_workbook(tmp_path / "edited.xlsx", rows, tick=importer.OK))
    assert code == importer.EXIT_EDITED and said["rows"]
    assert _approvals() == []


def test_a_quote_edited_with_its_row_check_redone_is_still_refused(tmp_path):
    _person()
    _compile()
    rows = _cell_rows()
    rows[0][importer.C_QUOTE] = "Other invented words on another page."
    rows[0][importer.C_CHECK] = importer.row_check(rows[0])
    code, _said = _run(_workbook(tmp_path / "forged.xlsx", rows, tick=importer.OK))
    assert code == importer.EXIT_EDITED and _approvals() == []


def test_the_import_writes_only_the_decision_and_its_event_and_changes_no_rule_text(
    tmp_path,
):
    _person()
    _compile()
    path = _ticked(tmp_path)
    tables = [
        "rulebook_rule",
        "rulebook_version",
        "rulebook_provenance",
        "rulebook_applicability",
        "rulebook_exception",
        "compiled_rules",
        "standard_requirements",
    ]
    before = {t: _rows(f"SELECT * FROM {t}") for t in tables}
    conn, written = _conn(), set()

    def spy(code, first, _second, _db, _trigger):
        if code in (
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
        ):
            written.add(first)
        return sqlite3.SQLITE_OK

    conn.set_authorizer(spy)
    try:
        assert _run(path)[0] == 0
    finally:
        conn.set_authorizer(None)
    assert written <= {"rulebook_approval", "rulebook_event", "sqlite_sequence"}
    assert "rulebook_approval" in written
    assert {t: _rows(f"SELECT * FROM {t}") for t in tables} == before


@pytest.mark.parametrize("who", ["nobody@example.test", "system", ""])
def test_a_signer_who_is_not_an_active_user_is_refused(tmp_path, who):
    _person()
    _compile()
    code, _said = _run(_ticked(tmp_path), signed_by=who)
    assert code == importer.EXIT_BAD and _approvals() == []


def test_a_signer_no_longer_active_is_refused(tmp_path):
    _person()
    _person("left", active=0)
    _compile()
    code, _said = _run(_ticked(tmp_path), signed_by="left")
    assert code == importer.EXIT_BAD and _approvals() == []


def test_a_live_shaped_database_is_refused(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(live).close()
    with pytest.raises(SystemExit, match="live database"):
        importer.run(live, tmp_path / "x.xlsx", EMAIL, "owner", emit=lambda _l: None)


def test_switch_off_nothing_is_read_or_written(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    said = []
    code = importer.run(
        settings.db_path, tmp_path / "x.xlsx", EMAIL, "owner", emit=said.append
    )
    assert code == importer.EXIT_OFF and "off" in said[0]


def test_a_tick_off_the_list_or_on_a_row_with_no_rule_id_is_refused(tmp_path):
    _person()
    _compile()
    bad = _workbook(tmp_path / "bad.xlsx", _cell_rows(), tick="yes")
    code, said = _run(bad)
    assert code == importer.EXIT_EDITED and said["tick_not_on_the_list"]
    rows = [
        *_cell_rows(),
        {
            "ID": "dropped-row",
            importer.C_RULE: None,
            importer.C_VERSION: None,
            importer.C_SNAPSHOT: None,
        },
    ]
    code, said = _run(_workbook(tmp_path / "gap.xlsx", rows, tick=importer.OK))
    assert code == importer.EXIT_EDITED
    assert said["ticked_row_has_no_rule_id"] == ["dropped-row"]
    assert _approvals() == []


def test_a_context_dependent_rule_needs_a_comment_and_nothing_else_in_the_file_is_recorded(
    tmp_path,
):
    _person()
    _compile()
    conn = _conn()
    conn.execute("DROP TRIGGER rulebook_version_no_update")
    conn.execute(
        "UPDATE rulebook_version SET strength = ?", (rulebook_v2.CONTEXT_DEPENDENT,)
    )
    conn.commit()
    code, said = _run(_ticked(tmp_path))
    assert code == importer.EXIT_EDITED and said["needs_a_comment"]
    assert _approvals() == []
    code, said = _run(
        _workbook(
            tmp_path / "noted.xlsx",
            _cell_rows(),
            tick=importer.OK,
            comment="the heading scopes it",
        )
    )
    assert code == 0 and said["approved"] == 1
    assert "the heading scopes it" in _approvals()[0]["note"]


def test_decisions_are_all_or_none():
    _person()
    _compile()
    version = _version()
    good = {
        "version_id": version["id"],
        "decision": rulebook_v2.REJECT,
        "engineer_id": ENGINEER,
        "tier": "owner",
    }
    with pytest.raises(sqlite3.IntegrityError):
        rulebook_v2.record_decisions(_conn(), [good, {**good, "tier": None}])
    assert _approvals() == []


def _forged(rows, **cells):
    """Words changed and the row check done again, so only the comparison with the rule can see it."""
    rows[0].update(cells)
    rows[0][importer.C_CHECK] = importer.row_check(rows[0])
    return rows


@pytest.mark.parametrize(
    "cells",
    [
        {"Limit": "<= 30"},
        {"Limit": ">= 25"},
        {"Limit": "25"},
        {"Limit": ""},
        {"Limit": "<= 25 or so"},
        {"Unit": "psi"},
        {"Unit": ""},
        {"Unit": "BAR"},
    ],
)
def test_a_file_showing_another_limit_or_unit_records_no_approval(tmp_path, cells):
    _person()
    _compile()
    path = _workbook(
        tmp_path / "other.xlsx", _forged(_cell_rows(), **cells), tick=importer.OK
    )
    code, said = _run(path)
    assert code == importer.EXIT_EDITED and said["rows"]
    assert _approvals() == []


def test_the_limit_as_the_rule_holds_it_is_accepted_however_the_number_is_written(
    tmp_path,
):
    _person()
    _compile()
    path = _workbook(
        tmp_path / "same.xlsx", _forged(_cell_rows(), Limit="<= 25.0"), tick=importer.OK
    )
    assert _run(path)[0] == 0


def test_a_rule_with_no_figure_refuses_a_file_that_shows_one(tmp_path):
    _person()
    _compile(
        rules=[
            _rule(comparator=None, limit=None, unit=None, condition="for gas service")
        ]
    )
    rows = _cell_rows()
    for row in rows:
        row.update({"Limit": "", "Unit": ""})
        row[importer.C_CHECK] = importer.row_check(row)
    assert rows, "the proof kept the rule with no figure"
    assert _run(_workbook(tmp_path / "plain.xlsx", rows, tick=importer.OK))[0] == 0
    code, _said = _run(
        _workbook(
            tmp_path / "shown.xlsx",
            _forged(_cell_rows(), Limit="<= 25", Unit=""),
            tick=importer.OK,
        )
    )
    assert code == importer.EXIT_EDITED


def test_the_approval_lists_only_the_source_this_file_showed(tmp_path):
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    _compile(doc="ed-2", pages=_edition_page(), edition="2026")
    sources = _rows(
        "SELECT id, standard_document_id FROM rulebook_provenance ORDER BY rowid"
    )
    assert len(sources) == 2
    rows = [
        r
        for r in _cell_rows()
        if r[importer.C_SNAPSHOT]
        == _rows("SELECT id FROM rulebook_snapshot ORDER BY rowid DESC")[0]["id"]
    ][:1]
    assert _run(_workbook(tmp_path / "ed2.xlsx", rows, tick=importer.OK))[0] == 0
    (row,) = _approvals()
    assert json.loads(row["provenance_viewed"]) == [sources[1]["id"]]


def test_tier_owner_needs_the_admin_role_and_tier_engineer_does_not(tmp_path):
    _plain_person()
    _compile()
    code, said = _run(_ticked(tmp_path), tier="owner")
    assert code == importer.EXIT_BAD and "admin" in said["refused"]
    assert _approvals() == []
    assert _run(_ticked(tmp_path), tier="engineer")[0] == 0
    _grant_admin(ENGINEER)
    assert (
        _run(
            _workbook(tmp_path / "o.xlsx", _cell_rows(), tick=importer.OK), tier="owner"
        )[0]
        == 0
    )
