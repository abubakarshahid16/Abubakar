"""A question that NAMES documents gets evidence from each of them.

Measured on the live corpus (#82): "Compare incident response requirements
across doc17.pdf and doc20.pdf" gathered 8 passages, and the context budget -
which fills in rank order and drops the rest - kept two, both from doc17 and
doc19. Every doc20 passage was cut before the model saw a word of it. The model
was then asked to compare against a document it had never been shown, said
INSUFFICIENT EVIDENCE, and was right.

The fix is not per-document retrieval. It is ORDERING: when the question names
documents, the already-retrieved passages are interleaved by named document so
that the budget, which keeps a prefix, keeps at least one from each. The
positional [S#] markers stay consistent because the reorder happens BEFORE the
model ever sees the list.
"""

from __future__ import annotations

import pytest

from app import access, analysis


# ------------------------------------------------------- naming detection


def test_filenames_written_in_the_question_are_recognised():
    corpus = ["doc17.pdf", "doc20.pdf", "NORSOKM501Rev5.pdf", "book2-Differential-Equations.pdf"]
    named = analysis.named_documents(
        "Compare incident response requirements across doc17.pdf and doc20.pdf", corpus)
    assert named == ["doc17.pdf", "doc20.pdf"]


def test_a_filename_is_matched_without_its_extension_and_regardless_of_case():
    corpus = ["doc17.pdf", "NORSOKM501Rev5.pdf"]
    assert analysis.named_documents("what does DOC17 say about training", corpus) == ["doc17.pdf"]
    assert analysis.named_documents("norsokm501rev5 coating thickness", corpus) == ["NORSOKM501Rev5.pdf"]


def test_a_question_naming_nothing_names_nothing():
    corpus = ["doc17.pdf", "doc20.pdf"]
    assert analysis.named_documents("what is the minimum coating thickness", corpus) == []


def test_a_bare_number_is_not_a_document_name():
    """"17 mm" must not resolve to doc17. Only the stem or the filename counts."""
    corpus = ["doc17.pdf"]
    assert analysis.named_documents("a radius of 17 mm is required", corpus) == []


# ------------------------------------------------------------ interleaving


def _ev(filename, n):
    return {"evidence_id": f"ev_{filename}_{n}", "filename": filename, "text": f"{filename} passage {n}"}


def test_named_documents_are_interleaved_so_each_reaches_the_front():
    """The measured failure: 5 doc17 passages rank ahead of 3 doc20 passages, and
    a budget that keeps two would keep doc17, doc17. After interleaving it keeps
    doc17, doc20."""
    ranked = [_ev("doc17.pdf", i) for i in range(5)] + [_ev("doc20.pdf", i) for i in range(3)]
    out = analysis.interleave_by_document(ranked, ["doc17.pdf", "doc20.pdf"])
    assert [e["filename"] for e in out[:2]] == ["doc17.pdf", "doc20.pdf"]
    # Nothing is lost and nothing is duplicated.
    assert sorted(e["evidence_id"] for e in out) == sorted(e["evidence_id"] for e in ranked)


def test_within_a_document_the_original_rank_is_preserved():
    ranked = [_ev("doc17.pdf", i) for i in range(3)] + [_ev("doc20.pdf", i) for i in range(3)]
    out = analysis.interleave_by_document(ranked, ["doc17.pdf", "doc20.pdf"])
    assert [e["evidence_id"] for e in out if e["filename"] == "doc17.pdf"] == [
        "ev_doc17.pdf_0", "ev_doc17.pdf_1", "ev_doc17.pdf_2"]


def test_passages_from_unnamed_documents_follow_the_named_ones():
    """doc19 was not asked about. It is not discarded - it may still be relevant
    - but it must not crowd out a document the question named."""
    ranked = [_ev("doc19.pdf", 0), _ev("doc17.pdf", 0), _ev("doc19.pdf", 1), _ev("doc20.pdf", 0)]
    out = analysis.interleave_by_document(ranked, ["doc17.pdf", "doc20.pdf"])
    assert [e["filename"] for e in out] == ["doc17.pdf", "doc20.pdf", "doc19.pdf", "doc19.pdf"]


def test_with_no_named_documents_the_order_is_untouched():
    ranked = [_ev("doc19.pdf", 0), _ev("doc17.pdf", 0), _ev("doc20.pdf", 0)]
    assert analysis.interleave_by_document(ranked, []) == ranked


# ------------------------------------------------------- through gather()


def test_gather_reorders_evidence_for_a_question_that_names_documents(monkeypatch):
    """End to end through gather, with search stubbed to return the measured
    shape: named documents ranked behind an unnamed one and behind each other."""
    hits = ([{"evidence_id": f"h{i}", "filename": "doc19.pdf", "text": "x", "document_id": "d19",
              "page_start": 1, "page_end": 1} for i in range(2)]
            + [{"evidence_id": f"h17_{i}", "filename": "doc17.pdf", "text": "x", "document_id": "d17",
                "page_start": 1, "page_end": 1} for i in range(3)]
            + [{"evidence_id": f"h20_{i}", "filename": "doc20.pdf", "text": "x", "document_id": "d20",
                "page_start": 1, "page_end": 1} for i in range(3)])
    monkeypatch.setattr(analysis.search_mod, "search", lambda *a, **k: {"hits": hits})
    monkeypatch.setattr(analysis, "_corpus_filenames",
                        lambda scope: ["doc17.pdf", "doc19.pdf", "doc20.pdf"])

    scope = access.AccessScope(user_id="u", allowed_document_ids=frozenset({"d17", "d19", "d20"}))
    evidence, _ = analysis.gather(
        "Compare incident response requirements across doc17.pdf and doc20.pdf", scope)

    assert [e["filename"] for e in evidence[:2]] == ["doc17.pdf", "doc20.pdf"], (
        "a budget that keeps two passages would have kept doc19, doc19 - "
        "neither of the documents the question asked about")
    assert len(evidence) == len(hits)


def test_gather_leaves_rank_order_alone_when_nothing_is_named(monkeypatch):
    hits = [{"evidence_id": f"h{i}", "filename": f"doc{i}.pdf", "text": "x", "document_id": f"d{i}",
             "page_start": 1, "page_end": 1} for i in (19, 17, 20)]
    monkeypatch.setattr(analysis.search_mod, "search", lambda *a, **k: {"hits": hits})
    monkeypatch.setattr(analysis, "_corpus_filenames", lambda scope: ["doc17.pdf", "doc19.pdf", "doc20.pdf"])
    scope = access.AccessScope(user_id="u", allowed_document_ids=frozenset({"d17", "d19", "d20"}))
    evidence, _ = analysis.gather("what is the minimum coating thickness", scope)
    assert [e["filename"] for e in evidence] == ["doc19.pdf", "doc17.pdf", "doc20.pdf"]
