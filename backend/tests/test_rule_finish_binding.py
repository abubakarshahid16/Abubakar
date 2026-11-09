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


@pytest.mark.parametrize("bad", ["<=", "garbage", ">", None, ""])
def test_apply_proposal_refuses_a_comparator_the_quote_does_not_give_the_figure(
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
    "quote, good",
    [
        ("The wall shall not be less than 10 mm thick.", ">="),
        ("The wall shall be not exceeding 10 mm.", "<="),
        ("Height 10 mm maximum.", "<="),
        ("Height 10 mm or more.", ">="),
    ],
)
def test_the_simple_shape_gives_proposals_the_right_polarity(tmp_path, quote, good):
    conn = make_copy(tmp_path / "w.sqlite", quote=quote)
    for bad in ({">=": "<=", "<=": ">="}[good], "<" if good == ">=" else ">"):
        with pytest.raises(ValueError):
            rr.apply_proposal(
                conn, "v1", {"value": 10.0, "unit": "mm", "comparator": bad}, "o"
            )
    rr.apply_proposal(
        conn, "v1", {"value": 10.0, "unit": "mm", "comparator": good}, "o"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The wall shall be at least 10 mm and at most 20 mm thick.",
        "Not less than 10 mm nor more than 20 mm.",
        "Height 10 mm minimum, 20 mm maximum.",
        "At least 10 mm and 20 mm or less.",
        "Wall is 5 mm (minimum) for 40 bar",
        "A minimum of 4 bolts of 12 mm shall be fitted.",
    ],
)
def test_a_proposal_outside_the_simple_shape_is_refused_as_engineer_required(
    tmp_path, quote
):
    conn = make_copy(tmp_path / "w.sqlite", quote=quote)
    value = {"The wall shall be at least 10 mm and at most 20 mm thick.": 10.0}.get(
        quote, 10.0
    )
    for comparator in (">=", "<="):
        with pytest.raises(ValueError, match="engineer_required"):
            rr.apply_proposal(
                conn,
                "v1",
                {"value": value, "unit": "mm", "comparator": comparator},
                "o",
            )
    assert st.latest_steps(conn, "v1") == {}


def test_a_range_proposal_is_for_the_closed_forms_and_has_no_comparator_of_its_own(
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


def test_apply_repair_stores_an_allowed_comparator_and_step_a_decides_whether_it_is_right(
    tmp_path,
):
    conn = make_copy(
        tmp_path / "w.sqlite", quote="The wall shall be at least 10 mm thick."
    )
    pages = {1: "The wall shall be at least 10 mm thick."}
    out = rr.apply_repair(conn, "v1", {"comparator": "garbage"}, "o", pages=pages)
    assert ("comparator", "comparator_not_allowed") in {
        (x["part"], x["reason"]) for x in out["refused"]
    }
    rr.apply_repair(
        conn,
        "v1",
        {"comparator": "<=", "figures": [{"value": 10.0, "unit": "mm"}]},
        "o",
        pages=pages,
    )
    assert rf.limit_and_unit(rec.rule_of(conn, "v1"))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )


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
    _, digest = rec.make_engineer_input(conn, "v1", tmp_path / "issued", pages)
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
    }
    data.update(kw)
    out = tmp_path / name
    out.write_text(json.dumps(data))
    return out


def test_the_engineer_input_is_written_by_code_with_the_rule_the_pages_and_the_content_hash(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    path, digest = rec.make_engineer_input(conn, "v1", tmp_path / "issued", pages)
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
        "comparator_needs_engineer",
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
        "comparator_needs_engineer",
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
    sheet, digest = rec.make_sample_sheet(conn, "v1", tmp_path / "sheets", "s1", "01")
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
        rec.make_sample_sheet(conn, "v1", tmp_path / "sheets", "", "01")
    with pytest.raises(ValueError):
        rec.make_sample_sheet(conn, "v1", tmp_path / "sheets", "s1", " ")


def test_the_same_tick_file_cannot_be_recorded_again_after_the_content_changed(
    tmp_path,
):
    conn, _ = two_figure_copy(tmp_path)
    _, digest = rec.make_sample_sheet(conn, "v1", tmp_path / "sheets", "s1", "01")
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
    assert "confirmed_figures" not in rec.rule_of(conn, "v1")
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
    assert "confirmed_figures" not in rec.rule_of(
        conn, "v1"
    )  # only a PASS check confirms figures


def test_a_check_bound_to_an_earlier_quote_or_content_is_stale_and_never_counts(
    tmp_path,
):
    conn, pages = two_figure_copy(tmp_path)
    rec.record_engineer_check(conn, "v1", answer(tmp_path, conn, pages), run_id="x")
    _, digest = rec.make_sample_sheet(conn, "v1", tmp_path / "sheets", "s1", "01")
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
    assert "confirmed_figures" in rec.rule_of(conn, "v1")
    conn.execute(
        "UPDATE rulebook_provenance SET quote = ? WHERE rule_version_id = 'v1'",
        (f"The inlet shall be {TWO} and more.",),
    )
    conn.commit()
    guard._write_marker(conn, guard._real(tmp_path / "w.sqlite"), "source-of-this-copy")
    assert "confirmed_figures" not in rec.rule_of(conn, "v1")


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
