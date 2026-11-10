"""The write guard, comparators of proposals and repairs, and the recorded steps bound to version and quote (Lane 1).
Every text here is INVENTED."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import rule_finish as rf
from app import rule_finish_guard as guard
from app import rule_finish_record as rec
from app import rule_finish_repair as rr
from app import rule_finish_store as st
from tests.test_rule_finish_kit import (  # noqa: F401
    make_copy,
    make_pages_db,
    marker_key,
    rule,
)

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ proposals


# ------------------------------------------------------------------------------------------------ H2 / M10 write guard


def _writers():
    return (
        lambda c: st.ensure_table(c),
        lambda c: st._append_step(
            c, "v1", "a", "pass", "r", {}, checker="c", model="m", run_id="x"
        ),
        lambda c: rr.apply_proposal(
            c, "v1", {"value": 10.0, "unit": "mm", "comparator": ">="}, "o"
        ),
        lambda c: rr.apply_repair(c, "v1", {}, "o", pages={}),
        lambda c: rec.record_code_step(c, "v1", "a", run_id="x"),
    )


def test_a_write_is_refused_unless_the_database_is_a_signed_marked_copy_whatever_its_name(
    tmp_path,
):
    for name in ("PSV-ALL.SQLITE", "Compile.sqlite", "anything.db", "work.sqlite"):
        conn = make_copy(tmp_path / name, marked=False)
        for call in _writers():
            with pytest.raises(guard.NotAWorkCopy):
                call(conn)
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='rule_finish_step'"
            ).fetchone()
            is None
        )


def test_a_hand_made_marker_is_refused_because_it_is_not_signed(tmp_path):
    conn = make_copy(tmp_path / "forged.sqlite", marked=False)
    conn.execute(
        f"CREATE TABLE {guard.MARKER} (marker_id TEXT, copy_path TEXT, source_path TEXT, created_at TEXT, rows_json TEXT, mac TEXT)"
    )
    conn.execute(
        f"INSERT INTO {guard.MARKER} VALUES ('x', ?, 'src', 'now', ?, 'forged')",
        (guard._real(tmp_path / "forged.sqlite"), guard._counts(conn)),
    )
    conn.commit()
    for call in _writers():
        with pytest.raises(guard.NotAWorkCopy, match="not signed"):
            call(conn)
    older = make_copy(
        tmp_path / "old.sqlite", marked=False
    )  # a marker of the first design: other columns
    older.execute(
        f"CREATE TABLE {guard.MARKER} (marker_id TEXT, copy_path TEXT, source_path TEXT, created_at TEXT)"
    )
    with pytest.raises(guard.NotAWorkCopy):
        guard.require_work_copy(older)


def test_a_live_shaped_database_is_never_a_work_copy_even_with_a_signed_marker(
    tmp_path,
):
    live = tmp_path / "other-checkout" / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    make_copy(live).close()  # a signed marker naming this very file
    with pytest.raises(guard.NotAWorkCopy, match="live"):
        guard.require_work_copy(sqlite3.connect(live))
    with pytest.raises(guard.NotAWorkCopy, match="live"):
        guard.open_work_copy(live)
    make_copy(tmp_path / "src.sqlite", marked=False).close()
    target = live.with_name("RAG_Intelligence.SQLITE")  # the same shape, any case
    for make in (guard.prepare_work_copy, guard.adopt_copy):
        with pytest.raises(guard.NotAWorkCopy, match="live"):
            make(tmp_path / "src.sqlite", target)


def test_the_runner_opens_its_one_read_write_connection_only_on_a_marked_copy(
    tmp_path,
):
    make_copy(tmp_path / "w.sqlite").close()
    conn = guard.open_work_copy(tmp_path / "w.sqlite")
    st.ensure_table(conn)  # usable for writing
    conn.close()
    make_copy(tmp_path / "plain.sqlite", marked=False).close()
    with pytest.raises(guard.NotAWorkCopy, match="no work-copy marker"):
        guard.open_work_copy(tmp_path / "plain.sqlite")
    assert guard.is_marked(tmp_path / "w.sqlite")
    assert not guard.is_marked(tmp_path / "plain.sqlite")


def test_a_marker_signed_with_another_key_is_refused(tmp_path, monkeypatch):
    conn = make_copy(tmp_path / "w.sqlite")
    guard.require_work_copy(conn)
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(tmp_path / "other.key"))
    with pytest.raises(guard.NotAWorkCopy, match="not signed"):
        guard.require_work_copy(conn)


def test_a_marker_copied_with_the_file_does_not_make_another_file_writable(tmp_path):
    make_copy(tmp_path / "a.sqlite").close()
    (tmp_path / "b.sqlite").write_bytes((tmp_path / "a.sqlite").read_bytes())
    with pytest.raises(guard.NotAWorkCopy, match="another file"):
        guard.require_work_copy(sqlite3.connect(tmp_path / "b.sqlite"))


def test_the_file_must_still_hold_the_rulebook_tables_it_was_marked_with(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    conn.execute("DELETE FROM rulebook_provenance")
    conn.commit()
    with pytest.raises(guard.NotAWorkCopy, match="no longer holds"):
        guard.require_work_copy(conn)


def _marked_pair(tmp_path):
    work = make_copy(tmp_path / "w.sqlite")
    return work, tmp_path / "w.sqlite"


def test_the_default_source_and_pages_databases_are_protected_whatever_the_caller_passes(
    tmp_path, monkeypatch
):
    conn, path = _marked_pair(tmp_path)
    guard.require_work_copy(conn)  # writable as it is
    for attr in ("DEFAULT_SOURCE", "DEFAULT_PAGES"):
        with monkeypatch.context() as m:
            m.setattr(guard, attr, path)
            for call in _writers():  # no protected list is passed by any writer
                with pytest.raises(guard.NotAWorkCopy, match="protected"):
                    call(conn)
    guard.require_work_copy(conn)


def test_the_apps_database_and_the_live_one_are_protected(tmp_path, monkeypatch):
    conn, path = _marked_pair(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(guard, "settings", SimpleNamespace(db_path=path))
        with pytest.raises(guard.NotAWorkCopy, match="protected"):
            guard.require_work_copy(conn)
    guard.require_work_copy(conn)
    with monkeypatch.context() as m:
        m.setenv("DB_PATH", str(path))
        with pytest.raises(guard.NotAWorkCopy, match="protected"):
            guard.require_work_copy(conn)


def test_a_registered_source_is_protected_by_inode_even_through_a_link(
    tmp_path, monkeypatch
):
    conn, path = _marked_pair(tmp_path)
    monkeypatch.setattr(guard, "_REGISTERED", [])
    link, hard = tmp_path / "link.sqlite", tmp_path / "hard.sqlite"
    link.symlink_to(path)
    os.link(path, hard)
    for other in (path, link, hard, tmp_path / "." / "w.sqlite"):
        monkeypatch.setattr(guard, "_REGISTERED", [])
        guard.register_protected(other)
        with pytest.raises(guard.NotAWorkCopy, match="protected"):
            guard.require_work_copy(conn)
    assert guard.same_file(path, hard) and not guard.same_file(path, tmp_path)


def test_the_inode_check_catches_a_path_the_resolved_name_does_not(
    tmp_path, monkeypatch
):
    path = tmp_path / "a.sqlite"
    path.write_bytes(b"x")
    hard = tmp_path / "b.sqlite"
    os.link(path, hard)
    assert guard._real(path) != guard._real(hard) and guard.same_file(path, hard)
    monkeypatch.setattr(
        guard, "_real", lambda p: str(p)
    )  # remove the resolved-path match: only the inode is left
    assert guard.same_file(path, hard)


def test_prepare_and_adopt_refuse_the_source_and_make_a_marker_only_for_a_verified_copy(
    tmp_path,
):
    source = tmp_path / "src.sqlite"
    make_copy(source, marked=False).close()
    for fn in (guard.prepare_work_copy, guard.adopt_copy):
        with pytest.raises(guard.NotAWorkCopy, match="protected"):
            fn(source, source)
        link = tmp_path / f"link-{fn.__name__}.sqlite"
        link.symlink_to(source)
        with pytest.raises(guard.NotAWorkCopy, match="protected"):
            fn(source, link)
    copy = guard.prepare_work_copy(source, tmp_path / "work.sqlite")
    guard.require_work_copy(sqlite3.connect(copy), [source])
    assert guard.prepare_work_copy(source, copy) == copy
    old = tmp_path / "old.sqlite"
    old.write_bytes(source.read_bytes())
    assert guard.adopt_copy(source, old) == old
    guard.require_work_copy(sqlite3.connect(old), [source])
    stranger = tmp_path / "stranger.sqlite"
    sqlite3.connect(stranger).close()
    with pytest.raises(guard.NotAWorkCopy):
        guard.adopt_copy(source, stranger)
    other = make_copy(tmp_path / "other.sqlite", marked=False)
    other.execute("DELETE FROM rulebook_provenance")
    other.commit()
    with pytest.raises(guard.NotAWorkCopy, match="differ"):
        guard.adopt_copy(source, tmp_path / "other.sqlite")
    unmarked = tmp_path / "unmarked.sqlite"
    unmarked.write_bytes(source.read_bytes())
    with pytest.raises(guard.NotAWorkCopy):
        guard.prepare_work_copy(
            source, unmarked
        )  # an existing file is reused only if marked


# ------------------------------------------------------------------------------------------------ H6 recorded code steps


def test_a_code_step_is_recomputed_from_the_work_copy_and_the_pages_not_handed_in(
    tmp_path,
):
    quote = "Things shall be as follows"
    conn = make_copy(tmp_path / "w.sqlite", quote=quote)
    conn.execute("UPDATE rulebook_applicability SET value = 'gizmos'")
    conn.commit()
    pages_db = make_pages_db(tmp_path / "pages.sqlite", {1: "Other text only."})
    (r,) = st.load_rules_by_version(conn, "v1")
    expected = {
        "a": rf.limit_and_unit(r),
        "b": rf.evidence_source(r),
        "c": rf.fragments(r, {1: "Other text only."}),
        "d": rf.conditions_of(r),
        "g": rf.quote_found(r, {1: "Other text only."}),
    }
    for step, want in expected.items():
        assert (
            want[0] != rf.PASS or step == "a"
        )  # a real failing or incomplete result for b, c, d, g
        got = rec.record_code_step(conn, "v1", step, run_id="x", pages_db=pages_db)
        assert got[:2] == want[:2]
        assert st.latest_steps(conn, "v1")[step]["result"] == want[0]
    assert expected["b"][0] == rf.INCOMPLETE and expected["c"][0] == rf.INCOMPLETE
    assert expected["d"][0] == rf.INCOMPLETE and expected["g"][0] == rf.FAIL
    with pytest.raises(ValueError):
        rec.record_code_step(
            conn, "v1", "c", run_id="x"
        )  # the pages database is needed
    with pytest.raises(ValueError):
        rec.record_code_step(conn, "v1", "e", run_id="x")
    with pytest.raises(ValueError):
        st._append_step(
            conn, "v1", "a", "maybe", "r", {}, checker="c", model="m", run_id="x"
        )
    assert (
        not hasattr(st, "record_step")
        and "rule" not in rec.record_code_step.__annotations__
    )


# ------------------------------------------------------------------------------------------------ steps e and f

TWO = "at least 3/4 inch for threaded valves and at least 1 inch for flanged valves"
CONFIRMED = [
    {"value": 0.75, "unit": "inch", "comparator": ">="},
    {"value": 1.0, "unit": "inch", "comparator": ">="},
]


def two_figure_copy(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite", quote=f"The inlet shall be {TWO}.")
    conn.execute(
        "INSERT INTO rulebook_applicability (rule_version_id, key_type, value) VALUES ('v1','condition','threaded')"
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    pages = make_pages_db(tmp_path / "pages.sqlite", {1: f"The inlet shall be {TWO}."})
    rr.apply_repair(
        conn,
        "v1",
        {
            "comparator": ">=",
            "figures": [
                {"value": 0.75, "unit": "inch"},
                {"value": 1.0, "unit": "inch"},
            ],
        },
        "o",
        pages={1: f"The inlet shall be {TWO}."},
    )
    return conn, pages


def answer(tmp_path, conn, pages, name="out.json", **kw):
    """The engineer's output to a REAL issued input: what the lead's flow does."""
    _, digest = rec.make_engineer_input(
        conn, "v1", tmp_path / "issued", pages, trace_root=tmp_path
    )
    rule_ = rec.rule_of(conn, "v1")
    data = {
        "rule_key": rule_["rule_key"],
        "rule_version_id": "v1",
        "quote_sha256": rec.quote_sha256(rule_),
        "content_sha256": rec.content_sha256(rule_),
        "input_sha256": digest,
        "checker_kind": rec.CHECKER_KIND,
        "verdict": "OK",
        "confirmed_figures": CONFIRMED,
        "accounted_numbers": [],
    }
    data.update(kw)
    out = tmp_path / name
    out.write_text(json.dumps(data))
    return out


def test_the_engineer_input_is_written_by_code_with_the_rule_the_pages_and_the_content_hash(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    path, digest = rec.make_engineer_input(
        conn, "v1", tmp_path / "issued", pages, trace_root=tmp_path
    )
    doc = json.loads(path.read_text())
    rule_ = rec.rule_of(conn, "v1")
    assert (
        digest == hashlib.sha256(path.read_bytes()).hexdigest()
        and oct(path.stat().st_mode & 0o777) == "0o600"
    )
    assert (
        doc["rule"]["content_sha256"] == rec.content_sha256(rule_)
        and doc["rule"]["rule_key"] == "keyabc12345"
    )
    assert list(doc["pages"]) == ["1"] and "inlet" in doc["pages"]["1"]
    row = conn.execute(
        "SELECT kind, rule_version_id, input_sha256 FROM rule_finish_issued"
    ).fetchone()
    assert tuple(row) == ("e", "v1", digest)


def test_step_a_passes_on_confirmed_figures_only_while_the_engineer_check_is_bound_to_this_content(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    assert rec.record_code_step(conn, "v1", "a", run_id="x")[:2] == (
        rf.INCOMPLETE,
        "engineer_confirmation_pending",
    )
    out = answer(tmp_path, conn, pages)
    assert rec.record_engineer_check(conn, "v1", out, run_id="x") == rf.PASS
    ev = st.latest_steps(conn, "v1")["e"]["evidence"]
    assert ev["confirmed_figures"] == CONFIRMED and ev[
        "content_sha256"
    ] == rec.content_sha256(rec.rule_of(conn, "v1"))
    assert rec.record_code_step(conn, "v1", "a", run_id="y")[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    rr.apply_repair(
        conn, "v1", {"exceptions": []}, "o", pages={1: ""}
    )  # nothing applied: still bound
    assert rec.current_steps(conn, "v1")["e"] == "pass"
    rr.apply_repair(
        conn, "v1", {"conditions": ["flanged"]}, "o", pages={1: "x"}
    )  # a change of content
    assert rec.current_steps(conn, "v1")["e"] == "incomplete"
    assert rec.record_code_step(conn, "v1", "a", run_id="z")[:2] == (
        rf.INCOMPLETE,
        "engineer_confirmation_pending",
    )


def test_the_same_old_file_cannot_be_recorded_again_after_the_content_changed(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    out = answer(tmp_path, conn, pages)
    assert rec.record_engineer_check(conn, "v1", out, run_id="1") == rf.PASS  # pass
    rr.apply_repair(conn, "v1", {"conditions": ["flanged"]}, "o", pages={1: "x"})
    assert (
        st.latest_steps(conn, "v1")["e"]["result"] == "incomplete"
    )  # reset after the change
    with pytest.raises(ValueError, match="other content"):
        rec.record_engineer_check(
            conn, "v1", out, run_id="2"
        )  # the SAME file again: refused
    assert st.latest_steps(conn, "v1")["e"]["result"] == "incomplete"
    fresh = answer(
        tmp_path, conn, pages, name="again.json"
    )  # a new input for the new content: accepted
    assert rec.record_engineer_check(conn, "v1", fresh, run_id="3") == rf.PASS


@pytest.mark.parametrize(
    "change",
    [
        {"verdict": "maybe"},
        {"verdict": ""},
        {"rule_key": "keyabc1234"},
        {"rule_key": None},
        {"rule_key_prefix": "keyabc12"},
        {"rule_keys": ["keyabc12345"]},
        {"rules": []},
        {"checker_kind": "code"},
        {"checker_kind": "owner"},
        {"checker_kind": "ai_engineer_chat_helper2"},
        {"checker_kind": "Claude chat helper, KJO engineer role"},
        {"checker_kind": None},
        {"rule_version_id": "v2"},
        {"quote_sha256": "0" * 64},
        {"content_sha256": "0" * 64},
        {"input_sha256": "0" * 64},
        {"input_sha256": None},
        {"confirmed_figures": None},
        {"confirmed_figures": [{"value": "x", "unit": "inch", "comparator": ">="}]},
        {"confirmed_figures": [{"value": 1, "unit": "", "comparator": ">="}]},
        {"confirmed_figures": [{"value": 1, "unit": "inch", "comparator": "garbage"}]},
    ],
)
def test_step_e_refuses_an_output_that_is_not_bound_to_this_rule_content_and_issued_input(
    tmp_path, change
):
    conn, pages = two_figure_copy(tmp_path)
    with pytest.raises(ValueError, match="refused"):
        rec.record_engineer_check(
            conn, "v1", answer(tmp_path, conn, pages, **change), run_id="x"
        )
    assert (
        "e" not in st.latest_steps(conn, "v1")
        or st.latest_steps(conn, "v1")["e"]["result"] == "incomplete"
    )
    with pytest.raises(ValueError):
        rec.record_engineer_check(conn, "v1", tmp_path / "missing.json", run_id="x")
    (tmp_path / "list.json").write_text("[1]")
    with pytest.raises(ValueError):
        rec.record_engineer_check(conn, "v1", tmp_path / "list.json", run_id="x")


def test_an_engineer_file_cannot_be_self_attested_and_an_input_for_other_content_does_not_count(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    forged = answer(
        tmp_path, conn, pages, input_sha256=hashlib.sha256(b"made up").hexdigest()
    )
    with pytest.raises(ValueError, match="input_sha256"):
        rec.record_engineer_check(conn, "v1", forged, run_id="x")
    out = answer(tmp_path, conn, pages)  # issued for the content as it is now
    rr.apply_repair(conn, "v1", {"conditions": ["flanged"]}, "o", pages={1: "x"})
    with pytest.raises(ValueError, match="refused"):
        rec.record_engineer_check(conn, "v1", out, run_id="x")


def test_an_engineer_output_file_cannot_be_replayed_for_another_version(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    out = answer(tmp_path, conn, pages)
    rec.record_engineer_check(conn, "v1", out, run_id="x")
    conn.execute(
        "INSERT INTO rulebook_version SELECT 'v2', rule_id, 2, kind, field, comparator, value, value_low, value_high, value_text, unit, unit_dimension, strength, sentence_strength, context_flag FROM rulebook_version WHERE id='v1'"
    )
    conn.execute(
        "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote) VALUES ('v2','d','4.1',1,'A changed quote shall apply to 5 mm.')"
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    with pytest.raises(ValueError, match="refused"):
        rec.record_engineer_check(conn, "v2", out, run_id="y")


def test_the_content_hash_covers_figures_comparator_conditions_exceptions_and_the_source(
    tmp_path,
):
    conn, _ = two_figure_copy(tmp_path)
    base = rec.rule_of(conn, "v1")
    h = rec.content_sha256(base)
    for change in (
        {"value": 5.0},
        {"value_low": 1.0},
        {"value_high": 2.0},
        {"unit": "mm"},
        {"comparator": "<="},
        {"figures": [{"value": 1.0}]},
        {"applicability": [*base["applicability"], ("condition", "welded")]},
        {"exceptions": ["x"]},
        {"field": "colour", "quote": "Things shall be good.", "figures": None},
    ):
        assert rec.content_sha256(dict(base, **change)) != h, change
    assert (
        rec.content_sha256(dict(base, confirmed_figures=CONFIRMED)) == h
    )  # the confirmation is not content
    assert (
        rec.content_sha256(
            dict(base, applicability=list(reversed(base["applicability"])))
        )
        == h
    )  # order is not content


def _tick(tmp_path, conn, input_sha, **kw):
    r = rec.rule_of(conn, "v1")
    data = {
        "sample_id": "s1",
        "folder": "01",
        "input_sha256": input_sha,
        "ticks": {
            "v1": {
                "tick": "ok",
                "quote_sha256": rec.quote_sha256(r),
                "content_sha256": rec.content_sha256(r),
            }
        },
    }
    data.update(kw)
    path = tmp_path / "tick.json"
    path.write_text(json.dumps(data))
    return path


def test_step_f_is_bound_to_an_issued_sheet_sample_folder_version_quote_and_content(
    tmp_path,
):
    conn, _ = two_figure_copy(tmp_path)
    sheet, digest = rec.make_sample_sheet(
        conn, "v1", tmp_path / "sheets", "s1", "01", trace_root=tmp_path
    )
    assert json.loads(sheet.read_text())["rule"][
        "content_sha256"
    ] == rec.content_sha256(rec.rule_of(conn, "v1"))
    tick = _tick(tmp_path, conn, digest)
    assert rec.record_owner_sample(conn, "v1", "s1", tick, run_id="x") == rf.PASS
    ev = st.latest_steps(conn, "v1")["f"]["evidence"]
    assert (
        ev["sha256"] == hashlib.sha256(tick.read_bytes()).hexdigest()
        and ev["input_sha256"] == digest
    )
    r = rec.rule_of(conn, "v1")
    wrong = {
        "tick": "wrong",
        "quote_sha256": rec.quote_sha256(r),
        "content_sha256": rec.content_sha256(r),
    }
    assert (
        rec.record_owner_sample(
            conn,
            "v1",
            "s1",
            _tick(tmp_path, conn, digest, ticks={"v1": wrong}),
            run_id="y",
        )
        == rf.FAIL
    )
    for kw, sid in (
        ({"sample_id": "s2"}, "s1"),
        ({}, "s2"),
        ({}, ""),
        ({"folder": ""}, "s1"),
        ({"folder": "02"}, "s1"),
        ({"input_sha256": "0" * 64}, "s1"),
        ({"input_sha256": None}, "s1"),
        ({"ticks": {"other": wrong}}, "s1"),
        ({"ticks": {"v1": dict(wrong, tick="ok", quote_sha256="0" * 64)}}, "s1"),
        ({"ticks": {"v1": dict(wrong, tick="ok", content_sha256="0" * 64)}}, "s1"),
        ({"ticks": {"v1": dict(wrong, tick="yes")}}, "s1"),
    ):
        with pytest.raises(ValueError, match="refused"):
            rec.record_owner_sample(
                conn, "v1", sid, _tick(tmp_path, conn, digest, **kw), run_id="z"
            )
    with pytest.raises(ValueError):
        rec.make_sample_sheet(
            conn, "v1", tmp_path / "sheets", "", "01", trace_root=tmp_path
        )
    with pytest.raises(ValueError):
        rec.make_sample_sheet(
            conn, "v1", tmp_path / "sheets", "s1", " ", trace_root=tmp_path
        )


def test_the_same_tick_file_cannot_be_recorded_again_after_the_content_changed(
    tmp_path,
):
    conn, _ = two_figure_copy(tmp_path)
    _, digest = rec.make_sample_sheet(
        conn, "v1", tmp_path / "sheets", "s1", "01", trace_root=tmp_path
    )
    tick = _tick(tmp_path, conn, digest)
    assert rec.record_owner_sample(conn, "v1", "s1", tick, run_id="1") == rf.PASS
    rr.apply_repair(conn, "v1", {"conditions": ["flanged"]}, "o", pages={1: "x"})
    assert st.latest_steps(conn, "v1")["f"]["result"] == "incomplete"
    with pytest.raises(ValueError, match="refused"):
        rec.record_owner_sample(conn, "v1", "s1", tick, run_id="2")


def test_a_check_bound_to_another_version_or_to_older_content_is_stale(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    rec.record_engineer_check(conn, "v1", answer(tmp_path, conn, pages), run_id="x")
    assert rec.current_steps(conn, "v1")["e"] == "pass"
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rule_finish_repair (id INTEGER PRIMARY KEY AUTOINCREMENT, rule_version_id TEXT, kind TEXT, payload_json TEXT, approver TEXT, at TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_finish_repair (rule_version_id, kind, payload_json, approver, at) VALUES ('v1','exception','{\"text\": \"small compressor widgets\"}','x','now')"
    )
    conn.commit()
    assert (
        rec.current_steps(conn, "v1")["e"] == "stale"
    )  # the content changed under a check that was not reset
    assert "engineer_check" not in rec.rule_of(conn, "v1")
    conn.execute("DELETE FROM rule_finish_repair WHERE kind = 'exception'")
    conn.commit()
    ev = dict(st.latest_steps(conn, "v1")["e"]["evidence"], rule_version_id="v2")
    st._append_step(
        conn, "v1", "e", "pass", "forged", ev, checker="c", model="m", run_id="r"
    )
    assert (
        rec.current_steps(conn, "v1")["e"] == "stale"
    )  # right quote and content, another version
    ev = dict(ev, rule_version_id="v1")
    st._append_step(
        conn, "v1", "e", "fail", "not ok", ev, checker="c", model="m", run_id="r"
    )
    assert rec.rule_of(conn, "v1")["engineer_check"]["result"] == "fail"
    assert rf.limit_and_unit(rec.rule_of(conn, "v1"))[:2] == (
        rf.INCOMPLETE,
        "engineer_not_ok",
    )  # only a PASS confirms


def test_a_check_bound_to_an_earlier_quote_or_content_is_stale_and_never_counts(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    rec.record_engineer_check(conn, "v1", answer(tmp_path, conn, pages), run_id="x")
    _, digest = rec.make_sample_sheet(
        conn, "v1", tmp_path / "sheets", "s1", "01", trace_root=tmp_path
    )
    rec.record_owner_sample(conn, "v1", "s1", _tick(tmp_path, conn, digest), run_id="x")
    assert (rec.current_steps(conn, "v1")["e"], rec.current_steps(conn, "v1")["f"]) == (
        "pass",
        "pass",
    )
    conn.execute(
        "UPDATE rulebook_provenance SET quote = 'The inlet shall be at least 11 inch.' WHERE rule_version_id = 'v1'"
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    now = rec.current_steps(conn, "v1")
    assert (now["e"], now["f"]) == ("stale", "stale")
    flat = {**now, "a": "pass", "b": "pass", "c": "pass", "d": "pass", "g": "pass"}
    assert (
        rf.finish_status(flat) == (rf.NOT_FINISHED, "e", "e_stale")
        and rf.may_decide(flat) is False
    )
    st._append_step(
        conn,
        "v1",
        "e",
        "pass",
        "forged",
        {"rule_version_id": "v2"},
        checker="c",
        model="m",
        run_id="r",
    )
    assert rec.current_steps(conn, "v1")["e"] == "stale"


def test_a_stale_check_does_not_give_step_a_its_confirmed_figures(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    rec.record_engineer_check(conn, "v1", answer(tmp_path, conn, pages), run_id="x")
    assert "engineer_check" in rec.rule_of(conn, "v1")
    conn.execute(
        "UPDATE rulebook_provenance SET quote = ? WHERE rule_version_id = 'v1'",
        (f"The inlet shall be {TWO} and more.",),
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    assert "engineer_check" not in rec.rule_of(conn, "v1")


def test_a_marker_key_file_must_be_private_long_enough_and_is_created_once(
    tmp_path, monkeypatch
):
    key = tmp_path / "k.key"
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(key))
    first = guard._key()
    assert (
        len(first) >= 32
        and oct(key.stat().st_mode & 0o777) == "0o600"
        and guard._key() == first
    )
    key.chmod(0o644)
    with pytest.raises(guard.NotAWorkCopy, match="mode 0600"):
        guard._key()
    key.chmod(0o600)
    key.write_text("short")
    with pytest.raises(guard.NotAWorkCopy, match="too short"):
        guard._key()
    key.write_text("")
    with pytest.raises(guard.NotAWorkCopy, match="too short"):
        guard._key()


# ------------------------------------------------------------------------------------------------ L12 paths and files


def test_the_runners_refuse_paths_outside_the_trace_folder(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_coverage_run as cov
    import rule_finish_run as run

    def must_not_get_here(*args, **kwargs):
        raise AssertionError("the path check must refuse before any work")

    monkeypatch.setattr(run, "prepare_work_db", must_not_get_here)
    monkeypatch.setattr(cov, "ro", must_not_get_here)
    with pytest.raises(SystemExit, match="refused"):
        run.main(["--rule-key", "abc", "--trace-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="refused"):
        cov.main(["--out", str(tmp_path)])
    inside = run.DEFAULT_TRACE / "lane1-test-never-written"
    assert inside.resolve().is_relative_to(run.DEFAULT_TRACE.resolve())


def test_files_with_sentence_text_are_written_mode_0600_even_over_an_open_file(
    tmp_path,
):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_coverage_run as cov

    target = tmp_path / "private.json"
    cov.write_private(target, "sentence text")
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    target.chmod(0o644)  # an earlier file with open permissions
    cov.write_private(target, "again")
    assert (
        target.read_text() == "again" and oct(target.stat().st_mode & 0o777) == "0o600"
    )


def test_the_run_id_is_sanitised_before_any_work(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_finish_run as run

    def must_not_get_here(*args, **kwargs):
        raise AssertionError("the run id check must refuse before any work")

    monkeypatch.setattr(run, "prepare_work_db", must_not_get_here)
    for bad in ("../x", "a/b", "a b", "", "x" * 65, "..", ".", "a\\b", "x;y"):
        with pytest.raises(SystemExit, match="refused"):
            run.main(["--rule-key", "abc", "--run-id", bad]) if bad else run.main(
                ["--rule-key", "abc", "--run-id", "bad id"]
            )
    with pytest.raises(AssertionError, match="run id check"):
        run.main(
            ["--rule-key", "abc", "--run-id", "ok-1.2_x"]
        )  # a good id goes on to the work


def test_the_work_db_must_carry_the_marker_and_be_a_verified_copy(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_finish_run as run

    source = tmp_path / "src.sqlite"
    make_copy(source, marked=False).close()
    pages = tmp_path / "pages.sqlite"
    sqlite3.connect(pages).close()
    stranger = tmp_path / "stranger.sqlite"
    sqlite3.connect(stranger).close()
    with pytest.raises(SystemExit):
        run.prepare_work_db(source, pages, stranger)
    marked = run.prepare_work_db(source, pages, tmp_path / "work.sqlite")
    guard.require_work_copy(sqlite3.connect(marked), [source])


def test_the_content_hash_follows_the_evidence_source_decision():
    a = rec.content_sha256(
        rule(field="inlet size", quote="The inlet shall be at least 5 mm.")
    )
    b = rec.content_sha256(
        rule(field="colour", quote="The inlet shall be at least 5 mm.")
    )
    assert a != b  # datasheet value against incomplete


def test_a_lost_race_creating_the_key_file_reads_the_winners_file(
    tmp_path, monkeypatch
):
    key = tmp_path / "race.key"
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(key))
    real_open = os.open

    def losing(path, flags, mode=0o777):
        if str(path) == str(key):
            key.write_text("w" * 64)
            key.chmod(0o600)
            raise FileExistsError(path)
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", losing)
    assert guard._key() == b"w" * 64


# ------------------------------------------------------------------------------------------------ e follows the stored figures


def test_a_second_engineer_check_that_differs_from_the_stored_figures_is_recorded_as_a_fail_and_step_a_follows(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    assert (
        rec.record_engineer_check(conn, "v1", answer(tmp_path, conn, pages), run_id="1")
        == rf.PASS
    )
    assert rec.current_steps(conn, "v1")["a"] == rf.PASS  # a follows the current e
    other = [dict(f, comparator="<=") for f in CONFIRMED]
    second = answer(
        tmp_path, conn, pages, name="second.json", confirmed_figures=other
    )  # OK, but another comparator
    assert rec.record_engineer_check(conn, "v1", second, run_id="2") == rf.FAIL
    row = st.latest_steps(conn, "v1")["e"]
    assert (row["result"], row["reason"]) == ("fail", "engineer_figures_differ")
    assert rec.current_steps(conn, "v1")["a"] == rf.INCOMPLETE
    assert st.latest_steps(conn, "v1")["a"]["reason"].endswith(
        "engineer_not_ok"
    )  # recorded when e was recorded
    assert (
        rec.record_engineer_check(
            conn, "v1", answer(tmp_path, conn, pages, name="third.json"), run_id="3"
        )
        == rf.PASS
    )
    assert rec.current_steps(conn, "v1")["a"] == rf.PASS


def test_step_a_is_derived_from_the_current_engineer_check_whenever_it_is_read(
    tmp_path,
):
    conn, _ = two_figure_copy(tmp_path)
    rec.record_code_step(conn, "v1", "a", run_id="x")  # recorded while no e exists
    st._append_step(
        conn, "v1", "a", "pass", "forged", {}, checker="c", model="m", run_id="r"
    )  # a stored pass is not read
    assert rec.current_steps(conn, "v1")["a"] == rf.INCOMPLETE


def test_confirmed_figures_and_accounted_numbers_of_the_wrong_shape_are_refused_cleanly(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    for change in (
        {"confirmed_figures": [1]},
        {"confirmed_figures": ["x"]},
        {"confirmed_figures": [None]},
        {"confirmed_figures": {"a": 1}},
        {"confirmed_figures": [{"kind": "range", "low": "x", "high": 2, "unit": "C"}]},
        {"accounted_numbers": None},
        {"accounted_numbers": ["4"]},
        {"accounted_numbers": [{"token": "4"}]},
        {"accounted_numbers": [{"token": "4", "reason": "because"}]},
        {"accounted_numbers": [{"token": "", "reason": "count"}]},
        {"accounted_numbers": [None]},
        {"accounted_numbers": [{"token": 4, "reason": "count"}]},
    ):
        with pytest.raises(ValueError, match="refused"):
            rec.record_engineer_check(
                conn, "v1", answer(tmp_path, conn, pages, **change), run_id="x"
            )


def test_the_engineer_input_lists_the_number_tokens_and_the_closed_reasons(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    path, _ = rec.make_engineer_input(
        conn, "v1", tmp_path / "issued", pages, trace_root=tmp_path
    )
    doc = json.loads(path.read_text())
    assert doc["number_tokens"] == ["3/4", "1"] and doc["account_reasons"] == [
        "count",
        "designator",
        "reference",
        "other_engineer_ok",
    ]
    for key in ("field", "kind", "strength", "clause", "page", "quote"):
        assert key in doc["rule"]


@pytest.mark.parametrize(
    "bad", ["../x", "a/b", "a b", "", "..", ".", "x" * 65, "a\\b", "x;y", "é"]
)
def test_a_sample_id_for_a_file_name_has_no_separator_and_is_plain(tmp_path, bad):
    conn, _ = two_figure_copy(tmp_path)
    with pytest.raises(ValueError, match=r"refused|required"):
        rec.make_sample_sheet(
            conn, "v1", tmp_path / "sheets", bad, "01", trace_root=tmp_path
        )
    assert not (tmp_path / "sheets").exists() or not list(
        (tmp_path / "sheets").iterdir()
    )
    path, _ = rec.make_sample_sheet(
        conn, "v1", tmp_path / "sheets", "s-1.a_b", "01", trace_root=tmp_path
    )
    assert path.name.startswith("s-1.a_b-")


def test_inputs_and_sheets_are_written_inside_the_trace_folder_with_no_symlink_and_mode_0600(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    outside = tmp_path.parent / "outside-the-trace"
    for call in (
        lambda d: rec.make_engineer_input(
            conn, "v1", d, pages, trace_root=tmp_path / "trace"
        ),
        lambda d: rec.make_sample_sheet(
            conn, "v1", d, "s1", "01", trace_root=tmp_path / "trace"
        ),
    ):
        with pytest.raises(ValueError, match="inside the trace folder"):
            call(outside)
        with pytest.raises(ValueError, match="inside the trace folder"):
            call(tmp_path / "trace" / ".." / "elsewhere")
    (tmp_path / "trace").mkdir()
    (tmp_path / "real").mkdir()
    (tmp_path / "trace" / "link").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError, match="symlink"):
        rec.make_engineer_input(
            conn,
            "v1",
            tmp_path / "trace" / "link",
            pages,
            trace_root=tmp_path / "trace",
        )
    good = tmp_path / "trace" / "ok"
    path, _ = rec.make_engineer_input(
        conn, "v1", good, pages, trace_root=tmp_path / "trace"
    )
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    path.unlink()
    path.symlink_to(tmp_path / "real" / "target")
    with pytest.raises(ValueError, match="symlink"):
        rec.make_engineer_input(conn, "v1", good, pages, trace_root=tmp_path / "trace")


def test_journeys_and_logs_are_written_mode_0600(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_finish_run as run

    target = tmp_path / "journey.json"
    run.write_private(target, "x")
    target.chmod(0o644)
    run.write_private(target, "y")
    assert target.read_text() == "y" and oct(target.stat().st_mode & 0o777) == "0o600"
    log = tmp_path / "run.jsonl"
    log.write_text("old\n")
    log.chmod(0o644)
    with run.open_private(log) as handle:
        handle.write("new\n")
    assert (
        log.read_text() == "old\nnew\n" and oct(log.stat().st_mode & 0o777) == "0o600"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"step": "z"},
        {"result": "maybe"},
        {"reason": ""},
        {"reason": "  "},
        {"run_id": ""},
        {"run_id": " "},
        {"model": ""},
        {"model": " "},
        {"checker": ""},
        {"checker": " "},
    ],
)
def test_the_one_writer_of_steps_refuses_an_unknown_step_or_result_and_every_empty_field(
    tmp_path, kwargs
):
    conn = make_copy(tmp_path / "w.sqlite")
    args = {
        "step": "a",
        "result": "pass",
        "reason": "r",
        "run_id": "x",
        "model": "m",
        "checker": "c",
    }
    args.update(kwargs)
    with pytest.raises(ValueError):
        st._append_step(
            conn,
            "v1",
            args["step"],
            args["result"],
            args["reason"],
            {},
            checker=args["checker"],
            model=args["model"],
            run_id=args["run_id"],
        )
    assert st.latest_steps(conn, "v1") == {}
    st._append_step(
        conn, "v1", "a", "pass", "r", {}, checker="c", model="m", run_id="x"
    )


def test_a_count_the_engineer_accounts_for_lets_step_a_pass_and_an_unaccounted_one_does_not(
    tmp_path,
):
    conn = make_copy(
        tmp_path / "w.sqlite",
        quote="At least 4 bolts of at least 12 mm shall be fitted.",
    )
    pages = make_pages_db(
        tmp_path / "pages.sqlite",
        {1: "At least 4 bolts of at least 12 mm shall be fitted."},
    )
    rr.apply_proposal(conn, "v1", {"value": 12, "unit": "mm"}, "o")
    rr.apply_repair(conn, "v1", {"comparator": ">="}, "o", pages={1: "x"})
    figures = [{"value": 12, "unit": "mm", "comparator": ">="}]

    def answer_with(name, accounted):
        _, digest = rec.make_engineer_input(
            conn, "v1", tmp_path / "issued", pages, trace_root=tmp_path
        )
        r = rec.rule_of(conn, "v1")
        data = {
            "rule_key": r["rule_key"],
            "rule_version_id": "v1",
            "quote_sha256": rec.quote_sha256(r),
            "content_sha256": rec.content_sha256(r),
            "input_sha256": digest,
            "checker_kind": rec.CHECKER_KIND,
            "verdict": "OK",
            "confirmed_figures": figures,
            "accounted_numbers": accounted,
        }
        out = tmp_path / name
        out.write_text(json.dumps(data))
        return out

    assert (
        rec.record_engineer_check(conn, "v1", answer_with("a.json", []), run_id="1")
        == rf.PASS
    )
    assert st.latest_steps(conn, "v1")["a"]["reason"].endswith("unaccounted_numbers")
    assert rec.current_steps(conn, "v1")["a"] == rf.INCOMPLETE
    counted = [{"token": "4", "reason": "count"}]
    assert (
        rec.record_engineer_check(
            conn, "v1", answer_with("b.json", counted), run_id="2"
        )
        == rf.PASS
    )
    assert st.latest_steps(conn, "v1")["a"]["reason"].endswith(
        "comparator_confirmed_by_engineer"
    )
    assert rec.current_steps(conn, "v1")["a"] == rf.PASS
    assert rec.rule_of(conn, "v1")["engineer_check"]["accounted_numbers"] == counted


def test_an_engineer_not_ok_with_other_figures_is_recorded_as_not_ok(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    other = [dict(f, comparator="<=") for f in CONFIRMED]
    out = answer(tmp_path, conn, pages, verdict="NOT_OK", confirmed_figures=other)
    assert rec.record_engineer_check(conn, "v1", out, run_id="x") == rf.FAIL
    assert st.latest_steps(conn, "v1")["e"]["reason"] == "engineer_check_not_ok"


def test_apply_proposal_needs_a_named_approver(tmp_path):
    conn = make_copy(
        tmp_path / "w.sqlite", quote="The wall shall be at least 10 mm thick."
    )
    for bad in ("", "  ", None):
        with pytest.raises(ValueError, match="approver"):
            rr.apply_proposal(conn, "v1", {"value": 10, "unit": "mm"}, bad)
    assert st.latest_steps(conn, "v1") == {}


def test_a_symlink_inside_the_trace_folder_is_refused_and_the_file_open_never_follows_one(
    tmp_path, monkeypatch
):
    conn, pages = two_figure_copy(tmp_path)
    root = tmp_path / "trace"
    (root / "real").mkdir(parents=True)
    (root / "link").symlink_to(
        root / "real"
    )  # a link to another place INSIDE the trace folder
    with pytest.raises(ValueError, match="symlink"):
        rec.make_engineer_input(conn, "v1", root / "link", pages, trace_root=root)
    good = root / "ok"
    path, _ = rec.make_engineer_input(conn, "v1", good, pages, trace_root=root)
    target = root / "real" / "target"
    target.write_text("do not overwrite")
    path.unlink()
    path.symlink_to(target)
    monkeypatch.setattr(
        Path, "is_symlink", lambda self: False
    )  # only the open itself is left to refuse it
    with pytest.raises(OSError):
        rec.make_engineer_input(conn, "v1", good, pages, trace_root=root)
    assert target.read_text() == "do not overwrite"


def test_an_issued_file_is_mode_0600_whatever_the_umask(tmp_path):
    conn, pages = two_figure_copy(tmp_path)
    old = os.umask(0)
    try:
        path, _ = rec.make_engineer_input(
            conn, "v1", tmp_path / "issued", pages, trace_root=tmp_path
        )
    finally:
        os.umask(old)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
