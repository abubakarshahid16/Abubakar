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


#: A printed edition is a WHOLE line: optional numbering or bullet, the LABEL first, an optional ':' or '-', the value.
#: (The revision date is not an edition: it is not in the list.)
_LINE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s+|[-*\u2022]\s+)?"
    r"(?P<label>issue\s*date|date\s*of\s*issue|issued|edition)\b\s*[:\-\u2013\u2014]?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_END_PUNCT = " \t.,;:)"


def _labelled(line: str) -> str | None:
    """The value (folded) of a line that is `<label> [:] <value>`, trailing end punctuation removed, else None."""
    found = _LINE.match(line)
    if not found:
        return None
    value = _edition_fold(found.group("value").rstrip(_END_PUNCT))
    return value or None


_DATELIKE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?!\d)|^\s*\d+(?:\.\d+)*\s*["
    + re.escape(_END_PUNCT)
    + r"]*$"
)


def _is_datelike(line: str) -> bool:
    """A labelled line whose value is a date or an edition number (a year, or a plain number): only such lines can
    conflict. 'Issued by the committee' is a label line, not a second edition."""
    found = _LINE.match(line)
    return bool(found and _DATELIKE.search(found.group("value")))


def _line_confirms(line: str, edition: str) -> bool:
    """True when this one line is a label followed by EXACTLY the edition and only end punctuation: no trailing
    words, no longer value ('2019.5', '2019-06-01', '3.1' do not confirm '2019' or '3')."""
    return _labelled(line) == _edition_fold(edition) != ""


def verify_quote(quote: str, page_text: str, edition: str) -> bool:
    """Code's check before a quote is shown: at most QUOTE_CHARS, a verbatim substring of the page, and it really
    is a labelled line that prints the edition."""
    return bool(
        quote
        and len(quote) <= QUOTE_CHARS
        and quote in page_text
        and _line_confirms(quote, edition)
    )


def _page_lines(
    page_no: int, page_text: str, edition: str
) -> tuple[list[dict], set[str]]:
    """(lines on this page that confirm `edition`, the values of ALL labelled lines on it)."""
    hits, values = [], set()
    for line in page_text.splitlines():
        value = _labelled(line)
        if value is None:
            continue
        if _is_datelike(line):
            values.add(value)
        quote = line.strip()
        if verify_quote(quote, page_text, edition):
            hits.append({"page": page_no, "quote": quote})
    return hits, values


def _in_file_name(stem: str, edition: str) -> bool:
    """The edition in the file name: not inside a longer letter/digit run, not the start of '2019-06-01' or '2019.5'."""
    body = r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", edition))
    return bool(
        re.search(
            r"(?<![0-9A-Za-z])" + body + r"(?![0-9A-Za-z])(?![.,:/\-][0-9])",
            stem,
            re.IGNORECASE,
        )
    )


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
        if _in_file_name(stem, edition):
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
        hits, values = [], set()
        for page in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? AND page_no <= ? ORDER BY page_no",
            (doc, EDITION_PAGES),
        ).fetchall():
            h, v = _page_lines(page["page_no"], page["text"] or "", edition)
            hits += h
            values |= v
        # two labelled lines with DIFFERENT values in pages 1-3: the same date repeated (a running header) is fine
        if hits and values == {want}:
            matches.append(
                {
                    "status": "confirmed",
                    "doc": doc,
                    "page": hits[0]["page"],
                    "quote": hits[0]["quote"],
                }
            )
    if len(matches) == 1:
        return matches[0]
    return _not_confirmed("two documents match" if matches else "edition not printed")


def resolve_edition(conn, candidates, standard: str, edition: str) -> str | None:
    """The confirmed document id, else None (see `edition_evidence`)."""
    found = edition_evidence(conn, candidates, standard, edition)
    return found["doc"] if found["status"] == "confirmed" else None
