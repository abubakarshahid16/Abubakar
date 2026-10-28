"""The converter's proof gates that read the SENTENCE's surroundings (orders 295.7 b and c).

Pure functions, no database, no network. `standards_converter.verify` calls them; they live here so that module
stays under the project's size limit and so each gate has one home.

  * `in_example` - is the stored sentence part of a worked example (an illustration, never a requirement)?
  * `quote_unreadable` - is the quote, or the sentence it was cut from, OCR noise?
  * `scope_refusal` - order 304.1: a sentence in an appendix or annex, or under a clause the page does not print,
    is not shown to apply to every sheet, so it is "unproven: scope" and never decides.
  * `limit_refusal` - order 304.1 add: a stored sentence cut mid-clause (no subject before the limit), or a limit
    that is one end of a stated range, is not a plain ceiling or floor: "unproven".
  * `fold` - the one way text is compared: lower case, one space between words.
"""

from __future__ import annotations

import re
import unicodedata


def fold(text: str | None) -> str:
    return " ".join((text or "").lower().split())


_fold = fold

#: A heading or label that opens a worked example. The text under it is an illustration, never a requirement.
_EXAMPLE_LABEL = re.compile(
    r"^\W*(?:\d+(?:\.\d+)*\.?\s+)?(?:worked\s+|sizing\s+|calculation\s+|design\s+)?examples?\b"
    r"|\bsample\s+calculation\b",
    re.IGNORECASE,
)
#: A line that starts a new numbered clause: it closes an example block.
_CLAUSE_HEADING = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s+[A-Za-z]")


def in_example(row: dict) -> bool:
    """Is this stored sentence part of a worked example (order 295.7 b)? Three general signs, any one is enough:
    the sentence itself opens as an example, the chunk's section title is an example, or the chunk text before the
    sentence has an "Example" heading line with no new numbered clause between it and the sentence."""
    sentence = " ".join(
        str(row.get("source_text") or row.get("requirement_text") or "").split()
    )
    if _EXAMPLE_LABEL.search(sentence[:80]):
        return True
    if _EXAMPLE_LABEL.search(str(row.get("section") or "")[:80]):
        return True
    chunk = str(row.get("chunk_text") or "")
    at = fold(chunk).find(fold(row.get("requirement_text"))[:60]) if chunk else -1
    if at < 0:
        return False
    lines = chunk.splitlines()
    seen = 0
    inside = False
    for line in lines:
        if seen > at + 40:  # the sentence's own line is reached: stop
            break
        seen += len(fold(line)) + 1
        if _CLAUSE_HEADING.match(line):
            inside = False
        elif _EXAMPLE_LABEL.search(line.strip()[:80]) and len(line.split()) <= 12:
            inside = True
    return inside


def quote_unreadable(quote: str, sentence: str) -> bool:
    """Is the quote (or the sentence it was cut from) OCR noise (order 295.7 c)? `requirement_quality.text_quality`
    is the one home of "unreadable as a sentence"; on top of it more than 15% garbled tokens in the QUOTE (a token
    with a mirror glyph or a non-Latin letter, or no vowel, or a run of six consonants - "lengths" and "strengths" end in five and are real words; acronyms and figures
    are not counted) is enough, because a short quote can carry a stamp's noise below that function's floor."""
    from . import requirement_quality

    if requirement_quality.text_quality(quote) or requirement_quality.text_quality(
        sentence
    ):
        return True
    tokens = [t for t in re.findall(r"\S+", quote) if re.search(r"[^\W\d_]", t)]
    if not tokens:
        return False
    garbled = 0
    for t in tokens:
        letters = re.sub(r"[^\w]", "", t)
        if any(
            c
            in "\u0258\u0252\u01a8\u027f\u0281\u0190\u018e\u1d0e\u0248\u0196\u029c\u025f\u019a\u0254"
            or (
                c.isalpha()
                and not unicodedata.name(c, "").startswith(("LATIN", "GREEK"))
            )
            for c in t
        ) or (
            letters.isalpha()
            and len(letters) >= 4
            and not letters.isupper()
            and (
                not re.search(r"[aeiouyAEIOUY]", letters)
                or re.search(r"[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]{6,}", letters)
            )
        ):
            garbled += 1
    return garbled / len(tokens) > 0.15


#: A heading that opens an appendix or an annex. A limit under one applies to the part the appendix is about.
_APPENDIX_HEADING = re.compile(
    r"^\W*(?:(?:non[-\s]?)?mandatory\s+)?(?:appendix|annex)\b", re.IGNORECASE
)
_WORD_AFTER = re.compile(r"\s*(\S+)")


def _is_heading_line(line: str) -> bool:
    return len(line.split()) <= 12


