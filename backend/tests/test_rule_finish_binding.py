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


# ------------------------------------------------------------------------------------------------ H1 proposals


@pytest.mark.parametrize("bad", ["<=", "garbage", ">", None, ""])
def test_apply_proposal_refuses_a_comparator_the_quote_does_not_give_that_figure(
    tmp_path, bad
):
    conn = make_copy(
        tmp_path / "w.sqlite", quote="The wall shall be at least 10 mm thick."
    )
    with pytest.raises(ValueError):
        rr.apply_proposal(
            conn, "v1", {"value": 10.0, "unit": "mm", "comparator": bad}, "o"
        )
    assert st.latest_steps(conn, "v1") == {}
    rr.apply_proposal(
        conn, "v1", {"value": 10.0, "unit": "mm", "comparator": ">="}, "o"
    )


@pytest.mark.parametrize(
    "quote, value, good",
    [
        ("The wall shall not be less than 10 mm thick.", 10.0, ">="),
        ("The wall shall be not exceeding 10 mm.", 10.0, "<="),
        ("Not less than 10 mm nor more than 20 mm.", 20.0, "<="),
        ("Height 10 mm minimum, 20 mm maximum.", 20.0, "<="),
    ],
)
def test_the_negated_and_trailing_phrases_give_proposals_the_right_polarity(
    tmp_path, quote, value, good
):
    conn = make_copy(tmp_path / "w.sqlite", quote=quote)
    wrong = {">=": "<=", "<=": ">="}[good]
    for bad in (wrong, "<" if good == ">=" else ">"):
        with pytest.raises(ValueError):
            rr.apply_proposal(
                conn, "v1", {"value": value, "unit": "mm", "comparator": bad}, "o"
            )
    rr.apply_proposal(
        conn, "v1", {"value": value, "unit": "mm", "comparator": good}, "o"
    )


