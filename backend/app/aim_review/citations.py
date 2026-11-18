"""How a cited name is matched to a held book and said once (18 Nov 2026): a held rule book's identifier standing in a paper's
text as a whole token; a cited name that begins with a book's identifier, edition words left out; and one key per standard for
the not-held list. No name-shape rule: the paper's words and the book's recorded identifier decide."""

from __future__ import annotations

import re

#: A RECORDED document number shorter than this, or with no digit, is never matched in a paper's text: a short or all-letter
#: number is too easily an ordinary word or a part of another number. Such a book is still found by the standard families.
NUMBER_MIN = 6


def _number_in(number: str, text: str) -> bool:
    """The recorded number stands in the text as a whole token, case ignored, its parts apart by spaces, hyphens, dots,
    slashes or underscores or by nothing (the variants `resolve` folds away); never a number under `NUMBER_MIN` or with no
    digit."""
    parts = re.findall(r"[A-Za-z0-9]+", number or "")
    if (
        len(number or "") < NUMBER_MIN
        or not any(c.isdigit() for c in number)
        or not parts
    ):
        return False
    pattern = (
        r"(?<![A-Za-z0-9])"
        + r"[\s\-_./]*".join(map(re.escape, parts))
        + r"(?![A-Za-z0-9])"
    )
    return re.search(pattern, text or "", re.IGNORECASE) is not None


#: Words of a citation that name an edition, never the standard ("latest edition", "11th Ed.", "2019", "Rev. 2", "current").
_EDITION = re.compile(
    r"(?i)\b(?:latest|current|last)\s+(?:edition|issue|revision)\b|\b\d{1,2}(?:st|nd|rd|th)\s+ed(?:ition|\.)?|"
    r"\bed(?:ition|\.)\s*\d*|\brev(?:ision|\.)?\s*[a-z0-9]{1,3}\b|\b(?:19|20)\d{2}\b|\(current\)"
)


def citation_tokens(name: str) -> list[str]:
    """The words of a cited name with the edition words left out, folded (case and punctuation ignored)."""
    return re.findall(r"[a-z0-9]+", _EDITION.sub(" ", str(name or "")).lower())


def identifier_key(name: str) -> str:
    """ONE key for a standard's name, for saying it once: the app's parsed identifiers (`standard_ids.parse_all`: publisher,
    number, part; a "Pt-2" and a "Part II" of one number, a dash or no dash, are one) when it knows the family, else the cited words
    with the edition left out ("ZQ TEST STD 001, latest edition" = "ZQ-TEST-STD-001"). The same key as citation matching uses."""
    from app import standard_ids

    ids = standard_ids.parse_all(str(name or ""))
    if ids:
        return "|".join(sorted({f"{i.family}:{i.number}:{i.part or ''}" for i in ids}))
    return "".join(citation_tokens(name))


def _starts_with_identifier(cited: str, identifier: str) -> bool:
    """The cited name begins with the book's whole identifier, word for word (title or edition words may follow); an identifier
    under `NUMBER_MIN` characters or with no digit never matches this way."""
    want, have = citation_tokens(cited), citation_tokens(identifier)
    text = "".join(have)
    if len(text) < NUMBER_MIN or not any(c.isdigit() for c in text) or not have:
        return False
    return want[: len(have)] == have
