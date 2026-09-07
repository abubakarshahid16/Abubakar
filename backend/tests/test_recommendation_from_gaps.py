"""Advice was gated on the summary alone, and the summary is the fragile half.

Live: Comprehensive returned REFUSAL_MODEL_DECLINED for the summary, and the
recommendation then stayed silent - correctly, under the old rule, because it
had no cited summary sentence to stand on. But the gap analysis had run, found
facets, and cited real passages for them; it needs no model at all. Silence
there was not honesty, it was a rule that only knew about one footing.

Two footings now, and they are not interchangeable:

  * cited summary sentences exist -> advise over the whole evidence ledger,
    exactly as before;
  * they do not, but the gap analysis produced a facet that is not
    `not_applicable` -> advise over THAT facet's evidence only, and say so in
    the recommendation's own first sentence, which carries the same citations.

WHAT IS NOT WEAKENED, and is tested here as hard as the new path: with no cited
summary sentence AND no gap facet, nothing cited exists. The model is not
called at all, the recommendation is null, and the reason names which of the
failures happened.

The retrieval and comparison stacks are stubbed rather than ingested: what is
under test is the joint between the three engines, and a real ingestion would
test the chunker's mood instead.
"""

from __future__ import annotations

import pytest

from app import analysis, synthesis

QUESTION = "do your deep analysis find all structural models from all documents"

ADVICE = "Commission a survey of the frame model before acceptance [S1]."
SUMMARY_PROSE = "The deck plate is welded throughout [S1]. Bracing is continuous [S2]."


def ev(eid: str, filename: str, page: int) -> dict:
    return {
        "evidence_id": eid,
        "document_id": filename,
        "filename": filename,
        "page_start": page,
        "page_end": page,
        "section": None,
        "exact_span": (
            "The deck plate is welded throughout and the bracing is continuous "
            "along the frame model, as recorded for this hull. "
        ) * 3,
        "text_source": "extracted",
        "relevance_score": 1.0,
        "relevance_score_type": "rerank",
    }


LEDGER = [
    ev("e1", "frame-model.pdf", 3),
    ev("e2", "deck-model.pdf", 7),
    ev("e3", "mooring-model.pdf", 11),
    ev("e4", "mooring-model.pdf", 12),
]


def gap_result(items: list[dict], applicability: str = "not_applicable") -> dict:
    return {
        "question": QUESTION,
        "evidence_ledger": LEDGER,
        "claim_clusters": [],
        "gaps": {"applicability": applicability, "baseline": None, "items": items},
        "not_implemented_sections": [],
    }


CONFLICT_ITEM = {
    "facet": "deck plate thickness",
    "status": "conflict",
    "baseline_citation_id": None,
    "baseline_span": "",
    "project_citation_ids": ["e1", "e2"],
    "note": None,
}
NOTHING_ITEM = {
    "facet": "frame spacing",
    "status": "not_applicable",
    "baseline_citation_id": None,
    "baseline_span": "",
    "project_citation_ids": ["e3"],
    "note": None,
}


class Stub:
    """Answers by which system prompt it was handed, and remembers both."""

    def __init__(self, summary_text: str, advice: str = ADVICE):
        self.summary_text = summary_text
        self.advice = advice
        self.seen: list[str] = []
        self.advice_prompts: list[str] = []

    def __call__(self, system: str, prompt: str) -> synthesis.Generation:
        if system == synthesis.SUMMARY_SYSTEM_PROMPT:
            self.seen.append("summary")
            return synthesis.Generation(text=self.summary_text, truncated=False)
        assert system == synthesis.RECOMMENDATION_SYSTEM_PROMPT, system[:60]
        self.seen.append("recommendation")
        self.advice_prompts.append(prompt)
        return synthesis.Generation(text=self.advice, truncated=False)


