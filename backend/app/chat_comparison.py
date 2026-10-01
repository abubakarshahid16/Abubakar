"""Chat-side comparisons: "compare X and Y" retrieves for EACH named side
separately (plan requirement C3, docs/chat-requirements-b6c-b9.md).

NOT `app/comparison.py` - that engine judges a CONTRACTOR SUBMITTAL against a
standard's requirements (Phase 5B, the review pipeline: numeric limits,
exceptions, compliance verdicts). This is a chat Q&A feature comparing what
two or more STANDARDS or other documents SAY, with no requirement pairing, no
numeric verdict and no compliance status - a different question about
different documents, answered by a different file.

THE BUG THIS CLOSES (evidence recorded 2026-10-01): "what do the welding
standards say about post weld heat treatment, and when relative to
hydrotest" retrieved ONE shared top-k across every named standard. SAES-W-010
clause 13.12 lost the ranking to the other standard's passages and was never
shown; ASME Section VIII's own passage on the same point (p.211) lost it too,
and the model - having no ASME evidence in front of it - was free to WORD
that gap however it liked, including "does not mention", a sentence
indistinguishable from a genuine targeted search that came back empty. It
was not a targeted search: it was a search that never ran for that side.

THE FIX. Two changes:
1. RETRIEVE EACH NAMED SIDE ON ITS OWN TOP-K BUDGET (`compare`, below) - one
   standard's passages can no longer crowd another's out of the ranking.
2. AN ABSENCE IS A SENTENCE THIS FILE WRITES, NEVER THE MODEL'S OWN WORDS FOR
   ONE (`_NOT_FOUND`). Plan C3: "never say a standard 'does not mention'
   something unless the targeted search on that side found nothing; say 'not
   found in the pages read' instead." The only evidence this file accepts
   that a side's targeted search found nothing is `answer.answer` itself
   reporting `insufficient_evidence` (or handing back no passages) for a
   retrieval scoped to that side alone - never a sentence the model chose to
   write.

Sides are found by REUSING `understanding.named_documents` - the same
designation matching Task 0 built on for "is this standard indexed" - never a
second matcher.
"""

from __future__ import annotations

import re

from . import answer as answer_mod
from . import chat_presentation
from . import understanding as understanding_mod
from .citations import _CITATION

#: A CHAT COMPARISON, not a request for a submittal review, a definition or a
#: general "what's the difference". Kept small and literal on purpose
#: (docs/chat-requirements-b6c-b9.md section 4: no growing pattern list) -
#: the handful of words a reader actually types to ask this.
_TRIGGER = re.compile(r"\bcompar(?:e|ison|ing)\b|\bversus\b|\bvs\.?\b(?!\w)", re.I)


def is_comparison_question(question: str) -> bool:
    """Does this question ASK for a comparison, in the reader's own words?"""
    return bool(_TRIGGER.search(question or ""))


def named_sides(
    question: str, documents: dict[str, str]
) -> list[tuple[str, frozenset[str]]] | None:
    """The comparison's own sides: one per DISTINCT designation the question
    names, each carrying every permitted document id filed under it (two
    editions or copies of the same standard are one side, not two).

    None when fewer than two distinct designations are named: a comparison
    with nothing named to split retrieval by is not this feature's job, and
    the question reaches the ordinary pipeline unchanged, scoped to the
    caller's whole permission as it always was.
    """
    named = understanding_mod.named_documents(question, documents)
    if len(named) < 2:
        return None
    return [(designation, frozenset(ids)) for designation, ids in sorted(named.items())]


#: A designation the reader TYPED in capitals with a digit in it ("SAES-W-010",
#: "B31.3", "API-510"). Deliberately strict: "post-weld", "10-inch" and
#: "H2S-service" must never be reported as a standard missing from the library.
_TYPED_DESIGNATION = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-.][A-Z0-9]+)+\b")

_CONNECTORS = {"and", "or", "against", "from", "than", "on", "about", "regarding", "for", "in", "of", "the", "between",
               "with", "to", "a", "an", "their", "its", "these", "those"}


