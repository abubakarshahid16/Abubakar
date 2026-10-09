"""#678: "not compared" split into three honest groups: checked / applies but not
checked / does not apply, each with its reason; repeats counted once; the
approval rule uses only the middle group. Synthetic data only.

Mutations: M4418-M4437 (scripts/mutations/w3_678_three_way_split.py).
"""
from __future__ import annotations

import pytest

from app import absence, comparison, db, requirement_split as rs, submittal_review, subject_scope, table_gate
from app.config import settings
from tests.test_w2b_598_review_table_filter import GRADES, _setup as table_setup
from tests.test_w3_453_applicability_by_subject import GENERAL, TURBINE, _review


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t678.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def req(text, std="s1", rid=None):
    return {"id": rid or text, "standard_document_id": std, "requirement_text": text}


_n = iter(range(10**6))


def item(text, code=None, detail=None, std="s1"):
    """Every stored row has its own id, as in the database: repeats are found by
    standard + text, never by id."""
    return {"requirement": req(text, std, rid=f"row-{next(_n)}"), "code": code, "detail": detail}


# --------------------------------------------------------------- pure split

def test_a_run_with_known_counts_shows_the_right_three_numbers():
    split = rs.build(
        [req(f"checked {i}") for i in range(3)],
        [item(f"cell {i}", "column_not_on_sheet") for i in range(4)],
        [item(f"other {i}", "other_equipment", "about a turbine, this submittal is a pump") for i in range(2)])
    assert (split["checked"], split["applies_not_checked"], split["does_not_apply"]) == (3, 4, 2)
    assert split["total"] == 9
    assert split["unchecked_share"] == pytest.approx(4 / 7)       # of the 7 that APPLY, not of 9


def test_requirements_that_do_not_apply_never_enter_the_share():
    split = rs.build([req("a")], [item("b", "no_label")], [item(f"x{i}", "other_equipment") for i in range(500)])
    assert split["unchecked_share"] == pytest.approx(0.5)
    none_apply = rs.build([], [], [item("x", "other_equipment")])
    assert none_apply["unchecked_share"] is None                    # never 0%


def test_each_group_names_its_reasons_most_common_first():
    split = rs.build([], [item("a", "no_label"), item("b", "column_not_on_sheet"), item("c", "column_not_on_sheet")],
                     [item("d", "other_equipment", "about a turbine, this submittal is a pump")])
    assert split["applies_not_checked_reasons"][0] == {
        "reason": rs.REASON_TEXT["column_not_on_sheet"], "count": 2}
    assert split["does_not_apply_reasons"] == [{"reason": "about a turbine, this submittal is a pump", "count": 1}]


def test_a_requirement_with_no_stored_reason_says_no_reason_recorded_never_a_guess():
    split = rs.build([], [item("a", None), item("b", "a_code_nobody_defined")], [item("c", None)])
    assert split["applies_not_checked_reasons"] == [{"reason": "no reason recorded", "count": 2}]
    assert split["does_not_apply_reasons"] == [{"reason": "no reason recorded", "count": 1}]


def test_a_repeated_requirement_counts_once_and_the_repeats_are_reported():
    rows = [item("The same table value", "no_label") for _ in range(5)]
    split = rs.build([req("The   SAME table value", std="s2", rid="row-x")], rows + [item("THE SAME TABLE VALUE.", "no_label")], [])
    # 6 stored rows of one requirement in standard s1, plus one checked row in s2
    assert split["applies_not_checked"] == 1 and split["checked"] == 1
    assert split["repeats_ignored"] == 5


def test_the_same_text_in_two_standards_is_two_requirements():
    split = rs.build([], [item("shall be 9", "no_label", std="a"), item("shall be 9", "no_label", std="b")], [])
    assert split["applies_not_checked"] == 2


def test_a_requirement_in_two_groups_counts_in_the_strongest_one():
    split = rs.build([req("x")], [item("x", "no_label")], [item("x", "other_equipment")])
    assert (split["checked"], split["applies_not_checked"], split["does_not_apply"]) == (1, 0, 0)
    weaker = rs.build([], [item("y", "no_label")], [item("y", "other_equipment")])
    assert (weaker["applies_not_checked"], weaker["does_not_apply"]) == (1, 0)


def test_two_unreadable_rows_with_no_text_never_merge():
    split = rs.build([], [{"requirement": {"id": "1", "standard_document_id": "s"}, "code": "text_quality"},
                          {"requirement": {"id": "2", "standard_document_id": "s"}, "code": "text_quality"}], [])
    assert split["applies_not_checked"] == 2


