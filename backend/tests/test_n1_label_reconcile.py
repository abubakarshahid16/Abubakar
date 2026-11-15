"""Labels two readers differ on only in a word code can reconcile (scripts/reconcile_rule_labels.py).
In-memory databases: the label tables from their own schema, a lab table with the readers' answers; no model, no request."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import rule_label_convert as conv
from app import rule_label_schema, rule_labels

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_rule_labels.py"
_spec = importlib.util.spec_from_file_location("reconcile_rule_labels", SCRIPT)
R = importlib.util.module_from_spec(_spec)
sys.modules["reconcile_rule_labels"] = (
    R  # a dataclass in the script needs its module registered
)
_spec.loader.exec_module(R)

QUOTE = "The pressure vessel shall be supported on a skirt."
LAB_COLS = (
    "source, rule_ref, prompt_version, a_model, a_paper_kind, a_field, a_prompt_version, a_comparator, a_values, a_unit, a_strength, a_subject,"
    " b_model, b_paper_kind, b_field, b_prompt_version, b_comparator, b_values, b_unit, b_strength, b_subject"
)


def _answer(comparator="required", strength="shall", values=None, unit=None):
    return {
        "comparator": comparator,
        "values": values or [],
        "unit": unit,
        "strength": strength,
        "subject": "vessel support",
    }


def _world(rules):
    """(conn, lab): one needs_human label per rule in `rules` = (ref, a answer, b answer, quote, stored value)."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for st in rule_label_schema._STATEMENTS:
        conn.execute(st)
    conn.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, page INTEGER, source_text TEXT, value REAL)"
    )
    lab = sqlite3.connect(":memory:")
    lab.row_factory = sqlite3.Row
    lab.execute(f"CREATE TABLE rule_label ({LAB_COLS})")
    for ref, a, b, quote, value in rules:
        conn.execute(
            "INSERT INTO standard_requirements VALUES (?, 'std1', 3, ?, ?)",
            (ref, quote, value),
        )
        lab.execute(
            f"INSERT INTO rule_label ({LAB_COLS}) VALUES ('requirement', ?, 'rule-label-v2', 'claude-sonnet-5-5', 'procedure', NULL, 'rule-label-v2',"
            " ?, ?, ?, ?, ?, 'claude-haiku-5-5', 'procedure', NULL, 'rule-label-v2', ?, ?, ?, ?, ?)",
            (
                ref,
                a["comparator"],
                json.dumps(a["values"]),
                a["unit"],
                a["strength"],
                a["subject"],
                b["comparator"],
                json.dumps(b["values"]),
                b["unit"],
                b["strength"],
                b["subject"],
            ),
        )
        row = lab.execute(
            "SELECT * FROM rule_label WHERE rule_ref = ?", (ref,)
        ).fetchone()
        pa, pb = (
            conv._pass(row, "a", quote, "rule-label-v2"),
            conv._pass(row, "b", quote, "rule-label-v2"),
        )
        d = rule_labels.decide(
            pa, pb, quote_found=True, quote_text=quote, prompt_version="rule-label-v2"
        )
        assert d.state == "needs_human"
        conn.execute(
            "INSERT INTO rule_label (source, rule_ref, paper_kind, field, state, disagreement, a_model, a_prompt, a_answer_sha256,"
            " b_model, b_prompt, b_answer_sha256, quote_page, quote_sha256, labelled_at)"
            " VALUES ('requirement', ?, ?, ?, 'needs_human', ?, ?, 'rule-label-v2', ?, ?, 'rule-label-v2', ?, 3, ?, '2026-11-11T00:00:00Z')",
            (
                ref,
                d.paper_kind,
                d.field,
                d.disagreement,
                pa.model,
                pa.answer_sha256,
                pb.model,
                pb.answer_sha256,
                rule_labels.quote_hash(quote),
            ),
        )
    return conn, lab


def _state(conn, ref):
    r = conn.execute(
        "SELECT state, disagreement, reading_json FROM rule_label WHERE rule_ref = ?",
        (ref,),
    ).fetchone()
    return tuple(r)


def test_required_against_statement_is_reconciled_with_both_readings_kept():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    plans, held = R.plan_all(conn, lab)
    assert [p.reason for p in plans] == [R.REASON_COMPARATOR] and not held
    assert R.apply(conn, plans) == 1
    state, disagreement, reading = _state(conn, "r1")
    assert (state, disagreement) == ("ai_approved", None) and json.loads(reading)[
        "comparator"
    ] == "required"
    ev = conn.execute("SELECT * FROM rule_label_reconciled").fetchone()
    assert (
        ev["kind"] == R.CODE_RECONCILED
        and ev["previous_state"] == "needs_human"
        and ev["previous_disagreement"] == "comparator"
    )
    assert (
        json.loads(ev["a_reading_json"])["comparator"] == "required"
        and json.loads(ev["b_reading_json"])["comparator"] == "statement"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM rule_label_event WHERE event_type = 'relabel'"
        ).fetchone()[0]
        == 1
    )  # the label's own history


