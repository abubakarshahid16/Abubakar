"""Multi-document coverage reporting: the two rules, and the shape.

The feature's whole value is that a reader can trust what it says, so these
tests hold the two rules that would make it a liability rather than an asset:
`complete: true` is never emitted, and the coverage layer never re-runs the
absolute presence gate per document.

Both are enforced here rather than by a comment in the module, because a
comment does not fail a build.
"""

import fitz
import pytest

from app import answer, coverage, db, keyword, lexical
from app.config import settings

SCOPE = frozenset({"doc_a", "doc_b"})


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def report(**over):
    """A coverage report over two documents, with the retrieval facts given."""
    kwargs = {
        "answered_ids": frozenset({"doc_a"}),
        "supporting_ids": frozenset(),
        "census": {
            "doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
            "doc_b": {"candidates": 5, "shortlisted": 2, "best_rerank_score": 1.4},
        },
        "shortlist_excluded": [],
        "min_rerank_score": -3.0,
        "reranked": True,
        "filenames": {"doc_a": "a.pdf", "doc_b": "b.pdf"},
    }
    kwargs.update(over)
    return coverage.document_incidence("what is the coating thickness", SCOPE, **kwargs)


def status_of(result, doc_id):
    return next(r["status"] for r in result["documents"] if r["document_id"] == doc_id)


# ------------------------------------------------------ rule 1: never complete


def test_complete_is_never_true_whatever_the_inputs():
    """Term incidence is a presence test, and presence is not relevance.

    Emitting true would be a completeness guarantee derived from word counts
    and rerank scores - a stronger claim than either supports. The field is
    false or null, and there is no input that makes it anything else.
    """
    both_cited = report(answered_ids=frozenset({"doc_a", "doc_b"}))
    assert both_cited["complete"] is None, (
        "citing every credible document must still say NOTHING about "
        "completeness, not claim it"
    )

    for result in (
        both_cited,
        report(),
        report(answered_ids=frozenset()),
        report(census={}),
        report(reranked=False),
        report(document_id="doc_a"),
        report(min_rerank_score=-99.0),
        report(min_rerank_score=99.0),
    ):
        assert result["complete"] in (False, None)


def test_the_positive_case_reports_no_counts_at_all():
    """"2 of 2" would be a completeness guarantee by arithmetic.

    A reader who is told the answer used two of the two documents that
    mattered has been told the answer is complete, whatever the `complete`
    field says. So the null case carries no counts.
    """
    result = report(answered_ids=frozenset({"doc_a", "doc_b"}))
    assert result["basis"] == "none"
    assert result["expected_documents"] is None
    assert result["found_documents"] is None


def test_a_null_expectation_is_null_and_not_zero():
    """0 of 0 reads as a measurement. Null reads as "not measured", correctly."""
    result = report(answered_ids=frozenset({"doc_a", "doc_b"}))
    assert result["expected_documents"] is not 0  # noqa: F632 - identity is the point
    assert result["expected_documents"] is None
    assert result["searched_documents"] == 2, "this one IS always counted"


def test_the_source_never_writes_a_true_completeness_value():
    """A structural check, so the rule survives a refactor that reads well."""
    import inspect

    source = inspect.getsource(coverage)
    assert '"complete": True' not in source
    assert "'complete': True" not in source


# --------------------------- rule 2: the absolute gate runs once, not per document


def test_coverage_never_calls_the_lexical_gate(monkeypatch):
    """`lexical.assess` threads document_id into the absolute presence gate.

    That gate produces the user-visible refusal "does not appear anywhere in
    the indexed documents". Called once with the request's own scope it is
    true. Called inside a per-document loop it silently means "does not appear
    in THIS document" and the word `anywhere` becomes false.
    """
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "coverage called lexical.assess - the absolute presence gate must "
            "run exactly once, before any per-document reasoning"
        )

    monkeypatch.setattr(lexical, "assess", forbidden)
    result = report()
    assert result["documents"], "the report should still have been produced"


def test_the_module_does_not_reference_the_gate_at_all():
    """Belt and braces: the monkeypatch above only catches a call that runs."""
    import inspect

    source = inspect.getsource(coverage)
    assert "assess" not in source.split('"""', 2)[2], (
        "coverage must not name lexical.assess outside its docstring"
    )


def test_distinctive_terms_are_never_asked_for_per_document(monkeypatch):
    """The term list is a property of the question, not of a document.

    `lexical.distinctive_terms` accepts a document_id, and threading a
    per-document one through would make the question's own term list change
    depending on which document was being examined.
    """
    seen: list[object] = []

    real = lexical.distinctive_terms

    def spy(question, document_id=None):
        seen.append(document_id)
        return real(question, document_id)

    # The index has to be non-empty or distinguishing_terms returns early and
    # the spy is never called - which would make this test pass vacuously,
    # asserting nothing. `seen and ...` below is what catches that.
    monkeypatch.setattr(keyword, "indexed_count", lambda document_id=None: 400)
    monkeypatch.setattr(keyword, "term_occurrences", lambda term, document_id=None: 3)
    monkeypatch.setattr(lexical, "distinctive_terms", spy)

    terms = coverage.distinguishing_terms("what is the coating thickness")
    assert terms, "the fixture produced no terms, so nothing was measured"
    assert seen and all(d is None for d in seen), f"got document ids {seen}"


# ----------------------------------------------------------------- the statuses


