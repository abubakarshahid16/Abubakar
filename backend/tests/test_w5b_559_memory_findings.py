"""#559 (W5b-11): a finding from the model's memory of a standard is its own class.

An AI engineering check item that relates to a standard the library does NOT
hold is stored and shown as "Potential, unverified: source not held, engineer
to verify": confidence low, no clause, and the label stays on the CRS row even
after an engineer confirms raising it. The model is a fake (no socket);
synthetic sheet only.

Mutations: M6101-M6107 (scripts/mutations/w5b_559_memory_findings.py).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import ai_engineering_check as aic, db
from app.main import app
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in
from tests.test_review_ai_check import GOOD, TEXT, Fake, _ai_rows, _preview, _resolver, world  # noqa: F401

HELD_ITEM = {**GOOD, "relates_to": "std", "observation": "The hydrotest pressure is not stated beside "
                                                          "the design pressure of 23.5 barg."}


def _run(world, items):
    _sub, run, scope = world
    aic.run_check(run, allowed_document_ids=scope, cited=["API 610"], provider=Fake(items))
    return run


def test_an_item_on_a_standard_not_held_is_stored_as_potential_unverified(world):
    """THE MUTATION TARGET: before #559 it was stored like any other draft."""
    run = _run(world, [GOOD])                    # relates to API 610, not held
    [row] = _ai_rows(run)
    assert row["ai_rationale"].startswith(aic.UNVERIFIED_LABEL)
    assert "Relates to: API 610." in row["ai_rationale"]
    assert row["confidence"] == "low", "the model's medium confidence survived"
    assert row["standard_clause"] is None
    assert (row["compliance_status"], row["approval_status"]) == (None, "pending")


def test_an_item_on_a_held_standard_is_not_in_that_class(world):
    run = _run(world, [HELD_ITEM])
    [row] = _ai_rows(run)
    assert not row["ai_rationale"].startswith(aic.UNVERIFIED_LABEL)
    assert aic.UNVERIFIED_LABEL not in row["ai_rationale"]
    assert row["confidence"] == "medium"


def test_an_item_naming_no_standard_is_a_general_observation(world):
    run = _run(world, [{**GOOD, "relates_to": ""}])
    [row] = _ai_rows(run)
    assert aic.UNVERIFIED_LABEL not in row["ai_rationale"]
    assert "no standard named" in row["ai_rationale"]


def test_part_of_a_held_name_is_not_the_held_standard():
    held = {"API 610.pdf": ["6.3"]}
    assert aic.from_memory({"relates_to": "API"}, held) is True
    assert aic.from_memory({"relates_to": "API 610"}, held) is False
    assert aic.from_memory({"relates_to": "API 6100"}, held) is True
    assert aic.from_memory({"relates_to": ""}, held) is False


def test_an_item_on_a_standard_not_held_can_never_carry_a_clause(world):
    sub, run, _scope = world
    verdict = aic.accept({**GOOD, "clause": "6.3.1"}, aic.datasheet_pages(sub),
                         aic._held_standards(run), ["API 610"])
    assert verdict["accepted"] is False and verdict["reason"] == "clause_not_verified"


def test_the_crs_draft_row_carries_the_label(world):
    run = _run(world, [GOOD])
    [row] = [r for r in _preview(run)["rows"] if TEXT in r["ai_review_comment"]]
    assert row["ai_review_comment"].startswith(aic.UNVERIFIED_LABEL)
    assert TEXT not in row["comment"]


def test_a_held_standard_item_on_the_crs_carries_no_label(world):
    run = _run(world, [HELD_ITEM])
    [row] = [r for r in _preview(run)["rows"] if TEXT in r["ai_review_comment"]]
    assert aic.UNVERIFIED_LABEL not in row["ai_review_comment"]


def test_confirming_it_keeps_the_label_the_source_is_still_not_held(world, monkeypatch):
    """Never Confirmed as if checked: an engineer may raise it, but the row
    still says the source is not held."""
    _sub, run, scope = world
    run = _run(world, [GOOD])
    [item] = _ai_rows(run)
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(f"/api/reviews/findings/{item['id']}",
                                 json={"confirmed": True}).status_code == 200
    [row] = [r for r in _preview(run)["rows"] if TEXT in r["comment"]]
    assert row["comment"].startswith(aic.UNVERIFIED_LABEL)


def test_an_engineers_own_wording_replaces_the_draft_and_its_label(world):
    run = _run(world, [GOOD])
    [item] = _ai_rows(run)
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET engineer_comment = ? WHERE id = ?",
                     ("Contractor to state the hydrotest pressure per the purchase order.", item["id"]))
    [row] = [r for r in _preview(run)["rows"] if r["row_kind"] == "ai_engineering_check"]
    text = row["ai_review_comment"]
    assert text.startswith("Contractor to state the hydrotest pressure per the purchase order.")
    assert aic.UNVERIFIED_LABEL not in text