def in_appendix(row: dict) -> bool:
    """Is the sentence under an appendix or annex heading: its chunk's section title, or a short heading line of
    the chunk before the sentence? ("see Annex A" in the middle of a line is not a heading.)"""
    if _APPENDIX_HEADING.search(str(row.get("section") or "")[:80]):
        return True
    chunk = str(row.get("chunk_text") or "")
    at = fold(chunk).find(fold(row.get("requirement_text"))[:60]) if chunk else -1
    if at < 0:
        return False
    seen = 0
    for line in chunk.splitlines():
        if seen > at + 40:
            break
        seen += len(fold(line)) + 1
        if _is_heading_line(line) and _APPENDIX_HEADING.search(line.strip()):
            return True
    return False


def clause_printed(row: dict) -> bool | None:
    """Is the stored clause number printed as a heading in the chunk the sentence came from (a line that starts
    with it, then a word or the end of the line; not a number followed by a unit)? None when the chunk text or
    the clause is not at hand: the gate stays silent rather than refuse on what it cannot see."""
    from . import field_vocabulary

    clause = str(row.get("clause") or "").strip().rstrip(".")
    chunk = str(row.get("chunk_text") or "")
    if not clause or not chunk:
        return None
    heading = re.compile(
        r"^\s*(?:clause\s+|section\s+)?" + re.escape(clause) + r"\.?(?=\s*$|\s)",
        re.IGNORECASE,
    )
    for source in [str(row.get("section") or ""), *chunk.splitlines()]:
        m = heading.match(source)
        if not m:
            continue
        rest = _WORD_AFTER.match(source[m.end() :])
        if rest is None or not field_vocabulary._unit_families(rest.group(1)):
            return True
    return False


def scope_refusal(row: dict) -> str | None:
    """The reason a verified-looking row must not decide (order 304.1), else None: `scope_in_appendix` (an
    appendix or annex), `scope_clause_not_printed` (its stored clause is not a heading of its own text, so the
    citation would point at a clause the engineer cannot find). Silent when the chunk text is not at hand.
    NOT detected, by design: a limit for one kind of part under a real, printed clause of the main body; no
    wording marks that in every standard, so it stays with the rule card an engineer approves."""
    if in_appendix(row):
        return "scope_in_appendix"
    if clause_printed(row) is False:
        return "scope_clause_not_printed"
    return None


#: Words a sentence cannot start with unless it was cut from a longer one: a limit phrase, a joiner, a relative.
_FRAGMENT_OPENERS = frozenset(
    [
        "not",
        "no",
        "at",
        "up",
        "from",
        "between",
        "above",
        "below",
        "over",
        "under",
        "less",
        "greater",
        "more",
        "maximum",
        "minimum",
        "max",
        "min",
        "and",
        "or",
        "but",
        "which",
        "where",
        "whereas",
        "whose",
        "than",
        "to",
        "of",
    ]
)
_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = r"[a-zA-Z%\u00b0/.()]{0,12}"
_RANGE = re.compile(
    rf"({_NUM})\s*({_UNIT})\s*(and|to|\u2013|\u2014|-)\s*({_NUM})\s*({_UNIT})",
    re.IGNORECASE,
)


def is_fragment(sentence: str) -> bool:
    """Was the stored sentence cut out of a longer clause? Its first word is lower-case (it began mid-sentence)
    or is a limit phrase, a joiner or a relative ("not more than 25 bar ...", "which shall ..."): nothing before the
    limit says what it limits."""
    words = re.findall(r"[^\W\d_]+", sentence or "")
    if not words:
        return False
    first = words[0]
    return first[0].islower() or first.lower() in _FRAGMENT_OPENERS


def range_boundary(sentence: str, limit: str) -> bool:
    """Is `limit` one end of a range the sentence states ("between 10 and 20 bar", "from 10 to 20", "10 to 20 bar")?
    A single comparator on one end drops the other end, so it is never a plain ceiling or floor. Two figures of
    different units ("25 bar and 30 degC") are two quantities, not a range; a hyphen is a range only with a unit."""
    from . import field_vocabulary

    wanted = str(limit or "").strip().replace(",", ".")
    for m in _RANGE.finditer(sentence or ""):
        first, u1, sep, second, u2 = m.groups()
        if u1 and u2 and u1.lower().strip(".") != u2.lower().strip("."):
            continue
        if sep == "-" and not any(
            field_vocabulary._unit_families(u) for u in (u1, u2) if u
        ):
            continue
        if wanted and wanted in (first.replace(",", "."), second.replace(",", ".")):
            return True
    return False


def limit_refusal(sentence: str, limit: str) -> str | None:
    """The reason a verified-looking row must not decide for the SENTENCE's own shape (order 304.1 add), else None:
    `sentence_is_fragment`, `limit_is_range_boundary`."""
    if is_fragment(sentence):
        return "sentence_is_fragment"
    if range_boundary(sentence, limit):
        return "limit_is_range_boundary"
    return None
