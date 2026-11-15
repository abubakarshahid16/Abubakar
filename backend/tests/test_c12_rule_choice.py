"""Rule choice v2 of the AI reviewer (owner order 15 Nov 2026). INVENTED data only; no model, no network.

Each test fails without the change it names: take the setting's branch out of `build_items`, or the ask mode out of
`decide_rule`, and the named assertion breaks."""

# ruff: noqa: F811 - the `con` fixture is imported by name
from __future__ import annotations

import itertools

from app import agent_review_items as it
from app import agent_review_rule_choice as RC
from app import agent_review_rules as R
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app.api import agent_review_schemas as S
from app.config import settings
from tests.test_agent_review_crs import META, rows_of
from tests.test_agent_review_items import (  # noqa: F401 - the fixture is used by name
    KIND,
    PAPER,
    SKILL,
    STD,
    _by_id,
    _eq_label,
    _label,
    con,
)


def _add_rule(
    con,
    rid,
    text,
    *,
    clause="4.1",
    page=2,
    op=None,
    value=None,
    state="needs_human",
    field="frame width",
    dis="invalid_reading",
):
    con.execute(
        "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
        " requirement_type, operator, value) VALUES (?,?,?,?,?,?,?,?,?)",
        (rid, STD, clause, page, text, text, "statement", op, value),
    )
    con.execute(
        "INSERT INTO review_scope_decisions VALUES ('run-new', ?, 'applies_not_checked', 'x')",
        (rid,),
    )
    over = {"disagreement": dis} if state == "needs_human" else {}
    if field is not None:
        over["field"] = field
    _label(con, rid, state=state, **over)


def _plan(con, **kw):
    return it.build_items(con, PAPER, KIND, skills=[SKILL], cache={}, **kw)


# ---------------------------------------------------------------- the setting is off by default and off changes nothing


def test_the_setting_is_off_and_the_budgets_are_the_ordered_ones():
    assert settings.agent_review_rule_choice_v2_enabled is False
    assert (
        settings.agent_review_budget_claude,
        settings.agent_review_budget_local,
    ) == (150, 40)
    assert RC.budget_for(False) == 150 and RC.budget_for(True) == 40


def test_off_the_plan_has_no_group_point_no_new_reason_and_no_new_key(con):
    doc = _plan(con)
    assert "group_points" not in doc and "rule_choice" not in doc["rule_labels"]
    counts = doc["rule_labels"]["counts"]
    assert not set(counts) & set(R.V2_REASONS)


# ---------------------------------------------------------------- 1. ask mode: kind AND field agreed


def test_a_needs_a_human_rule_with_kind_and_field_agreed_is_asked_marked_in_plain_words(
    con,
):
    _add_rule(
        con, "r-agreed", "frame width shall be at least 41 mm", field="frame width"
    )
    _add_rule(con, "r-nofield", "colour shall be stated", field=None)
    on = _plan(con, ask_unapproved="agreed_field")
    got = _by_id(on)
    assert "R-r-agreed" in got and "R-r-nofield" not in got
    why = got["R-r-agreed"]["rule_unapproved_why"]
    assert (
        why.startswith("rule not yet approved by an engineer")
        and "invalid_reading" not in why
    )
    assert got["R-r-agreed"][
        "rule_tier"
    ] == V.RULE_NOT_APPROVED and not V.calls_allowed(got["R-r-agreed"])
    # the older mode still asks the rule with no field; off asks neither
    both = _by_id(_plan(con, ask_unapproved="both"))
    assert "R-r-nofield" in both and "R-r-agreed" in both
    off = _by_id(_plan(con))
    assert "R-r-agreed" not in off and "R-r-nofield" not in off


def test_kind_disagreement_is_never_asked_in_the_new_mode(con):
    _add_rule(con, "r-kind", "frame width shall be at least 41 mm", dis="kind")
    con.execute("UPDATE rule_label SET paper_kind = NULL WHERE rule_ref = 'r-kind'")
    assert "R-r-kind" not in _by_id(_plan(con, ask_unapproved="agreed_field"))


# ---------------------------------------------------------------- 1. the class ceiling, brute force over the line table


def test_the_line_table_allows_the_unapproved_tier_only_on_four_classes_none_a_decision():
    with_tier = {
        c for c, (_w, tiers) in S.LINE_TABLE.items() if "Not AI approved" in tiers
    }
    assert with_tier == {
        "AI opinion, rule not yet approved",
        "Query for the engineer",
        "Not applicable",
        "Not reviewed",
    }
    for cls in with_tier:
        assert not set(S.LINE_TABLE[cls][0]) & {
            "Pass",
            "Fail",
            "AI verdict: met",
            "AI verdict: not met",
            "AI verdict: not stated",
        }


