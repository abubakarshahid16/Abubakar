"""The three engines joined to retrieval, the model and the access scope.

`synthesis.py` and `claims.py` are pure: they take evidence and a `generate`
callable and know nothing about SQLite, HTTP or Ollama. That is what let them
be developed and tested in isolation, and it is worth keeping - so everything
impure lives here, in one file, and the engines stay free of it.

WHAT AN EVIDENCE ITEM IS. `evidence_id` is
`sha256(document_id|page_start|page_end|section|exact_span)[:16]` and is
deliberately NOT a chunk id: chunk ids change when a document is re-chunked,
and a citation that moves when the chunker is retuned is not a citation. Two
identical spans on the same page of the same document are the same evidence,
which is the property a cross-document comparison needs.

WHY THE SPAN IS THE WHOLE PASSAGE. `exact_span` is what the reader is shown in
serif on a quote rule, and what every generated number is checked against. It
must be text that appears in the document verbatim, so it is the chunk's own
text and never a summary, a join or a reflow of it.

SCOPE. Every entry point takes an `AccessScope` and passes it to `search()`,
which filters before selection rather than after. Nothing here re-derives
authorisation, and nothing here accepts a document id from the caller that has
not been through `require_document`.
"""

from __future__ import annotations

import hashlib

import httpx

from . import access, claims, market, search as search_mod, synthesis
from .config import settings

#: What the plan asks for that this build does not produce. Named on the
#: result so a missing section is visible as missing rather than as an empty
#: one - the same rule the PDF follows on its first page.
NOT_IMPLEMENTED = [
    "conflict resolution across revisions (documents carry no revision or "
    "approval status)",
    "public market research (this machine is offline; the panel shows a "
    "labelled sample)",
    "analysis lifecycle and cancellation (there is no analyses table)",
]


def evidence_id(hit: dict) -> str:
    """Stable across re-chunking, because it is derived from what is quoted."""
    key = "|".join((
        str(hit.get("document_id") or ""),
        str(hit.get("page_start") or ""),
        str(hit.get("page_end") or ""),
        str(hit.get("section") or ""),
        str(hit.get("text") or ""),
    ))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def to_evidence(hit: dict) -> dict:
    """A retrieval hit as an evidence item.

    `exact_span` is the chunk's own text, unmodified.
    """
    return {
        "evidence_id": evidence_id(hit),
        "document_id": hit["document_id"],
        "filename": hit["filename"],
        "page_start": hit["page_start"],
        "page_end": hit["page_end"],
        "section": hit.get("section"),
        "exact_span": hit.get("text") or "",
        "text_source": hit.get("text_source") or "extracted",
        "ocr_min_conf": hit.get("ocr_min_conf"),
        "ocr_alphabet_violations": hit.get("ocr_alphabet_violations") or 0,
        "relevance_score": hit.get("rerank_score"),
        # WHICH SCALE, not just the number. A rerank score and an RRF score are
        # not comparable, and a bare figure would invite the comparison this
        # system forbids. None when nothing scored it - never 0.0, which sits
        # above the -3.0 floor and would read as credible.
        "relevance_score_type": "rerank" if hit.get("rerank_score") is not None else None,
    }


def gather(question: str, scope: access.AccessScope, *, limit: int = 8,
           document_id: str | None = None) -> tuple[list[dict], dict]:
    """Retrieve, and return evidence plus the raw search result.

    The raw result is kept because the coverage report and the per-document
    rows are built from the census and the eviction record, not from the hits -
    a document that contributed candidates and lost them all is invisible in
    the hits and visible in the census.
    """
    result = search_mod.search(
        question, limit=limit, document_id=document_id,
        allowed_document_ids=scope.allowed_document_ids,
    )
    return [to_evidence(h) for h in result["hits"]], result


# ------------------------------------------------------------------- the model


def ollama_generate(system: str, prompt: str) -> synthesis.Generation:
    """The `Generate` protocol, backed by the local model.

    Injected rather than imported by the engines, which is what let them be
    tested without a model and what lets a caller here swap in a stub.
    """
    body = {
        "model": settings.answer_model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_output_tokens,
            "num_ctx": settings.num_ctx,
            "num_thread": settings.num_thread,
            "num_batch": settings.num_batch,
        },
        "keep_alive": "30m",
    }
    with httpx.Client(timeout=180.0) as client:
        response = client.post(f"{settings.ollama_url}/api/generate", json=body)
        response.raise_for_status()
        return synthesis.Generation.from_ollama(response.json())


class ModelUnavailable(Exception):
    """The local model could not be reached. Not a crash, and not an answer."""


