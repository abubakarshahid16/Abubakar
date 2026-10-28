"""The converter's proof gates that read the SENTENCE's surroundings (orders 295.7 b and c).

Pure functions, no database, no network. `standards_converter.verify` calls them; they live here so that module
stays under the project's size limit and so each gate has one home.

  * `in_example` - is the stored sentence part of a worked example (an illustration, never a requirement)?
  * `quote_unreadable` - is the quote, or the sentence it was cut from, OCR noise?
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
