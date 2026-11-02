# ruff: noqa: F811 - pytest fixtures imported by name
"""#1608 (plan change 6 G): every review run records its models, its rulebook and the ticks imported, and the internal
CRS carries them with the could-not-check list on a sheet of its own. Switch off: nothing changes.

Invented documents and ticks, no model called.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app import crs_export, db, run_record
from app import main as main_mod
from app.config import settings
from tests.test_633_honest_exports import (  # noqa: F401 - fixtures
    _completed_run,
    _failed_run,
    temp_storage,
    world,
)

#: The shape the local checklist importer writes (`import_ticks.py`, not in git).
TICKS_SQL = """CREATE TABLE checklist_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT NOT NULL, standard TEXT NOT NULL,
    version_stamp TEXT NOT NULL, tick TEXT, comment TEXT, engineer TEXT NOT NULL, imported_at TEXT NOT NULL,
    source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL, UNIQUE (rule_id, source_sha256))"""


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "run_record_enabled", True)


def _stored(run_id: str) -> dict:
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["outcome_json"] or "{}")


def _book(world, run_id, copy="internal"):
    rows, meta, _name, _stamp = main_mod._crs_content(run_id, world["access"], copy)
    return openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(rows, meta)))


def _lines(world, run_id) -> dict[str, list[str]]:
    """The Run record sheet as {section: [detail, ...]}."""
    out: dict[str, list[str]] = {}
    sheet = _book(world, run_id)[run_record.SHEET]
    for section, _item, detail in list(sheet.iter_rows(values_only=True))[1:]:
        out.setdefault(section, []).append(detail)
    return out


def _tick(rule, tick, *, stamp="s1", sha="f1", std="SECRET-STD", who="An Engineer"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO checklist_ticks (rule_id, standard, version_stamp, tick, comment, engineer, imported_at,"
            " source_file, source_sha256) VALUES (?,?,?,?,NULL,?,?,?,?)",
            (
                rule,
                std,
                stamp,
                tick,
                who,
                "2026-11-02T10:00:00+00:00",
                "secret-file.xlsx",
                sha,
            ),
        )


def _make_ticks():
    with db.connect() as conn:
        conn.execute(TICKS_SQL)


# ---------------------------------------------------------------------- switch off


def test_off_the_run_stores_nothing_and_the_workbook_has_no_new_sheet(world):
    run_id = _completed_run(world)
    assert "run_record" not in _stored(run_id)
    _rows, meta, _name, _stamp = main_mod._crs_content(
        run_id, world["access"], "internal"
    )
    assert "run_record" not in meta
    assert run_record.SHEET not in _book(world, run_id).sheetnames


# ---------------------------------------------------------------------- the rulebook


def test_the_run_records_how_many_rules_it_applied_and_their_fingerprint(world, on):
    run_id = _completed_run(world)
    book = _stored(run_id)["run_record"]["rulebook"]
    count = (
        db.connect()
        .execute(
            "SELECT COUNT(*) AS n FROM standard_requirements r JOIN review_applicable_standards a"
            " ON a.standard_document_id = r.standard_document_id WHERE a.review_run_id = ?"
            " AND COALESCE(a.included, 1) = 1",
            (run_id,),
        )
        .fetchone()["n"]
    )
    assert count > 0  # positive control
    assert book["rules"] == count
    assert book["used_version"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", book["rules_sha256"])
    assert book["boundary"] == "the standards applied to this run"
    assert book["review_code"].startswith("review@")


def test_the_fingerprint_is_the_rules_words_not_their_ids_or_times(world, on):
    run_id = _completed_run(world)
    first = run_record._rules_of(db.connect(), run_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET updated_at = '2030-01-01T00:00:00Z'"
        )
    assert run_record._rules_of(db.connect(), run_id) == first
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET requirement_text = requirement_text || ' changed'"
        )
    assert run_record._rules_of(db.connect(), run_id)[1] != first[1]


def test_a_rule_of_a_standard_the_run_did_not_apply_is_not_in_its_record(world, on):
    run_id = _completed_run(world)
    first = run_record._rules_of(db.connect(), run_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_applicable_standards SET included = 0 WHERE review_run_id = ?",
            (run_id,),
        )
    assert first[0] > 0
    assert run_record._rules_of(db.connect(), run_id)[0] == 0


def test_the_crs_prints_what_the_run_stored_not_todays_rules(world, on):
    run_id = _completed_run(world)
    fingerprint = _stored(run_id)["run_record"]["rulebook"]["rules_sha256"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET requirement_text = requirement_text || ' changed'"
        )
    text = " ".join(_lines(world, run_id)["Rulebook"])
    assert fingerprint[:16] in text
    assert "Version 1" in text
    assert "the standards applied to this run" in text


def test_a_version_2_record_names_its_version_and_snapshot(world, on):
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE rulebook_snapshot (id TEXT PRIMARY KEY, snapshot_hash TEXT)"
        )
        conn.execute(
            "CREATE TABLE rulebook_run (review_run_id TEXT PRIMARY KEY, used_version INTEGER, snapshot_id TEXT)"
        )
        conn.execute("INSERT INTO rulebook_snapshot VALUES ('snap1', ?)", ("ab" * 32,))
    run_id = _completed_run(world)
    with db.connect() as conn:
        conn.execute("INSERT INTO rulebook_run VALUES (?, 2, 'snap1')", (run_id,))
    run_record.record_on_run(run_id)
    book = _stored(run_id)["run_record"]["rulebook"]
    assert book["used_version"] == 2
    assert book["snapshot_sha256"] == "ab" * 32
    text = " ".join(_lines(world, run_id)["Rulebook"])
    assert "Version 2" in text and ("ab" * 8) in text


def test_a_run_stored_before_the_switch_says_not_recorded_and_guesses_nothing(
    world,
    monkeypatch,
):
    run_id = _completed_run(world)  # switch off: no record
    monkeypatch.setattr(settings, "run_record_enabled", True)
    lines = _lines(world, run_id)
    assert lines["Rulebook"] == [run_record.NOT_RECORDED]
    assert lines["Checklist ticks"] == [run_record.NOT_RECORDED]


def test_a_failure_writing_the_record_never_fails_the_review(world, on, monkeypatch):
    def boom(*_a, **_k):
        raise sqlite3.OperationalError("nope")

    monkeypatch.setattr(run_record, "_rules_of", boom)
    run_id = _completed_run(world)  # asserts the run completed
    assert "run_record" not in _stored(run_id)
    assert _lines(world, run_id)["Rulebook"] == [run_record.NOT_RECORDED]


# ---------------------------------------------------------------------- the model


def _set_models(run_id, *, name=None, ai=None, matcher=None):
    outcome = _stored(run_id)
    if matcher is not None:
        outcome["ai_matcher"] = matcher
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET model_name = ?, ai_check_status = ?, outcome_json = ? WHERE id = ?",
            (name, json.dumps(ai) if ai else None, json.dumps(outcome), run_id),
        )


def test_every_stored_model_of_the_run_is_listed_local_and_claude(world, on):
    from app import model_metrics

    run_id = _completed_run(world)
    _set_models(
        run_id,
        name="cloud-a, cloud-b",
        ai={"model": "cloud-c"},
        matcher={"enabled": True, "model": "ollama:local-m", "asked": 2},
    )
    bucket = {
        "local-z": {
            "calls": 1,
            "errors": 0,
            "seconds": 1.0,
            "longest": 1.0,
            "kinds": {},
        }
    }
    model_metrics.store(run_id, bucket)
    text = _lines(world, run_id)["Model"][0]
    for name in ("cloud-a", "cloud-b", "cloud-c", "ollama:local-m", "local-z"):
        assert name in text


def test_a_model_only_configured_is_never_named(world, on, monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "only-configured")
    run_id = _completed_run(world)
    _set_models(
        run_id, matcher={"enabled": True, "model": "ollama:only-configured", "asked": 0}
    )
    assert _lines(world, run_id)["Model"] == [run_record.NO_MODEL]


def test_an_unreadable_ledger_says_so_as_a_could_not_check_line(world, on):
    from app.claude_models import LEDGER_UNREADABLE

    run_id = _completed_run(world)
    _set_models(run_id, name=LEDGER_UNREADABLE)
    lines = _lines(world, run_id)
    assert lines["Model"] == [LEDGER_UNREADABLE]
    assert LEDGER_UNREADABLE in " ".join(lines["Could not check"])


# ---------------------------------------------------------------------- the ticks


def test_no_tick_table_says_none_and_the_read_creates_nothing(world, on):
    run_id = _completed_run(world)
    assert _stored(run_id)["run_record"]["ticks"] == {"imported": None}
    assert _lines(world, run_id)["Checklist ticks"] == [run_record.NO_TICKS]
    found = (
        db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = 'checklist_ticks'")
        .fetchone()
    )
    assert found is None


def test_ticks_are_counted_by_their_own_words_with_files_and_stamps(world, on):
    _make_ticks()
    _tick("r1", "Checked OK")
    _tick("r2", "Checked OK")
    _tick("r3", "Wrong", stamp="s2", sha="f2")
    _tick("r4", None, stamp="s2", sha="f2")  # a comment with no tick is no tick
    run_id = _completed_run(world)
    ticks = _stored(run_id)["run_record"]["ticks"]
    assert ticks["imported"] == 3
    assert ticks["by_tick"] == {"Checked OK": 2, "Wrong": 1}
    assert (ticks["files"], ticks["version_stamps"]) == (2, 2)
    text = " ".join(_lines(world, run_id)["Checklist ticks"])
    assert "3 tick(s) imported from 2 file(s)" in text
    assert "Checked OK: 2" in text and "Wrong: 1" in text
    assert "no verdict reads them" in text


def test_the_sheet_names_no_standard_file_or_person_from_a_tick(world, on):
    _make_ticks()
    _tick("r1", "Checked OK")
    text = str(_lines(world, _completed_run(world)))
    for private in ("SECRET-STD", "secret-file", "An Engineer"):
        assert private not in text


def test_an_empty_tick_table_is_not_a_tick(world, on):
    _make_ticks()
    run_id = _completed_run(world)
    assert _lines(world, run_id)["Checklist ticks"] == [run_record.NO_TICKS]


def test_a_tick_table_that_cannot_be_read_is_a_could_not_check_line_never_zero(
    world,
    on,
):
    with db.connect() as conn:
        conn.execute("CREATE TABLE checklist_ticks (other TEXT)")
    run_id = _completed_run(world)
    assert _stored(run_id)["run_record"]["ticks"] == {"unreadable": True}
    lines = _lines(world, run_id)
    assert lines["Checklist ticks"] == [run_record.TICKS_UNREADABLE]
    assert run_record.TICKS_UNREADABLE in " ".join(lines["Could not check"])


def test_decisions_signed_into_the_rulebook_are_counted_apart(world, on):
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE rulebook_approval (id TEXT PRIMARY KEY, decision TEXT)"
        )
        conn.execute(
            "INSERT INTO rulebook_approval VALUES ('a', 'approve'), ('b', 'approve'), ('c', 'reject')"
        )
    run_id = _completed_run(world)
    assert _stored(run_id)["run_record"]["ticks"]["signed"] == {
        "approve": 2,
        "reject": 1,
    }
    assert "approve: 2" in " ".join(_lines(world, run_id)["Checklist ticks"])


def test_only_this_module_reads_the_tick_table_so_no_verdict_can():
    app = Path(run_record.__file__).parent
    readers = [
        p.name
        for p in app.rglob("*.py")
        if "checklist_ticks" in p.read_text(encoding="utf-8")
    ]
    assert readers == ["run_record.py"]


# ---------------------------------------------------------------------- the could-not-check list


def test_a_completed_run_with_nothing_listed_says_that_and_what_it_does_not_mean(
    world,
    on,
    monkeypatch,
):
    monkeypatch.setattr(main_mod.absence_mod, "unchecked_parts", lambda **_k: [])
    monkeypatch.setattr(main_mod, "_missing_references", lambda *_a: [])
    run_id = _completed_run(world)
    assert _lines(world, run_id)["Could not check"] == [run_record.NOTHING_LISTED]


def test_every_part_is_listed_with_the_count_the_notice_gives(world, on, monkeypatch):
    parts = [
        {"part": "a", "line": "Part a line.", "note": "Not checked"},
        {"part": "b", "line": "Part b line.", "note": "Not checked"},
        {
            "part": "c",
            "line": "Part c explains.",
            "note": "Not checked",
            "detail": True,
        },
    ]
    monkeypatch.setattr(main_mod.absence_mod, "unchecked_parts", lambda **_k: parts)
    run_id = _completed_run(world)
    listed = _lines(world, run_id)["Could not check"]
    assert listed[0].startswith("2 part(s) of this review run could not be checked")
    assert main_mod.absence_mod.notice_for(parts).startswith(
        "REVIEW INCOMPLETE: 2 part(s)"
    )
    for line in ("Part a line.", "Part b line.", "Part c explains."):
        assert line in listed


def test_a_failed_run_lists_why_and_says_its_record_was_not_made(world, on):
    run_id = _failed_run(world)
    lines = _lines(world, run_id)
    assert "the model host went away" in " ".join(lines["Could not check"])
    assert lines["Rulebook"] == [run_record.NOT_RECORDED]


def test_a_cited_standard_not_held_is_on_the_list_by_name(world, on):
    run_id = _completed_run(world)
    listed = " ".join(_lines(world, run_id)["Could not check"])
    assert "API 682" in listed and "not in the library" in listed


# ---------------------------------------------------------------------- the copies


def test_the_issue_copy_has_no_run_record_even_when_meta_carries_one(world, on):
    run_id = _completed_run(world)
    assert run_record.SHEET not in _book(world, run_id, "issue").sheetnames
    rows, meta, _name, _stamp = main_mod._crs_content(
        run_id, world["access"], "internal"
    )
    assert meta["run_record"]
    issue = {**meta, "copy": "issue"}
    workbook = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(rows, issue)))
    assert run_record.SHEET not in workbook.sheetnames


def test_the_internal_copy_has_the_sheet_with_every_section(world, on):
    lines = _lines(world, _completed_run(world))
    assert set(lines) == {"Model", "Rulebook", "Checklist ticks", "Could not check"}


def test_the_issue_copy_never_builds_the_record(world, on):
    _rows, meta, _name, _stamp = main_mod._crs_content(
        _completed_run(world), world["access"], "issue"
    )
    assert "run_record" not in meta


def test_a_model_whose_every_call_failed_is_not_named(world, on):
    from app import model_metrics

    run_id = _completed_run(world)
    bucket = {
        "failed-m": {
            "calls": 2,
            "errors": 2,
            "seconds": 1.0,
            "longest": 1.0,
            "kinds": {},
        }
    }
    model_metrics.store(run_id, bucket)
    assert _lines(world, run_id)["Model"] == [run_record.NO_MODEL]


def test_the_wording_model_is_named_only_when_it_tried(world, on):
    from app import crs_wording

    run_id = _completed_run(world)
    crs_wording.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO crs_ai_wording_runs VALUES (?, ?, '2026-11-02T00:00:00Z')",
            (run_id, json.dumps({"model": "wording-m", "tried": 0})),
        )
    assert _lines(world, run_id)["Model"] == [run_record.NO_MODEL]
    with db.connect() as conn:
        conn.execute(
            "UPDATE crs_ai_wording_runs SET summary = ? WHERE review_run_id = ?",
            (json.dumps({"model": "wording-m", "tried": 3}), run_id),
        )
    assert _lines(world, run_id)["Model"] == ["wording-m"]


def test_the_sheet_survives_the_export_quality_path(world, on, monkeypatch):
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    assert "Could not check" in _lines(world, _completed_run(world))
