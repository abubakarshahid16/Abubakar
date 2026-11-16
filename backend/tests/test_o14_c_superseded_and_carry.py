"""Order 14 lane C: (1) a rule a re-extraction superseded is never a candidate of the AI reviewer, by any road; (2) a
re-extraction carries a superseded rule's AI labels to its successor with IDENTICAL text in the same book, never a
person's approval. Invented rows only; no model, no network."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_items as it
from app import rule_equipment, rule_labels, standards
from app import rule_label_schema as schema
from tests import rule_label_support as s
from tests.test_agent_review_items import (  # noqa: F401  (fixture and helpers)
    KIND,
    PAPER,
    _label,
    con,
)

# ---- (1) superseded rules are not candidates ---------------------------------------------------------------------------


def _supersede(c, *ids):
    c.execute("ALTER TABLE standard_requirements ADD COLUMN superseded_at TEXT")
    for rid in ids:
        c.execute(
            "UPDATE standard_requirements SET superseded_at = '2026-11-16' WHERE id = ?",
            (rid,),
        )


def _rules(doc):
    return {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}


def test_a_superseded_rule_from_a_stored_runs_decisions_is_not_asked_and_is_counted(
    con,  # noqa: F811
):
    before = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert "r-limit" in _rules(before)
    _supersede(con, "r-limit")
    after = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert "r-limit" not in _rules(after)
    assert _rules(after) == _rules(before) - {"r-limit"}
    assert after["rules_left_out"]["superseded"] == 1


def test_a_superseded_rule_chosen_by_the_caller_is_not_asked(con):  # noqa: F811
    _supersede(con, "r-coat")
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in cur.execute(
            "SELECT * FROM standard_requirements WHERE id IN ('r-limit', 'r-coat')"
        )
    ]
    doc = it.build_items(
        con, "doc_never_reviewed", KIND, skills=[], cache={}, requirement_rows=rows
    )
    assert _rules(doc) == {"r-limit"} and doc["rules_left_out"]["superseded"] == 1


def test_nothing_superseded_changes_nothing(con):  # noqa: F811
    before = it.build_items(con, PAPER, KIND, skills=[], cache={})
    _supersede(con)  # the column exists, no row is superseded
    after = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert (
        _rules(after) == _rules(before) and "superseded" not in after["rules_left_out"]
    )


# ---- (2) labels carried to an identical successor ----------------------------------------------------------------------

RUN = "xrun_new"


@pytest.fixture
def book(monkeypatch):
    s.switch(monkeypatch)
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, requirement_text TEXT,"
        " source_text TEXT, superseded_at TEXT, superseded_by_run TEXT)"
    )
    c.execute(
        "CREATE TABLE rulebook_approval (id TEXT PRIMARY KEY, rule_version_id TEXT, decision TEXT, approver_id TEXT,"
        " decided_at TEXT, equipment_type TEXT, tier TEXT)"
    )
    schema.create_tables(c)
    rule_equipment.create_tables(c)

    def rule(rid, text, by=None, doc="d-book"):
        c.execute(
            "INSERT INTO standard_requirements VALUES (?, ?, ?, ?, ?, ?)",
            (rid, doc, text, text, "2026-11-16" if by else None, by),
        )

    rule("old-same", "The relief device shall be set at the stated pressure.", RUN)
    rule(
        "new-same", "The relief  device shall be set at the stated pressure."
    )  # whitespace aside: identical
    rule("old-changed", "The disk shall be marked.", RUN)
    rule("new-changed", "The disk shall be marked with its burst pressure.")
    rule("old-twice", "Each valve shall be tested.", RUN)
    rule("new-twice-a", "Each valve shall be tested.")
    rule("new-twice-b", "Each valve shall be tested.")
    rule("old-taken", "The seat shall be tight.", RUN)
    rule("new-taken", "The seat shall be tight.")
    rule("old-earlier", "Springs shall be marked.", "xrun_older")
    rule("new-earlier", "Springs shall be marked.")
    rule("old-person", "Bonnets shall be vented.", RUN)
    rule("new-person", "Bonnets shall be vented.")
    for ref in ("old-same", "old-changed", "old-twice", "old-taken", "old-earlier"):
        _label(c, ref, rule_version_id=None)
    _label(c, "new-taken", state="needs_human", rule_version_id=None)
    _label(c, "old-person")  # rule_version_id v-old-person
    c.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-old-person', 'approve', 'u1', 't', 'relief valve', 'owner')"
    )
    c.execute(
        "INSERT INTO rule_equipment_label (source, rule_ref, equip_state, equip_general, equip_type, labelled_at,"
        " model_a, model_b, prompt_version, list_sha) VALUES ('requirement', 'old-same', 'agreed', 0, 'relief valve',"
        " 't', ?, ?, 'rule-equip-v1', ?)",
        (s.MODEL_A, s.MODEL_B, "c" * 64),
    )
    return c


def test_an_identical_successor_gets_the_ai_label_and_is_judged_as_before(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert got["carried"] == 2  # old-same, old-person
    new = rule_labels.label_for(book, requirement_id="new-same")
    old = rule_labels.label_for(book, requirement_id="old-same")
    assert new is not None and {
        k: new[k] for k in ("state", "paper_kind", "quote_sha256", "a_model", "b_model")
    } == {
        k: old[k] for k in ("state", "paper_kind", "quote_sha256", "a_model", "b_model")
    }
    assert (
        rule_labels.usable_tier(book, requirement_id="new-same").tier
        == rule_labels.AI_TIER
    )
    assert got["carried_equipment"] == 1
    assert (
        rule_equipment.label_for(book, "requirement", "new-same")["equip_type"]
        == "relief valve"
    )


def test_changed_ambiguous_already_labelled_and_other_runs_are_not_carried(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert (
        rule_labels.label_for(book, requirement_id="new-changed") is None
        and got["no_successor"] == 1
    )
    assert (
        rule_labels.label_for(book, requirement_id="new-twice-a") is None
        and got["ambiguous"] == 1
    )
    assert (
        rule_labels.label_for(book, requirement_id="new-taken")["state"]
        == "needs_human"
    )  # its own label stays
    assert got["successor_labelled"] == 1
    assert (
        rule_labels.label_for(book, requirement_id="new-earlier") is None
    )  # superseded by another run


def test_a_persons_approval_is_never_carried_only_counted(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert got["person_decisions_not_carried"] == 1
    assert rule_labels.usable_tier(book, requirement_id="old-person").tier == "owner"
    carried = rule_labels.usable_tier(book, requirement_id="new-person")
    assert (
        carried.tier == rule_labels.AI_TIER and carried.label["rule_version_id"] is None
    )


def test_carrying_twice_changes_nothing(book):
    standards.carry_labels(book, "d-book", RUN)
    again = standards.carry_labels(book, "d-book", RUN)
    assert again["carried"] == 0 and again["successor_labelled"] == 3
