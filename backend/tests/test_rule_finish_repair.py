"""Applying a proposal or an engineer's repair to a marked work copy, verified by code (Lane 1).
Every text here is INVENTED."""

from __future__ import annotations

import pytest

from app import rule_finish as rf
from app import rule_finish_record as rec
from app import rule_finish_repair as rr
from app import rule_finish_store as st
from tests.test_rule_finish_kit import make_copy, marker_key, rule  # noqa: F401

QUOTE = "The inlet shall be at least 3/4 inch for threaded valves and at least 1 inch for flanged valves."
PAGES = {
    1: "Page text. The inlet shall be at least 3/4 inch for threaded valves and at least 1 inch for flanged valves. "
    "Small compressor widgets are exempt.\nWidgets shall not be painted."
}


def copy(tmp_path, quote=QUOTE, **kw):
    return make_copy(tmp_path / "w.sqlite", quote=quote, **kw)


# ------------------------------------------------------------------------------------------------ fractions


def test_a_fraction_is_one_figure_read_whole_never_its_denominator():
    _, _, ev = rf.limit_and_unit(rule(quote="at least 3/4 inch"))
    assert [p["value"] for p in ev["proposed"]] == [0.75]  # the old reading gave 4.0
    for quote, expected in (
        ("at least 1 1/2 inch", 1.5),
        ("at least 2-3/8 inch", 2.375),
        ("at least 3 / 4 inch", 0.75),
    ):
        assert (
            rf.limit_and_unit(rule(quote=quote))[2]["proposed"][0]["value"] == expected
        )


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
        assert rf.limit_and_unit(dict(ok, value=wrong))[:2] == (
            rf.FAIL,
            "value_not_in_quote",
        )


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


def test_a_denominator_does_not_stand_as_a_number_when_the_quote_has_no_unit_figure():
    r = rule(
        quote="The ratio shall be at least 3/4 of the total.",
        kind="limit",
        value=4.0,
        unit="none",
        comparator=">=",
    )
    assert rf.limit_and_unit(r)[:2] == (rf.FAIL, "value_not_in_quote")
    assert rf.limit_and_unit(dict(r, value=0.75))[0] == rf.PASS


# ------------------------------------------------------------------------------------------------ apply_proposal


def test_apply_proposal_refuses_the_denominator_and_a_value_that_is_not_a_quoted_figure(
    tmp_path,
):
    conn = copy(tmp_path)
    for bad in (4.0, 0.8):
        with pytest.raises(ValueError):
            rr.apply_proposal(
                conn, "v1", {"value": bad, "unit": "inch", "comparator": ">="}, "o"
            )
    rr.apply_proposal(
        conn, "v1", {"value": 0.75, "unit": "inch", "comparator": ">="}, "o"
    )
    assert st.latest_steps(conn, "v1")["a"]["reason"].startswith("proposal_applied")


def test_apply_proposal_resets_the_engineer_check_and_the_owner_sample(tmp_path):
    conn = copy(tmp_path)
    st._append_step(
        conn, "v1", "e", "pass", "ok", {}, checker="c", model="m", run_id="x"
    )
    st._append_step(
        conn, "v1", "f", "pass", "ok", {}, checker="c", model="m", run_id="x"
    )
    rr.apply_proposal(
        conn, "v1", {"value": 0.75, "unit": "inch", "comparator": ">="}, "o"
    )
    latest = st.latest_steps(conn, "v1")
    assert [(latest[s]["result"], latest[s]["reason"]) for s in "ef"] == [
        ("incomplete", "changed_after_check")
    ] * 2
    assert (
        conn.execute("SELECT COUNT(*) FROM rule_finish_step WHERE step='e'").fetchone()[
            0
        ]
        == 2
    )  # history kept


# ------------------------------------------------------------------------------------------------ B: step b, d


def test_step_b_a_quantity_field_with_a_figure_is_a_datasheet_value_by_a_cue_list():
    result, reason, ev = rf.evidence_source(
        rule(quote="The inlet shall be at least 3/4 inch.", field="inlet size")
    )
    assert (result, reason) == (rf.PASS, rf.DATASHEET_VALUE) and "size" in ev["cues"]
    assert (
        rf.evidence_source(rule(quote="Widgets shall be good.", field="widgets"))[0]
        == rf.INCOMPLETE
    )
    assert rf.evidence_source(rule(field="colour"))[0] == rf.INCOMPLETE


def test_step_d_connection_types_and_exceptions_are_testable_and_unknown_wording_is_incomplete():
    r = rule(
        applicability=[
            ("subject", "relief valves"),
            ("condition", "threaded"),
            ("condition", "flanged"),
        ]
    )
    result, _, ev = rf.conditions_of(r)
    assert result == rf.PASS and [t["values"] for t in ev["tests"]] == [
        ["threaded"],
        ["flanged"],
    ]
    ok = rule(
        applicability=[("subject", "relief valves")],
        exceptions=["small compressor valves"],
    )
    assert rf.conditions_of(ok)[0] == rf.PASS
    bad = rule(
        applicability=[("subject", "relief valves")], exceptions=["gizmos on the moon"]
    )
    assert rf.conditions_of(bad)[:2] == (rf.INCOMPLETE, "exception_not_read")