VERDICTS = (V.PASS, V.FAIL, V.QUERY, None)
CODES = (
    None,
    "met",
    "not_met",
    "absent",
    "not_applicable",
    "needs_drawing_or_calc",
    "sheet_silent",
)


def test_a_rule_not_yet_approved_can_never_be_a_decision_whatever_the_stored_line_says():
    """Brute force: every combination of stored verdict, AI verdict, reason code, guards and two-reader marks."""
    seen = set()
    for verdict, ai, code, hold, second in itertools.product(
        VERDICTS,
        VERDICTS,
        CODES,
        (False, True),
        (None, {"agree": True}, {"agree": False}),
    ):
        line = {
            "item_id": "R-x", "source": "rule", "verdict": verdict, "ai_verdict": ai, "reason_code": code,
            "rule_tier": V.RULE_NOT_APPROVED, "tier": "Not AI approved", "checklist": False,
            "conditional_hold": hold, "second_opinion": second,
            "quotes_checked": {"paper": True, "clause": True, "both": True, "clause_strong": True},
            "pages_searched": [1], "rule_kind": None,
        }  # fmt: skip
        out = W.classify(line)
        seen.add(out["verdict_class"])
        assert out["verdict_class"] not in {W.CLASS_PROVEN, W.CLASS_TWO_READERS}, (
            verdict,
            ai,
            code,
            hold,
            second,
        )
        assert out["verdict_label"] not in (V.PASS, V.FAIL)
    assert seen <= {
        W.CLASS_UNAPPROVED,
        W.CLASS_QUERY,
        W.CLASS_NOT_APPLICABLE,
        W.CLASS_NOT_REVIEWED,
    }


def test_the_second_reader_never_looks_at_a_rule_not_yet_approved():
    from app import agent_review_two_reader as T

    line = {"item_id": "R-x", "verdict": V.QUERY, "ai_verdict": V.PASS, "reason_code": "met", "rule_tier": V.RULE_NOT_APPROVED,
            "tier": "Not AI approved", "checklist": False, "pass_guard": {"ok": True},
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}}  # fmt: skip
    assert (
        T.is_candidate(
            {**line, "rule_tier": None, "tier": "AI approved", "unapproved_cap": False}
        )
        is not None
    )
    assert not T.is_candidate(line)
    assert not T.is_other_candidate({**line, "reason_code": "needs_drawing_or_calc"})
    assert not T.is_absence_candidate(
        {**line, "ai_verdict": V.FAIL, "reason_code": "absent", "pages_searched": [1]}
    )


def test_the_grouped_point_is_a_query_on_the_internal_copy_only(tmp_path):
    from app import agent_review_crs as C

    point = {"rule_book": "Book A", "count": 7, "book_id": "d1"}
    line = W.apply(RC.group_line(point))
    assert line["verdict_class"] == W.CLASS_QUERY
    assert (
        "7 rules of Book A could not be matched to a field of this paper: an engineer checks them"
        in line["why"]
    )
    assert not rows_of(
        C.write_contractor([line], tmp_path / "c.xlsx", META)
    )  # a contractor copy never holds it
    internal = rows_of(C.write_internal([line], tmp_path / "i.xlsx", META))
    cell = next(
        str(r["COMPANY Comments"])
        for r in internal
        if "could not be matched" in str(r["COMPANY Comments"])
    )
    assert cell.startswith(line["why"]) and "Contractor to" not in cell


# ---------------------------------------------------------------- 3. rank and budget


def test_the_score_is_the_ordered_one():
    row = {
        "standard_document_id": "gov",
        "requirement_text": "It shall be 5 bar",
        "operator": "<=",
        "value": 5.0,
    }
    full = RC.score(
        row,
        {"field": "design_pressure", "tier": "AI approved"},
        {"gov"},
        {"design_pressure"},
    )
    assert full == 3 + 2 + 1 + 1 + 1
    assert (
        RC.score(
            {"standard_document_id": "x", "requirement_text": "it may"},
            {"tier": "Not AI approved"},
            set(),
            set(),
        )
        == -2
    )
    assert (
        RC.score(
            row, {"field": "other", "tier": "AI approved"}, {"gov"}, {"design_pressure"}
        )
        == 3 + 1 + 1 + 1
    )


