"""Order 288.2: a "should" sentence of a standard is recorded as a recommendation, never a limit.

Invented standards only. API RP 520 held 4 of its 147 "should" sentences (coverage audit, order 289)."""

from __future__ import annotations

import json

import pytest

from app import comparison, db, recommendations, standards
from app import requirements_3b as r
from tests.test_w6_640_requirements_supersede import (  # noqa: F401
    _standard,
    temp_storage,
)

LINES = [
    "5.3 Set pressure",
    "The set pressure shall not exceed the maximum allowable working pressure of 10 bar.",
    "The set pressure should be at least 10 percent below the maximum allowable working pressure.",
    "The inlet piping should not exceed 3 percent of the set pressure in pressure drop.",
    "The valve may be fitted with a lifting lever where the owner agrees.",
    "The vendor shall size the valve and should state the sizing basis on the datasheet.",
]


def _rows(std):
    return {
        row["requirement_text"]: row
        for row in db.connect().execute(
            "SELECT * FROM standard_requirements WHERE standard_document_id = ?"
            " AND superseded_at IS NULL",
            (std,),
        )
    }


@pytest.fixture
def extracted(temp_storage):  # noqa: F811
    std = _standard(lines=LINES)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    return _rows(std)


def test_a_should_sentence_is_recorded_as_a_recommendation_with_no_limit(extracted):
    rec = [row for t, row in extracted.items() if "at least 10 percent below" in t]
    assert len(rec) == 1
    assert rec[0]["requirement_type"] == recommendations.TYPE == "recommendation"
    assert (
        rec[0]["raw_value"] is None and rec[0]["operator"] is None
    )  # advice states no threshold
    assert rec[0]["clause"] and rec[0]["page"]  # still cited


def test_should_not_is_a_recommendation_too(extracted):
    assert [
        r_["requirement_type"]
        for t, r_ in extracted.items()
        if "inlet piping should not" in t
    ] == ["recommendation"]


def test_a_sentence_with_shall_and_should_stays_the_mandatory_requirement(extracted):
    [row] = [row for t, row in extracted.items() if "vendor shall size" in t]
    assert row["requirement_type"] != "recommendation"


def test_the_shall_sentence_is_unchanged_and_may_is_still_not_recorded(extracted):
    [row] = [row for t, row in extracted.items() if "shall not exceed the maximum" in t]
    assert row["requirement_type"] == "numeric_limit" and row["raw_value"] == "10"
    assert not [t for t in extracted if "lifting lever" in t]


def test_no_existing_review_path_may_read_a_recommendation(extracted):
    rec = next(row for t, row in extracted.items() if "at least 10 percent below" in t)
    mandatory = next(
        row for t, row in extracted.items() if "shall not exceed the maximum" in t
    )
    assert standards.is_reviewable(rec) is False
    assert standards.is_reviewable(mandatory) is True
    assert not comparison.is_matchable(dict(rec))


def test_the_type_is_stored_and_the_api_can_return_it():
    assert recommendations.TYPE in r.STORED_REQUIREMENT_TYPES


@pytest.mark.parametrize(
    "sentence, expected",
    [
        ("The vent should be 2 m above the platform.", True),
        ("The line should not be insulated.", True),
        ("The valve shall be insulated.", False),
        ("The vent may be extended.", False),
        ("It is recommended that the vent is extended.", False),
        ("", False),
    ],
)
def test_which_words_make_a_recommendation(sentence, expected):
    assert recommendations.is_recommendation(sentence) is expected


# ------------------------------------------------------------------ a whole review


@pytest.fixture
def review_world(tmp_path, monkeypatch):
    from app import submittal_review
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rec.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _review_with_a_recommendation():
    from tests.test_field_naming import _world

    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    advice = "The set pressure should be at least 10 percent below the maximum allowable working pressure."
    standards.create_requirement(
        standard_document_id="std-1",
        chunk_id="sc",
        requirement_text=advice,
        source_text=advice,
        clause="6.4.2",
        page=1,
        structured={
            "requirement_type": "recommendation",
            "subject": "the set pressure",
        },
    )
    return comparison.run_comparison(run, allowed_document_ids=scope), run


def test_a_recommendation_is_not_in_the_scope_ledger_is_not_a_finding_and_is_counted_apart(
    review_world,
):
    result, run = _review_with_a_recommendation()
    held = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run,))
        .fetchone()
    )
    outcome = json.loads(held["outcome_json"])
    assert outcome["requirements_held_back"]["recommendation"] == 1
    assert (
        outcome["requirements_held_back"]["text_quality"] == 0
    )  # never "its text could not be read"
    split = outcome["requirement_split"]
    assert (
        split["checked"] + split["applies_not_checked"] + split["does_not_apply"] == 1
    )  # only the shall rule
    assert not [
        f
        for f in result["findings"]
        if "10 percent below" in str(f.get("requirement_source_text"))
    ]


# ----------------------------------------------- the library's counts and the verification queue (s1 on #1421)


def test_a_recommendation_is_in_no_requirement_count_and_not_in_the_verification_queue(
    extracted,
):
    std = next(iter(extracted.values()))["standard_document_id"]
    scope = frozenset({std})
    types = {
        row["requirement_type"]
        for row in db.connect().execute(
            "SELECT requirement_type FROM standard_requirements WHERE standard_document_id = ?",
            (std,),
        )
    }
    assert "recommendation" in types
    # every row of this invented standard is low-confidence enough to wait, so the queue would hold it
    db.connect().execute(
        "UPDATE standard_requirements SET confidence = 0.1 WHERE standard_document_id = ?",
        (std,),
    )
    db.connect().commit()
    queued = standards.verification_queue(allowed_document_ids=scope)
    assert queued and "recommendation" not in {q["requirement_type"] for q in queued}
    listed = next(
        s
        for s in standards.list_standards(allowed_document_ids=scope)
        if s["id"] == std
    )
    held = [
        r
        for r in extracted.values()
        if r["requirement_type"] not in ("recommendation", "definition")
    ]
    assert listed["requirement_count"] == len(held)
    assert listed["awaiting_verification"] == len(held)