def _generate_or_refuse(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except httpx.HTTPError as exc:
        raise ModelUnavailable(type(exc).__name__) from exc


# ------------------------------------------------------------------ stage 3


def summary(question: str, scope: access.AccessScope, *, limit: int = 8,
            generate=None) -> dict:
    """Generated prose over the retrieved evidence, every sentence cited."""
    evidence, _ = gather(question, scope, limit=limit)
    result = _generate_or_refuse(
        synthesis.summarise, question, evidence, generate or ollama_generate)
    return {
        "question": question,
        "evidence_ledger": evidence,
        **synthesis.summary_to_api(result),
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }


# ------------------------------------------------------------------ stage 6


def gaps(question: str, scope: access.AccessScope, *, limit: int = 8,
         baseline_document_id: str | None = None) -> dict:
    """Mechanical claim comparison. No model call, and no baseline invented.

    THE BASELINE MUST COME FROM THE USER. Choosing one here - the oldest
    document, the one with "standard" in its name - would be the system
    deciding which document is authoritative, which is an engineering
    judgement it has no basis for. With no baseline the applicability is
    `not_applicable` and the items are still returned, so the reader sees the
    comparison without being told which side is right.
    """
    evidence, _ = gather(question, scope, limit=limit)
    rows = claims.extract_claims(evidence)
    clusters = claims.cluster(rows, claims.question_terms(question))
    applicability = "applicable" if baseline_document_id else "not_applicable"
    baseline = None
    if baseline_document_id:
        baseline = {
            "kind": "document",
            "document_id": baseline_document_id,
            "section": None,
            "text": None,
        }
    return {
        "question": question,
        "evidence_ledger": evidence,
        "claim_clusters": claims.to_api(clusters),
        "gaps": {
            "applicability": applicability,
            "baseline": baseline,
            # Items are produced from the clusters, not invented: a facet with
            # no baseline to compare against is `insufficient_evidence`, never
            # `met`.
            "items": _gap_items(
                clusters,
                baseline_document_id,
                # Claim carries filename and exact_span, not document_id - it
                # is a claim about a sentence, not about a row in a table. The
                # mapping back to a document lives here, where the evidence is.
                {e["evidence_id"]: e["document_id"] for e in evidence},
            ),
        },
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }


def _gap_items(clusters, baseline_document_id: str | None,
               document_of: dict[str, str]) -> list[dict]:
    items: list[dict] = []
    for c in clusters:
        rows = list(c.rows)
        baseline_row = next(
            (r for r in rows
             if document_of.get(r.evidence_id) == baseline_document_id), None
        ) if baseline_document_id else None
        others = [r for r in rows if r is not baseline_row]
        if baseline_row is None:
            status = "insufficient_evidence"
        elif c.label == "possible_conflict":
            status = "conflict"
        elif c.label == "agreement":
            status = "met"
        else:
            status = "possible_gap"
        items.append({
            "facet": c.facet or "(unnamed)",
            "status": status,
            "baseline_citation_id": baseline_row.evidence_id if baseline_row else None,
            "baseline_span": baseline_row.exact_span if baseline_row else "",
            "project_citation_ids": [r.evidence_id for r in others],
            "note": c.note,
        })
    return items


# ------------------------------------------------------------------ stage 4


def recommendation(question: str, scope: access.AccessScope, *, limit: int = 8,
                   baseline_document_id: str | None = None,
                   generate=None) -> dict:
    """One advisory recommendation, with its confidence derived from checks.

    `high` is structurally unreachable - the same rule that forbids
    `coverage.complete === true`. Confidence comes from checks that FIRED,
    each named, so a reader can see why it is what it is rather than being
    handed a number.
    """
    evidence, raw = gather(question, scope, limit=limit)
    gap = gaps(question, scope, limit=limit,
               baseline_document_id=baseline_document_id)
    summarised = _generate_or_refuse(
        synthesis.summarise, question, evidence, generate or ollama_generate)

    checks = synthesis.confidence_checks(
        gaps_applicability=gap["gaps"]["applicability"],
        document_statuses=[],
        cluster_labels=[c["label"] for c in gap["claim_clusters"]],
        evidence_text_sources=[e["text_source"] for e in evidence],
        # This build computes no coverage object for an analysis, and a
        # missing check must not read as a passing one.
        coverage_complete=None,
        summary_truncated=summarised.truncated,
        evidence_was_removed=bool(summarised.evidence_removed),
    )
    rec = _generate_or_refuse(
        synthesis.recommend, question, evidence, generate or ollama_generate,
        checks=checks, basis="documents_only")
    return {
        "question": question,
        "evidence_ledger": evidence,
        "recommendation": synthesis.recommendation_to_api(rec),
        "public_market_findings": market.findings()["findings"],
        "not_implemented_sections": list(NOT_IMPLEMENTED),
    }