def test_over_the_budget_the_lowest_ranked_are_left_out_listed_and_said(con):
    for i in range(5):
        _add_rule(
            con,
            f"r-n{i}",
            f"frame width {i} shall be at least 4{i} mm",
            clause=f"4.{i + 3}",
            op=">=",
            value=40.0 + i,
        )
    doc = _plan(con, ask_unapproved="agreed_field", rule_budget=3)
    rules = [i for i in doc["items"] if i["source"] == "rule"]
    block = doc["rule_labels"]
    assert len(rules) == 3
    below = [r for r in block["left_out"] if r["reason"] == RC.BELOW_LIMIT]
    assert (
        len(below) == block["rule_choice"]["below"]
        and block["counts"][RC.BELOW_LIMIT] == len(below) > 0
    )
    sentence = f"{len(below)} more rules apply but were not asked: the limit for one review is 3; they are listed under Rules used"
    assert sentence in block["summary_lines"]
    assert block["rule_choice"]["asked"] == 3 and block["rule_choice"]["limit"] == 3
    # nothing disappears: every rule is asked or listed with one reason
    assert (
        len(
            {r["rule_version_id"] for r in block["left_out"]}
            & {i["rule_version_id"] for i in rules}
        )
        == 0
    )


def test_a_budget_larger_than_the_rules_cuts_nothing(con):
    doc = _plan(con, rule_budget=150)
    assert (
        "below" in doc["rule_labels"]["rule_choice"]
        and doc["rule_labels"]["rule_choice"]["below"] == 0
    )
    assert not [
        r for r in doc["rule_labels"]["left_out"] if r["reason"] == RC.BELOW_LIMIT
    ]


# ---------------------------------------------------------------- 4. the grouped points


def test_needs_a_human_rules_that_are_not_asked_make_one_group_point_per_book_with_its_count(
    con,
):
    for i in range(3):
        _add_rule(
            con,
            f"r-g{i}",
            f"frame width {i} shall be at least 4{i} mm",
            clause=f"4.{i + 3}",
            field=None,
        )
    doc = _plan(con, ask_unapproved="agreed_field", rule_budget=150)
    groups = doc["group_points"]
    assert groups == [{"rule_book": "INV-STD-100", "count": 3, "book_id": STD}]
    assert doc["rule_labels"]["rule_choice"]["group_points"] == groups


# ---------------------------------------------------------------- 2. the partial-standard gate


def _gate_world(con):
    from app import rule_equipment as REQ

    REQ.create_tables(con)
    con.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT)"
    )
    con.execute(
        "INSERT INTO document_classification VALUES (?, 'Pressure Safety Valve', NULL)",
        (PAPER,),
    )
    return R.load_equipment(con, PAPER, "type")


ASME = "ASME-Sec-VIII-Div1-2023.pdf"
LABELS = {"d-asme": ASME, "d-other": "SAES-X-1.pdf"}


def _row(rid, text, doc="d-asme"):
    return {
        "id": rid,
        "standard_document_id": doc,
        "requirement_text": text,
        "standard": LABELS[doc],
    }


def test_the_partial_gate_leaves_out_the_rules_outside_the_governed_part_with_its_reason(
    con,
):
    ctx = _gate_world(con)
    rows = [_row("a", "A pressure relief valve shall be marked"), _row("b", "Weld seams shall be examined"),
            _row("c", "A material shall be carbon steel"), _row("d", "Weld seams shall be examined", "d-other")]  # fmt: skip
    _label(con, "c", state="ai_approved", field="body_material")
    _eq_label(
        con, "c", "agreed", general=1
    )  # a datasheet field AND an agreed general equipment label: kept
    kept, left = RC.partial_gate_rows(con, rows, {"relief valve"}, LABELS, ctx)
    assert {r["id"] for r in kept} == {"a", "c", "d"} and [
        r["rule_version_id"] for r in left
    ] == ["b"]
    assert (
        left[0]["reason"] == RC.PART_OUTSIDE
        and R.REASON_WORDS[RC.PART_OUTSIDE]
        == "this part of the book does not govern this equipment"
    )
    kept2, left2 = RC.partial_gate_rows(
        con, rows, {"pump"}, LABELS, ctx
    )  # a book the equipment governs whole is untouched
    assert len(kept2) == 4 and left2 == []


