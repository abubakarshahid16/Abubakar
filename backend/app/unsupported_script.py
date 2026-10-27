"""A page written mostly in Arabic script is not read, and says so (#564).

The system reads English engineering documents. Arabic pages used to go through
the same chunker and readers as English ones, so a finding could be drawn from
text nobody had checked the system could read. A chunk whose letters are mostly
Arabic script is now held out of retrieval with a named reason; the page ledger
counts its pages as not reached, so a review says "not read" for them (never
"searched, nothing found").

General rule, no word list: the share of a chunk's LETTERS that fall in the
Arabic Unicode blocks. A chunk with fewer than `MIN_LETTERS` letters is never
judged: a short heading, a tag or an Arabic word inside an English sentence
does not hold anything back. Stated limit: a bilingual chunk whose Arabic share
is below `MAX_SHARE` is read as before (its Arabic part is not understood).
"""

from __future__ import annotations

#: The Arabic Unicode blocks (basic, supplement, extended-A, presentation forms A and B).
_ARABIC = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)

#: Fewer letters than this is too little text to judge a script by.
MIN_LETTERS = 20
#: A chunk is held out when more than this share of its letters is Arabic script.
MAX_SHARE = 0.5

RULE = "unsupported_script"
#: The page kind `chunker.classify_document_pages` gives such a page (not a searched kind).
KIND = RULE
WORDS = "language not supported, engineer review"


def counts(text: str) -> tuple[int, int]:
    """(Arabic-script letters, all letters) of `text`."""
    arabic = letters = 0
    for ch in text or "":
        if not ch.isalpha():
            continue
        letters += 1
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _ARABIC):
            arabic += 1
    return arabic, letters


def is_unsupported(text: str) -> bool:
    arabic, letters = counts(text)
    return letters >= MIN_LETTERS and arabic / letters > MAX_SHARE


def reason(text: str) -> str:
    """The stored reason: the rule name first, then plain words with the denominator."""
    arabic, letters = counts(text)
    return f"{RULE}: {WORDS} ({arabic} of {letters} letters are Arabic script)"


def kind(text: str) -> str | None:
    """The page kind for a page of this text, or None when the script is supported."""
    return KIND if is_unsupported(text) else None


def page_reason(page_kind: str, text: str) -> str:
    """The stored reason of a page excluded because of its kind."""
    return reason(text) if page_kind == KIND else f"page classified as {page_kind}"


def rule_of(exclusion) -> str:
    """The rule a chunk exclusion is filed under in the page ledger: this one when the
    stored reason names it, else the exclusion's own rule."""
    if str(exclusion["reason"] or "").startswith(RULE):
        return RULE
    return exclusion["rule"]


def not_reached(index_status: str, index_reason: str | None) -> str:
    """Why fact extraction never saw a page that no retrievable chunk covers."""
    if index_reason and RULE in index_reason:
        return f"{WORDS}: this page is mostly Arabic script, so fact extraction never saw it"
    return (
        f"no retrievable chunk covers this page ({index_status}"
        f"{': ' + index_reason if index_reason else ''}), so fact extraction never saw it"
    )
