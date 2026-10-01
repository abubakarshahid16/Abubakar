"""A question that names a FAMILY of standards in general words ("what do the
welding standards say about post weld heat treatment") is searched per
standard, never in one shared pass (GitHub issue #373).

THE BUG. Such a question went through ONE retrieval over everything the caller
may read, so one standard's passages crowded another's out of the shared top-k
and a standard that was never searched on its own could be reported silent on
a topic it does cover. `chat_comparison` already fixed that for standards the
reader NAMES; this file finds the standards the reader only DESCRIBED, then
hands them to `chat_comparison.compare` unchanged.

HOW A FAMILY IS RESOLVED (owner rule 2026-09-28: no hand-built taxonomy, no
keyword tables):
  - the descriptor is the reader's own words in front of "standards" - nothing
    here maps "welding" to anything;
  - a standard is a CANDIDATE when its AI-read scope record (what it covers and
    what it is done to; never its exclusions) carries every descriptor word, or
    when the app's own hybrid search, restricted to the caller's readable
    COMPANY_STANDARD documents, returns a passage that carries every one;
  - ranked by code (scope-record hits first, then search hits), capped at
    MAX_STANDARDS. No model call decides membership.

WHAT THE ANSWER SAYS. Which standards were searched, and that membership is a
guess until a person confirms it. A standard is never reported as silent
unless it was searched on its own (that sentence is `chat_comparison`'s).

CONSERVATIVE BY DESIGN. When unsure this file returns None and the question
reaches the ordinary pipeline unchanged.
"""

from __future__ import annotations

import re

from . import applicability, chat_comparison, search, understanding as understanding_mod
from .db import connect

#: The most standards searched for one family question.
MAX_STANDARDS = 8
#: Passages the descriptor search looks at when ranking candidates.
SEARCH_LIMIT = 40

#: Plural nouns that make a question about a FAMILY. "codes" is left out on
#: purpose: it is too often a different sort of word.
_FAMILY_NOUN = r"(?:standards|specifications|specs)"

#: Grammar words that end the descriptor walking backwards from the noun.
_BREAK = {
    "the", "a", "an", "our", "your", "their", "its", "my", "all", "these", "those",
    "do", "does", "did", "what", "which", "how", "are", "is", "there", "of", "in",
    "on", "at", "for", "to", "and", "or", "with", "from", "by", "about", "say",
    "says", "any", "every", "each", "both", "other", "have", "has", "we", "you",
    "tell", "me", "show", "list", "give", "that", "this", "where", "when", "can",
    "should", "must", "shall", "per", "under", "across", "between", "into",
}
#: Words that describe nothing: "the applicable standards", "our company
#: standards". A descriptor made only of these names no family.
_GENERIC = {
    "company", "client", "applicable", "relevant", "project", "current", "existing",
    "engineering", "technical", "following", "listed", "specific", "various",
    "different", "same", "new", "old", "international", "national", "industry",
    "internal", "external", "approved", "latest", "available", "uploaded", "own",
    "standard", "related", "associated", "general", "ours",
}

_AFTER_NOUN = re.compile(
    rf"\b{_FAMILY_NOUN}\b\s+(?P<mid>(?:[A-Za-z']+\s+){{0,2}}?)"
    r"(?P<prep>about|on|regarding|concerning|for)\s+(?P<topic>.+)$", re.I)
_BEFORE_NOUN = re.compile(rf"\b{_FAMILY_NOUN}\b", re.I)
#: A designation typed with a digit in it ("SAES-W-010", "B31.3"): the reader
#: named a standard, so this is not a family question.
_TYPED = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-.][A-Z0-9]+)+\b")


def stem(word: str) -> str:
    """A light, language-only normalisation so "welding", "welds" and "weld"
    meet. Not a vocabulary: it only trims a common ending."""
    w = re.sub(r"[^a-z0-9]", "", (word or "").lower())
    # Ending order matters: strip the verb/plural ending first, then a lone
    # final "e", so "valve", "valves", "pipe", "piping" and "pipes" each meet.
    for suffix, repl in (("ings", ""), ("ing", ""), ("ies", "y"), ("ed", "")):
        if w.endswith(suffix) and len(w) - len(suffix) + len(repl) >= 3:
            w = w[: -len(suffix)] + repl
            break
    else:
        if w.endswith(("sses", "shes", "ches", "xes", "zes", "ses")) and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def _stems(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[A-Za-z0-9]+", text or "") if len(w) >= 3}


def detect(question: str) -> tuple[str, str] | None:
    """(descriptor, topic) for a question that names a family of standards in
    general words and asks about a topic; None otherwise (including whenever
    unsure)."""
    text = (question or "").strip()
    if not text or _TYPED.search(text):
        return None
    nouns = list(_BEFORE_NOUN.finditer(text))
    if len(nouns) != 1:
        return None
    noun = nouns[0]
    after = _AFTER_NOUN.search(text)
    if after is None:
        return None
    # "welding standards for pumps": no verb between, so "for pumps" describes
    # the standards rather than naming what to look up in them.
    if after.group("prep").lower() == "for" and not after.group("mid").strip():
        return None
    topic = after.group("topic").strip(" ,.?!:;")
    if not re.search(r"[A-Za-z]{3,}", topic):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z-]*", text[: noun.start()])
    descriptor: list[str] = []
    for w in reversed(words):
        if w.lower() in _BREAK:
            break
        descriptor.insert(0, w.lower())
        if len(descriptor) == 3:
            break
    descriptor = [w for w in descriptor if w not in _GENERIC and len(w) >= 3]
    if not descriptor:
        return None
    return " ".join(descriptor), topic


