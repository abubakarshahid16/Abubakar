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
#: #618: below this share of words a real dictionary knows, the text is not
#: read as English. Judged on words that COUNT: acronyms, and capitalised
#: words the dictionary does not know (trade names - "Inconel", "Hastelloy"),
#: are neutral, never evidence of garbling.
_MIN_KNOWN_SHARE = 0.6


def _known(word: str) -> bool:
    """Is this lower-case word English? The committed SCOWL list (with British
    spellings) that `market_phrase` already uses - one home for the question -
    plus the short engineering list above."""
    from .market_phrase import vouched_for
    return word in _COMMON or vouched_for(word)


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
        more of the words are English when spelled backwards than forwards,
        fewer than half are in a real dictionary (#618: the committed SCOWL
        list, not a short built-in one), or too few look like words at all
        (no vowel, or a run of five consonants).

    Acronyms ("PSV", "NPS", "SAES") and capitalised names the dictionary does
    not know ("Inconel") are neutral: they are ignored, not counted against
    the text. None means "no evidence of a problem", not "verified".
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
    # A capitalised word the dictionary does not know is a name, not noise -
    # except the text's first word, which is capitalised whatever it is.
    words = [w for i, w in enumerate(words)
             if i == 0 or not (w[:1].isupper() and not _known(w.lower()))]
    if len(words) < _MIN_WORDS_FOR_RATIO:
        return None
    lowered = [w.lower() for w in words]
    forward = sum(1 for w in lowered if _known(w))
    backward = sum(1 for w in lowered if len(w) >= 3 and not _known(w) and _known(w[::-1]))
    if backward >= 3 and backward > forward:
        return TEXT_QUALITY
    if forward / len(words) < _MIN_KNOWN_SHARE:
        return TEXT_QUALITY
    wordlike = sum(1 for w in words
                   if _VOWEL.search(w) and not _CONSONANT_RUN.search(w))
    if wordlike / len(words) < 0.5 and forward / len(words) < 0.15:
        return TEXT_QUALITY
    return None