def test_the_datasheet_field_exception_never_keeps_a_rule_of_another_equipment_or_of_unknown_equipment(
    con,
):
    ctx = _gate_world(con)
    rows = [
        _row(k, "A material shall be carbon steel")
        for k in ("same", "gen", "vessel", "family", "none", "unsure", "offlist")
    ]
    for k in rows:
        _label(
            con,
            k["id"],
            state="ai_approved",
            field="zzz_not_on_the_list" if k["id"] == "offlist" else "body_material",
        )
    _eq_label(con, "same", "agreed", typ="relief_valve", fam="pressure_relief")
    _eq_label(con, "gen", "agreed", general=1)
    _eq_label(con, "vessel", "agreed", typ="pressure_vessel", fam="static")
    _eq_label(con, "family", "agreed", fam="heat_transfer")
    _eq_label(con, "unsure", "needs_human")
    _eq_label(con, "offlist", "agreed", general=1)
    kept, left = RC.partial_gate_rows(con, rows, {"relief valve"}, LABELS, ctx)
    assert {r["id"] for r in kept} == {
        "same",
        "gen",
    }  # not: another type, another family, no label, unsure, a field off the list
    assert {r["rule_version_id"] for r in left} == {
        "vessel",
        "family",
        "none",
        "unsure",
        "offlist",
    }
    assert (
        RC.partial_gate_rows(con, rows, {"relief valve"}, LABELS, None)[0] == []
    )  # no equipment context: nothing is rescued


def test_the_gate_matches_a_word_and_its_plain_plural_in_any_book():
    from app import subject_scope

    table = {"relief valve": [{"standard": "ASME BPVC Section VIII Division 1", "applies_to": "x",
                               "words": ["pressure relief device", "relief valve", "set pressure"]}]}  # fmt: skip

    def kept(text):
        got = subject_scope.partial_gate([{"id": "x", "standard_document_id": "d", "requirement_text": text}], equipment={"relief valve"},
                                         standard_labels={"d": ASME}, partial_standards=table)  # fmt: skip
        return bool(got["kept"])

    for text in ("Pressure relief devices shall be marked", "Pressure relief device shall be marked", "Relief valves shall open",
                 "The set pressures shall be stated", "Overpressure of the relief valve"):  # fmt: skip
        assert kept(text), text
    for text in (
        "Relief valvex shall open",
        "A pressure relief devicing step",
        "Weld seams shall be examined",
    ):
        assert not kept(text), text


def test_the_gate_is_called_by_the_plan_when_the_setting_is_on(con):
    """The wiring: a book the equipment governs only in part loses its rules outside the part in `build_items` (and only then)."""
    _gate_world(con)
    con.execute("UPDATE documents SET filename = ? WHERE id = ?", (ASME, STD))
    off = _plan(con, equipment_filter="type")
    on = _plan(con, equipment_filter="type", rule_budget=150)
    rules = lambda d: [i for i in d["items"] if i["source"] == "rule"]  # noqa: E731
    assert rules(off) and not rules(on)
    left = on["rule_labels"]["left_out"]
    assert left and {
        r["reason"]
        for r in left
        if r["rule_version_id"] in {i["rule_version_id"] for i in rules(off)}
    } == {RC.PART_OUTSIDE}
    assert (
        on["rule_labels"]["counts"][RC.PART_OUTSIDE]
        == len([r for r in left if r["reason"] == RC.PART_OUTSIDE])
        > 0
    )


def test_an_approved_rule_is_never_cut_in_favour_of_a_rule_not_yet_approved():
    gov = {"d-gov"}
    approved_low = [
        {
            "id": f"ok{i}",
            "standard_document_id": "d-cited",
            "page": i,
            "requirement_text": "it is",
        }
        for i in range(3)
    ]
    opinion_high = [
        {
            "id": f"op{i}",
            "standard_document_id": "d-gov",
            "page": i,
            "requirement_text": "it shall",
            "operator": "<=",
            "value": 1.0,
        }
        for i in range(3)
    ]
    why = {r["id"]: {"tier": "AI approved"} for r in approved_low} | {r["id"]: {"tier": "Not AI approved", "field": "design_pressure"} for r in opinion_high}  # fmt: skip
    assert RC.score(opinion_high[0], why["op0"], gov, {"design_pressure"}) > RC.score(
        approved_low[0], why["ok0"], gov, set()
    )
    top, cut, facts = RC.rank_and_cut(
        approved_low + opinion_high, why, "id", 3, gov, {"design_pressure"}
    )
    assert {r["id"] for r in top} == {"ok0", "ok1", "ok2"} and facts[
        "below"
    ] == 3  # a limit smaller than the approved set
    top, _c, _f = RC.rank_and_cut(
        approved_low + opinion_high, why, "id", 4, gov, {"design_pressure"}
    )
    assert {r["id"] for r in top} == {
        "ok0",
        "ok1",
        "ok2",
        "op0",
    }  # then the opinions, by their score


