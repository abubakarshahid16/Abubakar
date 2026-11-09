"""Hardening of the rule finishing line after review (Lane 1): comparators, the write guard, unreadable figures, closed
vocabulary, the finish rules and recorded steps. Every text here is INVENTED."""

# ruff: noqa: RUF001  (thin and no-break spaces in digit groups are the point of these tests)
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app import rule_finish as rf
from app import rule_finish_figures as ff
from app import rule_finish_guard as guard
from app import rule_finish_repair as rr
from app import rule_finish_store as st


def rule(**kw):
    base = {
        "rule_id": "r1",
        "rule_key": "abcdef0123",
        "version_id": "v1",
        "standard": "X.pdf",
        "kind": "no_figure",
        "field": "wall thickness",
        "comparator": None,
        "value": None,
        "value_low": None,
        "value_high": None,
        "unit": None,
        "quote": "Widgets shall be painted.",
        "page": 1,
        "standard_document_id": "d",
        "applicability": [("subject", "pumps")],
    }
    base.update(kw)
    return base


def make_copy(
    path: Path,
    quote="The wall shall be at least 10 mm and at most 20 mm thick.",
    marked=True,
):
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE rulebook_rule (id TEXT, rule_key TEXT, standard TEXT);
        CREATE TABLE rulebook_version (id TEXT, rule_id TEXT, version_no INT, kind TEXT, field TEXT, comparator TEXT,
          value REAL, value_low REAL, value_high REAL, value_text TEXT, unit TEXT, unit_dimension TEXT, strength TEXT,
          sentence_strength TEXT, context_flag TEXT);
        CREATE TABLE rulebook_provenance (id INTEGER PRIMARY KEY, rule_version_id TEXT, standard_document_id TEXT,
          edition TEXT, clause TEXT, page INT, quote TEXT, quote_start INT, quote_end INT, page_source TEXT);
        CREATE TABLE rulebook_applicability (id INTEGER PRIMARY KEY, rule_version_id TEXT, key_type TEXT, value TEXT);"""
    )
    conn.execute("INSERT INTO rulebook_rule VALUES ('r1','keyabc','X.pdf')")
    conn.execute(
        "INSERT INTO rulebook_version VALUES ('v1','r1',1,'no_figure','wall thickness',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'shall',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote) VALUES ('v1','d','4.1',1,?)",
        (quote,),
    )
    conn.execute(
        "INSERT INTO rulebook_applicability (rule_version_id, key_type, value) VALUES ('v1','subject','pumps')"
    )
    conn.commit()
    if marked:
        guard._write_marker(conn, guard._real(path), "source-of-this-copy")
    return conn


# ------------------------------------------------------------------------------------------------ H1 comparators


@pytest.mark.parametrize(
    "quote, expected",
    [
        ("at least 10 mm and at most 20 mm", [(10.0, ">="), (20.0, "<=")]),
        ("not less than 6 mm", [(6.0, ">=")]),
        ("shall not exceed 6 mm", [(6.0, "<=")]),
        ("exactly 6 mm", [(6.0, "=")]),
        ("between 10 and 40 C", [(10.0, ">="), (40.0, "<=")]),
        ("from 10 to 40 C", [(10.0, ">="), (40.0, "<=")]),
        ("10-40 C", [(10.0, ">="), (40.0, "<=")]),
        ("shall be 6 mm", [(6.0, None)]),  # no phrase of its own: no comparator
        ("at least 5 mm, at most 9 mm", [(5.0, ">="), (9.0, "<=")]),
    ],
)
def test_each_figure_takes_the_comparator_of_its_own_governing_phrase(quote, expected):
    assert [(f.value, f.comparator) for f in ff.figures(quote)] == expected


def test_conflicting_polarity_in_one_phrase_gives_no_comparator():
    (f,) = ff.figures("at least or at most 6 mm")
    assert f.comparator is None and f.comparator_source == "conflicting_phrases"


def test_a_range_proposal_is_two_figures_never_one_without_a_comparator():
    _, _, ev = rf.limit_and_unit(rule(quote="Ambient shall be between 10 and 40 C."))
    assert [(p["value"], p["comparator"]) for p in ev["proposed"]] == [
        (10.0, ">="),
        (40.0, "<="),
    ]


@pytest.mark.parametrize("bad", ["<=", "garbage", ">", None])
def test_apply_proposal_refuses_a_comparator_the_quote_does_not_give_that_figure(
    tmp_path, bad
):
    conn = make_copy(
        tmp_path / "w.sqlite", quote="The wall shall be at least 10 mm thick."
    )
    with pytest.raises(ValueError):
        st.apply_proposal(
            conn, "v1", {"value": 10.0, "unit": "mm", "comparator": bad}, "o"
        )
    assert st.latest_steps(conn, "v1") == {}
    st.apply_proposal(
        conn, "v1", {"value": 10.0, "unit": "mm", "comparator": ">="}, "o"
    )


def test_apply_proposal_checks_each_figure_against_its_own_phrase(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")  # at least 10 mm and at most 20 mm
    with pytest.raises(ValueError):
        st.apply_proposal(
            conn, "v1", {"value": 10.0, "unit": "mm", "comparator": "<="}, "o"
        )  # the other figure's
    st.apply_proposal(
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
            st.apply_proposal(conn, "v1", bad, "o")
    st.apply_proposal(
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


# ------------------------------------------------------------------------------------------------ H2 write guard


def test_a_write_is_refused_unless_the_database_is_a_marked_copy_by_what_it_is_not_by_its_name(
    tmp_path,
):
    for name in ("PSV-ALL.SQLITE", "Compile.sqlite", "anything.db", "work.sqlite"):
        conn = make_copy(tmp_path / name, marked=False)
        for call in (
            lambda c: st.ensure_table(c),
            lambda c: st._append_step(
                c, "v1", "a", "pass", "r", {}, checker="c", model="m", run_id="x"
            ),
            lambda c: st.apply_proposal(
                c, "v1", {"value": 10.0, "unit": "mm", "comparator": ">="}, "o"
            ),
            lambda c: rr.apply_repair(c, "v1", {}, "o", pages={}),
        ):
            with pytest.raises(guard.NotAWorkCopy):
                call(conn)
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='rule_finish_step'"
            ).fetchone()
            is None
        )


def test_a_marker_copied_with_the_file_does_not_make_another_file_writable(tmp_path):
    make_copy(tmp_path / "a.sqlite").close()
    (tmp_path / "b.sqlite").write_bytes((tmp_path / "a.sqlite").read_bytes())
    with pytest.raises(guard.NotAWorkCopy):
        guard.require_work_copy(sqlite3.connect(tmp_path / "b.sqlite"))


def test_a_marked_copy_that_is_a_protected_database_is_refused(tmp_path):
    conn = make_copy(tmp_path / "a.sqlite")
    guard.require_work_copy(conn)
    with pytest.raises(guard.NotAWorkCopy):
        guard.require_work_copy(conn, protected=[tmp_path / "a.sqlite"])
    link = tmp_path / "link.sqlite"
    link.symlink_to(tmp_path / "a.sqlite")
    with pytest.raises(guard.NotAWorkCopy):
        guard.require_work_copy(conn, protected=[link])


def test_the_app_and_live_databases_are_protected(tmp_path, monkeypatch):
    conn = make_copy(tmp_path / "live.sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "live.sqlite"))
    with pytest.raises(guard.NotAWorkCopy):
        guard.require_work_copy(conn)


def test_prepare_and_adopt_make_the_marker_only_for_a_verified_copy(tmp_path):
    source = tmp_path / "src.sqlite"
    make_copy(source, marked=False).close()
    copy = guard.prepare_work_copy(source, tmp_path / "work.sqlite")
    guard.require_work_copy(sqlite3.connect(copy), [source])
    old = tmp_path / "old.sqlite"
    old.write_bytes(source.read_bytes())
    assert guard.adopt_copy(source, old) == old
    guard.require_work_copy(sqlite3.connect(old), [source])
    stranger = tmp_path / "stranger.sqlite"
    sqlite3.connect(stranger).close()
    with pytest.raises(guard.NotAWorkCopy):
        guard.adopt_copy(source, stranger)
    with pytest.raises(guard.NotAWorkCopy):
        guard.adopt_copy(source, source)
    other = make_copy(tmp_path / "other.sqlite", marked=False)
    other.execute("DELETE FROM rulebook_provenance")
    other.commit()
    with pytest.raises(
        guard.NotAWorkCopy
    ):  # same tables, other rows: not a copy of this source
        guard.adopt_copy(source, tmp_path / "other.sqlite")


# ------------------------------------------------------------------------------------------------ H3 H4 M8 unreadable figures


@pytest.mark.parametrize(
    "quote, value", [("size ½ inch", 0.5), ("size 1½ inch", 1.5), ("size ¾ inch", 0.75)]
)
def test_a_vulgar_fraction_character_is_read_through_numparse(quote, value):
    result, reason, ev = rf.limit_and_unit(rule(quote=quote))
    assert (result, reason) == (rf.FAIL, "figure_not_filled") and ev["proposed"][0][
        "value"
    ] == value
    filled = rule(quote=quote, kind="limit", value=value, unit="inch", comparator=">=")
    assert rf.limit_and_unit(filled)[0] == rf.PASS


@pytest.mark.parametrize(
    "quote", ["a gap of 1 000 mm", "a gap of 1 000 mm", "a gap of 1 000 mm"]
)
def test_grouped_thousands_are_one_number_and_zero_never_stands_for_them(quote):
    assert [f.value for f in ff.figures(quote)] == [1000.0]
    assert rf.limit_and_unit(
        rule(quote=quote, kind="limit", value=0, unit="mm", comparator="=")
    )[:2] == (rf.FAIL, "value_not_in_quote")
    ok = rule(quote=quote, kind="limit", value=1000, unit="mm", comparator="=")
    assert rf.limit_and_unit(ok)[0] == rf.PASS
    assert (
        rf.limit_and_unit(
            rule(
                quote="a gap of 0 mm", kind="limit", value=0, unit="mm", comparator="="
            )
        )[0]
        == rf.PASS
    )


@pytest.mark.parametrize(
    "quote",
    [
        "a head of 10 mm Hg",
        "a head of 5 mm H2O",
        "a rate of 5 mm per side",
        "5 mm w.c.",
    ],
)
def test_a_unit_followed_by_a_second_unit_word_is_incomplete(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (rf.INCOMPLETE, "compound_unit")
    filled = rule(quote=quote, kind="limit", value=5, unit="mm", comparator="=")
    assert rf.limit_and_unit(filled)[0] == rf.INCOMPLETE


def test_a_compound_unit_the_unit_table_reads_is_a_figure():
    assert rf.limit_and_unit(rule(quote="a rate of 10 mm/s"))[:2] == (
        rf.FAIL,
        "figure_not_filled",
    )


# ------------------------------------------------------------------------------------------------ M5 closed vocabulary


def test_an_equipment_type_row_outside_the_vocabulary_is_incomplete_and_leaves_no_raw_text():
    r = rule(applicability=[("equipment_type", "banana widget")])
    result, reason, ev = rf.conditions_of(r)
    assert (result, reason) == (rf.INCOMPLETE, "equipment_type_not_in_vocabulary")
    assert "banana" not in json.dumps(ev)
    assert (
        rf.conditions_of(rule(applicability=[("equipment_type", "centrifugal pump")]))[
            0
        ]
        == rf.PASS
    )


# ------------------------------------------------------------------------------------------------ M6 finish rules

ALL = {
    "a": "pass",
    "b": "pass",
    "c": "pass",
    "d": "pass",
    "e": "pass",
    "f": "pass",
    "g": "pass",
}


def test_an_engineer_check_that_is_pending_does_not_finish_a_rule():
    for bad in ("incomplete", "not_applicable", "fail"):
        assert rf.may_decide(dict(ALL, e=bad)) is False
    assert rf.may_decide(dict(ALL, f="not_applicable")) is False
    assert (
        rf.may_decide(dict(ALL, b="not_applicable")) is True
        and rf.may_decide(dict(ALL, a="not_applicable")) is True
    )


def test_a_value_filled_with_no_unit_figure_in_the_quote_needs_unit_none():
    r = rule(
        quote="Provide at least 3 stages.",
        kind="limit",
        value=3,
        comparator=">=",
        unit=None,
    )
    assert rf.limit_and_unit(r)[:2] == (rf.PASS, "value_stands_no_unit_in_quote")
    assert rf.limit_and_unit(dict(r, unit="mm"))[:2] == (rf.FAIL, "unit_not_in_quote")


def test_a_fragment_needs_every_pointer_to_hold_its_list():
    q = "The vendor shall state the following: (a) the tag; (b) the service; (c) the date; as listed below"
    assert (
        rf.fragments(rule(quote=q), {})[0] == rf.INCOMPLETE
    )  # the second pointer holds no list


def test_a_condition_the_reader_cannot_read_whole_is_incomplete():
    r = rule(
        applicability=[
            ("subject", "pumps"),
            ("condition", "above 100 kPa and when the moon is full"),
        ]
    )
    assert rf.conditions_of(r)[0] == rf.INCOMPLETE


# ------------------------------------------------------------------------------------------------ M7 recorded steps


def test_a_code_step_is_recomputed_and_nobody_can_hand_in_a_pass(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    (r,) = st.load_rules_by_version(conn, "v1")
    assert (
        st.record_code_step(conn, r, "a", run_id="x")[0] == rf.FAIL
    )  # the quote has figures, none filled
    assert st.latest_steps(conn, "v1")["a"]["result"] == rf.FAIL
    with pytest.raises(ValueError):
        st.record_code_step(conn, r, "e", run_id="x")
    with pytest.raises(ValueError):
        st._append_step(
            conn, "v1", "a", "maybe", "r", {}, checker="c", model="m", run_id="x"
        )
    assert not hasattr(st, "record_step")


def _output(path: Path, **kw):
    data = {
        "rule_key_prefix": "keyabc",
        "verdict": "OK",
        "checker": "Claude chat helper (KJO engineer role)",
    }
    data.update(kw)
    path.write_text(json.dumps(data))
    return path


def test_step_e_needs_the_engineer_output_file_its_sha256_and_a_verdict(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    out = _output(tmp_path / "out.json")
    assert st.record_engineer_check(conn, "v1", out, run_id="x") == rf.PASS
    row = st.latest_steps(conn, "v1")["e"]
    assert row["evidence"]["sha256"] == hashlib.sha256(
        out.read_bytes()
    ).hexdigest() and row["checker"].startswith("Claude chat")
    assert (
        st.record_engineer_check(
            conn, "v1", _output(tmp_path / "n.json", verdict="NOT_OK"), run_id="y"
        )
        == rf.FAIL
    )
    for bad in (
        tmp_path / "missing.json",
        _output(tmp_path / "v.json", verdict="maybe"),
        _output(tmp_path / "k.json", rule_key_prefix="zzz"),
        _output(tmp_path / "c.json", checker=""),
    ):
        with pytest.raises(ValueError):
            st.record_engineer_check(conn, "v1", bad, run_id="z")


def test_step_f_needs_a_sample_id_and_the_owners_tick_in_a_file(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    tick = tmp_path / "tick.json"
    tick.write_text(json.dumps({"sample_id": "s1", "ticks": {"keyabc": "ok"}}))
    assert st.record_owner_sample(conn, "v1", "s1", tick, run_id="x") == rf.PASS
    assert (
        st.latest_steps(conn, "v1")["f"]["evidence"]["sha256"]
        == hashlib.sha256(tick.read_bytes()).hexdigest()
    )
    tick.write_text(json.dumps({"sample_id": "s1", "ticks": {"keyabc": "wrong"}}))
    assert st.record_owner_sample(conn, "v1", "s1", tick, run_id="y") == rf.FAIL
    for sid in ("s2", ""):
        with pytest.raises(ValueError):
            st.record_owner_sample(conn, "v1", sid, tick, run_id="z")
    tick.write_text(json.dumps({"sample_id": "s1", "ticks": {"other": "ok"}}))
    with pytest.raises(ValueError):
        st.record_owner_sample(conn, "v1", "s1", tick, run_id="z")


def test_history_stays_readable_and_the_latest_wins(tmp_path):
    conn = make_copy(tmp_path / "w.sqlite")
    st.record_engineer_check(
        conn, "v1", _output(tmp_path / "a.json", verdict="NOT_OK"), run_id="1"
    )
    st.record_engineer_check(conn, "v1", _output(tmp_path / "b.json"), run_id="2")
    assert st.latest_steps(conn, "v1")["e"]["result"] == rf.PASS
    assert (
        conn.execute("SELECT COUNT(*) FROM rule_finish_step WHERE step='e'").fetchone()[
            0
        ]
        == 2
    )


def test_a_quote_with_no_phrase_gives_no_comparator_and_none_is_not_accepted_as_one(
    tmp_path,
):
    conn = make_copy(tmp_path / "w.sqlite", quote="The wall shall be 10 mm thick.")
    for given in (None, "", ">="):
        with pytest.raises(ValueError):
            st.apply_proposal(
                conn, "v1", {"value": 10.0, "unit": "mm", "comparator": given}, "o"
            )