@pytest.fixture
def stubbed(monkeypatch):
    """Retrieval and the comparison, without a database."""
    def fake_gather(question, scope, *, limit=8, document_id=None):
        return [dict(e) for e in LEDGER], {"hits": []}

    monkeypatch.setattr(analysis, "gather", fake_gather)

    def install(items: list[dict], applicability: str = "not_applicable"):
        monkeypatch.setattr(
            analysis, "gaps",
            lambda *a, **k: gap_result(items, applicability))

    return install


SCOPE = object()  # never reached: gather and gaps are stubbed


# ------------------------------------------------ the gate, opened partway


def test_advice_runs_from_gap_evidence_when_the_summary_declined(stubbed):
    stubbed([CONFLICT_ITEM, NOTHING_ITEM])
    gen = Stub(synthesis.INSUFFICIENT)
    out = analysis.recommendation(QUESTION, SCOPE, generate=gen)

    rec = out["recommendation"]
    assert rec is not None, out["recommendation_refusal"]
    assert out["recommendation_refusal"] is None
    assert rec["text"].startswith(analysis.GAP_EVIDENCE_PREFACE), rec["text"]
    assert "Commission a survey" in rec["text"]
    assert "recommendation" in gen.seen


def test_the_preface_carries_the_same_citations_as_the_advice(stubbed):
    """It is a claim about evidence, so it cites that evidence. An uncited
    sentence cannot be constructed at all - CitedSentence refuses one."""
    stubbed([CONFLICT_ITEM])
    out = analysis.recommendation(QUESTION, SCOPE, generate=Stub(synthesis.INSUFFICIENT))
    rec = out["recommendation"]
    assert rec["citation_ids"], rec
    assert set(rec["citation_ids"]) <= {"e1", "e2"}


def test_gap_only_advice_sees_only_the_facets_evidence(stubbed):
    """`e3` is cited by a `not_applicable` facet - nothing was compared, so it
    is not a footing - and `e4` is cited by no facet at all. Neither may reach
    the advisory prompt."""
    stubbed([CONFLICT_ITEM, NOTHING_ITEM])
    gen = Stub(synthesis.INSUFFICIENT)
    analysis.recommendation(QUESTION, SCOPE, generate=gen)

    prompt = gen.advice_prompts[0]
    assert "frame-model.pdf" in prompt and "deck-model.pdf" in prompt
    assert "mooring-model.pdf" not in prompt, prompt


def test_gap_only_advice_is_never_confident_and_always_needs_an_engineer(stubbed):
    stubbed([CONFLICT_ITEM])
    out = analysis.recommendation(QUESTION, SCOPE, generate=Stub(synthesis.INSUFFICIENT))
    rec = out["recommendation"]
    assert rec["confidence"] in ("low", "medium")
    assert rec["requires_engineer_approval"] is True


# ------------------------------------------------ the refusal, not weakened


def test_nothing_cited_anywhere_still_refuses_without_calling_the_model(stubbed):
    stubbed([NOTHING_ITEM])
    gen = Stub(synthesis.INSUFFICIENT)
    out = analysis.recommendation(QUESTION, SCOPE, generate=gen)

    assert out["recommendation"] is None
    why = out["recommendation_refusal"]
    assert analysis.REFUSAL_NO_DOCUMENT_LAYER in why
    assert synthesis.REFUSAL_MODEL_DECLINED in why, \
        "the reader is told WHICH failure happened, not that something did"
    assert "recommendation" not in gen.seen, \
        "the advisory model call ran over evidence nothing cited"


def test_no_gap_items_at_all_refuses(stubbed):
    stubbed([])
    gen = Stub("")
    out = analysis.recommendation(QUESTION, SCOPE, generate=gen)
    assert out["recommendation"] is None
    assert synthesis.REFUSAL_EMPTY in out["recommendation_refusal"]
    assert "recommendation" not in gen.seen


@pytest.mark.parametrize("status", ["conflict", "possible_gap", "met",
                                    "insufficient_evidence"])
