"""The advisory layer is downstream of the document layer, and says so.

Three defects seen live on the Analysis screen, one test module:

  (i)   THE RECOMMENDATION RESTATED THE SUMMARY. Same passages, same
        requirements, no action - under the banner "AI ADVISORY - NOT A
        DOCUMENTED REQUIREMENT". A real, cited requirement was being labelled
        model opinion. A recommendation that adds nothing beyond the
        documented facts is suppressed, with a reason.

  (ii)  THE RECOMMENDATION SPOKE WHEN THE SUMMARY REFUSED. A Comprehensive run
        refused the summary ("too little of it survived to consolidate") and
        still rendered a confident cited recommendation. Whatever the summary's
        refusal - the model declined, the model returned nothing, the evidence
        did not fit - the recommendation refuses too, saying the document
        layer produced nothing to advise on.

  (iii) "the gap analysis did not apply" FIRED WHEN NO BASELINE WAS NOMINATED,
        lowering confidence for a section the reader never asked about. It
        fires only when a baseline WAS nominated and the comparison came back
        empty; with no baseline it is not in the list at all.

Every model call is injected; the stub answers by WHICH system prompt it was
given, because the summary and the recommendation are separate generations and
the defects live in the joint between them.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, analysis, db, keyword, synthesis
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: A SPECIFICATION, NOT A BUG REPORT. This module was written as a spec for
#: #90: all 27 tests described designed behaviour and were expected to fail,
#: reported as xfailed rather than failed. Eleven now pass - see PENDING below.
#:
#: A PERMANENTLY RED SUITE IS HOW A TEAM STOPS READING TEST OUTPUT. Committed
#: red, "27 failures, that's the spec file" becomes "28 failures, probably the
#: spec file" inside a week, and the 28th is a real regression nobody looked at.
#:
#: `strict=True` is the part that matters, and it is doing more work than the
#: xfail. The moment somebody implements the gate, these tests PASS - and a
#: strict xfail that passes is a FAILURE. So the suite goes red at the exact
#: moment the work is finished, the marker gets deleted, and those tests become
#: ordinary passing tests. Nobody has to remember to unmark them; the tests
#: announce their own completion.
#: PARTIALLY IMPLEMENTED. #90 has two halves and only the first has landed.
#:
#: DONE, and now ordinary passing tests: the advisory GATE. A summary that
#: produced no cited sentence no longer silently takes the recommendation with
#: it - advice may rest on the gap analysis evidence instead, saying so in its
#: first sentence, and with neither footing the model is not called at all.
#: Those eleven tests XPASSed the moment the gate was wired, which is exactly
#: what `strict=True` is for: they announced their own completion and the
#: marker came off them rather than being remembered about.
#:
#: STILL SPECIFICATION, and still marked: restatement suppression (advice that
#: merely re-words the summary must be withheld with a reason) and the
#: nominated-baseline confidence check. Neither is implemented, so these
#: thirteen functions describe designed behaviour rather than reporting a bug.
#: When somebody implements them the same mechanism fires again.
PENDING = pytest.mark.xfail(
    strict=True,
    reason="#90: restatement suppression and the nominated-baseline "
           "confidence check are specified here, not implemented yet. The "
           "advisory gate half of #90 IS implemented and its tests are "
           "unmarked.",
)

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow,",
    "and any exceedance shall be reported to the area engineer before the pump",
    "is returned to service under the procedure given in this specification.",
]
COATING = [
    "A.1 Coating system no. 1",
    "Coating system no. 1 shall have a nominal dry film thickness of 280 um",
    "applied over a near-white metal blast cleaned surface for all carbon steel",
    "substrates operating below 120 degrees C in offshore atmospheric service.",
]

#: What the summary generation returns in every integration test here: a
#: cited documented fact, in the words a 4B model uses.
SUMMARY_TEXT = (
    "Coating system no. 1 shall have a nominal dry film thickness of 280 um [S1][S2]. "
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the "
    "bearing housing of pump P-101A [S1][S2]."
)
#: A paraphrase of the same facts. No action, no decision, no risk.
RESTATEMENT = (
    "The nominal dry film thickness of coating system no. 1 is 280 um [S1][S2]. "
    "Pump P-101A vibration must stay within 3.0 mm/s RMS at the bearing housing [S1][S2]."
)
#: Advice: an action, a decision with a condition, a risk.
ADVICE = (
    "Commission a dry film thickness survey of coating system no. 1 before "
    "acceptance [S1][S2]. Reject the pump until vibration is measured at the "
    "bearing housing [S1][S2]."
)


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


def build(path, blocks):
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def ingest(name="spec.pdf", blocks=(VIBRATION, COATING)) -> str:
    client = TestClient(app)
    path = build(settings.data_dir / name, blocks)
    with open(path, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": (name, fh, "application/pdf")}
                             ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def by_prompt(summary: str, recommendation: str, *, summary_truncated=False):
    """A stub that tells the two generations apart by their system prompt."""
    seen: list[str] = []

    def generate(system: str, prompt: str) -> synthesis.Generation:
        if system == synthesis.SUMMARY_SYSTEM_PROMPT:
            seen.append("summary")
            return synthesis.Generation(text=summary, truncated=summary_truncated)
        assert system == synthesis.RECOMMENDATION_SYSTEM_PROMPT, system[:60]
        seen.append("recommendation")
        return synthesis.Generation(text=recommendation, truncated=False)

    generate.seen = seen  # type: ignore[attr-defined]
    return generate


def refused_summary(reason: str) -> synthesis.Summary:
    return synthesis.Summary(
        text=None, truncated=False, positional_evidence_ids=(),
        cited_evidence_ids=(), findings=(), refusal=reason,
    )


# ------------------------------------------------ (ii) downstream of the summary


@pytest.mark.parametrize("reason", [
    synthesis.REFUSAL_MODEL_DECLINED,
    synthesis.REFUSAL_EMPTY,
    synthesis.REFUSAL_EMPTY_TRUNCATED,
    synthesis.REFUSAL_MALFORMED,
    "the evidence for this question is too large for the local model's "
    "context window; too little of it survived to consolidate",
    "no evidence was supplied",
])
def test_every_summary_refusal_closes_the_advisory_layer(reason):
    """ANY refusal, including the ones synthesis.py just grew. The gate is on
    `refusal`, not on a list of known sentences, so a new reason is gated on
    the day it is written."""
    why = analysis.advisory_refusal(refused_summary(reason))
    assert why is not None
    assert analysis.REFUSAL_NO_DOCUMENT_LAYER in why
    assert reason in why, "the reader is told WHY the document layer was silent"


def test_a_summary_that_stands_does_not_close_the_advisory_layer():
    standing = synthesis.Summary(
        text="Coating shall be 280 um [S1][S2].", truncated=False,
        positional_evidence_ids=("e1",), cited_evidence_ids=("e1",),
        findings=(synthesis.CitedSentence("Coating shall be 280 um [S1][S2].", ("e1",), "extracted"),),
    )
    assert analysis.advisory_refusal(standing) is None


def test_the_recommendation_refuses_when_the_summary_declined():
    """The live shape: summary refused, recommendation generation would have
    returned a confident cited sentence. The sentence must not render, and the
    recommendation generation is not even attempted."""
    ingest()
    gen = by_prompt("INSUFFICIENT EVIDENCE", ADVICE)
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(), generate=gen)
    assert out["recommendation"] is None
    assert analysis.REFUSAL_NO_DOCUMENT_LAYER in out["recommendation_refusal"]
    assert synthesis.REFUSAL_MODEL_DECLINED in out["recommendation_refusal"]
    assert "recommendation" not in gen.seen, \
        "the advisory model call ran over evidence the document layer refused"


def test_the_recommendation_refuses_when_the_model_returned_nothing():
    """An empty completion is one of the NEW refusals; it must gate too."""
    ingest()
    gen = by_prompt("", ADVICE)
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(), generate=gen)
    assert out["recommendation"] is None
    assert synthesis.REFUSAL_EMPTY in out["recommendation_refusal"]


@PENDING
def test_the_recommendation_refuses_when_too_little_evidence_fit(monkeypatch):
    """The Comprehensive-run refusal, verbatim: the evidence did not fit the
    window and fewer than MIN_BATCH sources survived."""
    ingest()
    monkeypatch.setattr(synthesis, "_fit", lambda q, sources, system: ([], sources))
    gen = by_prompt(SUMMARY_TEXT, ADVICE)
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(), generate=gen)
    assert out["recommendation"] is None
    assert "too little of it survived" in out["recommendation_refusal"]
    assert gen.seen == [], "no generation ran at all"


def test_the_route_returns_null_not_a_sentence_when_the_summary_refused(monkeypatch):
    ingest()
    monkeypatch.setattr(analysis, "ollama_generate", by_prompt("INSUFFICIENT EVIDENCE", ADVICE))
    r = TestClient(app).post("/api/analysis/recommendations",
                             json={"question": "dry film thickness"})
    assert r.status_code == 200, r.text
    assert r.json()["recommendation"] is None


# ----------------------------------------------------- (i) advise or stay silent


@PENDING
def test_a_restatement_of_the_summary_is_suppressed_with_a_reason():
    ingest()
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        generate=by_prompt(SUMMARY_TEXT, RESTATEMENT))
    assert out["recommendation"] is None
    assert out["recommendation_refusal"] == analysis.REFUSAL_RESTATEMENT


@PENDING
def test_a_verbatim_copy_of_the_summary_is_suppressed():
    ingest()
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        generate=by_prompt(SUMMARY_TEXT, SUMMARY_TEXT))
    assert out["recommendation"] is None
    assert out["recommendation_refusal"] == analysis.REFUSAL_RESTATEMENT


def test_advice_that_adds_an_action_is_kept():
    ingest()
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        generate=by_prompt(SUMMARY_TEXT, ADVICE))
    rec = out["recommendation"]
    assert rec is not None, out.get("recommendation_refusal")
    assert "Commission" in rec["text"] and "Reject the pump until" in rec["text"]
    assert out["recommendation_refusal"] is None


@pytest.mark.parametrize("sentence", [
    "Commission a dry film thickness survey of coating system no. 1 before acceptance [S1][S2].",
    "Reject the pump until vibration is measured at the bearing housing [S1][S2].",
    "Risk: the 280 um requirement is stated for coating system no. 1 only, so other "
    "systems are unverified [S1][S2].",
])
@PENDING
def test_each_kind_of_advice_is_below_the_restatement_threshold(sentence):
    """An action, a decision with a condition, a named risk. Each introduces
    content the summary does not carry, and the metric sees it."""
    score = analysis.sentence_containment(sentence, synthesis.split_sentences(SUMMARY_TEXT))
    assert score < analysis.RESTATEMENT_THRESHOLD, (sentence, score)


@pytest.mark.parametrize("sentence", synthesis.split_sentences(RESTATEMENT))
@PENDING
def test_each_paraphrase_is_at_or_above_the_restatement_threshold(sentence):
    score = analysis.sentence_containment(sentence, synthesis.split_sentences(SUMMARY_TEXT))
    assert score >= analysis.RESTATEMENT_THRESHOLD, (sentence, score)


@PENDING
def test_containment_ignores_citation_markers_and_function_words():
    """[S1] vs [S3], "shall" vs "must", "the" vs "a": none of it is content, so
    none of it can make a restatement look novel."""
    summary = ["The coating shall be 280 um thick [S1][S2]."]
    assert analysis.sentence_containment("A coating must be 280 um thick [S3].", summary) == 1.0


@PENDING
def test_a_mixed_recommendation_is_kept_because_it_adds_something():
    """One restated premise and one action: the action is what the reader is
    owed, and it is not thrown away because a premise was repeated."""
    mixed = (
        "Coating system no. 1 shall have a nominal dry film thickness of 280 um [S1][S2]. "
        "Commission a survey before acceptance [S1][S2]."
    )
    assert analysis.restates(mixed, SUMMARY_TEXT) is False
    assert analysis.restates(RESTATEMENT, SUMMARY_TEXT) is True


# ------------------------------------------------- (iii) the gap check


def gap_result(applicability: str, items: list[dict]) -> dict:
    return {"gaps": {"applicability": applicability, "items": items}}


@PENDING
def test_no_baseline_nominated_means_no_gap_check_at_all():
    assert analysis.gap_check(None, gap_result("not_applicable", [])) is None
    assert analysis.gap_check("", gap_result("not_applicable", [])) is None


@PENDING
def test_a_nominated_baseline_that_matched_nothing_fires():
    """The comparison was asked for and came back with nothing measured
    against the baseline: every item has no baseline citation."""
    items = [{"status": "not_applicable", "baseline_citation_id": None},
             {"status": "insufficient_evidence", "baseline_citation_id": None}]
    check = analysis.gap_check("doc-1", gap_result("applicable", items))
    assert check is not None
    assert check.label == analysis.GAP_CHECK_LABEL
    assert check.fired is True
    assert analysis.gap_check("doc-1", gap_result("applicable", [])).fired is True
    assert analysis.gap_check("doc-1", gap_result("insufficient_baseline", items)).fired is True


@PENDING
def test_a_nominated_baseline_that_was_compared_does_not_fire():
    items = [{"status": "met", "baseline_citation_id": "abc"},
             {"status": "not_applicable", "baseline_citation_id": None}]
    check = analysis.gap_check("doc-1", gap_result("applicable", items))
    assert check is not None and check.fired is False


@PENDING
def test_confidence_is_not_lowered_for_a_section_the_reader_never_asked_about():
    """No baseline: the check is absent from the list, so it is neither fired
    nor counted, and confidence is not "low" because of it."""
    ingest()
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        generate=by_prompt(SUMMARY_TEXT, ADVICE))
    rec = out["recommendation"]
    assert rec is not None, out.get("recommendation_refusal")
    labels = [c["label"] for c in rec["checks"]]
    assert analysis.GAP_CHECK_LABEL not in labels, labels
    assert len(labels) == 6, labels
    assert len(labels) == len(set(labels))


@PENDING
def test_a_nominated_baseline_keeps_the_check_in_the_list():
    doc_id = ingest()
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        baseline_document_id=doc_id, generate=by_prompt(SUMMARY_TEXT, ADVICE))
    rec = out["recommendation"]
    assert rec is not None, out.get("recommendation_refusal")
    labels = [c["label"] for c in rec["checks"]]
    assert labels.count(analysis.GAP_CHECK_LABEL) == 1, labels
    assert len(labels) == 7, labels


@PENDING
def test_a_nominated_baseline_with_nothing_to_compare_fires_through_the_path(monkeypatch):
    doc_id = ingest()
    real = analysis.gaps

    def empty(*args, **kwargs):
        out = real(*args, **kwargs)
        out["gaps"]["items"] = []
        return out

    monkeypatch.setattr(analysis, "gaps", empty)
    out = analysis.recommendation(
        "dry film thickness and vibration", access.unrestricted_scope(),
        baseline_document_id=doc_id, generate=by_prompt(SUMMARY_TEXT, ADVICE))
    rec = out["recommendation"]
    assert rec is not None
    fired = {c["label"]: c["fired"] for c in rec["checks"]}
    assert fired[analysis.GAP_CHECK_LABEL] is True
    assert rec["confidence"] == "low"