def test_a_run_stored_before_the_split_has_only_counts_and_says_so():
    split = rs.from_counts({"checked": 40, "not_compared": 30, "not_applied": 10})
    assert split["applies_not_checked_reasons"] == [{"reason": "no reason recorded", "count": 30}]
    assert split["repeats_ignored"] is None
    assert rs.from_counts(None) is None and rs.from_counts({}) is None


# -------------------------------------------------- the gates keep a reason

def _cell(row, column, rid):
    return {"id": rid, "standard_document_id": "s1", "chunk_id": "c1", "page": 1,
            "requirement_type": "table_value", "condition": row, "field": column,
            "requirement_text": f"{row} - {column}", "structured": {}}


def test_a_skipped_table_cell_keeps_a_reason_code():
    facts = [{"field_label": "Material", "raw_value": "UNS S31600"}]
    cells = [_cell("UNS S31600", "Max hardness (HRC)", "match"),
             _cell("UNS S32205", "Max hardness (HRC)", "other"),            # another row of this table matched
             ]
    out = table_gate.gate(cells, facts)
    assert [i["code"] for i in out["not_compared_items"]] == ["other_row_matched"]
    assert out["not_compared"][0]["reasons"] == {"other_row_matched": 1}

    lonely = [_cell("UNS S32205", "Max yield", "a"),                         # row and column unknown
              {**_cell("", "Max yield", "b"), "chunk_id": "c2"},              # column words only
              {**_cell("", "", "c"), "chunk_id": "c3", "field": ""}]          # no label at all
    codes = {i["requirement"]["id"]: i["code"] for i in table_gate.gate(lonely, facts)["not_compared_items"]}
    assert codes == {"a": "row_label_not_on_sheet", "b": "column_not_on_sheet", "c": "no_label"}


def test_the_scope_gate_keeps_why_a_requirement_does_not_apply():
    sample = {"id": "r1", "standard_document_id": "s1", "clause": "8.7",
              "requirement_text": TURBINE, "structured": {"field": "x"}}
    out = subject_scope.gate([sample], classification={"equipment_type": "Pressure Safety Valve"}, facts=[])
    [only] = out["not_applied_items"]
    assert only["requirement"]["id"] == "r1" and only["code"] == "other_equipment"
    assert "this submittal is" in only["detail"] and "turbine" in only["detail"]


# ------------------------------------------------------ the approval rule

CODES = (comparison.CODE_APPROVED, comparison.CODE_APPROVED_WITH_COMMENTS,
         comparison.CODE_REJECTED, comparison.CODE_MANUAL)
SUFFICIENT = {"sufficient": True, "fields_read": 100, "fields_estimated": 100, "extraction_coverage": 1.0}
MET = [{"compliance_status": comparison.COMPLIANT}] * 3


def test_the_approval_rule_uses_only_applies_but_not_checked():
    # 5000 do not apply: a control that must NOT block an approval.
    ok = comparison.recommend_code(MET, SUFFICIENT,
                                   unchecked_counts={"not_compared": 1, "not_applied": 5000, "checked": 3})
    assert ok["code"] == comparison.CODE_APPROVED
    # 3 of the 6 that apply are not checked: blocked, and the reason says so.
    blocked = comparison.recommend_code(MET, SUFFICIENT,
                                        unchecked_counts={"not_compared": 3, "not_applied": 0, "checked": 3})
    assert blocked["code"] == comparison.CODE_MANUAL
    assert "3 of 6 requirements that apply" in blocked["reason"]


def test_the_notice_gives_three_counts_and_the_top_reasons_but_only_unchecked_makes_it_incomplete():
    split = rs.build([req("a")], [item("b", "column_not_on_sheet")], [item("c", "other_equipment", "about X, this is Y")])
    outcome = {"unchecked_counts": {"checked": 1, "not_compared": 1, "not_applied": 1}, "requirement_split": split}
    parts = absence.unchecked_parts(run_status="completed", outcome=outcome)
    notice = absence.notice_for(parts)
    assert "Of 3 requirements in scope: 1 checked, 1 apply but were not checked, 1 do not apply." in notice
    assert notice.startswith("REVIEW INCOMPLETE: 1 part(s)")       # the reason lines are detail, not parts
    lines = [p["line"] for p in parts if p["part"] == "requirement_reasons"]
    assert any("Apply but not checked (1): " + rs.REASON_TEXT["column_not_on_sheet"] in l for l in lines)
    assert any("Do not apply (1): about X, this is Y" in l for l in lines)
    # Only requirements that do not apply: nothing is unchecked, the sheet is not incomplete.
    clean = absence.unchecked_parts(run_status="completed", outcome={
        "unchecked_counts": {"checked": 9, "not_compared": 0, "not_applied": 40}})
    assert clean == []