def test_every_status_but_not_applicable_is_a_footing(status):
    item = {**CONFLICT_ITEM, "status": status}
    assert analysis.gap_evidence_ids(gap_result([item])) == ["e1", "e2"]


def test_not_applicable_is_not_a_footing():
    assert analysis.gap_evidence_ids(gap_result([NOTHING_ITEM])) == []


def test_a_baseline_citation_counts_as_gap_evidence():
    item = {**CONFLICT_ITEM, "baseline_citation_id": "e4", "project_citation_ids": []}
    assert analysis.gap_evidence_ids(gap_result([item])) == ["e4"]


# -------------------------------------------------- the unchanged first path


def test_a_summary_that_stands_advises_over_the_whole_ledger(stubbed):
    stubbed([NOTHING_ITEM])
    gen = Stub(SUMMARY_PROSE)
    out = analysis.recommendation(QUESTION, SCOPE, generate=gen)

    rec = out["recommendation"]
    assert rec is not None, out["recommendation_refusal"]
    assert not rec["text"].startswith(analysis.GAP_EVIDENCE_PREFACE), \
        "the advice did not come from gap evidence, so it must not say it did"
    assert "mooring-model.pdf" in gen.advice_prompts[0]


def test_advisory_refusal_is_on_the_sentences_not_on_the_reason_string():
    """A refusal reason added to synthesis.py tomorrow is gated tomorrow."""
    empty = synthesis.Summary(
        text=None, truncated=False, positional_evidence_ids=(),
        cited_evidence_ids=(), findings=(), refusal="a brand new reason")
    why = analysis.advisory_refusal(empty)
    assert why is not None and "a brand new reason" in why

    standing = synthesis.Summary(
        text="The deck plate is welded throughout [S1].", truncated=False,
        positional_evidence_ids=("e1",), cited_evidence_ids=("e1",),
        findings=(synthesis.CitedSentence(
            "The deck plate is welded throughout [S1].", ("e1",), "extracted"),))
    assert analysis.advisory_refusal(standing) is None


def test_a_summary_with_no_findings_is_refused_even_with_no_refusal_string():
    """The gate is the sentences. A Summary that somehow carries neither prose
    nor a reason is still nothing to advise on."""
    blank = synthesis.Summary(
        text=None, truncated=False, positional_evidence_ids=(),
        cited_evidence_ids=(), findings=())
    assert analysis.REFUSAL_NO_DOCUMENT_LAYER in analysis.advisory_refusal(blank)


# ------------------------------------------------------------- the two modes


def test_comprehensive_maps_over_every_document_and_quick_does_not(stubbed, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(analysis.synthesis, "map_reduce",
                        lambda *a, **k: calls.append("map_reduce") or _blank())
    monkeypatch.setattr(analysis.synthesis, "summarise",
                        lambda *a, **k: calls.append("summarise") or _blank())
    stubbed([NOTHING_ITEM])
    analysis.recommendation(QUESTION, SCOPE, limit=24, generate=Stub(""))
    analysis.recommendation(QUESTION, SCOPE, limit=8, generate=Stub(""))
    assert calls == ["map_reduce", "summarise"]


def test_quick_never_shows_the_engine_more_than_eight_passages(monkeypatch):
    seen: list[int] = []

    def fake_gather(question, scope, *, limit=8, document_id=None):
        return [ev(f"x{i}", "frame-model.pdf", i) for i in range(24)], {"hits": []}

    monkeypatch.setattr(analysis, "gather", fake_gather)
    monkeypatch.setattr(
        analysis.synthesis, "summarise",
        lambda q, evidence, gen, **k: seen.append(len(list(evidence))) or _blank())
    analysis.summary(QUESTION, SCOPE, limit=8, generate=Stub(""))
    assert seen == [analysis.QUICK_PASSAGES]


def _blank() -> synthesis.Summary:
    return synthesis.Summary(
        text=None, truncated=False, positional_evidence_ids=(),
        cited_evidence_ids=(), findings=(), refusal="stubbed")
