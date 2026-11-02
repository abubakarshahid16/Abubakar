"""#805 plan change 6, part A: the rulebook's version 2 tables. Invented standard text only; the Batch API is the
compiler tests' fake; no real Claude call, no local model, a temporary database copy."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import (
    comparison,
    compiled_rule_report,
    db,
    rulebook_v2,
    rulebook_v2_check,
    rulebook_v2_ingest,
    rulebook_v2_schema,
    standards,
    standards_compiler,
)
from app.config import Settings, settings
from app.rulebook_v2_check import (
    ALTERNATIVES,
    CANNOT_TELL,
    DEFERS_TO,
    DOES_NOT_MEET,
    LIMIT,
    MEETS,
    NO_FIGURE,
    NO_UNIT,
    RANGE,
    check_requirement,
)
from tests.test_1584_standards_compiler import (
    DOC,
    LABEL,
    QUOTE,
    FakeBatches,
    _document,
    _rule,
    lane,  # noqa: F401 - autouse: a temporary copy, the compiler's switches on
)
from tests.test_field_naming import _world

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rulebook_v2 as rulebook_script

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "backend" / "app"
PAGE_2 = "4.2 Bolts\nThe invented bolt torque shall be at least 40 Nm."
ENGINEER = "user-eng"
PSV = "Invented Relief Device"


@pytest.fixture(autouse=True)
def switched_on(lane, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "rulebook_v2_enabled", True)


def _conn():
    return db.connect()


def _person(user_id=ENGINEER, active=1):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, is_active, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}@example.test",
                "An engineer",
                "x",
                active,
                "2026-11-02",
            ),
        )
    return user_id


def _compile(doc=DOC, label=LABEL, rules=None, pages=None, edition=None):
    """A real compile through the compiler's fake batches, then the newest compile into the tables."""
    if not _exists(doc):
        _document(doc_id=doc, number=label, **({"pages": pages} if pages else {}))
    if edition:
        with _conn() as conn:
            conn.execute(
                "UPDATE document_classification SET revision = ? WHERE document_id = ?",
                (edition, doc),
            )
    standards_compiler.compile_standard(
        _conn(),
        doc,
        label,
        client=FakeBatches(rules if rules is not None else [_rule()]),
        sleep=lambda _s: None,
    )
    return rulebook_v2_ingest.ingest_latest(_conn(), doc)