def test_a_credible_passage_the_answer_did_not_use_is_named():
    """The finding this feature exists to report.

    Measured on gold question Q4: the second document's correct section was
    retrieved, shortlisted, and reranked to +2.104 against a -3.0 floor,
    fifth of sixteen. It lost to the passage count, not to a judgement.
    """
    result = report()
    assert status_of(result, "doc_b") == "credible_not_cited"
    assert result["basis"] == "credible_uncited"
    assert result["complete"] is False
    assert result["expected_documents"] == 2
    assert result["found_documents"] == 1


def test_a_document_scored_below_the_floor_is_not_called_credible():
    result = report(census={
        "doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
        "doc_b": {"candidates": 5, "shortlisted": 2, "best_rerank_score": -4.0},
    })
    assert status_of(result, "doc_b") == "retrieved_not_credible"
    assert result["complete"] is None, "an incredible passage is not a gap"


def test_a_document_whose_candidates_were_all_evicted_says_so():
    result = report(
        census={"doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
                "doc_b": {"candidates": 3, "shortlisted": 0, "best_rerank_score": None}},
        shortlist_excluded=[
            {"chunk_id": "c1", "document_id": "doc_b", "rrf": 0.01,
             "reason": "displaced_before_rerank"},
        ],
    )
    assert status_of(result, "doc_b") == "expected_not_shortlisted"


def test_a_candidate_lost_to_dedup_is_not_reported_as_never_retrieved():
    """A near-duplicate loss is still a contribution that reached the pool.

    Reporting it as "expected, not retrieved" would be false, and it is the
    same conflation that made recording only the shortlist cut insufficient.
    """
    result = report(
        census={"doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
                "doc_b": {"candidates": 2, "shortlisted": 0, "best_rerank_score": None}},
        shortlist_excluded=[
            {"chunk_id": "c1", "document_id": "doc_b", "rrf": 0.02,
             "reason": "near_duplicate"},
        ],
    )
    assert status_of(result, "doc_b") == "expected_not_shortlisted"


def test_best_rerank_score_is_null_rather_than_zero_when_nothing_scored_it():
    """0.0 sits above the -3.0 floor and would read as credible."""
    result = report(census={
        "doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
        "doc_b": {"candidates": 1, "shortlisted": 0, "best_rerank_score": None},
    })
    row = next(r for r in result["documents"] if r["document_id"] == "doc_b")
    assert row["best_rerank_score"] is None


def test_no_credibility_verdict_is_reported_without_a_rerank_pass():
    """Every status below `supporting` turns on the floor.

    With no cross-encoder pass nothing was scored against it, so reporting
    either "credible" or "not credible" would be a verdict from a test that
    did not run.
    """
    result = report(reranked=False)
    assert result["basis"] == "none"
    assert result["documents"] == []
    assert "credibility" in (result["note"] or "")


def test_a_readers_own_document_filter_is_not_second_guessed():
    result = report(document_id="doc_a")
    assert result["basis"] == "single_document_scope"
    assert result["searched_documents"] == 1
    assert result["complete"] is None


def test_every_row_comes_from_the_allowed_scope_and_nothing_else():
    """A row for a document outside the scope would leak that it exists.

    The same failure `keyword.py:230-237` argues against, and the reason there
    is no `out_of_scope` status to put such a row in.
    """
    result = report(
        census={"doc_a": {"candidates": 6, "shortlisted": 4, "best_rerank_score": 3.1},
                "doc_secret": {"candidates": 9, "shortlisted": 9,
                               "best_rerank_score": 5.0}},
        shortlist_excluded=[{"chunk_id": "x", "document_id": "doc_secret",
                             "rrf": 0.9, "reason": "displaced_before_rerank"}],
    )
    assert {r["document_id"] for r in result["documents"]} == SCOPE
    assert "doc_secret" not in str(result)


def test_a_cited_document_is_never_also_reported_as_a_gap():
    result = report(answered_ids=frozenset({"doc_a"}),
                    supporting_ids=frozenset({"doc_b"}))
    assert status_of(result, "doc_b") == "supporting"
    assert result["complete"] is None


# -------------------------------------------------------- end to end, and a refusal


def build(path, blocks):
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def test_a_refusal_carries_no_coverage_report():
    """An incidence table under a refusal invites the reader to read it as
    evidence the corpus could have answered after all."""
    from fastapi.testclient import TestClient

    from app.ingest import IngestionWorker
    from app.main import app

    path = build(settings.data_dir / "spec.pdf", [[
        "5.3.2 Vibration Limits",
        "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at",
        "the bearing housing of pump P-101A during continuous operation at the",
        "rated flow given in the datasheet for this equipment item.",
    ]])
    client = TestClient(app)
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": ("spec.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)

    refused = answer.answer(
        "what is the maximum permitted concentration of hafnium in the alloy",
        tier="extract", allowed_document_ids=frozenset({doc_id}),
    )
    assert refused["answer_type"] == "insufficient_evidence"
    assert refused.get("coverage") is None


def test_coverage_survives_reopening_a_conversation():
    """chat._PAYLOAD_KEYS is an explicit allow-list.

    A field missing from it is silently NOT persisted, so reopening a
    conversation would show a complete-looking answer with the
    partial-coverage warning gone. That is worse than not shipping the field.
    """
    from app import chat

    assert "coverage" in chat._PAYLOAD_KEYS