def test_the_reasons_on_the_sheet_are_the_top_three_and_say_how_many_more():
    reasons = [{"reason": f"reason {i}", "count": 10 - i} for i in range(5)]
    lines = absence.split_lines({"applies_not_checked": 40, "applies_not_checked_reasons": reasons,
                                 "does_not_apply": 0, "does_not_apply_reasons": []})
    assert lines == ["Apply but not checked (40): reason 0 (10); reason 1 (9); reason 2 (8); "
                     "and 2 more reason(s)."]


# ---------------------------------------------------------------- real runs

def test_a_real_run_counts_unreadable_text_as_applies_but_not_checked(monkeypatch):
    import json
    from app import standards
    monkeypatch.setattr(standards, "is_reviewable", lambda r: r["clause"] != "4.2")
    _review([("g", GENERAL, "4.1"), ("h", "The relief valve shall be stamped.", "4.2")])
    split = json.loads(db.connect().execute("SELECT refusal_reason FROM review_runs").fetchone()[0])[
        "requirement_split"]
    assert (split["checked"], split["applies_not_checked"]) == (1, 1)
    assert split["applies_not_checked_reasons"] == [{"reason": rs.REASON_TEXT["text_quality"], "count": 1}]

def test_a_real_run_stores_the_three_groups_with_their_reasons():
    ids, cited, result = table_setup([("Material", "UNS S31600")], {"std-a": [
        (row, "Max hardness (HRC)", v) for row, v in GRADES]})
    split = db.connect().execute("SELECT refusal_reason FROM review_runs").fetchone()
    import json
    stored = json.loads(split["refusal_reason"])["requirement_split"]
    assert stored["checked"] == 1 and stored["applies_not_checked"] == 2 and stored["does_not_apply"] == 0
    assert stored["applies_not_checked_reasons"] == [
        {"reason": rs.REASON_TEXT["other_row_matched"], "count": 2}]
    assert stored["total"] == 3
    assert result["table_values_not_compared"][0]["reasons"] == {"other_row_matched": 2}


def test_a_real_run_puts_other_equipment_in_does_not_apply_and_keeps_it_out_of_the_share():
    ids, cited, result = _review([("t", TURBINE, "8.7"), ("g", GENERAL, "4.1")])
    import json
    stored = json.loads(db.connect().execute("SELECT refusal_reason FROM review_runs").fetchone()[0])
    split = stored["requirement_split"]
    assert (split["checked"], split["applies_not_checked"], split["does_not_apply"]) == (1, 0, 1)
    assert "turbine" in split["does_not_apply_reasons"][0]["reason"]
    assert stored["unchecked_counts"] == {"not_compared": 0, "not_applied": 1, "checked": 1}
    assert split["unchecked_share"] == 0.0


def test_a_real_run_counts_stored_repeats_once():
    ids, cited, result = _review([("a", GENERAL, "4.1"), ("b", GENERAL, "4.2"), ("c", GENERAL, "4.3")])
    import json
    split = json.loads(db.connect().execute("SELECT refusal_reason FROM review_runs").fetchone()[0])["requirement_split"]
    assert split["checked"] == 1 and split["repeats_ignored"] == 2


def _summary_of_the_only_run():
    from app import access, main as main_mod
    run = dict(db.connect().execute("SELECT * FROM review_runs").fetchone())
    return main_mod._run_summary(run, access.unrestricted_scope())


def test_the_run_api_returns_the_split():
    _review([("t", TURBINE, "8.7"), ("g", GENERAL, "4.1")])
    got = _summary_of_the_only_run()["requirement_split"]
    assert (got["checked"], got["applies_not_checked"], got["does_not_apply"]) == (1, 0, 1)


def test_an_old_run_with_only_counts_gets_them_with_no_reason_recorded():
    import json
    _review([("g", GENERAL, "4.1")])
    with db.connect() as conn:
        raw = json.loads(conn.execute("SELECT refusal_reason FROM review_runs").fetchone()[0])
        raw.pop("requirement_split")
        raw["unchecked_counts"] = {"checked": 4, "not_compared": 6, "not_applied": 2}
        conn.execute("UPDATE review_runs SET refusal_reason = ?", (json.dumps(raw),))
    got = _summary_of_the_only_run()["requirement_split"]
    assert got["applies_not_checked"] == 6
    assert got["applies_not_checked_reasons"] == [{"reason": "no reason recorded", "count": 6}]
