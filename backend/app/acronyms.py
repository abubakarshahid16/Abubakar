"""Acronym expansions harvested from the documents themselves.

The lexical gate refuses a question naming something absent from the corpus,
which is right, and it made one thing wrong: a document that spells out
"nominal dry film thickness" without ever writing "NDFT" refused a question
asking for the NDFT. The term genuinely was not there, and the reader was
still asking a fair question.

NORSOK happens to carry a clause 3.2 Abbreviations, so relying on a glossary
clause would have looked sufficient. It is not. Aramco specifications are dense
with acronyms - SAES, SAMSS, MAWP, PWHT, NDT - and a client uploads their own
documents. One without a glossary clause would refuse half their questions.

So the map is built from the document in every form the definition occurs:

    nominal dry film thickness (NDFT)     parenthetical
    NDFT (nominal dry film thickness)     inverse parenthetical
    NDFT   nominal dry film thickness     glossary or abbreviations row

and matching is bidirectional: asking about "nominal dry film thickness" finds
chunks that only write NDFT, and asking about NDFT finds chunks that only
spell it out.

THE VALIDATOR IS THE WHOLE THING. Harvesting these patterns without one
produces mostly rubbish - measured on this corpus it gave "AB" meaning "show
that" and "BC" meaning "e interpret this by the two boundary conditions",
because the pattern captures whatever lowercase run happens to sit next to a
capitalised token. Requiring the expansion's word initials to spell the
acronym removes essentially all of it: "coating procedure specification" is
CPS, and "show that" is not AB.
"""

from __future__ import annotations

import re

from . import keyword
from .db import connect

#: Words an acronym is allowed to skip. "National Association of Corrosion
#: Engineers" is NACE, not NAOCE.
SKIPPABLE = {"of", "and", "the", "for", "in", "on", "at", "to", "a", "an", "or", "with"}

#: An acronym as documents write them: upper case, short, possibly hyphenated
#: or slashed. Two characters minimum - a single letter is not an abbreviation.
_ACRONYM = re.compile(r"^[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*$")

#: "nominal dry film thickness (NDFT)"
_PARENTHETICAL = re.compile(
    r"([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){1,6})\s*\(\s*([A-Z][A-Z0-9\-/]{1,9})\s*\)"
)

#: "NDFT (nominal dry film thickness)"
_INVERSE = re.compile(
    r"\b([A-Z][A-Z0-9\-/]{1,9})\s*\(\s*([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){1,6})\s*\)"
)

#: A glossary row: the acronym, then its expansion, then the next acronym.
#: Abbreviations clauses extract as one long run rather than as table rows, so
#: the boundary is the next all-caps token rather than a newline.
#: The expansion words may be capitalised - NORSOK's row reads "NACE National
#: Association of Corrosion Engineers" - but a word in ALL CAPS is the next
#: acronym, not part of this expansion, so only the first letter may be upper.
_EXPANSION_WORD = r"[A-Za-z][a-z\-]*"
_GLOSSARY_ROW = re.compile(
    r"\b([A-Z][A-Z0-9\-/]{1,9})\s+"
    r"(" + _EXPANSION_WORD + r"(?:\s+" + _EXPANSION_WORD + r"){1,7})"
    r"(?=\s+[A-Z][A-Z0-9\-/]{1,9}\s|\s*$)"
)

MIN_ACRONYM_LENGTH = 2
MAX_EXPANSION_WORDS = 8

#: Rebuilt when the number of indexed chunks changes. Harvesting scans the
#: whole corpus, so it is done once rather than per question.
_cache: dict[tuple[str | None, int], dict[str, set[str]]] = {}


def looks_like_acronym(term: str) -> bool:
    """Is this token written the way documents write abbreviations?"""
    return (
        len(term) >= MIN_ACRONYM_LENGTH
        and len(term) <= 12
        and bool(_ACRONYM.match(term))
        and any(c.isalpha() for c in term)
    )


