"""B8: the answer-level safety gate - does the evidence ANSWER the question?

Retrieval ranks passages; it does not decide whether they answer anything.
The reranker scores topical overlap (measured: an unanswerable question's
best passage scored higher than 20 of 72 correct answers), so the reranker
score is not used here at all. Every verdict is decided by STRUCTURE the code
can check, in this order, and carries the passages it rests on:

  insufficient_evidence     the existing gates refused: a named subject absent
                            from the reader's documents, no distinguishing
                            term covered (answer.py / lexical.py)
  requires_engineer_review  the question asks for a compliance judgement -
                            chat never computes one (requirements C4, N7)
  ambiguous_evidence        the answer's own text is in several documents, or
                            the document the question names matches several
                            (B6C) - which document is not the evidence's call
  requires_another_document the passage that matches the question only points
                            to another standard ("shall be in accordance with
                            X") and X is not among the reader's documents
  conflicting_evidence      the two leading passages come from different
                            documents, both are about the question, and they
                            state different values in the same unit
  supported                 none of the above. Never "high" confidence
                            (CLAUDE.md rule 4): supported means the evidence
                            passed every check, not that it is certainly right.

Deterministic; no model. A model answer (Tier 2) is judged on the same
evidence, after its own citation validation.
"""
from __future__ import annotations

import re

import json
import logging

from . import lexical
from . import understanding as understanding_mod
from .config import settings
from .datasheets import referenced_standards
from .db import connect
from .model_evidence import quote_verified

log = logging.getLogger(__name__)

SUPPORTED = "supported"
INSUFFICIENT = "insufficient_evidence"
CONFLICTING = "conflicting_evidence"
AMBIGUOUS = "ambiguous_evidence"
ANOTHER_DOCUMENT = "requires_another_document"
ENGINEER_REVIEW = "requires_engineer_review"
VERDICTS = (SUPPORTED, INSUFFICIENT, CONFLICTING, AMBIGUOUS, ANOTHER_DOCUMENT, ENGINEER_REVIEW)

#: A question asking for a compliance JUDGEMENT, not for what a document says.
_JUDGEMENT = re.compile(
    r"\b(?:is|are|does|do|will|would)\b[^?]*\b(?:compliant|comply|complies|conform(?:s|ing)?|"
    r"acceptable|accepted|approved?|allowed|permitted|ok(?:ay)?|meets?|satisf(?:y|ies))\b"
    r"|\bcompliance\s+(?:status|verdict|decision)\b|\bpass\s+or\s+fail\b|\bshould\s+(?:we|i)\s+approve\b",
    re.I)
#: A clause that DEFERS to another document rather than stating a value.
_DEFERS = re.compile(
    r"\b(?:in\s+accordance\s+with|as\s+per|according\s+to|shall\s+(?:comply|conform)\s+(?:with|to)|"
    r"specified\s+in|as\s+defined\s+in|refer\s+to)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.;:])\s+")
#: A number and its unit, for the conflict check: "3.5 bar", "38 mm", "85 dB".
_QUANTITY = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|°\s?[CF]|[A-Za-z][A-Za-z/²³]{0,5})\b")
_NOT_UNITS = {"and", "or", "to", "of", "the", "in", "for", "with", "per", "at", "is", "be", "shall", "mm2"}


def _evidence(passages: list[dict]) -> list[dict]:
    return [{"document_id": p.get("document_id"), "page_start": p.get("page_start"),
             "page_end": p.get("page_end"), "section": p.get("section")} for p in passages]


def _shown(result: dict) -> list[dict]:
    seen, out = set(), []
    for p in [result.get("passage"), *(result.get("answer_passages") or []),
              *(result.get("supporting") or []), *(result.get("passages") or [])]:
        if p and p.get("chunk_id") not in seen:
            seen.add(p.get("chunk_id"))
            out.append(p)
    return out


def _terms(question: str, allowed: frozenset[str]) -> list[str]:
    return [t.lower() for t in lexical.distinctive_terms(question, None, allowed_document_ids=allowed)]


def _best_sentence(text: str, terms: list[str]) -> str:
    """The passage sentence that carries most of the question's terms."""
    sentences = [s for s in _SENTENCE.split(text or "") if s.strip()] or [text or ""]
    return max(sentences, key=lambda s: sum(1 for t in terms if t in s.lower()))


