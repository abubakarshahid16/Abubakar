"""Two gates on what becomes a requirement: definitions and unreadable text.

Pure functions, no database, no network. `standards` calls them when it CREATES
a requirement; nothing here reads or rewrites a stored row.

#596 A DEFINITION IS NOT A REQUIREMENT. "Shall: a verb indicating a mandatory
requirement" carries the word "shall" and states no obligation on anyone. It
is stored with `requirement_type = 'definition'`, stays visible on the standard
and is never compared with a submittal.

#597 UNREADABLE TEXT IS NOT A REQUIREMENT. A mirrored or garbled OCR line has a
resolving citation and a normal confidence, so it looked like any other row.
It is marked `needs_verification` with the reason `text_quality`, and kept out
of reviews until a human reads it. It is never deleted.
"""
from __future__ import annotations

import re
import unicodedata

DEFINITION = "definition"
TEXT_QUALITY = "text_quality"

# ----------------------------------------------------------------- definitions

#: A section TITLE that is a definitions section, with or without its clause
#: number: "3 Terms and definitions", "Definitions", "Terms, Definitions and
#: Abbreviations". Anchored on the whole title, so "Definition of design
#: pressure" (a clause ABOUT a definition) is not one.
_DEFINITIONS_TITLE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(?:terms?(?:\s*(?:,|and|&)\s*|\s+))?"
    r"(?:definitions?|glossary)"
    r"(?:\s*(?:,|and|&)\s*(?:abbreviations?|acronyms?|symbols?|terms?))*\s*:?\s*$",
    re.IGNORECASE)


def is_definitions_heading(section: str | None) -> bool:
    """True when a chunk's section title opens a definitions section."""
    return bool(section and _DEFINITIONS_TITLE.match(section))


class SectionRun:
    """A run of chunks under one opening heading: it opens at a heading `opens` accepts and runs over the chunks
    filed under that clause (3, 3.1, 3.2.1 ...), closing at the first chunk filed elsewhere. `number_of` reads a
    clause number off a section title."""

    def __init__(self, opens, number_of) -> None:
        self.opens, self.number_of, self.on, self.clause = opens, number_of, False, None

    def step(self, section: str | None) -> bool:
        if self.opens(section):
            self.on, self.clause = True, self.number_of(section)
        elif self.on:
            here = self.number_of(section)
            self.on = (
                here is None
                if self.clause is None
                else here is None
                or here == self.clause
                or here.startswith(self.clause + ".")
            )
        return self.on


#: A references section: "2 References", "Normative references", "Saudi Aramco References", "Bibliography".
#: Its text lists the documents the standard cites; it states no obligation of its own (order 267.1).
_REFERENCES_WORDS = (
    r"(?:(?:normative|informative|applicable|referenced?|company|industry|[A-Za-z&]+)\s+){0,3}"
    r"(?:references?|bibliography|referenced\s+documents?|reference\s+documents?)"
)
_REFERENCES_TITLE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?" + _REFERENCES_WORDS + r"\s*:?\s*$", re.IGNORECASE
)
_REFERENCES_START = re.compile(r"^\W*" + _REFERENCES_WORDS + r"\b", re.IGNORECASE)


def is_references_heading(section: str | None) -> bool:
    """True when a chunk's section title opens a references section (the whole title, not a clause ABOUT references)."""
    return bool(section and _REFERENCES_TITLE.match(section))


#: A standard identifier as a references list writes it: an upper-case body then a number ("SAEP-31", "SAMSS-044",
#: "API 610", "ASME B31.3", "ISO 15156-3", "SAES-A-007"). Local on purpose: `standard_ids.parse_all` knows only the
#: families in its vocabulary and finds one identifier in "SAEP-31 and SAMSS-044".
_IDENTIFIER = re.compile(
    r"\b[A-Z]{2,6}(?:[-\s][A-Z]{1,2})?[-\s]?\d{1,4}(?:[.\-]\d+)*[A-Z]?\b"
)


def is_reference_list_sentence(sentence: str) -> bool:
    """True when a sentence is a references list run into one line: it starts with the references title, names
    two or more standards, and the first of them follows the title at once. The list states which documents are
    cited, not what anyone must do. "Reference conditions per API 610 and ASME B31.3 ..." is a sentence about
    conditions, not a list."""
    start = _REFERENCES_START.match(sentence or "")
    if start is None or len(_IDENTIFIER.findall(sentence)) < 2:
        return False
    return (
        _IDENTIFIER.match(sentence[start.end() :].lstrip(" :-\u2013\u2014\t"))
        is not None
    )


_MODAL = r"(?:shall|must|should|may|will|can)"

#: A sentence that only defines a word.
#:   * the modal itself, defined: "Shall: indicates a mandatory requirement",
#:     "The word 'shall' indicates ...", "\"Must\" means ...";
#:   * "<term> shall mean ..." / "<term> is defined as ..." / "... are defined
#:     as ...": the sentence's whole job is to say what a word means.
_DEFINING_SENTENCE = re.compile(
    r"^[\W\d]*(?:the\s+(?:word|term|verb|auxiliary)\s+)?[\"'“‘`]?" + _MODAL +
    r"[\"'”’`]?\s*(?:[:–—-]|means?\b|is\s+used\b|is\s+a\b|is\s+defined\b"
    r"|indicates?\b|denotes?\b|refers?\b|signifies\b|expresses\b)"
    r"|\bshall\s+mean\b|\b(?:is|are)\s+defined\s+as\b"
    r"|^[\W\d]*[\"“][^\"”]{1,40}[\"”]\s+(?:means?|is|refers?\s+to)\b",
    re.IGNORECASE)