# ------------------------------------------------------------------------------------------------ apply_repair

REPAIR = {
    "comparator": ">=",
    "figures": [
        {"value": 0.75, "unit": "inch", "condition": "threaded"},
        {"value": 1.0, "unit": "inch", "condition": "flanged"},
    ],
    "exceptions": ["small compressor widgets"],
}


def test_a_verified_repair_is_applied_and_resets_e_and_f(tmp_path):
    conn = copy(tmp_path)
    st._append_step(
        conn, "v1", "e", "fail", "not_ok", {}, checker="helper", model="m", run_id="r"
    )
    st._append_step(
        conn, "v1", "f", "pass", "ok", {}, checker="owner", model="m", run_id="r"
    )
    out = rr.apply_repair(conn, "v1", REPAIR, "lead", pages=PAGES)
    assert out["refused"] == []
    latest = st.latest_steps(conn, "v1")
    assert latest["b"]["result"] == "pass"
    assert [(latest[s]["result"], latest[s]["reason"]) for s in "ef"] == [
        ("incomplete", "changed_after_check")
    ] * 2
    after = rec.rule_of(conn, "v1")
    assert (
        len(after["figures"]) == 2
        and ("condition", "threaded") in after["applicability"]
    )
    assert after["exceptions"] == ["small compressor widgets"]
    assert rf.conditions_of(after)[0] == rf.PASS
    assert rf.limit_and_unit(after)[:2] == (
        rf.PASS,
        "figures_stand_in_quote",
    )  # each figure has its own phrase
    assert conn.execute("SELECT COUNT(*) FROM rule_finish_repair").fetchone()[0] == 6


def test_parts_that_code_cannot_verify_are_refused_and_the_rest_still_applies(tmp_path):
    conn = copy(tmp_path)
    repair = {
        "comparator": "<=",
        "figures": [
            {"value": 4.0, "unit": "inch", "condition": "threaded"},
            {"value": 1.0, "unit": "inch", "condition": "connection is flanged"},
            {"value": 0.75, "unit": "inch", "condition": "threaded"},
        ],
        "exceptions": ["purple gizmos", "compressor widgets 99"],
        "field": "inlet nps",
    }
    out = rr.apply_repair(conn, "v1", repair, "lead", pages=PAGES)
    reasons = {(x["part"], x["reason"]) for x in out["refused"]}
    assert ("comparator", "comparator_not_in_quote") in reasons
    assert ("figure 4.0", "value_not_in_quote") in reasons
    assert ("condition of figure 1.0", "not_a_contiguous_run_of_the_page") in reasons
    assert ("exception", "not_a_contiguous_run_of_the_page") in reasons and (
        "field",
        "not_a_contiguous_run_of_the_page",
    ) in reasons
    assert ("exception", "number_not_on_page") in reasons
    assert [x["part"] for x in out["applied"]] == [
        "condition of figure 0.75",
        "figure 0.75",
    ]


def test_repair_text_must_be_a_contiguous_run_of_the_page_in_order_with_its_negation():
    rule_ = rule(page=1)
    ok = lambda text: rr.verify_text(text, rule_, PAGES)  # noqa: E731
    assert ok("small compressor widgets") == (True, "stands_on_page")
    assert ok("compressor widgets are exempt") == (True, "stands_on_page")
    assert ok("widgets compressor") == (
        False,
        "not_a_contiguous_run_of_the_page",
    )  # the words, out of order
    assert ok("small widgets") == (False, "not_a_contiguous_run_of_the_page")  # a gap
    assert ok("widgets shall be painted") == (False, "not_a_contiguous_run_of_the_page")
    assert ok("be painted") == (
        False,
        "negation_differs",
    )  # the standard says "shall not be painted"
    assert ok("widgets shall not be painted") == (True, "stands_on_page")
    assert ok("widgets shall not be painted at 99 mm") == (False, "number_not_on_page")
    assert ok("pump") == (
        True,
        "closed_vocabulary",
    )  # one entry of the closed vocabulary
    assert ok("flanged") == (True, "stands_on_page")
    assert ok("welded") == (True, "closed_vocabulary")
    assert ok("") == (False, "no_words")
    assert rr.verify_text("small", rule_, {}) == (False, "page_text_missing")


def test_a_repair_refuses_an_unmarked_database_an_empty_approver_and_a_missing_rule(
    tmp_path,
):
    from app import rule_finish_guard as guard

    with pytest.raises(guard.NotAWorkCopy):
        rr.apply_repair(
            make_copy(tmp_path / "w0.sqlite", marked=False),
            "v1",
            REPAIR,
            "lead",
            pages=PAGES,
        )
    conn = copy(tmp_path)
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
