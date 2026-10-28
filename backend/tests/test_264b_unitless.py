"""Order 264b (row 340): two numbers that BOTH carry no unit are plain numbers, the same kind.

A clause that applies only where the specific gravity is below 0.5, and a sheet that states 0.974, was
held as "unit_mismatch ... these are not the same quantity" - false, and it hid the answer: the
clause does not apply. A number WITH a unit against one without still guesses no unit. Invented values."""

from __future__ import annotations

import uuid

import pytest

from app import (
    comparison,
    condition_bare,
    conditions,
    datasheets,
    db,
    standards,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-28T00:00:00Z"


def _fact(value="0.974", unit=None, name="specific gravity"):
    return {
        "id": "f1",
        "page": 1,
        "is_blank": 0,
        "field_name": name,
        "field_label": name.title(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": value,
        "raw_unit": unit,
        "unit": unit,
    }


def _limit(condition, operator="<=", value="25"):
    return {
        "raw_value": value,
        "raw_unit": None,
        "unit": None,
        "operator": operator,
        "requirement_type": "numeric_limit",
        "value": float(value),
        "condition": condition,
        "requirement_text": "x",
        "subject": "discharge pressure",
    }


def _guard(requirement_unit, fact_unit):
    requirement = {"raw_value": "300", "raw_unit": requirement_unit, "operator": "<="}
    fact = {"raw_value": "140", "raw_unit": fact_unit, "is_blank": 0}
    return comparison._units_comparable(
        requirement,
        fact,
        comparison._unit_measure(requirement),
        comparison._unit_measure(fact),
    )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            None,
            None,
            False,
        ),  # UNCHANGED: the model shortlist still offers no unit-less pair (cloud on #1405)
        ("", "", False),
        ("mm", None, False),
        (None, "mm", False),
        ("bar", "bar", True),
        ("mm", "°C", False),
    ],
)
def test_the_shortlist_guard_is_unchanged_two_unitless_numbers_are_not_offered_as_candidates(
    left, right, expected
):
    assert _guard(left, right) is expected


@pytest.mark.parametrize(
    ("condition", "state"),
    [
        ("specific gravity below 0.5", conditions.NOT_SATISFIED),
        ("specific gravity less than 0.5", conditions.NOT_SATISFIED),
        ("specific gravity at most 0.5", conditions.NOT_SATISFIED),
        ("specific gravity under 0.9", conditions.NOT_SATISFIED),
        ("specific gravity up to 0.9", conditions.NOT_SATISFIED),
        ("specific gravity above 0.5", conditions.SATISFIED),
        ("specific gravity more than 0.5", conditions.SATISFIED),
        ("specific gravity exceeding 0.9", conditions.SATISFIED),
        ("specific gravity at least 0.974", conditions.SATISFIED),
        ("specific gravity above 0.974", conditions.NOT_SATISFIED),
    ],
)
def test_a_threshold_with_no_unit_is_decided_against_a_value_with_no_unit(
    condition, state
):
    got = conditions._evaluate_numeric(condition, [_fact()])
    assert got["state"] == state, got


def test_a_value_with_a_unit_against_a_threshold_without_one_is_still_undecided():
    got = conditions._evaluate_numeric(
        "specific gravity below 0.5", [_fact("974", "kg/m3")]
    )
    assert got["state"] == conditions.UNKNOWN and "kg/m3" in got["reason"]


def test_no_number_that_speaks_to_the_threshold_leaves_it_undecided():
    got = conditions._evaluate_numeric(
        "specific gravity below 0.5", [_fact(name="bearing type")]
    )
    assert got["state"] == conditions.UNKNOWN
    unreadable = _fact("see note")
    assert (
        conditions._evaluate_numeric("specific gravity below 0.5", [unreadable])[
            "state"
        ]
        == conditions.UNKNOWN
    )


def test_a_clause_that_applies_only_below_the_value_is_not_applicable_never_a_unit_mismatch():
    fact = _fact()
    out = comparison.compare(
        _limit("for liquids with a specific gravity below 0.5"),
        fact,
        submittal_facts=[fact],
    )
    assert out["status"] == comparison.NOT_APPLICABLE
    assert (
        "unit_mismatch" not in out["rationale"]
        and "not the same quantity" not in out["rationale"]
    )


def test_a_clause_whose_condition_holds_is_then_compared_and_says_no_unit_was_stated():
    fact = _fact()
    out = comparison.compare(
        _limit("for liquids with a specific gravity above 0.5"),
        fact,
        submittal_facts=[fact],
    )
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert (
        "states a unit" in out["rationale"]
        and "not the same quantity" not in out["rationale"]
    )


