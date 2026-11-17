"""LPB review round 1 (order 14): books kept ONLY by our rule sorting's equipment tags never take a place from a book chosen
otherwise, wherever a run has a limit: the AI reviewer's rule budget and the division-scope reads. Also: the stored tier word
"not AI approved" ranks a rule after the approved ones (it was compared with a capitalised literal and never matched).
Invented data only; no model, no network."""

# ruff: noqa: F811 - fixtures are imported by name
from __future__ import annotations

from app import agent_review_items as it
from app import agent_review_rule_choice as RC
from app import ai_applicability
from app.agent_review_verdict import TIER_NOT_APPROVED
from tests.test_141_division_scope import (
    GENERAL,
    PAGES,
    SPECIAL,
    STEEL,
    FakeModel,
    temp_storage,  # noqa: F401 - the fixture is used by name
)
from tests.test_agent_review_items import KIND, PAPER, SKILL, con  # noqa: F401


def _row(rid, book, *, op=None, value=None):
    return {"id": rid, "standard_document_id": book, "page": 1, "requirement_text": "it shall", "operator": op,
            "value": value}  # fmt: skip


def test_a_pump_shaped_list_loses_no_rule_asked_before_when_tag_books_are_added():
    """Scope-book rules (approved and not approved) are all asked before; tag-book rules score higher. Budget binding."""
    scope = [_row(f"s{i}", "d-scope") for i in range(6)] + [
        _row(f"n{i}", "d-scope") for i in range(4)
    ]
    tag = [_row(f"t{i}", "d-tag", op="<=", value=1.0) for i in range(8)]
    why = {f"s{i}": {"tier": "AI approved"} for i in range(6)}
    why |= {f"n{i}": {"tier": TIER_NOT_APPROVED} for i in range(4)}
    why |= {f"t{i}": {"tier": "AI approved", "field": "rated_flow"} for i in range(8)}
    before, _c, _f = RC.rank_and_cut(scope, why, "id", 10, set(), {"rated_flow"})
    after, cut, facts = RC.rank_and_cut(
        scope + tag, why, "id", 10, set(), {"rated_flow"}, frozenset(), {"d-tag"}
    )
    asked_before = {r["id"] for r in before}
    assert asked_before == {r["id"] for r in scope}
    assert asked_before <= {r["id"] for r in after}  # lost from before: 0
    assert facts["below"] == 8 and {c["rule_version_id"] for c in cut} == {
        f"t{i}" for i in range(8)
    }
    after, _c, _f = RC.rank_and_cut(
        scope + tag, why, "id", 14, set(), {"rated_flow"}, frozenset(), {"d-tag"}
    )
    assert {r["id"] for r in after} - asked_before == {
        "t0",
        "t1",
        "t2",
        "t3",
    }  # room left: tag-book rules fill it


def test_the_stored_tier_word_ranks_a_rule_not_approved_after_an_approved_one():
    rows = [_row("op", "d1", op="<=", value=1.0), _row("ok", "d1")]
    why = {
        "op": {"tier": TIER_NOT_APPROVED, "field": "f"},
        "ok": {"tier": "AI approved"},
    }
    assert RC.not_approved(why["op"]) and RC.not_approved({"tier": "Not AI approved"})
    assert not RC.not_approved(why["ok"]) and not RC.not_approved(None)
    top, _c, _f = RC.rank_and_cut(rows, why, "id", 1, set(), {"f"})
    assert [r["id"] for r in top] == ["ok"]
    assert (
        RC.score(rows[0], why["op"], set(), set()) == 1 + 1 - 2
    )  # mandatory, a limit, not approved


def test_the_item_builder_gives_the_runs_tag_only_books_to_the_rule_budget(
    con, monkeypatch
):
    con.execute(
        "CREATE TABLE review_applicable_standards (review_run_id TEXT, standard_document_id TEXT, included INTEGER,"
        " selection_method TEXT)"
    )
    con.execute(
        "INSERT INTO review_applicable_standards VALUES ('run-new', 'doc_std', 1, 'equipment_rules')"
    )
    seen = {}
    real = RC.rank_and_cut

    def spy(*args, **kw):
        seen["last"] = args[7] if len(args) > 7 else kw.get("last_ids")
        return real(*args, **kw)

    monkeypatch.setattr(RC, "rank_and_cut", spy)
    it.build_items(con, PAPER, KIND, skills=[SKILL], cache={}, run_id="run-new", ask_unapproved="agreed_field",
                   rule_budget=150)  # fmt: skip
    assert seen["last"] == {"doc_std"}


def _reqs():
    first = {**GENERAL, "standard_document_id": "d-scope"}
    tag = [
        {**SPECIAL, "id": f"zz{i}", "standard_document_id": "d-tag"} for i in range(2)
    ]
    return [first, *tag]


def _gate(last):
    return ai_applicability.division_gate(
        _reqs(), classification={"equipment_type": "Pressure vessel"}, facts=STEEL,
        standard_labels={"d-scope": "XYZ code", "d-tag": "QRS code"}, provider=FakeModel(),
        pages_of=lambda sid: PAGES, limit=1, last_ids=last,
    )  # fmt: skip


def _ids(rows):
    return {r["requirement"]["id"] if "requirement" in r else r["id"] for r in rows}


def test_division_units_of_a_tag_only_book_are_read_after_the_other_books(temp_storage):
    """One read under the limit. Before: the heavier tag-book part (2 rules, limited) takes it and the other book's rule is
    past the limit. After: the other book's part is read and only the tag book's 2 rules are past the limit."""
    before = _gate(frozenset())
    assert (
        before["summary"]["limited"] == 1
        and before["summary"]["requirements_beyond_limit"] == 1
    )
    after = _gate(frozenset({"d-tag"}))
    assert (
        after["summary"]["limited"] == 0
        and after["summary"]["requirements_beyond_limit"] == 2
    )
    assert (
        after["summary"]["not_read_limit"] == before["summary"]["not_read_limit"] == 1
    )


def test_a_review_run_gives_its_tag_only_books_to_the_division_reads(
    temp_storage, monkeypatch
):
    from app import equipment_rule_books
    from tests.test_141_division_scope import _review

    seen = {}
    real = ai_applicability.division_gate_for_run

    def spy(*args, **kw):
        seen["last"] = args[4] if len(args) > 4 else kw.get("last_ids")
        return real(*args, **kw)

    def books(conn, run):  # the run's own id reaches the reader
        held = conn.execute("SELECT 1 FROM review_runs WHERE id = ?", (run,)).fetchone()
        return frozenset({"std"}) if held else frozenset()

    monkeypatch.setattr(ai_applicability, "division_gate_for_run", spy)
    monkeypatch.setattr(equipment_rule_books, "tag_only_books", books)
    _review(monkeypatch, FakeModel())
    assert seen["last"] == {"std"}