def test_apply_proposal_checks_each_figure_against_its_own_phrase(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")  # at least 10 mm and at most 20 mm
    with pytest.raises(ValueError):
        rr.apply_proposal(
            conn, "v1", {"value": 10.0, "unit": "mm", "comparator": "<="}, "o"
        )
    rr.apply_proposal(
        conn, "v1", {"value": 20.0, "unit": "mm", "comparator": "<="}, "o"
    )


def test_a_range_proposal_needs_the_quotes_low_and_high_ends_and_no_comparator(
    tmp_path,
):
    conn = make_copy(
        tmp_path / "w.sqlite", quote="Ambient shall be between 10 and 40 C."
    )
    for bad in (
        {"value_low": 10.0, "value_high": 40.0, "unit": "C", "comparator": ">="},
        {"value_low": 40.0, "value_high": 40.0, "unit": "C"},
    ):
        with pytest.raises(ValueError):
            rr.apply_proposal(conn, "v1", bad, "o")
    rr.apply_proposal(
        conn, "v1", {"value_low": 10.0, "value_high": 40.0, "unit": "C"}, "o"
    )


def test_apply_repair_checks_the_comparator_against_the_figures_it_is_applied_to(
    tmp_path,
):
    conn = make_copy(tmp_path / "w.sqlite")
    pages = {1: "The wall shall be at least 10 mm and at most 20 mm thick."}
    out = rr.apply_repair(
        conn,
        "v1",
        {"comparator": "<=", "figures": [{"value": 10.0, "unit": "mm"}]},
        "o",
        pages=pages,
    )
    assert ("comparator", "comparator_not_in_quote") in {
        (x["part"], x["reason"]) for x in out["refused"]
    }
    out = rr.apply_repair(
        conn,
        "v1",
        {"comparator": "<=", "figures": [{"value": 20.0, "unit": "mm"}]},
        "o",
        pages=pages,
    )
    assert out["refused"] == []
    out = rr.apply_repair(
        conn, "v1", {"comparator": "<="}, "o", pages=pages
    )  # no figure of this repair, the rule has none
    assert ("comparator", "comparator_not_in_quote") in {
        (x["part"], x["reason"]) for x in out["refused"]
    }


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


# ------------------------------------------------------------------------------------------------ H7 / H8 steps e and f


def _output(path: Path, **kw):
    data = {
        "rule_key_prefix": "keyabc12",
        "verdict": "OK",
        "checker": "Claude chat helper (KJO engineer role)",
    }
    data.update(kw)
    path.write_text(json.dumps(data))
    return path


def _tick(path: Path, conn, **kw):
    (r,) = st.load_rules_by_version(conn, "v1")
    data = {
        "sample_id": "s1",
        "folder": "01",
        "ticks": {"v1": {"tick": "ok", "quote_sha256": rec.quote_sha256(r)}},
    }
    data.update(kw)
    path.write_text(json.dumps(data))
    return path


def test_step_e_is_bound_to_the_full_key_the_version_and_the_quote_hash(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    out = _output(tmp_path / "out.json")
    assert rec.record_engineer_check(conn, "v1", out, run_id="x") == rf.PASS
    row = st.latest_steps(conn, "v1")["e"]
    (r,) = st.load_rules_by_version(conn, "v1")
    assert row["checker"] == rec.CHECKER_KIND
    assert row["evidence"] == {
        "file": "out.json",
        "path": str(out),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "verdict": "OK",
        "rule_key": "keyabc12345",
        "rule_version_id": "v1",
        "quote_sha256": rec.quote_sha256(r),
    }
    assert (
        rec.record_engineer_check(
            conn, "v1", _output(tmp_path / "n.json", verdict="not ok"), run_id="y"
        )
        == rf.FAIL
    )


@pytest.mark.parametrize(
    "change",
    [
        {"verdict": "maybe"},
        {"verdict": ""},
        {"rule_key_prefix": "keyabc1"},  # shorter than 8
        {"rule_key_prefix": "keyabc99"},
        {"rule_key_prefix": 123456789},
        {"checker": ""},
        {"checker": "code"},
        {"checker": "owner"},
        {"rule_keys": ["keyabc12345", "other"]},
        {"rules": []},
        {"rule_version_id": "v2"},
        {"quote_sha256": "0" * 64},
    ],
)
def test_step_e_refuses_an_output_that_cannot_be_bound_to_this_rule(tmp_path, change):
    conn = make_copy(tmp_path / "w.sqlite")
    with pytest.raises(ValueError, match="refused"):
        rec.record_engineer_check(
            conn, "v1", _output(tmp_path / "o.json", **change), run_id="x"
        )
    assert st.latest_steps(conn, "v1") == {}
    with pytest.raises(ValueError):
        rec.record_engineer_check(conn, "v1", tmp_path / "missing.json", run_id="x")
    (tmp_path / "list.json").write_text("[1]")
    with pytest.raises(ValueError):
        rec.record_engineer_check(conn, "v1", tmp_path / "list.json", run_id="x")


def test_step_e_ties_the_closed_checker_kind_by_name_or_by_kind(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    assert (
        rec.record_engineer_check(
            conn,
            "v1",
            _output(
                tmp_path / "k.json", checker="", checker_kind="ai_engineer_chat_helper"
            ),
            run_id="x",
        )
        == rf.PASS
    )


def test_an_engineer_output_file_cannot_be_replayed_for_another_version(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    out = _output(tmp_path / "out.json")
    rec.record_engineer_check(conn, "v1", out, run_id="x")
    conn.execute(
        "INSERT INTO rulebook_version SELECT 'v2', rule_id, 2, kind, field, comparator, value, value_low, value_high, value_text, unit, unit_dimension, strength, sentence_strength, context_flag FROM rulebook_version WHERE id='v1'"
    )
    conn.execute(
        "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote) VALUES ('v2','d','4.1',1,'A changed quote shall apply to 5 mm.')"
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    with pytest.raises(ValueError, match="another version"):
        rec.record_engineer_check(conn, "v2", out, run_id="y")


def test_step_f_is_bound_to_sample_folder_version_quote_and_the_tick_file(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    tick = _tick(tmp_path / "t.json", conn)
    assert rec.record_owner_sample(conn, "v1", "s1", tick, run_id="x") == rf.PASS
    ev = st.latest_steps(conn, "v1")["f"]["evidence"]
    assert ev["sha256"] == hashlib.sha256(tick.read_bytes()).hexdigest()
    assert (ev["sample_id"], ev["folder"], ev["rule_version_id"]) == ("s1", "01", "v1")
    assert (
        rec.record_owner_sample(
            conn,
            "v1",
            "s1",
            _tick(
                tmp_path / "w.json",
                conn,
                ticks={"v1": {"tick": "wrong", "quote_sha256": ev["quote_sha256"]}},
            ),
            run_id="y",
        )
        == rf.FAIL
    )
    for kw, sid in (
        ({"sample_id": "s2"}, "s1"),
        ({}, "s2"),
        ({}, ""),
        ({"folder": ""}, "s1"),
        ({"ticks": {"other": {"tick": "ok"}}}, "s1"),
        ({"ticks": {"v1": {"tick": "ok", "quote_sha256": "0" * 64}}}, "s1"),
        ({"ticks": {"v1": {"tick": "yes", "quote_sha256": ev["quote_sha256"]}}}, "s1"),
    ):
        with pytest.raises(ValueError, match="refused"):
            rec.record_owner_sample(
                conn, "v1", sid, _tick(tmp_path / "x.json", conn, **kw), run_id="z"
            )


def test_a_check_bound_to_an_earlier_quote_is_stale_and_never_counts(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    rec.record_engineer_check(conn, "v1", _output(tmp_path / "o.json"), run_id="x")
    rec.record_owner_sample(
        conn, "v1", "s1", _tick(tmp_path / "t.json", conn), run_id="x"
    )
    assert (
        rec.current_steps(conn, "v1")["e"] == "pass"
        and rec.current_steps(conn, "v1")["f"] == "pass"
    )
    conn.execute(
        "UPDATE rulebook_provenance SET quote = 'The wall shall be at least 11 mm thick.' WHERE rule_version_id = 'v1'"
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    now = rec.current_steps(conn, "v1")
    assert (now["e"], now["f"]) == ("stale", "stale")
    flat = {"a": "pass", "b": "pass", "c": "pass", "d": "pass", "g": "pass", **now}
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
        {
            "rule_version_id": "v2",
            "quote_sha256": rec.quote_sha256(rec.rule_of(conn, "v1")),
        },
        checker="c",
        model="m",
        run_id="r",
    )
    assert rec.current_steps(conn, "v1")["e"] == "stale"  # bound to another version


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