def _readable_standards(allowed_document_ids: frozenset[str]) -> dict[str, str]:
    """{document_id: filename} of the COMPANY_STANDARD documents the caller may
    read. An intersection with `allowed_document_ids`; never wider."""
    if not allowed_document_ids:
        return {}
    marks = ",".join("?" * len(allowed_document_ids))
    rows = connect().execute(
        f"SELECT d.id, d.filename FROM documents d"
        f" JOIN document_classification c ON c.document_id = d.id"
        f" WHERE c.document_role = 'COMPANY_STANDARD' AND d.id IN ({marks})",
        sorted(allowed_document_ids))
    return {r[0]: r[1] for r in rows}


def _scope_text(document_id: str) -> str:
    """What the AI-read scope record says the standard COVERS: equipment,
    activities and construction wording. Exclusions are left out: a standard
    that excludes welding is not a welding standard."""
    found = applicability.scope_record(document_id)
    if found is None:
        return ""
    record = found[0] or {}
    parts: list[str] = []
    for key in ("covered_equipment", "covered_activities", "new_construction"):
        for item in record.get(key) or []:
            if isinstance(item, dict):
                parts.extend(str(item.get(f) or "") for f in ("term", "activity", "quote"))
    return " ".join(parts)


def _label(document_id: str, filename: str) -> str:
    return understanding_mod.designation(filename) or filename.rsplit(".", 1)[0]


def resolve(descriptor: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """Rank the readable standards for the family phrase.

    Returns {"candidates": [(name, frozenset(ids))] ranked and capped,
    "judged": how many standards qualified before the cap}. Two editions or
    copies filed under one designation are one standard."""
    standards = _readable_standards(allowed_document_ids)
    want = _stems(descriptor)
    if not standards or not want:
        return {"candidates": [], "judged": 0}

    scope_hits = {d: len(want & _stems(_scope_text(d))) for d in standards}
    scope_ok = {d for d, n in scope_hits.items() if n == len(want)}

    search_hits: dict[str, int] = {}
    result = search.search(descriptor, limit=SEARCH_LIMIT, rerank=False,
                           allowed_document_ids=frozenset(standards))
    for hit in result.get("hits") or []:
        doc = hit.get("document_id")
        if doc in standards and want <= _stems(
                f"{hit.get('text') or ''} {hit.get('section') or ''}"):
            search_hits[doc] = search_hits.get(doc, 0) + 1

    groups: dict[str, dict] = {}
    for doc_id, filename in standards.items():
        if doc_id not in scope_ok and doc_id not in search_hits:
            continue
        g = groups.setdefault(_label(doc_id, filename), {"ids": set(), "scope": 0, "search": 0})
        g["ids"].add(doc_id)
        g["scope"] += 1 if doc_id in scope_ok else 0
        g["search"] += search_hits.get(doc_id, 0)
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["scope"], -kv[1]["search"], kv[0].lower()))
    # The cap keeps the best ranked; the ones kept are then listed by name so
    # the answer reads the same way every time.
    kept = sorted(ranked[:MAX_STANDARDS], key=lambda kv: kv[0].lower())
    return {
        "candidates": [(name, frozenset(g["ids"])) for name, g in kept],
        "judged": len(ranked),
    }


def lead_sentence(descriptor: str, names: list[str], judged: int) -> str:
    """The sentence written in code that says which standards were searched
    and that membership is a guess."""
    text = (f"Searched {len(names)} standards judged to be {descriptor} standards: "
            f"{', '.join(names)}.")
    if judged > len(names):
        text += (f" {judged} standards matched; only the {len(names)} best ranked "
                 "were searched, the rest were not.")
    return text + (" Which standards belong to this family is a guess made by this app "
                   "until a person confirms it. Each was searched on its own.")


def not_enough_notice(descriptor: str, names: list[str]) -> str:
    found = (f"only {names[0]}" if len(names) == 1 else "none") if len(names) < 2 else ""
    return (f"Looked for standards judged to be {descriptor} standards and found {found}. "
            "That is too few to search one by one, so this answer was not searched standard "
            "by standard, and a standard that is not cited here was not searched on its own.")


def run(
    question: str, documents: dict[str, str], *, tier: str,
    allowed_document_ids: frozenset[str], progress_id: str | None,
    model: str | None, history: str,
) -> tuple[dict | None, str | None]:
    """(result, notice). `result` is a per-standard comparison answer when the
    question is a family question that resolved to at least two standards;
    `notice` is the plain sentence to show when it was a family question that
    resolved to fewer than two (the ordinary path then answers). Both None when
    the question is not a family question, or names a standard itself (the
    existing comparison/ordinary path owns that)."""
    found = detect(question)
    if found is None or chat_comparison.matched_sides(question, documents):
        return None, None
    descriptor, topic = found
    resolved = resolve(descriptor, allowed_document_ids=allowed_document_ids)
    sides = resolved["candidates"]
    names = [n for n, _ in sides]
    if len(sides) < 2:
        return None, not_enough_notice(descriptor, names)
    result = chat_comparison.compare(
        question, sides, tier=tier, allowed_document_ids=allowed_document_ids,
        progress_id=progress_id, model=model, history=history, topic=topic,
        family={"label": descriptor, "searched": names, "judged": resolved["judged"],
                "membership_is_a_guess": True,
                "note": lead_sentence(descriptor, names, resolved["judged"])})
    return result, None