def _compile_with_exception():
    """A stored row holding a condition and an exception. What the proof keeps is its own tests' business."""
    _document()
    standards_compiler.compile_standard(
        _conn(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )
    with _conn() as conn:
        conn.execute(
            "UPDATE compiled_rules SET exception_text = 'unless the flange is blind'"
        )
    return rulebook_v2_ingest.ingest_latest(_conn(), DOC)


def _exists(doc):
    return _conn().execute("SELECT 1 FROM documents WHERE id = ?", (doc,)).fetchone()


def _rows(sql, *args):
    return [dict(r) for r in _conn().execute(sql, args)]


def _version(version_no=1):
    return _rows(
        "SELECT * FROM rulebook_version WHERE version_no = ? ORDER BY rowid", version_no
    )[0]


def _sources(version_id):
    return tuple(
        r["id"]
        for r in _rows(
            "SELECT id FROM rulebook_provenance WHERE rule_version_id = ?", version_id
        )
    )


def _approve(version_id, engineer=ENGINEER, note=None):
    return rulebook_v2.record_decision(
        _conn(),
        version_id,
        decision=rulebook_v2.APPROVE,
        engineer_id=engineer,
        tier=rulebook_v2.ENGINEER,
        equipment_type=PSV,
        provenance_viewed=_sources(version_id),
        note=note,
    )


def _row(**over):
    base = {
        "field": "flange pressure",
        "limit_text": None,
        "unit": None,
        "comparator": None,
        "quote": "The invented flange shall be painted.",
    }
    return {**base, **over}


# ------------------------------------------------------------------------------------------- the switch


def test_the_switch_is_off_by_default():
    assert Settings.model_fields["rulebook_v2_enabled"].default is False


def test_switch_off_nothing_is_read_created_or_written(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    conn = _conn()
    with pytest.raises(rulebook_v2.SwitchedOff):
        rulebook_v2.ensure_schema(conn)
    with pytest.raises(rulebook_v2.SwitchedOff):
        rulebook_v2_ingest.ingest_latest(conn, DOC)
    rulebook_v2_ingest.after_compile(conn, DOC)
    assert rulebook_v2.record_run(conn, "run-1") is None
    assert rulebook_v2_ingest.report_row(conn, DOC) == {}
    assert not rulebook_v2.has_schema(conn)


def test_switch_off_the_script_stops_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    said = []
    assert (
        rulebook_script.run(tmp_path / "copy.sqlite", [DOC], emit=said.append)
        == rulebook_script.EXIT_OFF
    )
    assert "nothing was read or written" in said[0]


# ------------------------------------------------------------------------------------------ the migration


def _other_schema(conn):
    return sorted(
        tuple(r)
        for r in conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE '%rulebook%'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    )


def test_starting_the_app_creates_none_of_the_tables():
    db.init_db()
    assert not rulebook_v2.has_schema(_conn())


def test_the_migration_adds_only_its_tables_and_run_twice_does_nothing():
    conn = _conn()
    before = _other_schema(conn)
    rulebook_v2.ensure_schema(conn)
    rulebook_v2.ensure_schema(conn)
    assert _other_schema(conn) == before
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert set(rulebook_v2.TABLES) <= held
    assert rulebook_v2.integrity_problems(conn) == {}


def test_a_migration_that_fails_part_way_leaves_nothing(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(
        rulebook_v2, "SCHEMA", (*rulebook_v2.SCHEMA[:3], "CREATE TABLE broken (")
    )
    with pytest.raises(sqlite3.Error):
        rulebook_v2.ensure_schema(conn)
    assert not conn.in_transaction
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'rulebook_rule'"
    ).fetchone()


def test_a_live_shaped_database_is_refused_and_gets_no_table(tmp_path):
    path = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    with pytest.raises(rulebook_v2.RefusedLive):
        rulebook_v2.ensure_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    conn.close()
    with pytest.raises(SystemExit, match="live database"):
        rulebook_script.run(path, ["x"], emit=lambda _line: None)


def test_a_run_on_a_database_without_the_tables_creates_none():
    assert rulebook_v2.record_run(_conn(), "run-1") is None
    assert not rulebook_v2.has_schema(_conn())


# ------------------------------------------------------------------------------- nothing is ever rewritten


def _a_full_book():
    _person()
    _compile()
    version = _version()
    _approve(version["id"])
    rulebook_v2.record_run(_conn(), "run-1")
    return version


@pytest.mark.parametrize("table", rulebook_v2.TABLES)
def test_no_row_of_any_table_can_be_changed_or_deleted(table):
    if table == "rulebook_exception":
        _compile_with_exception()
    else:
        _a_full_book()
    conn = _conn()
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 1
    before = [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")]
    column = conn.execute(f"PRAGMA table_info({table})").fetchone()[1]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"UPDATE {table} SET {column} = {column}")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"DELETE FROM {table}")
    conn.rollback()
    assert [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")] == before


def test_insert_or_replace_cannot_erase_a_row_past_the_delete_trigger():
    version = _a_full_book()
    conn = _conn()
    rule = _rows("SELECT * FROM rulebook_rule")[0]
    with pytest.raises(sqlite3.IntegrityError, match="never replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO rulebook_rule (id, rule_key, standard, created_by, created_at)"
            " VALUES ('other', ?, 'S', 'x', 'x')",
            (rule["rule_key"],),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="never replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO rulebook_approval (id, rule_version_id, decision, approver_id, decided_at,"
            " provenance_viewed, tier) SELECT id, rule_version_id, 'reject', approver_id, decided_at, '[]', 'owner'"
            " FROM rulebook_approval"
        )
    conn.rollback()
    assert rulebook_v2.approval_in_force(conn, version["id"])


def test_a_written_version_is_sealed_against_new_applicability_and_exceptions():
    _compile()
    version, conn = _version(), _conn()
    source = _sources(version["id"])[0]
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        conn.execute(
            "INSERT INTO rulebook_applicability (id, rule_version_id, key_type, value, provenance_id)"
            " VALUES ('x', ?, 'service', 'invented', ?)",
            (version["id"], source),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        conn.execute(
            "INSERT INTO rulebook_exception (id, rule_version_id, condition_text, provenance_id)"
            " VALUES ('x', ?, 'invented', ?)",
            (version["id"], source),
        )
    conn.rollback()


def test_the_same_quote_read_another_way_is_a_new_version():
    _compile()
    old = _version()
    (source,) = _rows("SELECT * FROM rulebook_provenance")
    reading = rulebook_v2.Reading(
        rule_key=_rows("SELECT rule_key FROM rulebook_rule")[0]["rule_key"],
        standard=LABEL,
        requirement={
            "kind": LIMIT,
            "field": old["field"],
            "comparator": ">=",
            "value": old["value"],
            "unit": old["unit"],
        },
        strength=old["strength"],
        sentence_strength=old["sentence_strength"],
        context_flag=old["context_flag"],
        applicability=tuple(
            (r["key_type"], r["value"], r["on_page"])
            for r in _rows("SELECT * FROM rulebook_applicability")
        ),
        exceptions=(),
        provenance=source,
    )
    conn = _conn()
    with conn:
        assert rulebook_v2.append_reading(conn, reading, "test")[0] == "new_version"
    assert _version(2)["comparator"] == ">=" and _version(1) == old


def test_a_recorded_book_with_the_switch_off_records_no_run(monkeypatch):
    _compile()
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    assert rulebook_v2.record_run(_conn(), "run-1") is None
    assert _rows("SELECT * FROM rulebook_run") == []


def test_another_sentence_cannot_be_linked_to_a_written_version():
    _compile()
    version, conn = _version(), _conn()
    with pytest.raises(sqlite3.IntegrityError, match="another quote"):
        conn.execute(
            "INSERT INTO rulebook_provenance (id, rule_version_id, standard_document_id, clause, page, quote,"
            " quote_sha256, text_sha256, model, prompt_version, compile_run_id, verified_at)"
            " VALUES ('x', ?, 'd', '1', 1, 'other words', ?, 't', 'm', 'p', 'c', 'now')",
            (version["id"], "c" * 64),
        )
    conn.rollback()


def test_the_event_log_is_written_by_the_database_not_by_the_caller():
    version = _a_full_book()
    conn = _conn()
    entities = {
        (e["entity"], e["actor"])
        for e in _rows("SELECT entity, actor FROM rulebook_event")
    }
    assert ("rulebook_approval", ENGINEER) in entities
    assert {e[0] for e in entities} >= {
        "rulebook_rule",
        "rulebook_version",
        "rulebook_provenance",
        "rulebook_applicability",
        "rulebook_approval",
        "rulebook_snapshot",
        "rulebook_run",
    }
    source = Path(rulebook_v2_schema.__file__).read_text(encoding="utf-8")
    # the only inserts into the log sit inside a trigger
    assert source.count("INSERT INTO rulebook_event") == 1 and "AFTER INSERT" in source
    assert version["id"] in {
        e["entity_id"] for e in _rows("SELECT entity_id FROM rulebook_event")
    }
    assert rulebook_v2.integrity_problems(conn) == {}


def test_a_dropped_guard_is_reported():
    _compile()
    conn = _conn()
    assert rulebook_v2.integrity_problems(conn) == {}
    conn.execute("DROP TRIGGER rulebook_version_no_update")
    assert rulebook_v2.integrity_problems(conn) == {"trigger_missing": 1}


# ---------------------------------------------------------------------------------------- the requirement


def test_a_number_with_comparator_and_unit_is_a_limit():
    need = rulebook_v2_ingest.requirement_of(
        _row(limit_text="25", unit="bar", comparator="<=")
    )
    assert (need["kind"], need["comparator"], need["value"], need["unit"]) == (
        LIMIT,
        "<=",
        25.0,
        "bar",
    )
    assert need["unit_dimension"] == "pressure"


def test_a_figure_whose_sentence_prints_no_unit_says_so():
    need = rulebook_v2_ingest.requirement_of(
        _row(
            limit_text="2",
            comparator=">=",
            quote="At least 2 invented bolts shall be fitted.",
        )
    )
    assert need["kind"] == LIMIT and need["unit"] == NO_UNIT


@pytest.mark.parametrize(
    ("row", "kind"),
    [
        (_row(), NO_FIGURE),
        (_row(limit_text="painted", comparator="="), NO_FIGURE),
        (_row(limit_text="10 to 20", unit="bar"), RANGE),
        (_row(limit_text="10-20", unit="bar"), RANGE),
        (_row(limit_text="10 or 20", unit="bar"), ALTERNATIVES),
        (_row(limit_text="grade A or grade B"), ALTERNATIVES),
        (
            _row(quote="The invented valve shall comply with Invented Code 7."),
            DEFERS_TO,
        ),
    ],
)
def test_no_figure_alternatives_and_ranges_hold_no_single_figure(row, kind):
    need = rulebook_v2_ingest.requirement_of(row)
    assert need["kind"] == kind
    assert need.get("value") is None and need.get("comparator") is None


def test_a_range_holds_both_ends_and_a_defer_names_its_target():
    need = rulebook_v2_ingest.requirement_of(_row(limit_text="10 to 20", unit="bar"))
    assert (need["value_low"], need["value_high"]) == (10.0, 20.0)
    defer = rulebook_v2_ingest.requirement_of(
        _row(quote="The invented valve shall comply with Invented Code 7.")
    )
    assert defer["value_text"] == "Invented Code 7"


def test_a_number_with_an_unknown_comparator_is_never_stored_as_a_limit():
    need = rulebook_v2_ingest.requirement_of(
        _row(limit_text="25", unit="bar", comparator="about")
    )
    assert need["kind"] == NO_FIGURE and need.get("value") is None


@pytest.mark.parametrize(
    ("kind", "comparator", "value", "low", "high", "unit"),
    [
        (LIMIT, "<=", 25.0, None, None, None),  # a bare number
        (LIMIT, None, 25.0, None, None, "bar"),
        (LIMIT, "about", 25.0, None, None, "bar"),
        (NO_FIGURE, None, 25.0, None, None, None),
        (ALTERNATIVES, None, 25.0, None, None, "bar"),
        (DEFERS_TO, "<=", None, None, None, None),
        (RANGE, None, 25.0, 10.0, 20.0, "bar"),
        (RANGE, None, None, 20.0, 10.0, "bar"),
    ],
)
def test_the_table_refuses_a_requirement_of_the_wrong_shape(
    kind, comparator, value, low, high, unit
):
    conn = _conn()
    rulebook_v2.ensure_schema(conn)
    conn.execute(
        "INSERT INTO rulebook_rule (id, rule_key, standard, created_by, created_at)"
        " VALUES ('r', 'k', 'S', 'x', 'x')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO rulebook_version (id, rule_id, version_no, content_hash, quote_sha256, kind, field, comparator,"
            " value, value_low, value_high, value_text, unit, applicability_count, exception_count, recorded_by,"
            " recorded_at) VALUES ('v','r',1,?,?,?,'f',?,?,?,?,'words',?,0,0,'x','x')",
            ("a" * 64, "b" * 64, kind, comparator, value, low, high, unit),
        )
    conn.rollback()


def test_applicability_and_exceptions_are_rows_apart():
    _compile_with_exception()
    version = _version()
    assert {
        (r["key_type"], r["value"])
        for r in _rows("SELECT key_type, value FROM rulebook_applicability")
    } == {("subject", "relief flanges"), ("condition", "for gas service")}
    assert [r["condition_text"] for r in _rows("SELECT * FROM rulebook_exception")] == [
        "unless the flange is blind"
    ]
    assert (version["applicability_count"], version["exception_count"]) == (2, 1)


# ------------------------------------------------------------------------------- identity across versions


def test_provenance_holds_the_verified_quote_hash_page_model_and_prompt():
    _compile(edition="2026")
    (source,) = _rows("SELECT * FROM rulebook_provenance")
    assert source["quote"] == QUOTE and len(source["quote_sha256"]) == 64
    assert source["page"] == 1 and source["edition"] == "2026"
    assert (
        source["model"]
        and source["prompt_version"] == standards_compiler.PROMPT_VERSION
    )
    assert source["text_sha256"] and source["compile_run_id"]


def test_running_on_unchanged_text_adds_nothing():
    first = _compile()
    assert first["written"] == {"new_rule": 1}
    again = rulebook_v2_ingest.ingest_latest(_conn(), DOC)
    assert (
        again["written"] == {"unchanged": 1}
        and again["snapshot_id"] == first["snapshot_id"]
    )
    assert len(_rows("SELECT id FROM rulebook_version")) == 1
    assert len(_rows("SELECT id FROM rulebook_provenance")) == 1
    assert len(_rows("SELECT id FROM rulebook_snapshot")) == 1


def _edition_page(limit="25"):
    return (
        f"Invented edition.\n4.1 Flanges\nThe relief flange pressure shall not exceed {limit} bar for gas service.",
        PAGE_2,
    )


def test_a_new_edition_with_the_same_reading_keeps_its_rule_and_version_and_gains_a_source():
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    key = _rows("SELECT rule_key FROM rulebook_rule")[0]["rule_key"]
    done = _compile(doc="ed-2", pages=_edition_page(), edition="2026")
    assert done["written"] == {"new_source": 1}
    assert [r["rule_key"] for r in _rows("SELECT rule_key FROM rulebook_rule")] == [key]
    assert len(_rows("SELECT id FROM rulebook_version")) == 1
    assert {r["edition"] for r in _rows("SELECT edition FROM rulebook_provenance")} == {
        "2020",
        "2026",
    }


def test_a_changed_limit_appends_a_version_of_the_same_rule_and_leaves_the_old_one():
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    old = _version()
    _approve(old["id"])
    done = _compile(
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
    assert done["written"] == {"new_version": 1}
    new = _version(2)
    assert new["rule_id"] == old["rule_id"] and new["supersedes_id"] == old["id"]
    assert new["value"] == 30.0
    assert _version(1) == old
    assert len(_rows("SELECT id FROM rulebook_rule")) == 1
    # the approval stayed with the reading it was given to
    assert rulebook_v2.approval_in_force(_conn(), new["id"]) is None
    newest = _rows("SELECT id FROM rulebook_snapshot ORDER BY rowid DESC")[0]["id"]
    assert rulebook_v2.in_force(_conn(), newest) == []


def test_two_rules_on_one_field_in_one_compile_stay_two_rules():
    other = "The relief flange pressure shall not exceed 40 bar for gas service."
    done = _compile(
        pages=(_edition_page()[0], f"4.2 More\n{other}"),
        rules=[_rule(), _rule(limit="40", page=2, clause="4.2", quote=other)],
    )
    assert done["compiled_rows"] == 2 and done["written"] == {"new_rule": 2}
    assert _rows("SELECT id FROM rulebook_version WHERE version_no = 2") == []
    # and compiled again in the same order, each finds itself
    again = rulebook_v2_ingest.ingest_latest(_conn(), DOC)
    assert again["written"] == {"unchanged": 2}


def test_a_rule_not_seen_in_a_later_compile_is_not_retired():
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    version = _version()
    done = _compile(doc="ed-2", pages=_edition_page("31"), edition="2026", rules=[])
    assert done["compiled_rows"] == 0
    assert (
        _rows("SELECT rule_version_id FROM rulebook_snapshot_rule ORDER BY rowid DESC")[
            0
        ]["rule_version_id"]
        == version["id"]
    )


def test_a_quote_no_longer_on_its_page_is_dropped_and_counted():
    _document()
    standards_compiler.compile_standard(
        _conn(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )
    with _conn() as conn:
        conn.execute(
            "UPDATE pages SET text = 'Other invented words only.' WHERE document_id = ? AND page_no = 1",
            (DOC,),
        )
    done = rulebook_v2_ingest.ingest_latest(_conn(), DOC)
    assert done["dropped"] == {"quote_not_on_page": 1} and done["written"] == {}
    assert _rows("SELECT id FROM rulebook_version") == []


def test_a_quote_whose_stored_hash_differs_is_dropped_and_counted():
    _document()
    standards_compiler.compile_standard(
        _conn(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )
    with _conn() as conn:
        conn.execute("UPDATE compiled_rules SET quote_sha256 = ?", ("0" * 64,))
    done = rulebook_v2_ingest.ingest_latest(_conn(), DOC)
    assert done["dropped"] == {"quote_hash_differs": 1}


# ----------------------------------------------------------------------------------------------- approvals


def test_no_rule_is_in_force_and_no_check_decides_until_a_person_approves():
    _person()
    done = _compile()
    version = _version()
    assert rulebook_v2.in_force(_conn(), done["snapshot_id"]) == []
    assert rulebook_v2.check_version(
        _conn(), version["id"], "10", "bar"
    ) == rulebook_v2_check.Outcome(CANNOT_TELL, "not_approved")
    _approve(version["id"])
    (row,) = _rows("SELECT * FROM rulebook_approval")
    assert row["approver_id"] == ENGINEER and row["decided_at"]
    assert json.loads(row["provenance_viewed"]) == list(_sources(version["id"]))


@pytest.mark.parametrize(
    "approver", ["claude-sonnet-5-5", "compile:compile-v2", "system", ""]
)
def test_only_an_active_person_can_approve_the_database_refuses_anything_else(approver):
    _compile()
    version = _version()
    with pytest.raises(sqlite3.IntegrityError, match="active person"):
        _approve(version["id"], engineer=approver)
    assert _rows("SELECT id FROM rulebook_approval") == []


def test_a_person_no_longer_active_cannot_approve():
    _person("left", active=0)
    _compile()
    with pytest.raises(sqlite3.IntegrityError, match="active person"):
        _approve(_version()["id"], engineer="left")


def test_only_the_import_of_a_signers_ticks_decides_on_a_rule():
    callers = []
    for root in (APP, REPO / "scripts"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "record_decision" in text or "INTO rulebook_approval" in text:
                callers.append(path.name)
    assert set(callers) <= {"rulebook_v2.py", "import_rule_approvals.py"}
    assert "rulebook_v2.py" in callers


def test_an_approval_must_name_a_quote_of_this_version():
    _person()
    _compile()
    version = _version()
    for viewed in ((), ("not-a-source",)):
        with pytest.raises(rulebook_v2.RuleRefused):
            rulebook_v2.record_decision(
                _conn(),
                version["id"],
                decision=rulebook_v2.APPROVE,
                engineer_id=ENGINEER,
                tier=rulebook_v2.ENGINEER,
                equipment_type=PSV,
                provenance_viewed=viewed,
            )
    conn = _conn()
    with pytest.raises(sqlite3.IntegrityError, match="quote that was read"):
        conn.execute(
            "INSERT INTO rulebook_approval (id, rule_version_id, decision, approver_id, decided_at, provenance_viewed,"
            " tier, equipment_type) VALUES ('a', ?, 'approve', ?, 'now', '[]', 'owner', 'x')",
            (version["id"], ENGINEER),
        )
    conn.rollback()


def test_a_superseded_version_cannot_be_decided_on():
    _person()
    _compile(doc="ed-1", pages=_edition_page())
    old = _version()
    _compile(
        doc="ed-2",
        pages=_edition_page("30"),
        rules=[
            _rule(
                limit="30",
                quote="The relief flange pressure shall not exceed 30 bar for gas service.",
            )
        ],
    )
    with pytest.raises(sqlite3.IntegrityError, match="superseded"):
        _approve(old["id"])


def test_a_rule_whose_scope_sits_outside_its_sentence_needs_a_note():
    _person()
    _compile()
    conn = _conn()
    version_id = _version()["id"]
    conn.execute("DROP TRIGGER rulebook_version_no_update")
    conn.execute(
        "UPDATE rulebook_version SET strength = ? WHERE id = ?",
        (rulebook_v2.CONTEXT_DEPENDENT, version_id),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="needs a note"):
        _approve(version_id)
    assert _approve(version_id, note="the heading above scopes it to gas service")


def test_the_last_decision_stands_and_a_retired_rule_is_not_in_force():
    _person()
    _compile()
    version_id = _version()["id"]
    _approve(version_id)
    assert rulebook_v2.approval_in_force(_conn(), version_id)
    rulebook_v2.record_decision(
        _conn(),
        version_id,
        decision=rulebook_v2.RETIRE,
        engineer_id=ENGINEER,
        tier=rulebook_v2.OWNER,
    )
    assert rulebook_v2.approval_in_force(_conn(), version_id) is None


# ----------------------------------------------------------------------------------------------- snapshots


def test_a_snapshot_is_taken_per_compile_and_a_later_approval_does_not_change_it():
    _person()
    first = _compile(doc="ed-1", pages=_edition_page(), edition="2020")["snapshot_id"]
    version_id = _version()["id"]
    _approve(version_id)
    assert rulebook_v2.in_force(_conn(), first) == []
    second = _compile(doc="ed-2", pages=_edition_page(), edition="2026")["snapshot_id"]
    assert second != first
    assert rulebook_v2.in_force(_conn(), second) == [version_id]
    assert rulebook_v2.in_force(_conn(), first) == []
    hashes = [
        r["snapshot_hash"] for r in _rows("SELECT snapshot_hash FROM rulebook_snapshot")
    ]
    assert hashes[0] != hashes[1]


def test_a_run_records_version_1_and_no_snapshot_because_no_verdict_reads_version_2():
    first = _compile()["snapshot_id"]
    recorded = rulebook_v2.record_run(_conn(), "run-1")
    assert recorded == {
        "used_version": rulebook_v2.V1,
        "snapshot_id": None,
        "latest_snapshot_id": first,
    }
    # written once: asking again changes nothing and does not fail
    assert rulebook_v2.record_run(_conn(), "run-1") == recorded
    assert len(_rows("SELECT * FROM rulebook_run")) == 1


def test_a_run_that_used_a_snapshot_names_it_and_the_table_refuses_version_2_without_one():
    first = _compile()["snapshot_id"]
    recorded = rulebook_v2.record_run(_conn(), "run-2", used_snapshot_id=first)
    assert (
        recorded["used_version"] == rulebook_v2.V2 and recorded["snapshot_id"] == first
    )
    conn = _conn()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO rulebook_run (review_run_id, used_version, recorded_at) VALUES ('r', 2, 'now')"
        )
    conn.rollback()


# ---------------------------------------------------------------------------------------- the three outcomes


_LIMIT = {"kind": LIMIT, "comparator": "<=", "value": 25.0, "unit": "bar"}
_RANGE_RULE = {"kind": RANGE, "value_low": 10.0, "value_high": 20.0, "unit": "bar"}


def test_there_are_exactly_three_outcomes():
    assert set(rulebook_v2_check.OUTCOMES) == {MEETS, DOES_NOT_MEET, CANNOT_TELL}


@pytest.mark.parametrize(
    ("rule", "value", "unit", "outcome", "reason"),
    [
        (_LIMIT, "25", "bar", MEETS, "compared"),
        (_LIMIT, "26", "bar", DOES_NOT_MEET, "compared"),
        (_LIMIT, 10, "BAR", MEETS, "compared"),
        (_LIMIT, None, None, CANNOT_TELL, "not_mentioned"),
        (_LIMIT, "   ", "bar", CANNOT_TELL, "not_mentioned"),
        (_LIMIT, "tbd", "bar", CANNOT_TELL, "value_unclear"),
        (_LIMIT, "25", None, CANNOT_TELL, "units_not_comparable"),
        (_LIMIT, "25", "mm", CANNOT_TELL, "units_not_comparable"),
        (_LIMIT, "1000", "kPa", MEETS, "compared"),
        (_LIMIT, "4000", "kPa", DOES_NOT_MEET, "compared"),
        (_RANGE_RULE, "15", "bar", MEETS, "compared"),
        (_RANGE_RULE, "21", "bar", DOES_NOT_MEET, "compared"),
        (_RANGE_RULE, "9", "bar", DOES_NOT_MEET, "compared"),
        (_RANGE_RULE, None, "bar", CANNOT_TELL, "not_mentioned"),
        ({"kind": NO_FIGURE}, "anything", None, CANNOT_TELL, NO_FIGURE),
        ({"kind": ALTERNATIVES}, "10", "bar", CANNOT_TELL, ALTERNATIVES),
        ({"kind": DEFERS_TO}, "yes", None, CANNOT_TELL, DEFERS_TO),
        (
            {"kind": LIMIT, "comparator": ">=", "value": 2.0, "unit": NO_UNIT},
            "3",
            None,
            MEETS,
            "compared",
        ),
        (
            {"kind": LIMIT, "comparator": ">=", "value": 2.0, "unit": NO_UNIT},
            "3",
            "bar",
            CANNOT_TELL,
            "units_not_comparable",
        ),
        (
            {"kind": LIMIT, "comparator": "!=", "value": 2.0, "unit": "bar"},
            "2",
            "kPa",
            CANNOT_TELL,
            "units_not_comparable",
        ),
    ],
)
def test_the_outcome_of_one_requirement(rule, value, unit, outcome, reason):
    got = check_requirement(rule, value, unit)
    assert (got.outcome, got.reason) == (outcome, reason)


def test_a_rule_reads_who_it_is_for_then_unless_then_what_it_demands():
    _person()
    _compile_with_exception()
    version_id = _version()["id"]
    _approve(version_id)
    conn = _conn()
    applies = {r["id"]: True for r in _rows("SELECT id FROM rulebook_applicability")}
    (exception,) = [r["id"] for r in _rows("SELECT id FROM rulebook_exception")]

    def outcome(**kw):
        got = rulebook_v2.check_version(conn, version_id, "26", "bar", **kw)
        return got.outcome, got.reason

    assert outcome() == (CANNOT_TELL, "applicability_unknown")
    one_false = dict(applies) | {next(iter(applies)): False}
    assert outcome(applies=one_false) == (None, "does_not_apply")
    assert outcome(applies=applies) == (CANNOT_TELL, "exception_unknown")
    assert outcome(applies=applies, excepted={exception: True}) == (None, "excepted")
    assert outcome(applies=applies, excepted={exception: False}) == (
        DOES_NOT_MEET,
        "compared",
    )


# ------------------------------------------------------------------------------- version 1 and the verdicts


_RULEBOOK_NAME = re.compile(
    r"\brulebook_(?:rule|version|provenance|applicability|exception|approval|snapshot|run|event)\b"
)
_OURS = {"rulebook_v2.py", "rulebook_v2_ingest.py", "rulebook_v2_schema.py"}
_V1_WRITE = re.compile(
    r"(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+standard_requirements\b"
)


def test_only_the_rulebook_modules_name_its_tables():
    named = {
        p.name
        for p in APP.rglob("*.py")
        if _RULEBOOK_NAME.search(p.read_text(encoding="utf-8"))
    }
    assert named == _OURS


def test_no_route_retrieval_or_verdict_module_imports_the_rulebook():
    imports = re.compile(
        r"\b(?:from\s+[.\w]*\s+import\s+[^\n]*|import\s+[^\n]*)\brulebook_v2"
    )
    importers = {
        str(p.relative_to(APP))
        for p in APP.rglob("*.py")
        if p.name not in {*_OURS, "rulebook_v2_check.py"}
        and imports.search(p.read_text(encoding="utf-8"))
    }
    # the report's counts, and (when added) the compiler's two seams; both only write the book or count it
    assert importers <= {"compiled_rule_report.py", "standards_compiler.py"}
    assert "compiled_rule_report.py" in importers


def _written_tables(conn, action):
    written = set()
    writes = (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)

    def spy(code, first, _second, _db, _trigger):
        if code in writes:
            written.add(first)
        return sqlite3.SQLITE_OK

    conn.set_authorizer(spy)
    try:
        action()
    finally:
        conn.set_authorizer(None)
    return written


def test_the_migration_and_the_ingest_write_only_the_rulebook():
    _document()
    made = standards.create_requirement(
        standard_document_id=DOC,
        chunk_id=f"c-{DOC}",
        requirement_text=QUOTE,
        source_text=QUOTE,
        clause="4.1",
        page=1,
        structured={"requirement_type": "statement"},
    )
    standards_compiler.compile_standard(
        _conn(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )

    def v1():
        return [dict(r) for r in _conn().execute("SELECT * FROM standard_requirements")]

    before = v1()
    conn = _conn()
    written = _written_tables(conn, lambda: rulebook_v2_ingest.ingest_latest(conn, DOC))
    assert written and all(
        t.startswith("rulebook_")
        or t in ("sqlite_master", "sqlite_sequence", "sqlite_temp_master")
        for t in written
    )
    assert v1() == before and before[0]["id"] == made["id"]


def test_no_new_module_writes_version_1():
    """The writers version 1 has today are the app's own, reviewed and off this path. A new one fails here."""
    writers = set()
    for root in (APP, REPO / "scripts"):
        for path in root.rglob("*.py"):
            if "mutations" in path.parts:
                continue
            if _V1_WRITE.search(path.read_text(encoding="utf-8")):
                writers.add(path.name)
    assert writers == {
        "ai_requirement_chunks.py",
        "ai_requirements.py",
        "orphan_guard.py",
        "reader_score_standard.py",
        "reextract_rule_equipment_scope.py",
        "rule_equipment_scope.py",
        "rule_eval.py",
        "standards.py",
    }


_VOLATILE = {"id", "review_run_id", "created_at", "updated_at"}


def _findings(result):
    keep = sorted(k for k in result["findings"][0] if k not in _VOLATILE)
    return sorted(
        json.dumps({k: f.get(k) for k in keep}, sort_keys=True, default=str)
        for f in result["findings"]
    )


def test_a_filled_rulebook_changes_no_verdict_and_a_review_reads_none_of_it(
    monkeypatch,
):
    _req, _fact, run, scope = _world("Set pressure", "10 barg")
    before = comparison.run_comparison(run, allowed_document_ids=scope)
    outcome_before = _rows("SELECT status FROM review_runs WHERE id = ?", run)
    _person()
    _compile(doc="std-book", label="SAES-Z-901")
    _approve(_version()["id"])  # even an approved rule is not read
    conn = _conn()
    read = set()

    def spy(code, first, _second, _db, _trigger):
        if code == sqlite3.SQLITE_READ:
            read.add(first)
        return sqlite3.SQLITE_OK

    conn.set_authorizer(spy)
    try:
        after = comparison.run_comparison(run, allowed_document_ids=scope)
    finally:
        conn.set_authorizer(None)
    assert read, "the spy saw the review's reads"
    assert not {t for t in read if t.startswith("rulebook_")}
    assert before["findings"] and _findings(after) == _findings(before)
    assert _rows("SELECT status FROM review_runs WHERE id = ?", run) == outcome_before


# ---------------------------------------------------------------------------------------- the v1 vs v2 proof


def _four_standards():
    docs = {}
    for n in range(1, 5):
        doc, label = f"std-{n}", f"SAES-Z-90{n}"
        _document(doc_id=doc, number=label)
        standards_compiler.compile_standard(
            _conn(), doc, label, client=FakeBatches([_rule()]), sleep=lambda _s: None
        )
        docs[doc] = label
    return docs


def test_switch_off_the_side_by_side_table_is_what_it_was(monkeypatch):
    docs = _four_standards()
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    table = compiled_rule_report.side_by_side(_conn(), docs)
    assert all("rulebook_v2" not in row for row in table["per_standard"])


def test_the_script_proves_four_standards_at_no_cost_and_prints_no_document_text(
    tmp_path,
):
    docs = _four_standards()
    said = []
    assert rulebook_script.run(settings.db_path, sorted(docs), emit=said.append) == 0
    line = said[0]
    proof = json.loads(line)
    assert QUOTE not in line and "gas service" not in line and "relief" not in line
    assert proof["integrity_problems"] == {}
    rows = proof["side_by_side"]["per_standard"]
    assert len(rows) == 4
    for row in rows:
        book = row["rulebook_v2"]
        assert book["rules"] == 1 and book["versions"] == 1
        assert (
            book["applicability_rows"] == 2 and book["versions_with_applicability"] == 1
        )
        assert book["sources"] == book["sources_quote_verified"] == 1
        assert book["versions_approved"] == 0 and book["boundary"]
        assert book["last_ingest"]["dropped"] == {}
        assert book["last_ingest"]["proof_proposed"] == 1
        assert row["v1"]["rules"] == 0
    assert proof["ingested"]["SAES-Z-901"]["written"] == {"new_rule": 1}
    # the same words in another standard are another rule: identity carries the standard's name
    assert len(_rows("SELECT id FROM rulebook_rule")) == 4


def test_the_script_is_found_and_says_how_to_use_it():
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "rulebook_v2.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0 and "--migrate-only" in done.stdout


def test_the_compilers_seam_fills_the_book_on_and_does_nothing_off(monkeypatch):
    _document()
    standards_compiler.compile_standard(
        _conn(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    rulebook_v2_ingest.after_compile(_conn(), DOC)
    assert not rulebook_v2.has_schema(_conn())
    monkeypatch.setattr(settings, "rulebook_v2_enabled", True)
    rulebook_v2_ingest.after_compile(_conn(), DOC)
    assert len(_rows("SELECT id FROM rulebook_rule")) == 1


# ------------------------------------------------------------------------- the contract for a review (piece 3)


CONTRACT_KEYS = {
    "rule_id",
    "version",
    "field",
    "comparator",
    "value",
    "unit",
    "applies_to",
    "conditions",
    "exceptions",
    "clause",
    "page",
    "quote",
    "quote_sha256",
    "standard",
    "edition",
    "context_flag",
    "strength",
    "approval",
}


def _decide(version_id, decision, equipment_type=PSV, tier=rulebook_v2.ENGINEER):
    return rulebook_v2.record_decision(
        _conn(),
        version_id,
        decision=decision,
        engineer_id=ENGINEER,
        tier=tier,
        equipment_type=equipment_type,
        provenance_viewed=_sources(version_id),
    )


def test_an_approved_rule_comes_out_with_every_field_of_the_contract():
    _person()
    _compile_with_exception()
    version = _version()
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET display_name = 'An Invented Signer' WHERE id = ?",
            (ENGINEER,),
        )
    _decide(version["id"], rulebook_v2.APPROVE, tier=rulebook_v2.OWNER)
    (rule,) = rulebook_v2.approved_rules(_conn(), PSV)
    assert set(rule) == CONTRACT_KEYS
    assert rule["rule_id"] == version["rule_id"] and rule["version"] == 1
    assert (rule["comparator"], rule["value"], rule["unit"]) == ("<=", 25.0, "bar")
    assert rule["applies_to"] == "relief flanges"
    assert rule["conditions"] == ["for gas service"]
    assert rule["exceptions"] == ["unless the flange is blind"]
    assert (rule["clause"], rule["page"], rule["quote"]) == ("4.1", 1, QUOTE)
    assert len(rule["quote_sha256"]) == 64 and rule["standard"] == LABEL
    assert rule["strength"] == version["strength"]
    assert "context_flag" in rule and "edition" in rule
    assert set(rule["approval"]) == {"by", "at", "tier"}
    assert rule["approval"]["by"] == "An Invented Signer"
    assert rule["approval"]["tier"] == rulebook_v2.OWNER and rule["approval"]["at"]


def test_an_unapproved_rule_never_comes_out():
    _person()
    _compile()
    assert rulebook_v2.approved_rules(_conn(), PSV) == []


def test_an_approval_covers_only_its_equipment_type_whatever_the_spelling():
    _person()
    _compile()
    _decide(_version()["id"], rulebook_v2.APPROVE)
    assert rulebook_v2.approved_rules(_conn(), "An Invented Pump") == []
    assert rulebook_v2.approved_rules(_conn(), "") == []
    assert len(rulebook_v2.approved_rules(_conn(), f"  {PSV.upper()} ")) == 1


def test_a_superseded_rule_never_comes_out_and_its_new_reading_waits_for_a_person():
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    old = _version()
    _decide(old["id"], rulebook_v2.APPROVE)
    assert [r["version"] for r in rulebook_v2.approved_rules(_conn(), PSV)] == [1]
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
    assert rulebook_v2.approved_rules(_conn(), PSV) == []
    new = _version(2)
    _decide(new["id"], rulebook_v2.APPROVE)
    (rule,) = rulebook_v2.approved_rules(_conn(), PSV)
    assert (rule["version"], rule["value"]) == (2, 30.0)


def test_the_last_decision_for_a_type_stands_and_another_types_decision_does_not_touch_it():
    _person()
    _compile()
    version_id = _version()["id"]
    _decide(version_id, rulebook_v2.APPROVE)
    _decide(version_id, rulebook_v2.REJECT, equipment_type="An Invented Pump")
    assert len(rulebook_v2.approved_rules(_conn(), PSV)) == 1
    _decide(version_id, rulebook_v2.REJECT)
    assert rulebook_v2.approved_rules(_conn(), PSV) == []
    _decide(version_id, rulebook_v2.APPROVE)
    assert len(rulebook_v2.approved_rules(_conn(), PSV)) == 1
    _decide(version_id, rulebook_v2.RETIRE, equipment_type=None)
    assert rulebook_v2.approved_rules(_conn(), PSV) == []


def test_switch_off_or_no_tables_no_rule_comes_out(monkeypatch):
    assert rulebook_v2.approved_rules(_conn(), PSV) == []
    assert not rulebook_v2.has_schema(_conn())
    _person()
    _compile()
    _decide(_version()["id"], rulebook_v2.APPROVE)
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    assert rulebook_v2.approved_rules(_conn(), PSV) == []


@pytest.mark.parametrize(
    ("tier", "equipment_type", "decision"),
    [
        (None, PSV, "approve"),
        ("system", PSV, "approve"),
        ("owner", None, "approve"),
        ("owner", "  ", "approve"),
        (None, None, "retire"),
    ],
)
def test_the_database_refuses_a_decision_with_no_tier_or_an_approval_with_no_type(
    tier, equipment_type, decision
):
    _person()
    _compile()
    version_id = _version()["id"]
    with pytest.raises(sqlite3.IntegrityError):
        rulebook_v2.record_decision(
            _conn(),
            version_id,
            decision=decision,
            engineer_id=ENGINEER,
            tier=tier,
            equipment_type=equipment_type,
            provenance_viewed=_sources(version_id),
        )
    assert _rows("SELECT id FROM rulebook_approval") == []


def test_a_copy_made_before_the_tier_columns_is_brought_up_to_date():
    conn = _conn()
    rulebook_v2.ensure_schema(conn)
    fresh = sorted(r[1] for r in conn.execute("PRAGMA table_info(rulebook_approval)"))
    # the shape the first copies have: no tier column, none of the guards that read it
    for name in ("rulebook_approval_signed", "rulebook_approval_event"):
        conn.execute(f"DROP TRIGGER {name}")
    for column in ("tier", "equipment_type", "approver_name", "source_sha256"):
        conn.execute(f"ALTER TABLE rulebook_approval DROP COLUMN {column}")
    conn.commit()
    conn.execute("DROP TRIGGER rulebook_compiled_row_no_update")
    conn.commit()
    rulebook_v2.ensure_schema(conn)
    assert (
        sorted(r[1] for r in conn.execute("PRAGMA table_info(rulebook_approval)"))
        == fresh
    )
    assert rulebook_v2.integrity_problems(conn) == {}


def test_each_compiled_row_names_the_version_it_became():
    done = _compile()
    (row,) = _rows("SELECT * FROM rulebook_compiled_row")
    assert row["rule_version_id"] == _version()["id"]
    assert row["compiled_row_id"] == _rows("SELECT id FROM compiled_rules")[0]["id"]
    assert (
        rulebook_v2_ingest.ingest_latest(_conn(), DOC)["snapshot_id"]
        == done["snapshot_id"]
    )
    assert len(_rows("SELECT * FROM rulebook_compiled_row")) == 1
