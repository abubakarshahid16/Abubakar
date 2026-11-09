"""Fractions in step a, and the verified repair of a rule in a work copy (Lane 1). Every text here is INVENTED."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import rule_finish as rf
from app import rule_finish_repair as rr
from app import rule_finish_store as st

QUOTE = "The inlet shall be at least 3/4 inch for threaded valves and at least 1 inch for flanged valves."
PAGES = {
    1: "Page text. The inlet shall be at least 3/4 inch for threaded valves and at least 1 inch for flanged valves. Small widgets may be smaller.\nSmall compressor widgets are exempt."
}


def rule(**kw):
    base = {
        "quote": QUOTE,
        "kind": "no_figure",
        "field": "inlet size",
        "value": None,
        "unit": None,
    }
    base.update(kw)
    return base


# ------------------------------------------------------------------------------------------------ A: fractions


@pytest.mark.parametrize(
    "quote, expected",
    [
        ("at least 3/4 inch", 0.75),
        ("at least 1 1/2 inch", 1.5),
        ("at least 2-3/8 inch", 2.375),
        ("at least 3 / 4 inch", 0.75),
    ],
)
def test_a_fraction_is_one_figure_read_whole_by_numparse_never_its_denominator(
    quote, expected
):
    result, reason, ev = rf.limit_and_unit(rule(quote=quote))
    assert (result, reason) == (rf.FAIL, "figure_not_filled")
    assert [p["value"] for p in ev["proposed"]] == [
        expected
    ]  # the old reading gave 4.0 for 3/4 inch


def test_a_fraction_and_a_plain_figure_in_one_quote_are_both_proposed():
    _, _, ev = rf.limit_and_unit(rule())
    assert sorted(p["value"] for p in ev["proposed"]) == [0.75, 1.0]


def test_a_filled_fraction_value_stands_and_its_denominator_does_not():
    ok = rule(
        quote="at least 3/4 inch",
        kind="limit",
        value=0.75,
        unit="inch",
        comparator=">=",
    )
    assert rf.limit_and_unit(ok)[0] == rf.PASS
    for wrong in (4.0, 3.0):
        bad = dict(ok, value=wrong)
        assert rf.limit_and_unit(bad)[:2] == (rf.FAIL, "value_not_in_quote")


def test_a_slash_figure_numparse_does_not_read_whole_is_ambiguous_so_step_a_is_incomplete():
    for quote in ("at least 1/2/3 inch of cover", "use 12/25/2019 mm"):
        assert rf.limit_and_unit(rule(quote=quote))[:2] == (
            rf.INCOMPLETE,
            "figure_ambiguous",
        )
    assert (
        rf.limit_and_unit(rule(quote="issued 12/25/2019 for the project"))[0]
        == rf.NOT_APPLICABLE
    )


def _copy(path: Path) -> sqlite3.Connection:
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
        "INSERT INTO rulebook_version VALUES ('v1','r1',1,'no_figure','inlet size',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'shall',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote) VALUES ('v1','d',  '4.1', 1, ?)",
        (QUOTE,),
    )
    conn.execute(
        "INSERT INTO rulebook_applicability (rule_version_id, key_type, value) VALUES ('v1','subject','relief valves')"
    )
    conn.commit()
    return conn


def test_apply_proposal_refuses_the_denominator_that_the_old_reading_proposed(tmp_path):
    conn = _copy(tmp_path / "w.sqlite")
    with pytest.raises(ValueError):
        st.apply_proposal(
            conn, "v1", {"value": 4.0, "unit": "inch", "comparator": ">="}, "o"
        )
    with pytest.raises(ValueError):  # a value that is not exactly a quoted figure
        st.apply_proposal(
            conn, "v1", {"value": 0.8, "unit": "inch", "comparator": ">="}, "o"
        )
    st.apply_proposal(
        conn, "v1", {"value": 0.75, "unit": "inch", "comparator": ">="}, "o"
    )
    assert st.latest_steps(conn, "v1")["a"]["reason"] == "proposal_applied"


# ------------------------------------------------------------------------------------------------ B: step b, d


def test_step_b_a_quantity_field_with_a_figure_is_a_datasheet_value_by_a_cue_list():
    result, reason, ev = rf.evidence_source(
        rule(quote="The inlet shall be at least 3/4 inch.")
    )
    assert (result, reason) == (rf.PASS, rf.DATASHEET_VALUE) and "size" in ev["cues"]
    assert (
        rf.evidence_source(rule(quote="Widgets shall be good.", field="widgets"))[0]
        == rf.INCOMPLETE
    )
    assert (
        rf.evidence_source(rule(field="colour"))[0] == rf.INCOMPLETE
    )  # a figure but no quantity cue on the field


def test_step_d_connection_types_and_exceptions_are_testable_and_unknown_wording_is_incomplete():
    r = rule(
        applicability=[
            ("subject", "relief valves"),
            ("condition", "threaded"),
            ("condition", "flanged"),
        ]
    )
    result, _, ev = rf.conditions_of(r)
    assert result == rf.PASS
    assert [t["values"] for t in ev["tests"]] == [["threaded"], ["flanged"]]
    ok = rule(
        applicability=[("subject", "relief valves")],
        exceptions=["small compressor valves"],
    )
    assert rf.conditions_of(ok)[0] == rf.PASS
    bad = rule(
        applicability=[("subject", "relief valves")], exceptions=["gizmos on the moon"]
    )
    assert rf.conditions_of(bad)[:2] == (rf.INCOMPLETE, "exception_not_read")


# ------------------------------------------------------------------------------------------------ B: apply_repair

REPAIR = {
    "comparator": ">=",
    "figures": [
        {"value": 0.75, "unit": "inch", "condition": "threaded"},
        {"value": 1.0, "unit": "inch", "condition": "flanged"},
    ],
    "exceptions": ["small compressor widgets"],
}


def test_a_verified_repair_is_applied_to_the_copy_and_steps_a_b_d_pass(tmp_path):
    conn = _copy(tmp_path / "w.sqlite")
    st.record_step(
        conn, "v1", "e", "fail", "not_ok", {}, checker="helper", model="m", run_id="r"
    )
    out = rr.apply_repair(conn, "v1", REPAIR, "lead", pages=PAGES)
    assert out["refused"] == [] and out["steps"]["a"] == (
        "pass",
        "figures_stand_in_quote",
    )
    latest = st.latest_steps(conn, "v1")
    assert latest["a"]["result"] == latest["b"]["result"] == "pass"
    assert (latest["e"]["result"], latest["e"]["reason"]) == (
        "incomplete",
        "pending_recheck_after_repair",
    )
    (r,) = st.load_rules_by_version(conn, "v1")
    after = st.overlay_applied(conn, r)
    assert (
        len(after["figures"]) == 1 + 1
        and ("condition", "threaded") in after["applicability"]
    )
    assert after["exceptions"] == ["small compressor widgets"]
    assert (
        rf.conditions_of(after)[0] == rf.PASS and rf.limit_and_unit(after)[0] == rf.PASS
    )
    assert conn.execute("SELECT COUNT(*) FROM rule_finish_repair").fetchone()[0] == 6


def test_parts_that_code_cannot_verify_are_refused_and_the_rest_still_applies(tmp_path):
    conn = _copy(tmp_path / "w.sqlite")
    repair = {
        "comparator": "<=",  # the quote implies a minimum
        "figures": [
            {"value": 4.0, "unit": "inch", "condition": "threaded"},  # the denominator
            {
                "value": 1.0,
                "unit": "inch",
                "condition": "connection is flanged",
            },  # words not on the page
            {"value": 0.75, "unit": "inch", "condition": "threaded"},
        ],
        "exceptions": [
            "purple gizmos",
            "compressor widgets 99",
        ],  # a word not on the page; a number not on it
        "field": "inlet nps",
    }
    out = rr.apply_repair(conn, "v1", repair, "lead", pages=PAGES)
    reasons = {(x["part"], x["reason"]) for x in out["refused"]}
    assert ("comparator", "comparator_not_in_quote") in reasons
    assert ("figure 4.0", "value_not_in_quote") in reasons
    assert ("condition of figure 1.0", "word_not_on_page") in reasons
    assert ("exception", "word_not_on_page") in reasons and (
        "field",
        "word_not_on_page",
    ) in reasons
    assert ("exception", "number_not_on_page") in reasons
    assert [x["part"] for x in out["applied"]] == [
        "condition of figure 0.75",
        "figure 0.75",
    ]


def test_a_repair_refuses_an_original_database_an_empty_approver_and_a_missing_rule(
    tmp_path,
):
    with pytest.raises(PermissionError):
        rr.apply_repair(
            _copy(tmp_path / "psv-all.sqlite"), "v1", REPAIR, "lead", pages=PAGES
        )
    conn = _copy(tmp_path / "w.sqlite")
    with pytest.raises(ValueError):
        rr.apply_repair(conn, "v1", REPAIR, " ", pages=PAGES)
    with pytest.raises(ValueError):
        rr.apply_repair(conn, "nope", REPAIR, "lead", pages=PAGES)
    assert (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE name='rule_finish_repair'"
        ).fetchone()
        is None
    )


def test_a_repair_needs_the_page_text_for_a_condition():
    ok, why = rr.verify_text("threaded", {"page": 1}, {})
    assert (ok, why) == (False, "page_text_missing")


def test_a_denominator_does_not_stand_as_a_number_when_the_quote_has_no_unit_figure():
    r = rule(
        quote="The ratio shall be 3/4 of the total.",
        kind="limit",
        value=4.0,
        unit="none",
        comparator=">=",
    )
    assert rf.limit_and_unit(r)[:2] == (rf.FAIL, "value_not_in_quote")
    assert rf.limit_and_unit(dict(r, value=0.75))[0] == rf.PASS