def initials_match(acronym: str, expansion: str) -> bool:
    """Do the expansion's word initials spell the acronym?

    Skippable function words may be omitted but never inserted, and every
    letter of the acronym has to be consumed in order. This is what separates
    "coating procedure specification" = CPS from "show that" = AB.
    """
    letters = [c for c in acronym.upper() if c.isalnum()]
    words = [w for w in re.split(r"[\s\-]+", expansion.strip()) if w]
    if not letters or not words or len(words) > MAX_EXPANSION_WORDS:
        return False

    i = 0
    for word in words:
        if i < len(letters) and word[:1].upper() == letters[i]:
            i += 1
            continue
        if word.lower() in SKIPPABLE:
            continue
        # a substantive word that does not contribute a letter means this is
        # not an expansion of this acronym
        return False
    return i == len(letters)


def normalise_expansion(expansion: str) -> str:
    """One canonical spelling of an expansion.

    The patterns capture whatever precedes the bracket, so "the nominal dry
    film thickness (NDFT)" yields a leading article. Left in, the stored
    expansion no longer equals the phrase a reader types, and the reverse
    lookup silently misses - which is how "nominal dry film thickness" failed
    to find NDFT while "the nominal dry film thickness" would have found it.
    """
    words = [w for w in " ".join(expansion.split()).strip(" .,;:").split() if w]
    while words and words[0].lower() in SKIPPABLE:
        words.pop(0)
    return " ".join(words).lower()


def _add(found: dict[str, set[str]], acronym: str, expansion: str) -> None:
    acronym = acronym.strip()
    expansion = normalise_expansion(expansion)
    if not expansion or not looks_like_acronym(acronym):
        return
    if not initials_match(acronym, expansion):
        return
    found.setdefault(acronym.upper(), set()).add(expansion)


def harvest(document_id: str | None = None) -> dict[str, set[str]]:
    """Acronym -> expansions, built from the retrievable text of the corpus."""
    indexed = keyword.indexed_count(document_id)
    key = (document_id, indexed)
    if key in _cache:
        return _cache[key]

    conn = connect()
    params: list[object] = []
    where = "retrievable = 1"
    if document_id:
        where += " AND document_id = ?"
        params.append(document_id)
    rows = conn.execute(f"SELECT text FROM chunks WHERE {where}", params).fetchall()

    found: dict[str, set[str]] = {}
    for row in rows:
        text = row["text"]
        for m in _PARENTHETICAL.finditer(text):
            _add(found, m.group(2), m.group(1))
        for m in _INVERSE.finditer(text):
            _add(found, m.group(1), m.group(2))
        for m in _GLOSSARY_ROW.finditer(text):
            _add(found, m.group(1), m.group(2))

    _cache.clear()          # only ever one corpus state worth keeping
    _cache[key] = found
    return found


def reverse_map(document_id: str | None = None) -> dict[str, set[str]]:
    """Expansion -> acronyms, so a question can be asked either way round."""
    out: dict[str, set[str]] = {}
    for acronym, expansions in harvest(document_id).items():
        for expansion in expansions:
            out.setdefault(expansion, set()).add(acronym)
    return out


def equivalents(term: str, document_id: str | None = None) -> list[str]:
    """Other ways this corpus writes the same thing, `term` excluded.

    Bidirectional: an acronym returns its expansions, an expansion returns its
    acronyms. Returns an empty list when the corpus never defines it, which is
    the case that must still refuse.
    """
    # Normalised the same way on lookup as on store, or a reader typing the
    # phrase with its article would match and one typing it without would not.
    term_norm = normalise_expansion(term)
    out: list[str] = []

    for expansion in sorted(harvest(document_id).get(term.upper(), ())):
        if expansion != term_norm:
            out.append(expansion)

    for acronym in sorted(reverse_map(document_id).get(term_norm, ())):
        if acronym.lower() != term_norm:
            out.append(acronym)

    return out


def known_expansions(document_id: str | None = None) -> list[str]:
    """Multi-word expansions this corpus defines, longest first.

    Needed because a question is tokenised into single words, so the PHRASE
    "nominal dry film thickness" was never looked up at all and its acronym
    was never found. Longest first so "post weld heat treatment" is matched
    before any shorter phrase inside it.
    """
    phrases = {
        expansion
        for expansions in harvest(document_id).values()
        for expansion in expansions
        if " " in expansion
    }
    return sorted(phrases, key=len, reverse=True)


def reset_cache() -> None:
    """For tests, and for after a re-chunk within one process."""
    _cache.clear()
