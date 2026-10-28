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


# ----------------------------------------------- step 2: a review raises a recommendation as a query

ADVICE = "The set pressure should not exceed 3 bar in normal operation of the unit."


def _add_advice(standard, chunk, clause, page=1, text=ADVICE):
    return standards.create_requirement(
        standard_document_id=standard,
        chunk_id=chunk,
        requirement_text=text,
        source_text=text,
        clause=clause,
        page=page,
        structured={
            "requirement_type": "recommendation",
            "subject": "the set pressure",
        },
    )


def _second_standard(run):
    """A standard the review includes because of the equipment type, NOT because the sheet names it."""
    import uuid

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('std-2','std-2.pdf','sha-std-2',1,'std-2.pdf','ready',1,'2026-10-28T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES ('std-2','test','COMPANY_STANDARD')"
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES ('sc2','std-2','f.pdf',0,1,1,NULL,'prose','x',1,'h2',1)"
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
            "selection_method,included,created_at) VALUES (?,?,'std-2','type','equipment_type',1,'2026-10-28T00:00:00Z')",
            (str(uuid.uuid4()), run),
        )


@pytest.fixture
def queries_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "recommendation_queries_enabled", True)


def _reasons(split):
    return {r["reason"]: r["count"] for r in split["applies_not_checked_reasons"]}


def _outcome(run):
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run,))
        .fetchone()
    )
    return json.loads(row["outcome_json"])


def test_a_recommendation_of_a_standard_the_sheet_names_is_raised_as_a_query_never_a_verdict(
    review_world, queries_on
):
    from tests.test_field_naming import _world

    _req, _fact, run, scope = _world(
        "Set pressure", "9 bar"
    )  # the sheet states 9 bar: the advice says 3
    _add_advice("std-1", "sc", "6.4.2")
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    [query] = [
        f
        for f in result["findings"]
        if "recommended by" in str(f.get("finding") or f.get("ai_rationale"))
    ]
    assert (
        query["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    )  # not NON_COMPLIANT: 9 > 3
    assert query["fact_id"] is None
    text = str(query.get("finding") or "") + str(query.get("ai_rationale") or "")
    assert (
        "cl. 6.4.2" in text
        and "Please confirm or justify" in text
        and "not a requirement" in text
    )
    split = _outcome(run)["requirement_split"]
    assert (
        split["recommendation_queries"] == 1
    )  # outside checked / not checked / does not apply
    assert _reasons(split).get(recommendations.REASON) is None
    cov = _outcome(run)["clause_coverage"]
    assert (
        cov["counts"]["recommendation_query"] == 1
        and "1 recommendation(s) raised as queries" in cov["line"]
    )
    assert (
        cov["adds_up"] is True
        and cov["applicable"] == split["checked"] + split["applies_not_checked"]
    )


def test_a_recommendation_of_a_standard_the_sheet_does_not_name_raises_nothing_and_is_counted(
    review_world, queries_on
):
    from tests.test_field_naming import _world

    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    _second_standard(run)
    _add_advice("std-2", "sc2", "2.1")
    result = comparison.run_comparison(run, allowed_document_ids=scope | {"std-2"})
    assert not [f for f in result["findings"] if "recommended by" in str(f)]
    out = _outcome(run)
    assert out["requirements_held_back"]["recommendation"] == 1
    assert _reasons(out["requirement_split"]).get(recommendations.REASON) is None


def test_every_recommendation_is_its_own_query_however_many_there_are(
    review_world, queries_on
):
    from tests.test_field_naming import _world

    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    for n in range(8):  # more than held_findings.GROUP_ABOVE
        _add_advice(
            "std-1",
            "sc",
            f"6.5.{n}",
            text=f"The vent {n} should be 2 m above the platform edge.",
        )
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    queries = [f for f in result["findings"] if "recommended by" in str(f)]
    assert len(queries) == 8
    assert {q["compliance_status"] for q in queries} == {
        comparison.NEEDS_ENGINEER_REVIEW
    }


def test_with_the_switch_off_a_recommendation_of_a_named_standard_raises_nothing(
    review_world,
):
    from tests.test_field_naming import _world

    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    _add_advice("std-1", "sc", "6.4.2")
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert not [f for f in result["findings"] if "recommended by" in str(f)]
    out = _outcome(run)
    assert out["requirements_held_back"]["recommendation"] == 1
    assert _reasons(out["requirement_split"]).get(recommendations.REASON) is None


def _numbers_of_the_run(monkeypatch, tmp_path, switch):
    from app import submittal_review
    from app.config import settings
    from tests.test_field_naming import _world

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rec.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    monkeypatch.setattr(settings, "recommendation_queries_enabled", switch)
    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    for n in range(3):
        _add_advice(
            "std-1",
            "sc",
            f"6.6.{n}",
            text=f"The vent {n} should be 2 m above the platform edge.",
        )
    comparison.run_comparison(run, allowed_document_ids=scope)
    out = _outcome(run)
    queries = (
        db.connect()
        .execute(
            "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ? AND ai_rationale LIKE 'Query: recommended by%'",
            (run,),
        )
        .fetchone()[0]
    )
    return {
        "counts": out["unchecked_counts"],
        "share": out["requirement_split"]["unchecked_share"],
        "code": out["recommended_code"],
        "applicable": out["clause_coverage"]["applicable"],
    }, queries


def test_the_headline_numbers_and_the_recommended_code_are_the_same_with_the_queries_on_or_off(
    monkeypatch, tmp_path
):
    """cloud-2 on #1425: advice must not move the unchecked share, the count the 'manual review' rule reads,
    the clause-coverage denominator or the run's recommended code."""
    off, off_queries = _numbers_of_the_run(monkeypatch, tmp_path / "off", False)
    on, on_queries = _numbers_of_the_run(monkeypatch, tmp_path / "on", True)
    assert (off_queries, on_queries) == (0, 3)  # the queries are really there
    assert on == off
    db.reset_connection()