def _norm_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def missing_designations(question: str, matched_names: list[str]) -> list[str]:
    """Designations the question TYPED that match no readable document, in the
    order written. A compare naming a standard the library does not hold must
    say so for that side - never fall through to a search that cannot tell the
    reader one of the two standards was never there."""
    have = {_norm_name(n) for n in matched_names}
    out: list[str] = []
    for token in _TYPED_DESIGNATION.findall(question or ""):
        if not re.search(r"\d", token):
            continue
        key = _norm_name(token)
        if key in have or any(key in h or h in key for h in have):
            continue
        if key not in {_norm_name(o) for o in out}:
            out.append(token)
    return out


def matched_sides(
    question: str, documents: dict[str, str]
) -> list[tuple[str, frozenset[str]]]:
    """Every named side found in the readable documents (possibly just one)."""
    named = understanding_mod.named_documents(question, documents)
    return [(d, frozenset(ids)) for d, ids in sorted(named.items())]


def topic_of(question: str, names: list[str]) -> str | None:
    """What the comparison is ABOUT: the question with every named standard and
    the word "compare" taken out. None when nothing is left - a comparison of
    two standards on no subject has nothing to search for."""
    text = question or ""
    for name in names:
        text = re.sub(re.escape(name), " ", text, flags=re.I)
    text = _TRIGGER.sub(" ", text)
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    while words and words[0].lower().strip(",.?!:;") in _CONNECTORS:
        words.pop(0)
    while words and words[-1].lower().strip(",.?!:;") in _CONNECTORS:
        words.pop()
    topic = " ".join(words).strip(" ,.?!:;")
    return topic if re.search(r"[A-Za-z]{3,}", topic) else None


def _renumber(text: str, offset: int) -> str:
    """A side's own [S1], [S2] point at ITS passages; once every side's passages
    sit in one list, side two's [S1] must point past side one's."""
    if not offset:
        return text
    return _CITATION.sub(lambda m: f"[S{int(m.group(1)) + offset}]", text)


def _clarify(question: str, names: list[str]) -> dict:
    """A comparison with no subject asks what to compare. Nothing is searched,
    so nothing is reported as not found."""
    return {
        "question": question, "retrieval_mode": "not_searched", "reranked": False,
        "timings": {}, "candidates_considered": 0, "passages": [], "examples": [],
        "input_kind": "comparison_question", "answer_type": "guidance",
        "answer": (f"Compare {' and '.join(names)} on what? Name the topic, for example: "
                   f"\"compare {' and '.join(names)} on post weld heat treatment\"."),
        "reason": None, "seconds": 0.0,
    }


def _not_found(name: str) -> str:
    """The one sentence this file writes for a side whose OWN, targeted
    search found nothing - never a model's wording for an absence."""
    return f"{name}: not found in the pages read."


def _not_in_library(name: str) -> str:
    return f"{name}: not among the documents you can read."


def _side_answer(
    question: str, ids: frozenset[str], *, tier: str,
    allowed_document_ids: frozenset[str], progress_id: str | None,
    model: str | None, history: str,
) -> dict:
    """One side's own answer, retrieved on its own top-k budget, scoped to
    ONLY the ids this side names, intersected with what the caller may read
    (CLAUDE.md rule 5: a filter only narrows). A side the caller may read
    none of is reported exactly as an empty targeted search - never sent to
    retrieval, and never claimed to have been searched."""
    scope = allowed_document_ids & ids
    if not scope:
        return {"answer_type": "insufficient_evidence", "answer": None,
                "passages": [], "candidates_considered": 0, "reranked": False,
                "seconds": 0.0}
    return answer_mod.answer(
        question, tier=tier, document_id=None, allowed_document_ids=scope,
        progress_id=progress_id, history=history, model=model)


