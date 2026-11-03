"""STEP 5 (#805), rulebook book versions: every change is numbered, any version restores in one verified, logged step on
a copy. Invented standards only; the compiler's fake batches; a temporary database copy."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db, live_guard, rulebook_v2, rulebook_v2_book
from app.config import settings
from tests.test_805_rulebook_v2 import (
    ENGINEER,
    _approve,
    _compile,
    _conn,
    _edition_page,
    _person,
    _rows,
    _rule,
    _version,
    lane,  # noqa: F401 - autouse: a temporary copy
    switched_on,  # noqa: F401 - autouse: the rulebook switch on
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rulebook_book

PSV = "Invented Relief Device"
THIRTY = _rule(
    limit="30",
    quote="The relief flange pressure shall not exceed 30 bar for gas service.",
)


def _approve_as_the_import_does(version_id):
    _approve(version_id)
    with _conn() as conn:
        rulebook_v2_book.mark_change(conn, ENGINEER, "approvals")


def _three_books():
    """Book 1: a rule, unapproved. Book 2: the same, approved. Book 3: a changed limit (version 2, unapproved)."""
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    _approve_as_the_import_does(_version()["id"])
    _compile(doc="ed-2", pages=_edition_page("30"), edition="2026", rules=[THIRTY])


def _served():
    return [
        (r["version"], r["value"]) for r in rulebook_v2.approved_rules(_conn(), PSV)
    ]


def test_every_change_to_the_book_gets_the_next_number_and_a_non_change_gets_none():
    _person()
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")
    assert [b["book_no"] for b in rulebook_v2_book.books(_conn())] == [1]
    _compile(doc="ed-1", pages=_edition_page(), edition="2020")  # nothing changed
    assert len(rulebook_v2_book.books(_conn())) == 1
    _approve_as_the_import_does(_version()["id"])  # the approval is a change of its own
    _compile(doc="ed-2", pages=_edition_page("30"), edition="2026", rules=[THIRTY])
    got = rulebook_v2_book.books(_conn())
    assert [b["book_no"] for b in got] == [1, 2, 3]
    assert [b["rules_in_force"] for b in got] == [0, 1, 0]
    assert all(b["restored_from_book"] is None for b in got)


def test_a_review_runs_own_snapshot_is_not_a_book_version():
    _three_books()
    with _conn() as conn:
        rulebook_v2.take_snapshot(
            conn, "review:r1", "review_run", {"review_run": 1}, "review:r1"
        )
    assert len(rulebook_v2_book.books(_conn())) == 3


def test_restoring_an_earlier_book_serves_the_rule_as_it_stood_and_release_returns_to_the_newest():
    _three_books()
    assert (
        _served() == []
    )  # the newest reading waits for a person: absent, not served from the old one
    done = rulebook_v2_book.restore_book(
        _conn(), 2, "the owner", "the 30 bar reading is not approved yet"
    )
    assert done["restored_book"] == 2 and done["new_book_no"] == 4
    assert _served() == [(1, 25.0)]
    assert rulebook_v2_book.books(_conn())[-1]["restored_from_book"] == 2
    assert (
        rulebook_v2_book.books(_conn())[-1]["hash"]
        == rulebook_v2_book.books(_conn())[1]["hash"]
    )
    # the old versions and the newest one are all still there
    assert [
        r["version_no"]
        for r in _rows("SELECT version_no FROM rulebook_version ORDER BY version_no")
    ] == [1, 2]
    assert rulebook_v2_book.release_pin(
        _conn(), "the owner", "approved the 30 bar reading elsewhere"
    ) == {"released": True}
    assert _served() == []
    assert rulebook_v2_book.active_pin(_conn()) is None


def test_a_restore_pins_the_snapshot_a_review_takes_to_the_restored_versions():
    _three_books()
    newest = _version(2)["id"]
    assert newest in [r[0] for r in rulebook_v2._current_versions(_conn())]
    rulebook_v2_book.restore_book(_conn(), 2, "the owner", "back to the approved book")
    ids = [r[0] for r in rulebook_v2._current_versions(_conn())]
    assert ids == [_version(1)["id"]] and newest not in ids


def test_a_restore_is_logged_with_who_why_and_the_book_hash():
    _three_books()
    rulebook_v2_book.restore_book(_conn(), 1, "the owner", "a drill")
    rows = _rows("SELECT * FROM rulebook_restore")
    assert len(rows) == 1 and (rows[0]["actor"], rows[0]["reason"]) == (
        "the owner",
        "a drill",
    )
    events = _rows(
        "SELECT actor, detail_json FROM rulebook_event WHERE entity = 'rulebook_restore'"
    )
    assert len(events) == 1 and events[0]["actor"] == "the owner"
    assert json.loads(events[0]["detail_json"])["source_hash"] == rows[0]["source_hash"]


@pytest.mark.parametrize(
    ("book", "actor", "reason"),
    [
        (9, "the owner", "x"),
        (0, "the owner", "x"),
        (1, "", "x"),
        (1, "the owner", "  "),
        (1, "  ", "x"),
    ],
)
def test_a_restore_that_names_no_book_person_or_reason_writes_nothing(
    book, actor, reason
):
    _three_books()
    before = _rows("SELECT COUNT(*) AS n FROM rulebook_snapshot")
    with pytest.raises(rulebook_v2.RuleRefused):
        rulebook_v2_book.restore_book(_conn(), book, actor, reason)
    assert _rows("SELECT COUNT(*) AS n FROM rulebook_snapshot") == before
    assert _rows("SELECT id FROM rulebook_restore") == []


def test_a_book_whose_members_no_longer_match_its_hash_is_not_restored():
    _three_books()
    conn = _conn()
    # An operator who drops the guard and edits a member: the restore recomputes the hash and refuses.
    conn.execute("DROP TRIGGER rulebook_snapshot_rule_no_delete")
    conn.execute(
        "DELETE FROM rulebook_snapshot_rule WHERE snapshot_id = ?",
        (rulebook_v2_book.books(conn)[1]["snapshot_id"],),
    )
    conn.commit()
    with pytest.raises(rulebook_v2.RuleRefused, match="does not verify"):
        rulebook_v2_book.restore_book(conn, 2, "the owner", "x")
    assert _rows("SELECT id FROM rulebook_restore") == []
    assert len(rulebook_v2_book.books(conn)) == 3


def test_release_needs_a_restore_to_release():
    _three_books()
    with pytest.raises(rulebook_v2.RuleRefused, match="no restore"):
        rulebook_v2_book.release_pin(_conn(), "the owner", "x")


def test_the_switch_off_reads_and_writes_nothing(monkeypatch):
    _three_books()
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    with pytest.raises(rulebook_v2.SwitchedOff):
        rulebook_v2_book.restore_book(_conn(), 1, "the owner", "x")


def test_a_live_shaped_file_is_refused_and_the_live_write_gate_is_never_called(
    tmp_path, monkeypatch
):
    live = tmp_path / "backend" / "data"
    live.mkdir(parents=True)
    conn = sqlite3.connect(live / "rag_intelligence.sqlite")
    conn.execute("CREATE TABLE rulebook_event (id INTEGER)")
    conn.execute("CREATE TABLE rulebook_restore (id TEXT)")
    with pytest.raises(rulebook_v2.RefusedLive):
        rulebook_v2_book.restore_book(conn, 1, "the owner", "x")
    assert conn.execute("SELECT COUNT(*) FROM rulebook_restore").fetchone()[0] == 0

    def boom(*_a, **_k):
        raise AssertionError("a restore must never ask for live write clearance")

    monkeypatch.setattr(live_guard, "prepare_live_write", boom)
    _three_books()
    rulebook_v2_book.restore_book(_conn(), 1, "the owner", "a drill")


def test_the_script_lists_restores_and_releases_on_a_copy(capsys):
    _three_books()
    db.reset_connection()
    path = settings.db_path
    assert rulebook_book.main(["--db", str(path), "--list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [b["book_no"] for b in listed["books"]] == [1, 2, 3] and listed[
        "pinned"
    ] is None
    assert (
        rulebook_book.main(
            ["--db", str(path), "--restore", "2", "--by", "me", "--reason", "drill"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["restored_book"] == 2
    assert (
        rulebook_book.main(
            ["--db", str(path), "--restore", "9", "--by", "me", "--reason", "drill"]
        )
        == 2
    )
    assert "no book version 9" in json.loads(capsys.readouterr().out)["refused"]
    assert (
        rulebook_book.main(
            ["--db", str(path), "--release", "--by", "me", "--reason", "done"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"released": True}


def test_the_script_stops_when_the_switch_is_off(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(settings, "rulebook_v2_enabled", False)
    assert rulebook_book.main(["--db", str(tmp_path / "x.sqlite"), "--list"]) == 3
    assert "RULEBOOK_V2_ENABLED is off" in capsys.readouterr().out


def test_the_approval_import_makes_a_book_version(tmp_path):
    from tests.test_805_rule_approvals_import import _compile as compile_one
    from tests.test_805_rule_approvals_import import _person as person
    from tests.test_805_rule_approvals_import import _run, _ticked

    person()
    compile_one()
    assert len(rulebook_v2_book.books(_conn())) == 1
    assert _run(_ticked(tmp_path))[0] == 0
    got = rulebook_v2_book.books(_conn())
    assert [b["rules_in_force"] for b in got] == [0, 1]
