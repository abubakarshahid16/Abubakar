"""Order 288.2: a "should" sentence of a standard is recorded as a recommendation, never a limit.

Invented standards only. API RP 520 held 4 of its 147 "should" sentences (coverage audit, order 289)."""

from __future__ import annotations

import pytest

from app import comparison, db, recommendations, standards
from app import requirements_3b as r
from tests.test_w6_640_requirements_supersede import _standard, temp_storage  # noqa: F401

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
    rec = [row for t, row in extracted.items() if "at least 10 percent below" in t][0]
    mandatory = [
        row for t, row in extracted.items() if "shall not exceed the maximum" in t
    ][0]
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
