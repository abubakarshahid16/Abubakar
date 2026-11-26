"""Review round of update 9 (lead 4, 26 Nov 2026): the formula checks never decide from a guess, never stop a review, never overwrite
another field's comment, and say when they did not run. Pure: invented rows and figures, no model, no database."""

from __future__ import annotations

import pytest

from app.aim_review import faults
from app.aim_review import formulas as F
from app.aim_review_sheet import team_note

from .test_g_formula_join import ai, firm


def _fields(*rows: str):
    return F.read_fields({1: "\n".join(rows)}).get(1, {})


def _check(check_id: str):
    return next(c for c in F.checks() if c.id == check_id)


# ---- B1: a cell with two values is never decided
def test_two_values_in_one_cell_make_no_line_not_even_a_wrong_pass_or_fail():
    f = _fields("Design temperature   -20 / 200 C", "Operating temperature   150 C")
    assert F._operands(_check("design_temperature"), f) is None
    g = _fields("Design pressure   6 barg", "Operating pressure   5 / 7 barg")
    assert F._operands(_check("design_pressure"), g) is None


def test_one_value_per_row_and_a_combined_row_are_still_read():
    ok = _fields("Design temperature   -20 to 200 C", "Operating temperature   150 C")
    ops = F._operands(_check("design_temperature"), ok)
    assert ops is not None and ops[1].high == 200 and ops[3].high == 150
    combined = _fields("Design / Operating pressure   9 / 7 barg")
    ops = F._operands(_check("design_pressure"), combined)
    assert ops is not None and (ops[1].high, ops[3].high) == (9, 7)


# ---- B2: a dash never raises; any fault in the stage is a step that did not run, and the review goes on
def test_a_dash_in_a_value_cell_does_not_raise():
    f = _fields("Design pressure   - / 10 barg", "Operating pressure   4 barg")
    assert F._operands(_check("design_pressure"), f) is None
    h = _fields("Design / Operating pressure   - / 10 barg")
    assert F._operands(_check("design_pressure"), h) is None


class _State:
    def __init__(self):
        self.decided = [ai(1)]
        self.books = {"b1"}
        self.reference_ids = set()


def test_a_fault_in_the_formula_stage_is_recorded_and_the_run_goes_on(monkeypatch):
    def boom(*a, **k):
        raise AttributeError("none has no unit")

    monkeypatch.setattr(F, "lines", boom)
    state, calls = _State(), []
    with faults.recording(calls):
        F.add_lines(None, None, state)  # does not raise
    assert len(state.decided) == 1  # the run's lines are as they were
    assert [c.step for c in calls] == ["aim_formula_checks"] and calls[0].ok is False
    assert " not applied" in calls[0].code and "AttributeError" in calls[0].code


def test_an_unreadable_row_is_counted_once_and_the_other_rows_still_check(monkeypatch):
    monkeypatch.setattr(F, "_carried", lambda conn, ids: {"b": ("X-STD", {1: "x"})})
    monkeypatch.setattr(
        F, "find_clause", lambda books, probe: F.Hit("b", "X-STD", 1, None)
    )
    monkeypatch.setattr(
        F, "_operands", lambda check, fields: (_ for _ in ()).throw(TypeError("x"))
    )

    from types import SimpleNamespace

    paper = SimpleNamespace(pages={1: "Design pressure   9 barg"})
    calls = []
    with faults.recording(calls):
        assert F.lines(None, paper, ["b"]) == []
    assert len(calls) == 1 and "row(s) of the paper could not be read" in calls[0].code


# ---- M1: the upgrade needs the same FIELD
def test_a_comment_about_another_field_with_the_same_two_figures_is_not_overwritten():
    other = ai(1, field="Material of the bolting", quote="Bolting  ASTM A193")
    decided = [other]
    appended = F.join_into(decided, [firm()])
    assert len(appended) == 1 and decided[0]["label"] == "AI opinion"
    assert decided[0]["comment"] == "The AI's words."  # untouched


def test_the_label_may_stand_in_the_quote_instead_of_the_field():
    target = ai(1, field="Pressure relief", quote="Set pressure  200 psig")
    decided = [target]
    assert F.join_into(decided, [firm()]) == [] and decided[0]["label"] == "Not met"


def test_a_combined_row_serves_both_of_its_labels():
    line = firm()
    line["read_keys"] = ["design_operating_pressure", "mawp"]
    target = ai(
        1, field="Operating pressure limit", quote="Operating pressure  200 psig"
    )
    assert F.join_into([target], [line]) == []


# ---- M2: the replaced words are kept, with a mark, in the team file
def test_the_replaced_ai_words_are_kept_in_the_note_and_the_team_file():
    decided = [
        ai(1, comment='The AI says "the set pressure may exceed the limit"; check it.')
    ]
    F.join_into(decided, [firm()])
    note = decided[0]["code"] if "code" in decided[0] else decided[0]["code_note"]
    got = F.replaced_of(note)
    assert got == [
        {
            "kind": "replaced",
            "before": 'The AI says "the set pressure may exceed the limit"; check it.',
        }
    ]
    words = team_note({"cut": got})
    assert (
        "replaced by a reading proven by code" in words
        and "may exceed the limit" in words
    )


# ---- M3: no guess of which cell is the value or which test it is
def test_a_value_with_a_unit_and_a_further_number_cell_is_not_read():
    assert not _fields("Design pressure   2   barg   10.5")
    assert _fields("Design pressure   2   barg")["design_pressure"][0].vals[0].high == 2


def test_only_a_hydrostatic_test_pressure_is_the_hydrotest_row():
    assert not _fields("Test pressure   5 barg")
    assert not _fields("Seat leak test pressure   5 barg") and not _fields(
        "Pneumatic test pressure   5 barg"
    )
    assert _fields("Hydrostatic test pressure   5 barg")["test_pressure"]
    assert _fields("Hydro test pressure   5 barg")["test_pressure"]


# ---- M4: a table that cannot be read is shown as a step that did not run
def test_an_unreadable_table_of_checks_is_recorded_and_worded(monkeypatch, tmp_path):
    bad = tmp_path / "formula_checks.json"
    bad.write_text("{not json")
    monkeypatch.setattr(F, "PATH", bad)
    calls = []
    with faults.recording(calls):
        assert F.checks() == ()
    assert [c.step for c in calls] == ["aim_formula_checks"]
    assert "aim_formula_checks" in faults.NOT_APPLIED_WORDS
    assert "did not run" in faults.NOT_APPLIED_WORDS["aim_formula_checks"]


@pytest.mark.parametrize("cell", ["NA / 8 barg", "- / 10 barg"])
def test_parse_value_keeps_the_dash_as_no_value(cell):
    assert F.parse_value(cell)[0] is None
