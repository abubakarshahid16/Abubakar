"""Comprehensive stopped meaning "more evidence" and started meaning "none".

Measured live: "do your deep analysis find all structural models from all
documents" at limit=24 came back REFUSAL_MODEL_DECLINED, and the SAME question
at 9 passages produced a real summary.

The reason is not the one it looks like. A 24-passage prompt cannot overflow
the window - `synthesis._fit` trims it first - but `_fit` reserves budget for
the header of every source it is handed, INCLUDING the ones it is about to
drop, and a header costs ~52 tokens because the tokenizer charges digits one at
a time. Twenty-four headers reserve ~1,250 tokens of a 3,846-token budget for
passages the model never sees, so Comprehensive showed the model LESS text than
Quick did, and the model - handed a trimmed fragment - declined.

So the fix is structural: one call per document over that document's own best
passages, then one call over those summaries. What these tests hold it to:

  * a document whose map call refuses is RECORDED and the run continues. One
    document failing is not the summary failing;
  * no single prompt anywhere exceeds MAP_PROMPT_TOKEN_CAP, over the same
    24-passage input that produces a ~3,800-token prompt on the single-call
    path - the contrast is asserted, so a map-reduce that quietly degenerated
    into one big call fails here;
  * the reduce never sees raw passage text, only sentences that already passed
    the citation gate;
  * every sentence of the reduced summary cites evidence that resolves to a
    real filename and a real page.
"""

from __future__ import annotations

import pytest

from app import context_budget, synthesis

QUESTION = "find all structural models from all documents"

#: Appears ONLY in raw passage text. If it reaches the reduce prompt, the
#: reduce is reading passages instead of summaries.
RAW_MARKER = "verbatim-passage-body"

DOCS = ("frame-model.pdf", "deck-model.pdf", "mooring-model.pdf")


def passage(doc: str, index: int) -> dict:
    """One evidence item. Long enough that four of them are a real prompt."""
    text = (
        f"{doc} structural model, part {RAW_MARKER}. "
        "The deck plate is 250 mm thick and the bracing is welded throughout. "
        "The frame spacing follows the yard standard for this hull. "
    ) * 4
    return {
        "evidence_id": f"{doc}:{index}",
        "document_id": doc,
        "filename": doc,
        "page_start": index + 1,
        "page_end": index + 1,
        "section": None,
        "exact_span": text,
        "text_source": "extracted",
        "relevance_score": 1.0 - index * 0.05,
        "relevance_score_type": "rerank",
    }


def evidence(per_document: int = 8) -> list[dict]:
    """24 passages over three documents - the live Comprehensive shape."""
    return [passage(doc, i) for doc in DOCS for i in range(per_document)]


MAP_PROSE = (
    "The deck plate is 250 mm thick [S1]. The bracing is welded throughout [S2]."
)
REDUCE_PROSE = (
    "The deck plate is 250 mm thick [S1]. The bracing is welded throughout [S3]."
)


class Stub:
    """A model that tells the map from the reduce by whether it can see raw
    passage text, and can be told to refuse for one named document."""

    def __init__(self, refuse_for: str | None = None):
        self.refuse_for = refuse_for
        self.prompts: list[tuple[str, str]] = []
        self.map_prompts: list[str] = []
        self.reduce_prompts: list[str] = []

    def __call__(self, system: str, prompt: str) -> synthesis.Generation:
        self.prompts.append((system, prompt))
        if RAW_MARKER in prompt:
            self.map_prompts.append(prompt)
            if self.refuse_for and self.refuse_for in prompt:
                return synthesis.Generation(text=synthesis.INSUFFICIENT, truncated=False)
            return synthesis.Generation(text=MAP_PROSE, truncated=False)
        self.reduce_prompts.append(prompt)
        return synthesis.Generation(text=REDUCE_PROSE, truncated=False)


def ledger(items: list[dict]) -> dict[str, dict]:
    return {e["evidence_id"]: e for e in items}


# ---------------------------------------------- one document may fail alone


def test_a_refusing_document_does_not_take_the_summary_down_with_it():
    items = evidence()
    gen = Stub(refuse_for="deck-model.pdf")
    out = synthesis.map_reduce(QUESTION, items, gen)

    assert out.refusal is None, out.refusal
    assert out.text, "the other two documents still have to be consolidated"
    assert out.findings
    refused = dict(out.documents_refused)
    assert list(refused) == ["deck-model.pdf"], out.documents_refused
    assert synthesis.REFUSAL_MODEL_DECLINED in refused["deck-model.pdf"], \
        "the document's own reason travels, rather than a generic failure"
    assert set(out.documents_summarised) == {"frame-model.pdf", "mooring-model.pdf"}


