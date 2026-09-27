"""Acronym expansions harvested from the documents themselves.

The lexical gate refuses a question naming something absent from the corpus,
which is right, and it made one thing wrong: a document that spells out
"nominal dry film thickness" without ever writing "NDFT" refused a question
asking for the NDFT. The term genuinely was not there, and the reader was
still asking a fair question.

NORSOK happens to carry a clause 3.2 Abbreviations, so relying on a glossary
clause would have looked sufficient. It is not. Engineering specifications are
dense with acronyms - SSPC, EEMUA, MAWP, PWHT, NDT - and a client uploads their own
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
import threading
from collections import OrderedDict

from .config import settings
from .db import connect

#: Words an acronym is allowed to skip. "National Association of Corrosion
#: Engineers" is NACE, not NAOCE.
SKIPPABLE = {"of", "and", "the", "for", "in", "on", "at", "to", "a", "an", "or", "with"}

#: An acronym as documents write them: upper case, short, possibly hyphenated
#: or slashed. Two characters minimum - a single letter is not an abbreviation.
_ACRONYM = re.compile(r"^[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*$")

#: "nominal dry film thickness (NDFT)"
#:
#: THE DEFINITION OF A MATCH, AND NEVER RUN OVER A WHOLE TEXT. With no leading
#: anchor, `finditer` tried it at every letter of the corpus and each attempt
#: walked up to seven words before failing: 9.2 s of a 9.5 s harvest over
#: 3.4 MB (perf audit item 2). `_parentheticals` below finds the bracket first
#: and runs this only over the words that could precede it; the matches are
#: identical, which a golden-diff test holds it to.
_PARENTHETICAL = re.compile(
    r"([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){1,6})\s*\(\s*([A-Z][A-Z0-9\-/]{1,9})\s*\)"
)

#: The bracketed acronym alone - the cheap, rare thing to look for first.
#: Exactly the tail of `_PARENTHETICAL`, so every place that pattern can end
#: is one of these hits.
_BRACKETED = re.compile(r"\(\s*[A-Z][A-Z0-9\-/]{1,9}\s*\)")

#: The characters a `_PARENTHETICAL` word may contain.
_WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-")

#: How many words `_PARENTHETICAL` allows before the bracket: one, then 1-6.
_MAX_WORDS = 7

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

#: PER-DOCUMENT MAPS, bounded LRU, keyed on the document's retrievable-chunk
#: signature. It was ONE entry for the whole (document, count, scope) key and
#: `.clear()`ed on every miss, so alternating a library question with a
#: one-document question - or two users with different scopes - re-harvested
#: the whole corpus every time (measured 8.8-10.3 s each, perf audit item 2).
_doc_cache: OrderedDict[tuple, dict[str, frozenset[str]]] = OrderedDict()

#: PER-SCOPE MERGED MAPS, bounded LRU. A scope's map is the UNION of the maps
#: of the documents it may read - never more - so the scoping rule is the
#: same as before: a document outside the caller's grants contributes nothing.
_scope_cache: OrderedDict[tuple, dict[str, set[str]]] = OrderedDict()

_cache_lock = threading.Lock()


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


def _parentheticals(text: str):
    """`_PARENTHETICAL.finditer(text)`, the same matches, without the scan.

    Each bracketed acronym is found first, and `_PARENTHETICAL` is searched
    only in the stretch that could hold its words: at most seven runs of
    letters and hyphens, separated by whitespace, directly before it - never
    before the end of the previous match, because `finditer` does not overlap.
    A match cannot span a bracket (no word character is one), so the leftmost
    match ending at this bracket is exactly the one `finditer` would return.
    """
    floor = 0
    for hit in _BRACKETED.finditer(text):
        if hit.start() < floor:
            continue
        i = hit.start()
        while i > floor and text[i - 1].isspace():
            i -= 1
        for _ in range(_MAX_WORDS):
            j = i
            while j > floor and text[j - 1] in _WORD_CHARS:
                j -= 1
            if j == i:
                break
            i = j
            k = i
            while k > floor and text[k - 1].isspace():
                k -= 1
            if k == i:
                break
            i = k
        m = _PARENTHETICAL.search(text, i, hit.end())
        if m is not None and m.end() == hit.end():
            floor = m.end()
            yield m


def _harvest_text(found: dict[str, set[str]], text: str) -> None:
    for m in _parentheticals(text):
        _add(found, m.group(2), m.group(1))
    for m in _INVERSE.finditer(text):
        _add(found, m.group(1), m.group(2))
    for m in _GLOSSARY_ROW.finditer(text):
        _add(found, m.group(1), m.group(2))


def _signatures(document_id: str | None,
                allowed_document_ids: frozenset[str]) -> dict[str, tuple]:
    """document id -> fingerprint of its retrievable chunks, for the scope.

    COUNT + MAX/SUM(rowid) catch additions, deletions and a chunk being
    excluded or restored (the `retrievable` flag); `chunk_signature` catches a
    re-chunk that happens to reuse rowids (vectorcache.signature's lesson).
    A document with no retrievable chunk is absent, and contributes nothing.
    """
    conn = connect()
    params: list[object] = []
    where = "c.retrievable = 1"
    if document_id:
        where += " AND c.document_id = ?"
        params.append(document_id)
    where += " AND c.document_id IN (%s)" % ",".join("?" * len(allowed_document_ids))
    params.extend(sorted(allowed_document_ids))
    rows = conn.execute(
        "SELECT c.document_id, COUNT(*), MAX(c.rowid), SUM(c.rowid),"
        " (SELECT chunk_signature FROM documents d WHERE d.id = c.document_id)"
        f" FROM chunks c WHERE {where} GROUP BY c.document_id", params).fetchall()
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


def _document_map(document_id: str, signature: tuple) -> dict[str, frozenset[str]]:
    key = (str(settings.db_path), document_id, signature)
    with _cache_lock:
        cached = _doc_cache.get(key)
        if cached is not None:
            _doc_cache.move_to_end(key)
            return cached
    found: dict[str, set[str]] = {}
    for row in connect().execute(
            "SELECT text FROM chunks WHERE retrievable = 1 AND document_id = ?",
            (document_id,)):
        _harvest_text(found, row["text"])
    frozen = {acronym: frozenset(exp) for acronym, exp in found.items()}
    with _cache_lock:
        _doc_cache[key] = frozen
        _doc_cache.move_to_end(key)
        while len(_doc_cache) > max(1, settings.acronym_cache_documents):
            _doc_cache.popitem(last=False)
    return frozen


def harvest(
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, set[str]]:
    """Acronym -> expansions, built from the retrievable text the caller may read.

    Scoped because `lexical.assess` expands every question term through this
    map before asking whether it occurs: an unscoped map let a document the
    caller cannot read supply the expansion that decided their verdict, and
    the expansions themselves are phrases lifted from that document's text.

    Built per DOCUMENT and cached per document; the caller's map is the union
    of the documents in their scope (and, when `document_id` is given, of that
    one document only if it is in scope).
    """
    if not allowed_document_ids:
        return {}
    signatures = _signatures(document_id, allowed_document_ids)
    # The scope and every contributing document's fingerprint are the key.
    # Without the scope, one caller's map was served to the next.
    key = (str(settings.db_path), document_id, allowed_document_ids,
           tuple(sorted(signatures.items())))
    with _cache_lock:
        cached = _scope_cache.get(key)
        if cached is not None:
            _scope_cache.move_to_end(key)
            return cached

    found: dict[str, set[str]] = {}
    for doc_id in sorted(signatures):
        for acronym, expansions in _document_map(doc_id, signatures[doc_id]).items():
            found.setdefault(acronym, set()).update(expansions)

    with _cache_lock:
        _scope_cache[key] = found
        _scope_cache.move_to_end(key)
        while len(_scope_cache) > max(1, settings.acronym_cache_scopes):
            _scope_cache.popitem(last=False)
    return found


def reverse_map(
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, set[str]]:
    """Expansion -> acronyms, so a question can be asked either way round."""
    out: dict[str, set[str]] = {}
    for acronym, expansions in harvest(
            document_id, allowed_document_ids=allowed_document_ids).items():
        for expansion in expansions:
            out.setdefault(expansion, set()).add(acronym)
    return out


def equivalents(
    term: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> list[str]:
    """Other ways this corpus writes the same thing, `term` excluded.

    Bidirectional: an acronym returns its expansions, an expansion returns its
    acronyms. Returns an empty list when the corpus never defines it, which is
    the case that must still refuse.
    """
    # Normalised the same way on lookup as on store, or a reader typing the
    # phrase with its article would match and one typing it without would not.
    term_norm = normalise_expansion(term)
    out: list[str] = []

    for expansion in sorted(harvest(
            document_id,
            allowed_document_ids=allowed_document_ids).get(term.upper(), ())):
        if expansion != term_norm:
            out.append(expansion)

    for acronym in sorted(reverse_map(
            document_id,
            allowed_document_ids=allowed_document_ids).get(term_norm, ())):
        if acronym.lower() != term_norm:
            out.append(acronym)

    return out


def known_expansions(
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> list[str]:
    """Multi-word expansions this corpus defines, longest first.

    Needed because a question is tokenised into single words, so the PHRASE
    "nominal dry film thickness" was never looked up at all and its acronym
    was never found. Longest first so "post weld heat treatment" is matched
    before any shorter phrase inside it.
    """
    phrases = {
        expansion
        for expansions in harvest(
            document_id, allowed_document_ids=allowed_document_ids).values()
        for expansion in expansions
        if " " in expansion
    }
    return sorted(phrases, key=len, reverse=True)


def reset_cache() -> None:
    """For tests. A re-chunk no longer needs it: the signatures change."""
    with _cache_lock:
        _doc_cache.clear()
        _scope_cache.clear()