def is_defining_sentence(sentence: str) -> bool:
    """True when the sentence only gives the meaning of a word."""
    return bool(_DEFINING_SENTENCE.search(sentence or ""))


# ---------------------------------------------------------------- text quality

#: Words that make up ordinary engineering English. Not a spelling dictionary:
#: a short list of frequent function and engineering words, enough to tell
#: English from reversed or garbled letters. A technical word that is missing
#: from it costs nothing - it only matters through the RATIO below.
_COMMON = frozenset("""
the of and to in is be for that with as on by are or at this shall must should
may not from it an all any each than more less less not no if when where which
such been has have had will can also other into only both these those their its
between under over above below per one two three four five six ten about after
before during within without against through used use using required require
requirement requirements provided provide shall design designed pressure
temperature minimum maximum value values valve valves pipe piping vessel
vessels material materials stress test tested testing inspection installed
installation system systems equipment shall section table figure standard
standards specification clause clauses unless except according following
applicable applied apply allowed allowable limit limits level levels water
steel flow rate size diameter thickness length height load loads voltage
current power field area type class rating ratings service cover covered
supply supplied supplier manufacturer contractor owner approved approval
documents document drawing drawings data sheet report records record
procedure procedures welding weld welds joints joint surface surfaces coating
coatings protection protective safety fire gas oil air process operating
operation normal maximum shall exceed exceeding greater lower higher total
overpressure relief set opening closing seat back leakage capacity
""".split())

#: Letters printed backwards or upside down by a mirrored scan.
_MIRROR_GLYPHS = frozenset("ɘɒƨɿʁƐƎᴎɈƖʜɟƚɔ")

_WORD = re.compile(r"[A-Za-z]{2,}")
_ACRONYM = re.compile(r"[A-Z]{2,6}[a-z]?")
_VOWEL = re.compile(r"[aeiouyAEIOUY]")
_CONSONANT_RUN = re.compile(r"[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]{5,}")

#: Below this many words a sentence is judged by its characters only: a short
#: line has too few words for a ratio to mean anything, and "10 % or less
#: overpressure" must never be flagged.
_MIN_WORDS_FOR_RATIO = 6


#: Words are judged by the committed dictionary (`market_phrase`) as well as the short list above:
#: a technical word the short list lacks no longer counts against a sentence (#618). The share of
#: unknown words above which a sentence of at least `_MIN_WORDS_FOR_UNKNOWN` words is flagged;
#: `scripts/text_quality_count.py` counts what it flags on a copy before it is trusted.
_UNKNOWN_SHARE = 0.6
_MIN_WORDS_FOR_UNKNOWN = 8


def _is_word(word: str) -> bool:
    from . import market_phrase  # late: the dictionary is read once, on first use

    return word in _COMMON or market_phrase.vouched_for(word)


def _non_latin_letter_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return 0.0
    foreign = 0
    for c in letters:
        name = unicodedata.name(c, "")
        if not name.startswith(("LATIN", "GREEK")):
            foreign += 1
    return foreign / len(letters)


def text_quality(text: str | None) -> str | None:
    """`TEXT_QUALITY` when the text is not readable as a sentence, else None.

    Four tests, any one is enough:
      * mirror glyphs (two or more letters that only a mirrored scan produces);
      * most letters outside the Latin alphabet in an English standard;
      * mostly punctuation and symbols;
      * enough words to judge, and the words read as reversed or as noise:
        more of the words are English when spelled backwards than forwards, or
        too few look like words at all (no vowel, or a run of five consonants).

    Acronyms ("PSV", "NPS", "SAES") are neutral: they are ignored, not counted
    against the text. None means "no evidence of a problem", not "verified".
    """
    if not text or not text.strip():
        return None
    if sum(1 for c in text if c in _MIRROR_GLYPHS) >= 2:
        return TEXT_QUALITY
    if _non_latin_letter_share(text) > 0.3:
        return TEXT_QUALITY
    visible = [c for c in text if not c.isspace()]
    if len(visible) >= 12:
        symbols = sum(1 for c in visible
                      if not c.isalnum() and c not in ".,;:()-%/'\"°±<>=≤≥[]")
        if symbols / len(visible) > 0.3:
            return TEXT_QUALITY

    words = [w for w in _WORD.findall(text) if not _ACRONYM.fullmatch(w)]
    if len(words) < _MIN_WORDS_FOR_RATIO:
        return None
    lowered = [w.lower() for w in words]
    forward = sum(1 for w in lowered if _is_word(w))
    # a reversed word counts only from four letters: "net"/"ten" read as words both ways (#618)
    backward = sum(1 for w in lowered if len(w) >= 4 and _is_word(w[::-1]))
    if backward >= 3 and backward > forward:
        return TEXT_QUALITY
    wordlike = sum(1 for w in words
                   if _VOWEL.search(w) and not _CONSONANT_RUN.search(w))
    if wordlike / len(words) < 0.5 and forward / len(words) < 0.15:
        return TEXT_QUALITY
    # noise that keeps its vowels: most of the words are in no dictionary (#618)
    unknown = (len(words) - forward) / len(words)
    if len(words) >= _MIN_WORDS_FOR_UNKNOWN and unknown > _UNKNOWN_SHARE:
        return TEXT_QUALITY
    return None