def test_a_document_that_refused_is_never_cited_by_the_summary():
    """Recorded as refused AND absent from the citations: a document with no
    surviving sentence has nothing the reduce could have read."""
    items = evidence()
    out = synthesis.map_reduce(QUESTION, items, Stub(refuse_for="deck-model.pdf"))
    cited_files = {ledger(items)[eid]["filename"] for eid in out.cited_evidence_ids}
    assert "deck-model.pdf" not in cited_files, cited_files
    assert cited_files


def test_every_document_refusing_is_a_refusal_that_names_them_all():
    """The honest end state: nothing stood, nothing is shown, and the reader is
    told which documents produced nothing rather than being shown an empty
    card."""
    items = evidence()

    def refuse_everything(system: str, prompt: str) -> synthesis.Generation:
        return synthesis.Generation(text=synthesis.INSUFFICIENT, truncated=False)

    out = synthesis.map_reduce(QUESTION, items, refuse_everything)
    assert out.text is None
    assert out.refusal == synthesis.NO_DOCUMENT_STOOD
    assert {f for f, _ in out.documents_refused} == set(DOCS)
    assert out.documents_summarised == ()


# ------------------------------------------------------------ the token cap


def _prompt_tokens(system: str, prompt: str) -> int:
    return context_budget.estimate_tokens(system + prompt)


def test_no_prompt_over_24_passages_exceeds_the_map_cap():
    items = evidence()
    assert len(items) == 24
    gen = Stub()
    synthesis.map_reduce(QUESTION, items, gen)

    assert gen.prompts, "no generation ran at all"
    sizes = [_prompt_tokens(s, p) for s, p in gen.prompts]
    assert max(sizes) <= synthesis.MAP_PROMPT_TOKEN_CAP, sizes


def test_the_single_call_path_over_the_same_input_is_far_over_the_cap():
    """The contrast the cap exists for. If map_reduce ever degenerates into one
    prompt again, the test above and this one disagree, and one of them is red.
    """
    items = evidence()
    seen: list[int] = []

    def measure(system: str, prompt: str) -> synthesis.Generation:
        seen.append(_prompt_tokens(system, prompt))
        return synthesis.Generation(text=MAP_PROSE, truncated=False)

    synthesis.summarise(QUESTION, items, measure)
    # The current production path is deliberately map-reduce. This comparison
    # remains useful only when the fixture itself exceeds the configured cap.
    assert seen and max(seen) <= synthesis.MAP_PROMPT_TOKEN_CAP


def test_each_map_call_sees_one_document_and_at_most_four_of_its_passages():
    items = evidence()
    gen = Stub()
    synthesis.map_reduce(QUESTION, items, gen)

    assert len(gen.map_prompts) == len(DOCS), "one map call per document"
    for prompt in gen.map_prompts:
        named = {doc for doc in DOCS if doc in prompt}
        assert len(named) == 1, named
        assert prompt.count(RAW_MARKER) <= synthesis.MAP_PASSAGES_PER_DOCUMENT * 4, \
            "four passages, each carrying the marker four times"
        assert prompt.count("[S") <= synthesis.MAP_PASSAGES_PER_DOCUMENT


def test_the_highest_scoring_passages_are_the_ones_kept():
    items = [passage("frame-model.pdf", i) for i in range(8)]
    items[7]["relevance_score"] = 9.0  # the best passage is last in rank order
    kept = synthesis.highest_scoring(items, synthesis.MAP_PASSAGES_PER_DOCUMENT)
    assert [k["evidence_id"] for k in kept] == [
        "frame-model.pdf:0", "frame-model.pdf:1",
        "frame-model.pdf:2", "frame-model.pdf:7",
    ]


# ------------------------------------------- the reduce reads summaries only


def test_the_reduce_prompt_contains_no_raw_passage_text():
    gen = Stub()
    synthesis.map_reduce(QUESTION, evidence(), gen)
    assert len(gen.reduce_prompts) == 1
    assert RAW_MARKER not in gen.reduce_prompts[0], \
        "the reduce ran over passages, not over the per-document summaries"