# ------------------------------------------------------------ through the whole run


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "bare.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _run(condition, *, req_unit=None, fact_unit=None, fact_value="0.974"):
    std, sub = "std-1", "sub-1"
    with db.connect() as conn:
        for doc_id, role in ((std, "COMPANY_STANDARD"), (sub, "CONTRACTOR_SUBMITTAL")):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                "uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,document_role) VALUES (?,?,?)",
                (doc_id, "test", role),
            )
        for chunk_id, doc_id in (("sc", std), ("fc", sub)):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
                "token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose','x',1,1,1)".replace(
                    "1,1)", "?,1)"
                ),
                (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"),
            )
    text = f"The specific gravity shall be at most 25, {condition}."
    req = standards.create_requirement(
        standard_document_id=std,
        chunk_id="sc",
        requirement_text=text,
        source_text=text,
        clause="6.4.1",
        page=1,
        structured={
            "subject": "the specific gravity",
            "operator": "<=",
            "raw_value": "25",
            "raw_unit": req_unit,
            "requirement_type": "numeric_limit",
            "condition": condition,
        },
    )
    datasheets.create_fact(
        submittal_document_id=sub,
        chunk_id="fc",
        field_label="Specific gravity",
        raw_value=fact_value,
        page=1,
        unit=fact_unit,
        printed_unit=fact_unit,
    )
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run_id, sub, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_reason,selection_method,included,created_at) VALUES "
            "(?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run_id, std, NOW),
        )
    result = comparison.run_comparison(
        run_id, allowed_document_ids=frozenset({std, sub})
    )
    return req, next(
        f for f in result["findings"] if f.get("requirement_id") == req["id"]
    )


def test_the_run_decides_the_clause_does_not_apply_and_does_not_overwrite_it_with_a_unit_mismatch(
    world,
):
    _req, finding = _run("for a specific gravity below 0.5")
    assert finding["compliance_status"] == comparison.NOT_APPLICABLE
    why = (finding.get("ai_rationale") or "") + (finding.get("finding") or "")
    assert "unit_mismatch" not in why


def test_a_value_read_by_the_model_and_not_confirmed_decides_no_condition():
    fact = {**_fact(), "extraction_method": "model"}
    got = conditions._evaluate_numeric("specific gravity below 0.5", [fact])
    assert got["state"] == conditions.UNKNOWN and "not yet trusted" in got["reason"]
    confirmed = {**fact, "confirmed_by": "an engineer"}
    assert (
        conditions._evaluate_numeric("specific gravity below 0.5", [confirmed])["state"]
        == conditions.NOT_SATISFIED
    )


@pytest.mark.parametrize(
    ("condition", "fact"),
    [
        # a quantity that is NOT dimensionless by nature keeps needing a unit (cloud, finding 1)
        ("design pressure above 10", _fact("5", None, "design pressure")),
        ("temperature below 100", _fact("120", None, "temperature")),
        ("thickness over 12", _fact("20", None, "thickness")),
        # a field that shares ONE word with the quantity is another quantity (cloud, finding 2)
        ("specific gravity below 0.5", _fact("2.1", None, "specific heat")),
        ("specific gravity below 0.5", _fact("5", None, "test pressure")),
        ("joint efficiency below 0.9", _fact("0.85", None, "joint type")),
    ],
)
def test_a_bare_number_decides_only_a_dimensionless_quantity_named_by_the_same_phrase(
    condition, fact
):
    got = conditions._evaluate_numeric(condition, [fact])
    assert got["state"] == conditions.UNKNOWN, got


def test_the_same_phrase_in_a_longer_field_name_still_speaks_to_the_threshold():
    fact = _fact("0.974", None, "specific gravity at operating temperature")
    got = conditions._evaluate_numeric("specific gravity below 0.5", [fact])
    assert got["state"] == conditions.NOT_SATISFIED


def test_the_list_holds_words_only_and_is_a_draft():
    import json

    data = json.loads(condition_bare.PATH.read_text(encoding="utf-8"))
    assert data["sign_off"]["status"] == "draft" and data["sign_off"]["by"] is None
    assert "specific gravity" in data["phrases"] and "pressure" not in " ".join(
        data["phrases"]
    )


@pytest.mark.parametrize(
    ("req_unit", "fact_unit", "fact_value"),
    [("bar", None, "0.974"), (None, "kg/m3", "974")],
)
def test_a_number_with_a_unit_against_one_without_is_still_a_unit_mismatch_in_the_run(
    world, req_unit, fact_unit, fact_value
):
    _req, finding = _run(
        None, req_unit=req_unit, fact_unit=fact_unit, fact_value=fact_value
    )
    why = (finding.get("ai_rationale") or "") + (finding.get("finding") or "")
    assert finding["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "unit_mismatch" in why


def test_two_numbers_with_no_unit_keep_the_compare_verdict_not_a_unit_mismatch_in_the_run(
    world,
):
    _req, finding = _run(None)
    why = (finding.get("ai_rationale") or "") + (finding.get("finding") or "")
    assert finding["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "unit_mismatch" not in why and "states a unit" in why
