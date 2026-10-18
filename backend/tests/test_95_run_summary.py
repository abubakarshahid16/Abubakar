"""Order 95 piece 1: the CRS-first Sheet's tiers on the server, and `GET .../summary`.

The tier table is tiers.ts's (order 96 item 5; v2 of #1112, order 100): every case of
`frontend/src/components/review/crs/tiers.test.ts` is here too, so the two
cannot drift apart. Display only; an unknown status is never Met; a removed
finding is counted, not tiered. Invented data.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import comparison, review_tiers
from app.api import run_summary
from app.db import connect
from app.main import app
from tests.test_w5_677_scope_ledger import review_run, temp_storage  # noqa: F401

T = review_tiers
FACTS = T.RunFacts(
    pages_not_read=frozenset({4, 9}),
    reader_timed_out_pages=frozenset({7}),
    missing_standards=("API 526",),
    library_standard_ids=frozenset({"std-1"}),
)
MET, NA, COMMENT = (
    ("A", "Met", None),
    ("A", "Not applicable", None),
    ("B", "Comment", None),
)
OTHER_DOC = ("A", "Another document", None)


def f(**over) -> dict:
    return {
        "id": "x",
        "compliance_status": "NON_COMPLIANT",
        "contractor_page": 2,
        "standard_document_id": "std-1",
        **over,
    }


def you(reason: str) -> tuple:
    return ("C", "Needs you", reason)


@pytest.mark.parametrize(
    "finding, facts, expected",
    [
        # Tier A
        (f(compliance_status="COMPLIANT"), FACTS, MET),
        (f(compliance_status="NOT_IN_DOCUMENT_SCOPE"), FACTS, OTHER_DOC),
        (f(compliance_status="NOT_APPLICABLE"), FACTS, NA),
        # Tier B
        (f(), FACTS, COMMENT),
        (f(compliance_status="MISSING_INFORMATION"), FACTS, COMMENT),
        # a failed standards list is not an empty one
        (
            f(compliance_status="MISSING_INFORMATION"),
            T.RunFacts(
                FACTS.pages_not_read,
                FACTS.reader_timed_out_pages,
                FACTS.missing_standards,
                None,
            ),
            COMMENT,
        ),
        # Tier C
        (
            f(compliance_status="NEEDS_ENGINEER_REVIEW"),
            FACTS,
            you("condition unsettled"),
        ),
        (f(compliance_status="CONDITIONAL"), FACTS, you("condition unsettled")),
        (f(contractor_page=4), FACTS, you("page not read")),
        (
            f(contractor_page=9, compliance_status="MISSING_INFORMATION"),
            FACTS,
            you("page not read"),
        ),
        (
            f(contractor_page=4, compliance_status="COMPLIANT"),
            FACTS,
            you("page not read"),
        ),
        (f(contractor_page=7), FACTS, you("page not read")),
        (
            f(standard_document_id=None, governing_sources=["API 526 clause 4.1"]),
            FACTS,
            you("standard not in library"),
        ),
        (
            f(ai_rationale="Could not check: API-526 is not held locally"),
            FACTS,
            you("standard not in library"),
        ),
        (
            f(compliance_status="MISSING_INFORMATION", standard_document_id="std-gone"),
            FACTS,
            you("standard not in library"),
        ),
        (
            f(compliance_status="MISSING_INFORMATION", standard_document_id=None),
            FACTS,
            you("standard not in library"),
        ),
        (
            f(ai_rationale="VALUE CONFLICT: page 3 also states 32 bar"),
            FACTS,
            you("value conflict"),
        ),
        (
            f(ai_rationale="Unit unknown for 25 (bar or barg?)"),
            FACTS,
            you("unit unknown"),
        ),
        # the page comes before the missing standard in the reason
        (
            f(
                contractor_page=9,
                standard_document_id=None,
                governing_sources=["API 526"],
            ),
            FACTS,
            you("page not read"),
        ),
        # a status this table does not know is never swept quietly
        (f(compliance_status="SOMETHING_NEW"), FACTS, you("condition unsettled")),
        (f(compliance_status=None), FACTS, you("condition unsettled")),
        # with no facts at all, only the status decides
        (f(contractor_page=4), T.RunFacts(), COMMENT),
        # a met value nobody has confirmed yet needs you (tiers.ts v2, #1112)
        (
            f(compliance_status="COMPLIANT", show_for_engineer_tick=True),
            FACTS,
            you("safety field"),
        ),
        (
            f(
                compliance_status="COMPLIANT",
                show_for_engineer_tick=True,
                confirmed_by="eng",
            ),
            FACTS,
            MET,
        ),
        (
            f(compliance_status="COMPLIANT", match_method="field_name"),
            FACTS,
            you("AI guess"),
        ),
        (f(match_method="field_name"), FACTS, you("AI guess")),
        (
            f(compliance_status="NEEDS_ENGINEER_REVIEW", match_method="model"),
            FACTS,
            you("AI guess"),
        ),
        (f(compliance_status="COMPLIANT", match_method="model"), FACTS, MET),
        (
            f(compliance_status="COMPLIANT", trust_label="UNPROVEN"),
            FACTS,
            you("rule not proven"),
        ),
        (f(compliance_status="COMPLIANT", trust_label="AUTO_PROVEN"), FACTS, MET),
        (
            f(
                contractor_page=4,
                compliance_status="COMPLIANT",
                match_method="field_name",
            ),
            FACTS,
            you("page not read"),
        ),
    ],
)
def test_each_tier_rule_matches_the_screens_table(finding, facts, expected):
    assert T.tier_of(finding, facts) == expected


def test_a_finding_citing_a_missing_standard_names_it():
    assert (
        T.missing_standard_of(f(governing_sources=["API 526 clause 4.1"]), FACTS)
        == "API 526"
    )
    assert (
        T.missing_standard_of(f(ai_rationale="API-526 is not held"), FACTS) == "API 526"
    )
    assert T.missing_standard_of(f(), FACTS) is None
    assert T.missing_standard_of(f(governing_sources=["API 526"]), T.RunFacts()) is None


def test_counts_keep_met_not_applicable_and_another_document_apart_and_removed_is_not_tiered():
    out = T.summarise(
        [
            f(id="1", compliance_status="COMPLIANT"),
            f(id="2", compliance_status="NOT_IN_DOCUMENT_SCOPE"),
            f(id="2b", compliance_status="NOT_APPLICABLE"),
            f(id="3"),
            f(id="4"),
            f(id="5", compliance_status="CONDITIONAL"),
            f(id="6", approval_status="rejected"),
        ],
        FACTS,
    )
    assert out["counts"] == {
        "met": 1,
        "not_applicable": 1,
        "another_document": 1,
        "comment": 2,
        "needs_you": 1,
        "removed": 1,
        "total": 7,
    }
    assert "6" not in {r["finding_id"] for r in out["rows"]}


def test_rows_come_in_screen_order_comment_needs_you_met_then_page_then_clause():
    out = T.summarise(
        [
            f(id="met", compliance_status="COMPLIANT", contractor_page=1),
            f(id="nopage", contractor_page=None),
            f(id="p2b", standard_clause="5.2"),
            f(id="p2a", standard_clause="5.1"),
            f(id="you", compliance_status="CONDITIONAL", contractor_page=1),
        ]
    )
    assert [r["finding_id"] for r in out["rows"]] == [
        "p2a",
        "p2b",
        "nopage",
        "you",
        "met",
    ]
    # null renders as nothing: no page stays None, never 0
    assert (
        next(r for r in out["rows"] if r["finding_id"] == "nopage")["contractor_page"]
        is None
    )


def test_the_summary_route_tiers_every_finding_of_a_stored_run(review_run):  # noqa: F811
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    findings = comparison.list_findings(run, allowed_document_ids=scope)
    assert findings, "the fixture run produced findings"
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    assert body["review_run_id"] == run
    assert body["boundary"]
    assert {r["finding_id"] for r in body["rows"]} == {f["id"] for f in findings}
    counts = body["counts"]
    assert counts["total"] == len(findings)
    assert sum(
        counts[k]
        for k in ("met", "not_applicable", "another_document", "comment", "needs_you")
    ) == len(findings)
    outcome = comparison.run_outcome(run, allowed_document_ids=scope)
    facts = run_summary._facts(run, outcome, None)
    assert facts.library_standard_ids, "the run's included standards are the library"
    for row in body["rows"]:
        stored = next(x for x in findings if x["id"] == row["finding_id"])
        assert (row["tier"], row["label"], row["reason"]) == T.tier_of(stored, facts)
    # "How this was reviewed" is the stored outcome's own fields, not a recount
    how = body["how_reviewed"]
    assert how["requirement_split"] == outcome["requirement_split"]
    assert how["page_coverage"] == outcome["page_coverage"]
    assert how["completeness"] == outcome["completeness"]


def test_a_removed_finding_leaves_the_rows_and_is_counted(review_run):  # noqa: F811
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    first = comparison.list_findings(run, allowed_document_ids=scope)[0]["id"]
    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET approval_status = 'rejected' WHERE id = ?",
            (first,),
        )
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    assert first not in {r["finding_id"] for r in body["rows"]}
    assert body["counts"]["removed"] == 1


def test_an_unknown_run_is_404_and_writes_nothing(temp_storage):  # noqa: F811
    client = TestClient(app)
    assert client.get("/api/reviews/runs/nope/summary").status_code == 404
    assert client.get("/api/reviews/runs/nope/summary?x=1").status_code in (404, 422)


# --------------------------------------------- order 96: five more fields


def _store_outcome(run, **extra):
    with connect() as conn:
        row = conn.execute(
            "SELECT refusal_reason FROM review_runs WHERE id = ?", (run,)
        ).fetchone()
        outcome = {**json.loads(row["refusal_reason"] or "{}"), **extra}
        conn.execute(
            "UPDATE review_runs SET refusal_reason = ? WHERE id = ?",
            (json.dumps(outcome), run),
        )
    return outcome


def test_timed_out_pages_come_from_the_stored_reader_record(review_run):  # noqa: F811
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    client = TestClient(app)
    split = comparison.run_outcome(run, allowed_document_ids=scope)["requirement_split"]
    _store_outcome(run, requirement_split={**split, "reader": None})
    assert (
        client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"][
            "timed_out_pages"
        ]
        is None
    )  # no reader record: null, never []
    _store_outcome(
        run,
        requirement_split={
            **split,
            "reader": {"engine": "ollama", "pages": 6, "timed_out": [5, 3]},
        },
    )
    assert client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"][
        "timed_out_pages"
    ] == [3, 5]


def test_versions_stages_and_clauses_are_read_from_what_the_run_stored(
    review_run,  # noqa: F811
    monkeypatch,
):
    from app import clause_coverage, review_jobs, review_trace

    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    client = TestClient(app)
    how = client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"]
    # no job row and no stored trace: null, never invented
    assert (how["code_version"], how["config_version"], how["stage_seconds"]) == (
        None,
        None,
        None,
    )
    cov = clause_coverage.for_run(run, allowed_document_ids=scope)
    assert sum(sum(s["counts"].values()) for s in how["clauses_by_standard"]) == len(
        cov["rows"]
    )

    monkeypatch.setattr(
        review_jobs,
        "last_run_versions",
        lambda rid: {"code_version": "abc123", "config_version": "cfg9"},
    )
    review_trace.store(
        run,
        SimpleNamespace(allowed_document_ids=scope),
        {
            phase: {"started_at": "t", "seconds": 1.5}
            for phase in set(review_trace.PHASE_OF.values())
        },
    )
    how = client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"]
    assert (how["code_version"], how["config_version"]) == ("abc123", "cfg9")
    assert how["stage_seconds"] and set(how["stage_seconds"].values()) == {1.5}


def test_a_finding_on_a_page_the_reader_timed_out_on_needs_you(review_run):  # noqa: F811
    """cloud-2's note 2 on #1111: the route itself turns the stored timed-out
    pages into the tier, not only `tier_of` in isolation."""
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    fid = comparison.list_findings(run, allowed_document_ids=scope)[0]["id"]
    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET compliance_status = 'COMPLIANT',"
            " contractor_page = 7, match_method = NULL WHERE id = ?",
            (fid,),
        )
    split = comparison.run_outcome(run, allowed_document_ids=scope)["requirement_split"]
    client = TestClient(app)

    def row():
        rows = client.get(f"/api/reviews/runs/{run}/summary").json()["rows"]
        return next(r for r in rows if r["finding_id"] == fid)

    _store_outcome(run, requirement_split={**split, "reader": None})
    assert (row()["tier"], row()["label"]) == ("A", "Met")
    _store_outcome(
        run, requirement_split={**split, "reader": {"pages": 9, "timed_out": [7]}}
    )
    assert (row()["tier"], row()["reason"]) == ("C", "page not read")


def test_a_run_the_caller_may_not_read_is_404_like_one_that_is_not_there(review_run):  # noqa: F811
    """cloud-2's note 3 on #1111: a run that exists, read by a caller whose
    grants do not include its submittal."""
    from app import access

    run, _ids, _scope = review_run
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="stranger", allowed_document_ids=frozenset({"some-other-doc"})
    )
    try:
        response = TestClient(app).get(f"/api/reviews/runs/{run}/summary")
    finally:
        app.dependency_overrides.pop(access.current_scope, None)
    assert response.status_code == 404
    assert TestClient(app).get(f"/api/reviews/runs/{run}/summary").status_code == 200
