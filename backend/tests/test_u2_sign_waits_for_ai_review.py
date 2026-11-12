"""U2: signing (POST .../crs/issue) is refused while the run's AI review has open lines, unless the request says the engineer read them.

Open = any line that is not "Pass" and not class "Not applicable". Invented runs only. MUTATION PROOF (by hand): drop the check in
`issue_review_crs` and the refusal test fails; ignore `ai_review_read` and the accept test fails.
"""

from __future__ import annotations

import pytest

from app import agent_review_open_points as OP
from app import agent_review_schema, db
from tests.test_885_crs_issue_gate import _finding, _run, _client, _submittal, temp_db  # noqa: F401 - fixture
from tests.test_crs_endpoint import NOW


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_enabled", True)


def _ai_review(run: str, doc: str, lines: list[tuple[str, str, str]]) -> None:
    with db.connect() as conn:
        agent_review_schema.create_tables(conn)
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at) VALUES (?,?,?,?,?)",
            (run, doc, "datasheet", "title", NOW),
        )
        for i, (klass, word, _) in enumerate(lines):
            conn.execute(
                "INSERT INTO agent_review_line (run_id,item_id,verdict_class,word,line_json,decided_at) VALUES (?,?,?,?,?,?)",
                (run, f"S-EQ-{i:02d}", klass, word, "{}", NOW),
            )


def _ready(doc: str) -> str:
    run = _run(doc)
    _finding(doc, run, "COMPLIANT")
    return run


def test_open_points_count_everything_but_pass_and_not_applicable_and_none_without_an_ai_review():
    doc = _submittal()
    run = _run(doc)
    assert OP.open_points(db.connect(), run) is None
    _ai_review(
        run,
        doc,
        [
            ("Proven by code", "Pass", ""),
            ("Not applicable", "Not applicable", ""),
            ("Query for the engineer", "Query", ""),
            ("Proven by code", "Fail", ""),
        ],
    )
    assert OP.open_points(db.connect(), run) == 2


def test_a_sign_is_refused_with_a_plain_reason_while_the_ai_review_has_open_points():
    doc = _submittal()
    run = _ready(doc)
    _ai_review(run, doc, [("Query for the engineer", "Query", "")])
    client = _client(doc)
    r = client.post(f"/api/reviews/runs/{run}/crs/issue")
    assert r.status_code == 409
    assert (
        "the AI review of this document has 1 open point that is not on this sheet"
        in r.json()["detail"]["message"]
    )


def test_the_acknowledgement_lets_it_through_and_a_review_with_nothing_open_signs_freely():
    doc = _submittal()
    run = _ready(doc)
    _ai_review(run, doc, [("Query for the engineer", "Query", "")])
    client = _client(doc)
    assert (
        client.post(
            f"/api/reviews/runs/{run}/crs/issue?ai_review_read=true"
        ).status_code
        == 200
    )
    doc2 = _submittal("doc_two", "Second.pdf")
    run2 = _ready(doc2)
    _ai_review(
        run2,
        doc2,
        [("Proven by code", "Pass", ""), ("Not applicable", "Not applicable", "")],
    )
    assert _client(doc2).post(f"/api/reviews/runs/{run2}/crs/issue").status_code == 200


def test_a_run_with_no_ai_review_is_unaffected():
    doc = _submittal()
    run = _ready(doc)
    assert _client(doc).post(f"/api/reviews/runs/{run}/crs/issue").status_code == 200


def test_the_issued_copy_records_the_acknowledgement_and_the_open_count():
    doc = _submittal()
    run = _ready(doc)
    _ai_review(run, doc, [("Query for the engineer", "Query", ""), ("Query for the engineer", "Query", "")])
    client = _client(doc)
    assert client.post(f"/api/reviews/runs/{run}/crs/issue?ai_review_read=true").status_code == 200
    copy = client.get(f"/api/reviews/runs/{run}/crs/issued").json()["copies"][0]
    assert (copy["ai_open_points"], copy["ai_review_acknowledged"]) == (2, True)
    doc2 = _submittal("doc_two", "Second.pdf")
    run2 = _ready(doc2)
    assert _client(doc2).post(f"/api/reviews/runs/{run2}/crs/issue").status_code == 200
    plain = _client(doc2).get(f"/api/reviews/runs/{run2}/crs/issued").json()["copies"][0]
    assert (plain["ai_open_points"], plain["ai_review_acknowledged"]) == (None, None)