def compare(
    question: str,
    sides: list[tuple[str, frozenset[str]]],
    *,
    tier: str,
    allowed_document_ids: frozenset[str],
    progress_id: str | None,
    model: str | None,
    history: str,
    missing: list[str] | None = None,
) -> dict:
    """Retrieve EACH side on its own top-k budget, cite both, and never let
    an absence on one side borrow the other's evidence or the model's words.

    Every side calls the SAME `answer.answer` the rest of chat uses for a
    single document question - no parallel retrieval path, no shortcut
    around the credibility floor, the citation checks or the honesty gates
    it already applies. This function only decides how to SPLIT retrieval
    and how to WORD an absence; it answers nothing itself.
    """
    breakdown: list[dict] = []
    passages: list[dict] = []
    parts: list[str] = []
    candidates_considered = 0
    seconds = 0.0
    any_reranked = False
    all_names = [name for name, _ in sides]
    missing = list(missing or [])
    topic = topic_of(question, all_names + missing)
    if topic is None:
        return _clarify(question, all_names + missing)
    for name, ids in sides:
        # EVERY OTHER SIDE'S NAME IS STRIPPED from the question this side is
        # asked. Without this, "compare SAES-W-010 and ASME-B31-3..." reaches
        # a retrieval scoped to SAES-W-010 alone still NAMING ASME-B31-3 -
        # a designation the lexical gate can no longer find indexed once the
        # scope has narrowed to the other side, so it refuses the whole
        # question as naming an absent subject (`search.without_terms`,
        # built for exactly this: keeping a carried term out of the
        # named-subject check while leaving the rest of the question as
        # typed).
        # The question each side is asked is built, never carved out of the
        # reader's: "What does <this standard> say about <the topic>?". Carving
        # left "compare SAES-W-019" for the model, which then answered that no
        # second standard had been named.
        side_question = f"What does {name} say about {topic}?"
        side = _side_answer(
            side_question, ids, tier=tier, allowed_document_ids=allowed_document_ids,
            progress_id=progress_id, model=model, history=history)
        # WHAT THIS SIDE'S OWN ANSWER ACTUALLY USED - never `side["passages"]`
        # directly: an extract answer carries its used passage(s) in
        # `passage`/`answer_passages`, not `passages` (that key, when
        # present, is the wider candidate list the gate considered and
        # rejected). `chat_presentation.used_passages` is the one place that
        # already knows the difference.
        side_passages = chat_presentation.used_passages(side)
        candidates_considered += side.get("candidates_considered") or 0
        seconds += side.get("seconds") or 0.0
        any_reranked = any_reranked or bool(side.get("reranked"))
        # Was a search REALLY run for this side? Only when the caller may read
        # at least one of its documents (`_side_answer` sends nothing to
        # retrieval otherwise). A side never searched is never reported as a
        # search that found nothing.
        searched = bool(allowed_document_ids & ids)
        entry = {
            "name": name, "document_ids": sorted(ids),
            "answer_type": side.get("answer_type"), "searched": searched,
            "text": None, "source_start": len(passages), "source_count": 0,
        }
        breakdown.append(entry)
        if not searched:
            entry["answer_type"] = "not_in_library"
            entry["text"] = _not_in_library(name)
            parts.append(_not_in_library(name))
        elif side.get("answer_type") == "insufficient_evidence" or not side_passages:
            # THE ONLY CONDITION PLAN C3 ALLOWS AN ABSENCE TO BE STATED
            # UNDER: this side's own targeted search found nothing. Its
            # rejected candidates (if any) are not carried into `passages`:
            # a chip built from them would present a side reported absent as
            # though it had evidence backing something.
            entry["text"] = _not_found(name)
            parts.append(_not_found(name))
        else:
            text = _renumber((side.get("answer") or "").strip(), len(passages))
            passages.extend(side_passages)
            entry["source_count"] = len(side_passages)
            entry["text"] = text or _not_found(name)
            parts.append(f"{name}: {text}" if text else _not_found(name))
    for name in missing:
        # A designation typed in the question that no document the caller can
        # read carries. Written here, in code, never by a model.
        breakdown.append({"name": name, "document_ids": [], "answer_type": "not_in_library",
                          "searched": False, "text": _not_in_library(name), "source_start": len(passages),
                          "source_count": 0})
        parts.append(_not_in_library(name))

    return {
        "question": question,
        "retrieval_mode": "comparison",
        "reranked": any_reranked,
        "timings": {},
        "candidates_considered": candidates_considered,
        "answer_type": "comparison",
        "answer": "\n\n".join(parts),
        "reason": None,
        "input_kind": "comparison_question",
        "comparison": {"sides": breakdown},
        "examples": [],
        "passages": passages,
        "seconds": seconds,
    }