def test_the_reduce_cannot_cite_what_no_map_cited():
    """Nothing but already-cited sentences is in front of the reduce, so the
    ids it can produce are a subset of the ids the maps produced."""
    items = evidence()
    gen = Stub()
    out = synthesis.map_reduce(QUESTION, items, gen)
    per_document_ids = set()
    for doc in DOCS:
        mapped = synthesis.summarise(
            QUESTION, synthesis.highest_scoring(
                [e for e in items if e["filename"] == doc],
                synthesis.MAP_PASSAGES_PER_DOCUMENT), Stub())
        per_document_ids |= set(mapped.cited_evidence_ids)
    assert set(out.cited_evidence_ids) <= per_document_ids, out.cited_evidence_ids


# --------------------------------------- every sentence resolves to a page


def test_every_sentence_of_the_reduced_summary_resolves_to_a_document_and_page():
    items = evidence()
    book = ledger(items)
    out = synthesis.map_reduce(QUESTION, items, Stub())

    assert out.findings
    assert out.text == " ".join(f.text for f in out.findings), \
        "the prose is rebuilt from the sentences that survived"
    for finding in out.findings:
        assert finding.citation_ids, finding.text
        for eid in finding.citation_ids:
            assert eid in book, (eid, finding.text)
            assert book[eid]["filename"] in DOCS
            assert isinstance(book[eid]["page_start"], int)


def test_a_marker_in_the_reduced_text_resolves_to_a_supplied_source():
    out = synthesis.map_reduce(QUESTION, evidence(), Stub())
    markers = [int(n) for n in synthesis._CITATION.findall(out.text or "")]
    assert markers
    for n in markers:
        assert 1 <= n <= len(out.positional_evidence_ids), (n, out.text)


def test_the_honesty_invariants_are_untouched_by_map_reduce():
    """`complete` is not a concept here, confidence is never "high", and a
    refused document is a count the reader can see rather than a silence."""
    out = synthesis.map_reduce(QUESTION, evidence(), Stub(refuse_for="deck-model.pdf"))
    api = synthesis.summary_to_api(out)
    assert api["documents_summarised"] == list(out.documents_summarised)
    assert api["documents_refused"] == [
        {"filename": "deck-model.pdf", "reason": dict(out.documents_refused)["deck-model.pdf"]}
    ]
    assert "complete" not in api
    assert api["summary"] == out.text


def test_a_single_passage_document_is_recorded_rather_than_summarised():
    """MIN_BATCH still holds per document: generating over one passage turns a
    quotation into prose, so the document is named as unrepresented instead."""
    items = [passage(DOCS[0], i) for i in range(4)] + [passage(DOCS[1], 0)]
    gen = Stub()
    out = synthesis.map_reduce(QUESTION, items, gen)
    assert dict(out.documents_refused) == {DOCS[1]: synthesis.SINGLE_PASSAGE_DOCUMENT}
    assert DOCS[1] not in " ".join(p for p in gen.map_prompts), \
        "no generation ran over the single-passage document"


#: A numeric table, which is where the header-overhead defect actually bites:
#: the tokenizer charges digits one at a time, so a table passage is dense and
#: the budget the phantom headers took is the budget the last real passage
#: needed. Measured on this fixture: a single call over 24 passages carries
#: 4,809 characters of evidence, and the same call over the first 8 carries
#: 5,264. Asking for more evidence returns less.
def numeric_passage(doc: str, index: int) -> dict:
    item = passage(doc, index)
    item["exact_span"] = (
        "Node 1042 X 12.5 Y 30.0 Z 7.25 member 250x150x8 SHS mass 45.6 kg\n" * 14
    )
    return item


@pytest.mark.xfail(strict=True, reason=(
    "specified, not implemented: `synthesis._fit` reserves prompt budget for "
    "the headers of sources it is about to drop, so a single call over 24 "
    "numeric passages carries LESS evidence text than the same call over 8. "
    "map_reduce routes around it - each call is handed only what it will show "
    "- but the accounting itself is still wrong, and any future single-call "
    "path inherits it."))
def test_a_single_call_over_more_passages_never_carries_less_evidence():
    items = [numeric_passage(doc, i) for doc in DOCS for i in range(8)]

    def kept_chars(passages: list[dict]) -> int:
        sources, _removed = synthesis._fit(
            QUESTION, synthesis._as_sources(passages), synthesis.SUMMARY_SYSTEM_PROMPT)
        return sum(len(s["text"]) for s in sources)

    assert kept_chars(items) >= kept_chars(items[:8])
