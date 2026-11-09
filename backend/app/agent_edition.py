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


#: The label a printed edition must follow, on the SAME line, before the date.
_LABEL = re.compile(
    r"\b(?P<label>issue\s*date|date\s*of\s*issue|issued|edition|revision\s*date)\b",
    re.IGNORECASE,
)
#: Labels that make a line the document's own issue (the revision date is allowed but is not the issue date).
_ISSUE_LABELS = ("issuedate", "dateofissue", "issued", "edition")
#: Any of these anywhere in the line rejects it, even next to an allowed label.
_REJECT = re.compile(
    r"previous|prior|\bnext\b|planned|supersed|copyright|\u00a9|\(c\)|revised\s+paragraph|effective",
    re.IGNORECASE,
)


def _edition_pattern(edition: str) -> re.Pattern:
    """The edition at the START of a value, spacing and case ignored, not followed by a letter or digit."""
    body = r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", edition))
    return re.compile(body + r"(?![0-9A-Za-z])", re.IGNORECASE)


def _labelled(line: str) -> tuple[str, str] | None:
    """(label folded, value) of a line that carries an ALLOWED label and no rejected word, else None."""
    if _REJECT.search(line):
        return None
    found = _LABEL.search(line)
    if not found:
        return None
    value = line[found.end() :].lstrip(" \t:-\u2013\u2014.")
    return _edition_fold(found.group("label")), value


def _line_confirms(line: str, edition: str) -> bool:
    """True when this one line prints `edition` as its value after an allowed label (boundaries respected)."""
    got = _labelled(line)
    return bool(got and _edition_pattern(edition).match(got[1]))


def verify_quote(quote: str, page_text: str, edition: str) -> bool:
    """Code's check before a quote is shown: at most QUOTE_CHARS, a verbatim substring of the page, and it really
    prints the edition after an allowed label."""
    return bool(
        quote
        and len(quote) <= QUOTE_CHARS
        and quote in page_text
        and _line_confirms(quote, edition)
    )


def _window(line: str) -> str | None:
    """The line as a quote: whole if it fits, else a window from its label; None if the window loses the date."""
    text = line.strip()
    if len(text) <= QUOTE_CHARS:
        return text
    found = _LABEL.search(text)
    return text[found.start() : found.start() + QUOTE_CHARS] if found else None


def _page_lines(
    page_no: int, page_text: str, edition: str
) -> tuple[list[dict], list[str]]:
    """(lines on this page that confirm `edition`, the values of the OTHER allowed-label lines)."""
    hits, others = [], []
    for line in page_text.splitlines():
        got = _labelled(line)
        if not got:
            continue
        if _edition_pattern(edition).match(got[1]):
            quote = _window(line)
            if quote is not None and verify_quote(quote, page_text, edition):
                hits.append(
                    {"page": page_no, "quote": quote, "issue": got[0] in _ISSUE_LABELS}
                )
        else:
            others.append(_edition_fold(got[1]))
    return hits, others


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
        if _edition_pattern(edition).search(stem) and not re.search(
            r"[0-9A-Za-z]" + _edition_pattern(edition).pattern, stem, re.IGNORECASE
        ):
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
        hits, others = [], []
        for page in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? AND page_no <= ? ORDER BY page_no",
            (doc, EDITION_PAGES),
        ).fetchall():
            h, o = _page_lines(page["page_no"], page["text"] or "", edition)
            hits += h
            others += o
        issue = [h for h in hits if h["issue"]]
        # an allowed line with a DIFFERENT date is a conflict, unless the asked edition is the issue date itself
        if hits and (issue or not others):
            best = (issue or hits)[0]
            matches.append(
                {
                    "status": "confirmed",
                    "doc": doc,
                    "page": best["page"],
                    "quote": best["quote"],
                }
            )
    if len(matches) == 1:
        return matches[0]
    return _not_confirmed("two documents match" if matches else "edition not printed")


def resolve_edition(conn, candidates, standard: str, edition: str) -> str | None:
    """The confirmed document id, else None (see `edition_evidence`)."""
    found = edition_evidence(conn, candidates, standard, edition)
    return found["doc"] if found["status"] == "confirmed" else None