def test_a_grouped_point_is_not_counted_as_a_rule_line():
    from app import agent_review_crs as C

    rule = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": V.PASS,
        "quotes_checked": {"paper": True, "clause": True},
        "decided_by": "code",
    }
    group = W.apply(RC.group_line({"rule_book": "B", "count": 7, "book_id": "d"}))
    got = C.run_counts(
        [W.apply({**rule, "verdict_class": None}) if False else rule, group]
    )
    assert (
        got["lines_with_a_verdict"] == "1 of 1"
        and got["both_quotes_checked"] == "1 of 1"
    )
    assert got["grouped_points"] == 1 and got["grouped_rules"] == 7
    assert "grouped_points" not in C.run_counts(
        [rule]
    )  # off: the counts are as they were


def test_the_gate_reason_is_counted_and_said(con):
    counts = R.count_left_out([{"reason": RC.PART_OUTSIDE, "rule_book": "B"}] * 4)
    assert counts[RC.PART_OUTSIDE] == 4
    lines = R.summary_lines(counts, "datasheet")
    assert any(
        x.startswith(
            "4 rules of a book that governs this equipment only in part were not asked"
        )
        for x in lines
    )


# ---------------------------------------------------------------- 5. the three proof cases, shaped like the valve's rows 6, 52, 53


def test_rules_shaped_like_valve_rows_6_52_and_53_are_asked_with_the_setting_on(con):
    # row 6: the two readers' numbers did not check (invalid_reading); row 52: a number in the quote unread; row 53: invalid again
    _add_rule(
        con,
        "r-row6",
        "built-up back pressure shall not exceed 10 % of set pressure",
        dis="invalid_reading",
        field="built_up_back_pressure",
        clause="5.3",
    )
    _add_rule(
        con,
        "r-row52",
        "springs for sour service shall be protected",
        dis="numbers_unread",
        field="spring_material",
        clause="6.2",
    )
    _add_rule(
        con,
        "r-row53",
        "bellows for sour service shall be made of listed alloys",
        dis="invalid_reading",
        field="bellows_material",
        clause="6.3",
    )
    off = _by_id(_plan(con))
    on = _by_id(_plan(con, ask_unapproved="agreed_field", rule_budget=150))
    for rid in ("R-r-row6", "R-r-row52", "R-r-row53"):
        assert rid not in off and rid in on
        assert on[rid]["rule_unapproved_why"].startswith(
            "rule not yet approved by an engineer"
        )


def test_among_equal_scores_the_book_that_governs_the_equipment_comes_before_a_book_only_cited():
    rows = [
        {"id": "a", "standard_document_id": "d-cited", "page": 1, "requirement_text": "x shall", "standard": "ASME-Sec-VIII-Div1-2023.pdf"},
        {"id": "b", "standard_document_id": "d-gov", "page": 9, "requirement_text": "x shall", "standard": "SAES-J-600.pdf"},
    ]  # fmt: skip
    why = {"a": {"tier": "AI approved"}, "b": {"tier": "AI approved"}}
    top, cut, facts = RC.rank_and_cut(
        rows, why, "id", 1, {"d-cited", "d-gov"}, set(), {"d-gov"}
    )
    assert (
        [r["id"] for r in top] == ["b"]
        and [r["rule_version_id"] for r in cut] == ["a"]
        and facts["below"] == 1
    )
    top, _c, _f = RC.rank_and_cut(rows, why, "id", 1, {"d-cited", "d-gov"}, set())
    assert [r["id"] for r in top] == ["a"]  # no governing list: book order


def test_the_books_governing_this_equipment_are_found_by_the_one_identifier_matcher():
    got = RC.equipment_governing_ids(
        {"relief valve"},
        {
            "d1": "API-520-I.pdf",
            "d2": "SAES-J-600.pdf",
            "d3": "ASME-Sec-VIII-Div1-2023.pdf",
        },
    )
    assert got == {"d1", "d2"}
    assert (
        RC.equipment_governing_ids({"no such equipment"}, {"d1": "API-520-I.pdf"})
        == set()
    )