def test_strength_only_takes_the_weaker_word():
    conn, lab = _world(
        [("r1", _answer(strength="shall"), _answer(strength="should"), QUOTE, None)]
    )
    plans, _ = R.plan_all(conn, lab)
    assert [p.reason for p in plans] == [R.REASON_STRENGTH]
    R.apply(conn, plans)
    assert json.loads(_state(conn, "r1")[2])["strength"] == "should"


@pytest.mark.parametrize(
    ("a", "b", "quote", "value", "why"),
    [
        (
            _answer("required"),
            _answer("statement"),
            "The vessel shall not be supported on a skirt.",
            None,
            "quote_holds_a_negation_or_exception_word",
        ),
        (
            _answer("required"),
            _answer("statement"),
            "The vessel shall be supported only on a skirt.",
            None,
            "quote_holds_a_negation_or_exception_word",
        ),
        (
            _answer("required"),
            _answer("statement"),
            "The vessel is supported on a skirt.",
            None,
            "quote_holds_no_modal_word",
        ),
        (_answer("required"), _answer("statement"), QUOTE, 5.0, "rule_holds_a_number"),
        (
            _answer("prohibited"),
            _answer("required"),
            QUOTE,
            None,
            "comparator_pair_not_required_statement",
        ),
        (
            _answer("ge", "shall", [10], None),
            _answer("ge", "should", [10], None),
            "The minimum thickness shall be 10.",
            None,
            "strength_with_a_number_comparator",
        ),
    ],
)
def test_what_code_may_not_reconcile_is_held_and_nothing_is_written(
    a, b, quote, value, why
):
    conn, lab = _world([("r1", a, b, quote, value)])
    plans, held = R.plan_all(conn, lab)
    assert plans == [] and held == {why: 1}
    assert R.apply(conn, plans) == 0 and _state(conn, "r1")[0] == "needs_human"


def test_a_lab_answer_that_is_not_the_stored_answer_is_held():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    lab.execute(
        "UPDATE rule_label SET b_strength = 'should'"
    )  # a different answer than the one hashed in the label
    plans, held = R.plan_all(conn, lab)
    assert plans == [] and held == {"lab_answer_differs_from_stored_hash": 1}


def test_a_quote_that_changed_since_the_label_is_held():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    conn.execute(
        "UPDATE standard_requirements SET source_text = 'The vessel shall be supported on legs.'"
    )
    assert R.plan_all(conn, lab)[1] == {"quote_changed": 1}


def test_a_label_that_differs_in_more_than_one_part_is_not_in_scope():
    conn, lab = _world(
        [
            (
                "r1",
                _answer("required", "shall"),
                _answer("statement", "should"),
                QUOTE,
                None,
            )
        ]
    )
    assert R.plan_all(conn, lab) == (
        [],
        {},
    )  # disagreement "comparator,strength": untouched


def test_apply_twice_changes_nothing_the_second_time_and_other_labels_are_untouched():
    conn, lab = _world(
        [
            ("r1", _answer("required"), _answer("statement"), QUOTE, None),
            ("r2", _answer("prohibited"), _answer("required"), QUOTE, None),
        ]
    )
    other = _state(conn, "r2")
    plans, _ = R.plan_all(conn, lab)
    assert R.apply(conn, plans) == 1 and R.apply(conn, plans) == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM rule_label_reconciled").fetchone()[0] == 1
        and _state(conn, "r2") == other
    )


def test_undo_puts_the_label_back_exactly_and_keeps_the_history():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    before = _state(conn, "r1")
    R.apply(conn, R.plan_all(conn, lab)[0])
    assert R.undo(conn) == 1 and _state(conn, "r1") == before
    kinds = [
        r[0] for r in conn.execute("SELECT kind FROM rule_label_reconciled ORDER BY id")
    ]
    assert kinds == [R.CODE_RECONCILED, R.UNDONE] and R.undo(conn) == 0


def test_undo_leaves_a_label_that_changed_since_alone():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    R.apply(conn, R.plan_all(conn, lab)[0])
    conn.execute(
        "UPDATE rule_label SET reading_json = '{\"comparator\": \"statement\"}' WHERE rule_ref = 'r1'"
    )
    assert R.undo(conn) == 0 and _state(conn, "r1")[0] == "ai_approved"


def test_the_event_table_is_append_only():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    R.apply(conn, R.plan_all(conn, lab)[0])
    for sql in (
        "UPDATE rule_label_reconciled SET reason = 'x'",
        "DELETE FROM rule_label_reconciled",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)


def test_the_reconciled_label_is_ai_approved_for_the_reviewer():
    conn, lab = _world([("r1", _answer("required"), _answer("statement"), QUOTE, None)])
    R.apply(conn, R.plan_all(conn, lab)[0])
    assert (
        rule_labels.usable_tier(conn, requirement_id="r1").tier == rule_labels.AI_TIER
    )


def test_the_script_refuses_a_live_shaped_path_without_live_and_a_run_without_a_lab(
    tmp_path, capsys
):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    mod = R
    assert mod.main(["--db", str(live), "--lab", str(tmp_path / "lab.sqlite")]) == 2
    assert "REFUSED" in capsys.readouterr().out
    assert mod.main(["--db", str(tmp_path / "copy.sqlite")]) == 2
