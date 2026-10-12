"""Engineering synonyms: the words people type -> the words documents print.

WHY (docs/limitations.md, "paraphrase / vocabulary"). Retrieval matches
words, and a question that shares none of the document's words has nothing to
match. Measured: "how humid is too humid to paint" cited the wrong page
because the standard says *relative humidity*, never *humid*; "how much salt
is allowed on the surface" cited the wrong clause because it says *chlorides*
and *NaCl*, never *salt*. The limitations entry called a curated glossary the
fix and left it "a decision for later"; this is that glossary.

WHAT IT DOES AND DOES NOT DO. A typed word that has an entry here is OR-ed,
on the KEYWORD side only, with the document phrasings listed for it - exactly
how an acronym is OR-ed with the expansion the corpus defines. It never
removes or replaces the typed word, never touches the dense side, and never
touches the reranker or the refusal floor: the reranker still scores the
reader's own question. So an entry can widen which passages are CONSIDERED;
it cannot make an absent answer look present. Every expansion used is
reported in the search result (`synonyms_searched`), as spelling corrections
are - the reader is told what was actually searched.

HOW TO ADD AN ENTRY. Lay word (lowercase, as typed) -> the phrases a standard
prints for it. Direction matters: lay -> technical only, never the reverse
(adding "paint" to a question about "coating" would widen a precise question).
Each entry names why it is here. An engineer reviews additions; nothing is
generated.
"""
from __future__ import annotations

import re

#: typed word -> (document phrasings, why). Multi-word phrasings are searched as
#: phrases ("relative humidity"), exactly as keyword.search quotes them.
GLOSSARY: dict[str, tuple[tuple[str, ...], str]] = {
    "humid": (("relative humidity",), "measured miss, docs/limitations.md"),
    "humidity": (("relative humidity",), "a bare 'humidity' question is about RH"),
    "salt": (("chlorides", "chloride", "soluble salts", "nacl"),
             "measured miss, docs/limitations.md"),
    "salts": (("chlorides", "chloride", "soluble salts", "nacl"),
              "plural of the measured miss"),
    "salty": (("chlorides", "chloride", "soluble salts", "nacl"),
              "adjective of the measured miss"),
    "rust": (("corrosion", "corroded"), "specifications say corrosion"),
    "rusty": (("corrosion", "corroded"), "specifications say corrosion"),
    "paint": (("coating", "coatings"), "specifications say coating"),
    "painting": (("coating", "coatings"), "specifications say coating"),
    "painted": (("coating", "coated"), "specifications say coated"),
}


#: A lay word that is part of a DIFFERENT technical term when followed by one
#: of these: "salt spray" is a corrosion test, not a chloride limit, so a
#: question about salt spray must not be widened to chlorides.
NOT_BEFORE: dict[str, frozenset[str]] = {
    "salt": frozenset({"spray", "fog", "mist", "water"}),
    "salts": frozenset({"spray", "fog", "mist", "water"}),
}

_WORD = re.compile(r"[A-Za-z]+")


def expansions(question: str) -> dict[str, tuple[str, ...]]:
    """{typed word (lowercase): document phrasings} for this question's words
    that have an entry - skipping a word that begins a different term."""
    words = [m.group(0).lower() for m in _WORD.finditer(question)]
    out: dict[str, tuple[str, ...]] = {}
    for i, word in enumerate(words):
        entry = GLOSSARY.get(word)
        if not entry or word in out:
            continue
        following = words[i + 1] if i + 1 < len(words) else ""
        if following in NOT_BEFORE.get(word, frozenset()):
            continue
        out[word] = entry[0]
    return out


def rewrite(question: str) -> str | None:
    """The question in the document's own words - each expanded lay word
    replaced by its first phrasing - or None when nothing was expanded. For the
    reranker, which scores meaning against wording: measured on synthetic
    pages, "how humid is too humid to paint" scored -3.81 against the relative
    humidity clause, and its rewrite +3.66; an unanswerable "what paint colour
    is required for the handrails" stayed at -9.30 either way."""
    found = expansions(question)
    if not found:
        return None
    words = [m.group(0).lower() for m in _WORD.finditer(question)]

    def swap(m: re.Match) -> str:
        word = m.group(0).lower()
        idx = swap.at
        swap.at += 1
        following = words[idx + 1] if idx + 1 < len(words) else ""
        if word in found and following not in NOT_BEFORE.get(word, frozenset()):
            return found[word][0]
        return m.group(0)

    swap.at = 0
    return _WORD.sub(swap, question)