def _quantities(sentence: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for value, unit in _QUANTITY.findall(sentence):
        u = unit.replace(" ", "").lower()
        if u in _NOT_UNITS:
            continue
        found.setdefault(u, set()).add(value.rstrip("0").rstrip(".") if "." in value else value)
    return found


def _held(allowed: frozenset[str]) -> set[str]:
    """Normalised designations of the documents the reader can open."""
    names = understanding_mod.document_names(allowed)
    return {re.sub(r"[^A-Z0-9]", "", d.upper())
            for d in (understanding_mod.designation(f) for f in names.values()) if d}


def _dropped_copies(result: dict, top: dict, allowed: frozenset[str]) -> list[dict]:
    """Chunks search dropped as near-copies of the leading passage, from OTHER
    permitted documents, read back with their stored text and location."""
    ids = [d["chunk_id"] for d in result.get("near_duplicates") or []
           if d.get("duplicate_of") == top.get("chunk_id") and d.get("chunk_id")
           and d.get("document_id") != top.get("document_id") and d.get("document_id") in allowed]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [dict(r) for r in connect().execute(
        f"SELECT id AS chunk_id, document_id, page_start, page_end, section, text"
        f" FROM chunks WHERE id IN ({marks})", ids)]


def assess(question: str, result: dict, *, allowed_document_ids: frozenset[str]) -> dict:
    """The verdict on one answer, with its reasons and the evidence it used."""
    shown = _shown(result)
    def verdict(kind: str, reason: str, used: list[dict]) -> dict:
        return {"verdict": kind, "reason": reason, "evidence": _evidence(used)}

    if result.get("answer_type") == "insufficient_evidence" or not shown:
        return verdict(INSUFFICIENT, result.get("reason") or "no passage answers the question", [])
    if _JUDGEMENT.search(question):
        return verdict(ENGINEER_REVIEW, "the question asks for a compliance judgement; the "
                       "documents are shown, the judgement is an engineer's", shown[:1])
    terms = _terms(question, allowed_document_ids)
    top = shown[0]
    sentence = _best_sentence(top.get("text") or "", terms)

    # CONFLICT FIRST - it outranks ambiguity. Search drops a chunk that is a
    # near-copy of a better one, and "design pressure shall be 3.5 bar" /
    # "... 5 bar" in two standards ARE near-copies: one token differs. So the
    # dropped copies of the leading passage are read back and compared too;
    # otherwise a real disagreement between two standards would vanish.
    others = [p for p in shown[1:] if p.get("document_id") != top.get("document_id")
              and lexical.assess(question, p.get("text") or "", None,
                                 allowed_document_ids=allowed_document_ids)["ok"]]
    others += _dropped_copies(result, top, allowed_document_ids)
    a = _quantities(sentence)
    for other in others:
        b = _quantities(_best_sentence(other.get("text") or "", terms))
        clash = sorted(u for u in a.keys() & b.keys() if a[u].isdisjoint(b[u]))
        if clash:
            return verdict(CONFLICTING, "two documents state different values ("
                           + ", ".join(clash) + ") for what was asked", [top, other])

    understood = result.get("understanding") or {}
    if result.get("scope_ambiguity") or understood.get("ambiguous_documents"):
        return verdict(AMBIGUOUS, "the same text or name is in more than one document; "
                       "name the document to answer from one", shown[:1])
    # A clause that STATES a value is not a deferral even when it also cites a
    # standard ("a 1.5 m net, per <standard>"), and a standard the question
    # itself names is the reader's subject, not a missing document - measured:
    # without both, 4 of 4 flags on correctly answered real questions were
    # false alarms.
    if _DEFERS.search(sentence) and not _quantities(sentence):
        held = _held(allowed_document_ids)
        asked = re.sub(r"[^A-Z0-9]", "", question.upper())
        missing = [ref for ref in referenced_standards(sentence)
                   if re.sub(r"[^A-Z0-9]", "", ref.upper()) not in held
                   and re.sub(r"[^A-Z0-9]", "", ref.upper()) not in asked]
        if missing:
            return verdict(ANOTHER_DOCUMENT, "the matching clause defers to "
                           + ", ".join(missing) + ", which is not among your documents", [top])

    return verdict(SUPPORTED, "the leading passage passed every evidence check", [top])


# ------------------------------------------------------------ the model judge

JUDGE_STEP = "b8-answer-judge"
JUDGE_PROMPT_VERSION = "b8-judge-v1"
JUDGE_PASSAGES = 3
JUDGE_SCHEMA = {
    "type": "object", "required": ["answers", "passage", "quote"],
    "properties": {"answers": {"type": "boolean"}, "passage": {"type": "integer"},
                   "quote": {"type": "string"}, "reason": {"type": "string"}},
}
JUDGE_SYSTEM = (
    "You check whether engineering document passages ANSWER a question. "
    "Reply with JSON only: {\"answers\": true|false, \"passage\": n, \"quote\": \"...\", "
    "\"reason\": \"...\"}. answers=true only if one passage states the answer itself; "
    "then passage is its number and quote is the exact words from that passage that "
    "answer - copied character for character. A passage on the same topic that does "
    "not state the answer is answers=false. Never use knowledge outside the passages.")


def _judge_packet(question: str, passages: list[dict]):
    from .reasoning_provider import Packet
    body = "\n\n".join(f"[{i}] {(p.get('section') or '').strip()}\n{(p.get('text') or '').strip()}"
                        for i, p in enumerate(passages, start=1))
    return Packet(prompt=f"Question: {question}\n\nPassages:\n{body}", num_ctx=4096,
                  num_predict=300, json_schema=JUDGE_SCHEMA, system=JUDGE_SYSTEM,
                  step=JUDGE_STEP, prompt_version=JUDGE_PROMPT_VERSION)


def judge(question: str, result: dict, current: dict, provider) -> dict:
    """The model's reading of the evidence, ACCEPTED ONLY WHEN CODE CAN CHECK IT.

    Applies only to a structural `supported`; it can never turn a refusal or a
    flag into an answer. A "no" downgrades to insufficient_evidence (the safe
    direction). A "yes" is accepted only with a quote that is verbatim in the
    passage it names - then the verdict points at THAT passage, which may be
    lower than the top one. Anything else (bad JSON, schema errors, an unknown
    passage, an unverifiable quote, a refusal) leaves the structural verdict
    as it was and says why the model's output was not used.
    """
    if current["verdict"] != SUPPORTED or provider is None:
        return current
    from .reasoning_provider import ProviderRefused, schema_errors
    passages = _shown(result)[:JUDGE_PASSAGES]
    try:
        response = provider.reason(_judge_packet(question, passages))
    except ProviderRefused as exc:
        return {**current, "judge": {"accepted": False, "why": f"model refused: {exc}"}}
    except Exception as exc:  # noqa: BLE001 - a judge failure never breaks an answer
        log.warning("answer judge failed: %s", type(exc).__name__)
        return {**current, "judge": {"accepted": False, "why": "model unavailable"}}
    errors = schema_errors(response.text, JUDGE_SCHEMA)
    if errors:
        return {**current, "judge": {"accepted": False, "why": "output rejected: " + "; ".join(errors)}}
    body = response.text.strip().strip("`")
    body = body[body.find("{"):]
    out = json.loads(body)
    if not out["answers"]:
        return {"verdict": INSUFFICIENT,
                "reason": "the passages are on the topic but none states the answer (model judgement, "
                          + (out.get("reason") or "no reason given") + ")",
                "evidence": [], "judge": {"accepted": True, "answers": False}}
    n = out["passage"]
    if not (1 <= n <= len(passages)) or not quote_verified(out["quote"], passages[n - 1].get("text")):
        return {**current, "judge": {"accepted": False,
                                     "why": "output rejected: the quote is not verbatim in the passage it names"}}
    chosen = passages[n - 1]
    return {"verdict": SUPPORTED,
            "reason": "the answer is stated in the cited passage" + ("" if n == 1 else f" (passage {n}, not the top one)"),
            "evidence": _evidence([chosen]),
            "judge": {"accepted": True, "answers": True, "passage": n, "quote": out["quote"]}}


def judge_provider():
    """The configured reasoning provider when the judge is on, else None."""
    if not settings.answer_judge_enabled:
        return None
    from .reasoning_provider import get_provider
    return get_provider("labelling", step=JUDGE_STEP)
