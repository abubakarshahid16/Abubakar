"""Which document IS a standard at the contract's edition, WITH evidence (#1690, part of #805, owner order 9 Nov).

An edition is read from the file name or from a standard's first pages and always carries its evidence: the page and the
printed line (verbatim, at most 80 characters, checked by code against the page text) or the file-name source. If it
cannot be shown it is 'edition not confirmed': never guessed, no latest-edition fallback, no first-held fallback.
Shared by `agent_tools` (get_clause) and `agent_run` (scope, RESULTS), so the two cannot drift.
"""

from __future__ import annotations

import re

from . import standard_ids

EDITION_PAGES = 3  # a standard prints its issue date on its first pages
QUOTE_CHARS = 80
NOT_CONFIRMED = "edition not confirmed"


def _edition_fold(text: str) -> str:
    """Case and ALL whitespace removed: '23 May 2019', '23  May  2019' and '23may2019' are one edition."""
    return re.sub(r"\s+", "", str(text or "")).lower()


def _printed_line(page_text: str, edition: str) -> str | None:
    """The line of `page_text` that prints `edition`, verbatim, at most QUOTE_CHARS characters, or None.

    Matching ignores case and spacing; the quote is the ORIGINAL text, and code checks that it is a substring of the
    page before it is returned. A long line is cut to a window that still holds the edition."""
    pattern = re.compile(
        r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", edition)), re.IGNORECASE
    )
    for line in page_text.splitlines():
        found = pattern.search(line)
        if not found:
            continue
        text = line.strip()
        at = text.lower().find(found.group(0).lower())
        if len(text) > QUOTE_CHARS:
            if found.end() - found.start() > QUOTE_CHARS or at < 0:
                continue
            start = max(0, at - (QUOTE_CHARS - (found.end() - found.start())) // 2)
            text = text[start : start + QUOTE_CHARS]
        if text and text in page_text and _edition_fold(edition) in _edition_fold(text):
            return text
    return None


def _not_confirmed(reason: str) -> dict:
    return {
        "status": NOT_CONFIRMED,
        "doc": None,
        "page": None,
        "quote": None,
        "reason": reason,
    }


def edition_evidence(conn, candidates, standard: str, edition: str) -> dict:
    """Which candidate document IS `standard` at `edition`, WITH evidence. Never guessed.

    Confirmed: {"status": "confirmed", "doc", "page", "quote"} (the line from pages 1..EDITION_PAGES that prints the
    edition, verbatim, code-verified) or {"status": "confirmed", "doc", "page": None, "quote": None, "source":
    "file name"} when the file name prints it. Anything else is "edition not confirmed": empty edition, not printed, a
    quote that cannot be verified on the page, or two different documents matching. ONE helper for the tools and the
    runner. `conn`: sqlite with `documents(id, filename)` and `pages(document_id, page_no, text)`."""
    want = _edition_fold(edition)
    if not want:
        return _not_confirmed("empty edition")
    matches = []
    for doc in sorted(candidates):
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (doc,)
        ).fetchone()
        if row is None:
            continue
        stem = re.sub(r"\.(pdf|docx?)$", "", row["filename"] or "", flags=re.IGNORECASE)
        if not standard_ids.same_standard(standard, stem):
            continue
        if want in _edition_fold(stem):
            matches.append(
                {
                    "status": "confirmed",
                    "doc": doc,
                    "page": None,
                    "quote": None,
                    "source": "file name",
                }
            )
            continue
        for page in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? AND page_no <= ? ORDER BY page_no",
            (doc, EDITION_PAGES),
        ).fetchall():
            if want in _edition_fold(page["text"]):
                quote = _printed_line(page["text"] or "", edition)
                if quote is not None:
                    matches.append(
                        {
                            "status": "confirmed",
                            "doc": doc,
                            "page": page["page_no"],
                            "quote": quote,
                        }
                    )
                break
    if len(matches) == 1:
        return matches[0]
    return _not_confirmed("two documents match" if matches else "edition not printed")


def resolve_edition(conn, candidates, standard: str, edition: str) -> str | None:
    """The confirmed document id, else None (see `edition_evidence`)."""
    found = edition_evidence(conn, candidates, standard, edition)
    return found["doc"] if found["status"] == "confirmed" else None
