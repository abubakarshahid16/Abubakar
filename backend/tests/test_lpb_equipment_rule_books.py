"""LPB (owner's item 2, order 14, 17 Nov 2026): book selection keeps the books our own rule sorting tagged for the equipment.

Before: a book that the paper does not cite and whose classification does not match was dropped ("no citation, equipment,
discipline, service or project match"), although `rule_equipment_label` holds agreed rules tagged for the paper's equipment.
After: such a book is kept (`equipment_rules`), by the AI reviewer's own per-rule equipment decision; a general rule, a label
not agreed, another equipment type or a superseded rule keeps nothing; a stronger reason (cited, scope) is kept as it was; a
scope clause that excludes the equipment still excludes the book; the plan lists the kept book before a start, and a book not
approved is still not sent. Invented documents and values only."""

from __future__ import annotations

import pytest

from app import (
    applicability,
    applicability_v2,
    db,
    equipment_rule_books,
    review_leaving,
    rule_equipment,
)
from app.config import settings
from tests.test_applicability import _doc, _run, _scope, temp_storage  # noqa: F401
from tests.test_b1_review_engine import open_facts

_N = iter(range(10_000))


@pytest.fixture(autouse=True)
def labels_table(temp_storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    rule_equipment.create_tables(db.connect())


def _rule(
    book: str, state="agreed", typ=None, fam=None, general=0, superseded=False
) -> str:
    ref = f"req-{next(_N)}"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, requirement_text, created_at, updated_at)"
            " VALUES (?, ?, 'invented rule', 't', 't')",
            (ref, book),
        )
        if superseded:
            conn.execute(
                "UPDATE standard_requirements SET superseded_at = 't' WHERE id = ?",
                (ref,),
            )
        agreed = state == "agreed"
        conn.execute(
            "INSERT INTO rule_equipment_label (source, rule_ref, equip_family, equip_type, equip_general, equip_state,"
            " model_a, model_b, prompt_version, list_sha, labelled_at) VALUES ('requirement', ?, ?, ?, ?, ?, ?, ?, ?, ?, 't')",
            (ref, fam, typ, general, state, "model-one" if agreed else None, "model-two" if agreed else None,
             "p1" if agreed else None, "a" * 64 if agreed else None),
        )  # fmt: skip
    return ref


def _book(doc_id: str, number: str) -> str:
    return _doc(
        doc_id, f"{number} invented.pdf", "COMPANY_STANDARD", document_number=number
    )


def _rows(result) -> dict:
    return {s["standard_document_id"]: s for s in result["selected"]}


def _pump() -> str:
    return _doc(
        "sub",
        "pump-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Rated flow 10 m3/h.",
        equipment_type="pump",
    )


def test_a_book_holding_agreed_rules_tagged_for_the_equipment_is_kept():
    """THE OWNER'S FINDING: the book was dropped with "no citation, equipment ... match"."""
    book = _book("std_k", "SAES-X-101")
    _rule(book, typ="pump", fam="rotating")
    _rule(book, typ="pump", fam="rotating")
    sub = _pump()
    run = _run(sub)
    result = applicability.select(
        sub, allowed_document_ids=_scope(book, sub), review_run_id=run
    )
    row = _rows(result)[book]
    assert (
        row["method"] == applicability.METHOD_EQUIPMENT_RULES
        and row["included"] is True
    )
    assert "holds 2 agreed rule(s)" in row["reason"] and "pump" in row["reason"]
    stored = db.connect().execute(
        "SELECT included, selection_method, exclusion_reason FROM review_applicable_standards"
        " WHERE review_run_id = ? AND standard_document_id = ?", (run, book)).fetchone()  # fmt: skip
    assert tuple(stored) == (1, "equipment_rules", None)


def test_a_family_label_with_no_type_counts_for_the_paper_of_that_family():
    book = _book("std_f", "SAES-X-102")
    _rule(book, typ=None, fam="rotating")
    sub = _pump()
    assert _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )[book]["included"]


@pytest.mark.parametrize(
    "rule",
    [
        {"general": 1},  # general: applies to all equipment, not a tag for this one
        {"state": "needs_human", "typ": "pump", "fam": "rotating"},  # not agreed
        {
            "typ": "motor",
            "fam": "rotating",
        },  # another equipment type of the same family
        {"typ": "relief_valve", "fam": "pressure_relief"},  # another family
        {"typ": "pump", "fam": "rotating", "superseded": True},  # superseded rule
    ],
)
def test_rules_not_tagged_for_this_equipment_keep_no_book(rule):
    book = _book("std_n", "SAES-X-103")
    _rule(book, **rule)
    sub = _pump()
    row = _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    ).get(book)
    assert row is None or row["method"] != applicability.METHOD_EQUIPMENT_RULES


def test_a_paper_with_no_usable_equipment_keeps_nothing_by_this_route():
    book = _book("std_u", "SAES-X-104")
    _rule(book, typ="pump", fam="rotating")
    sub = _doc("sub", "notes.pdf", "CONTRACTOR_SUBMITTAL", text="General notes only.")
    assert book not in _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )


def test_valve_and_vessel_papers_keep_the_books_tagged_for_their_own_equipment():
    valve_book, vessel_book, pump_book = (
        _book("std_v", "SAES-X-201"),
        _book("std_p", "SAES-X-202"),
        _book("std_q", "SAES-X-203"),
    )
    _rule(valve_book, typ="relief_valve", fam="pressure_relief")
    _rule(vessel_book, typ="pressure_vessel", fam="static")
    _rule(pump_book, typ="pump", fam="rotating")
    books = (valve_book, vessel_book, pump_book)
    valve = _doc(
        "psv",
        "psv-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Set 10 barg.",
        equipment_type="relief valve",
    )
    vessel = _doc(
        "ves",
        "vessel-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Design 10 barg.",
        equipment_type="pressure vessel",
    )

    def kept(paper):
        rows = _rows(
            applicability.select(
                paper, allowed_document_ids=_scope(*books, paper), persist=False
            )
        )
        return {
            b
            for b in books
            if rows.get(b, {}).get("method") == applicability.METHOD_EQUIPMENT_RULES
        }

    assert kept(valve) == {valve_book}
    assert kept(vessel) == {vessel_book}


def test_a_cited_book_keeps_its_stronger_reason():
    book = _book("std_610", "API 610")
    _rule(book, typ="pump", fam="rotating")
    sub = _doc(
        "sub",
        "pump-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Pump shall comply with API 610.",
        equipment_type="pump",
    )
    row = _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )[book]
    assert row["method"] == applicability.METHOD_REFERENCED and row["included"] is True


def _scope_says(monkeypatch, book, verdict):
    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    monkeypatch.setattr(
        applicability, "scope_decisions_by_reasoning",
        lambda *a, **k: ({book: {"decision": verdict, "quote": "invented scope words", "page": 1}}, None),
    )  # fmt: skip


def test_a_scope_clause_that_excludes_the_equipment_still_excludes_the_book(
    monkeypatch,
):
    book = _book("std_s", "SAES-X-301")
    _rule(book, typ="pump", fam="rotating")
    sub = _pump()
    _scope_says(monkeypatch, book, applicability_v2.NOT_APPLICABLE)
    row = _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )[book]
    assert (
        row["included"] is False and "scope clause excludes" in row["excluded_by_scope"]
    )


def test_a_scope_clause_that_covers_the_equipment_records_the_book_as_scope(
    monkeypatch,
):
    book = _book("std_c", "SAES-X-302")
    _rule(book, typ="pump", fam="rotating")
    sub = _pump()
    _scope_says(monkeypatch, book, applicability_v2.APPLICABLE)
    row = _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )[book]
    assert row["method"] == applicability.METHOD_SCOPE and row["included"] is True


def test_the_plan_lists_the_kept_book_before_a_start_and_an_unapproved_book_is_not_sent(
    monkeypatch,
):
    book = _book("std_k", "SAES-X-401")
    _rule(book, typ="pump", fam="rotating")
    sub = _pump()
    scope = _scope(book, sub)

    def plan():
        return review_leaving.leaving_for(
            db.connect(), sub, scope, open_facts(), equipment_type="pump", leaves=True
        )

    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    leaving = {d["id"]: d for d in plan()["leaving"]}
    assert leaving[book]["why"] == review_leaving.METHOD_WORDS["equipment_rules"]
    # the existing limit stands: with the approved list enforced and no automatic approval, the book is listed as not sent
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    out = plan()
    assert book not in {d["id"] for d in out["leaving"]}
    assert book in {d.get("id") for d in out["not_sent"]}


def test_the_words_for_the_method_exist_in_every_home():
    from app import agent_review_book_table

    method = equipment_rule_books.METHOD
    assert (
        method == applicability.METHOD_EQUIPMENT_RULES
        and method in applicability.INCLUDING_METHODS
    )
    assert (
        method in review_leaving.METHOD_WORDS
        and method in agent_review_book_table.METHOD_WORDS
    )
    assert applicability._CONFIDENCE[method] < 0.9  # never "high" (rule 4)


def test_an_unsure_equipment_type_holds_the_book_for_the_engineer(monkeypatch):
    """Order 142 stands: a book kept only because of the equipment type is held when the type is unsure."""
    book = _book("std_h", "SAES-X-501")
    _rule(book, typ="pump", fam="rotating")
    sub = _pump()
    real = applicability.standards_check
    monkeypatch.setattr(
        applicability, "standards_check",
        lambda *a, **k: {**real(*a, **k), "equipment_unsure": "invented doubt, engineer to confirm"},
    )  # fmt: skip
    row = _rows(
        applicability.select(sub, allowed_document_ids=_scope(book, sub), persist=False)
    )[book]
    assert (
        row["included"] is False and "held for the engineer" in row["held_for_engineer"]
    )
