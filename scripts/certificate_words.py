"""Certificate check 8 (order 292.8): every stored rule's words are on the page it cites.

A rule is a quotation: `standard_requirements.source_text` is the sentence the extractor took from the page
`standard_requirements.page`. The citation is only worth anything if the sentence is really there. This check
looks for each rule's sentence in the text of its cited page (and the page after it, for a sentence that STARTS on the cited page and runs
over the page break), using the project's own folding (`standards._fold_for_page`: letters and digits only, so
line breaks, hyphenation and spacing do not matter). Not "70 percent alike": the whole sentence.

A page recognised by OCR is read through `page_ocr` (the recognised text), a page with a text layer through
`pages`. A rule that cites a page the document does not have, or has no sentence, is not proven either.

It lives in `scripts/` until the certificate store (cloud's item 7) reads it from the app; then it moves into
`backend/app` (a module nothing in the app imports fails the unused-module check).

    python scripts/certificate_words.py --db <copy.sqlite> [--document-id ID ...]

Pure apart from `read_rows` / `read_pages`, which only SELECT. Counts, requirement ids and reason codes: no
sentence, filename or page text leaves this module (CLAUDE.md rule 1). The result has the shape of every
certificate check (cloud's contract, #1309): `{check, state, counts, gaps}` plus `flags`, the
`(requirement_id, reason)` pairs the converter and the review read instead of working them out again.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import standards  # noqa: E402

CHECK = "exact_words"
#: Reasons a rule is not proven. Codes, never text.
NOT_ON_PAGE, NO_PAGE, NO_SENTENCE, TOO_SHORT = (
    "words_not_on_page",
    "page_not_in_document",
    "no_sentence",
    "sentence_too_short_to_prove",
)
#: A stored sentence shorter than this (letters and digits only) would match almost anywhere on a page, so finding
#: it proves nothing. A FIRST VALUE (cloud-3's suggestion on #1457), not measured.
MIN_FOLDED_CHARS = 20
#: A standard where more than this share of its rules is unproven FAILS the check; fewer is a named gap.
#: A FIRST VALUE, not measured: the planner's number (cloud's plan item N). Zero unproven passes.
FAIL_SHARE = 0.10


def read_rows(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """The standard's active rules: id, page, sentence and whether the extractor itself flagged the text."""
    cur = conn.execute(
        "SELECT id, page, source_text, quality_reason FROM standard_requirements"
        " WHERE standard_document_id = ? AND superseded_at IS NULL",
        (document_id,),
    )
    return [
        {"id": r[0], "page": r[1], "source_text": r[2], "quality_reason": r[3]}
        for r in cur
    ]


def read_pages(conn: sqlite3.Connection, document_id: str) -> dict[int, str]:
    """Folded text per page: the recognised text where OCR read the page, else the text layer."""
    pages: dict[int, str] = {}
    for number, text in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
    ):
        pages[number] = standards._fold_for_page(text)
    for number, text in conn.execute(
        "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL AND text != ''",
        (document_id,),
    ):  # a page whose recognition FAILED keeps its (empty) row: it is not recognised text
        pages[number] = standards._fold_for_page(text)
    return pages


def _reason(row: dict, pages: dict[int, str]) -> str | None:
    """Why this rule's words are not proven on its page, or None when they are."""
    probe = standards._fold_for_page(row.get("source_text") or "")
    if not probe:
        return NO_SENTENCE
    if len(probe) < MIN_FOLDED_CHARS:
        return TOO_SHORT
    page = row.get("page")
    if page is None or page not in pages:
        return NO_PAGE
    here = pages[page]
    if probe in here:
        return None
    # a sentence that runs over the page break STARTS on the cited page: a match that begins on the next page
    # is the next page's sentence, not this one's
    joined = here + pages.get(page + 1, "")
    start = joined.find(probe)
    if start != -1 and start < len(here):
        return None
    return NOT_ON_PAGE


def check(rows: list[dict], pages: dict[int, str]) -> dict:
    """The check's result over folded `pages`. Rows the extractor already flagged as unreadable text
    (`quality_reason`) are counted apart: their words are NOT expected to match, and they are listed, not
    failed twice."""
    flags: list[tuple[str, str]] = []
    unreadable = 0
    proven = 0
    for row in rows:
        reason = _reason(row, pages)
        if reason is None:
            proven += 1
        elif row.get("quality_reason"):
            unreadable += 1
        else:
            flags.append((row["id"], reason))
    unproven = len(flags)
    judged = proven + unproven
    by_reason: dict[str, int] = {}
    for _id, reason in flags:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    share = (unproven / judged) if judged else None
    if not rows:
        state = "not_run"
    elif unproven == 0:
        state = "passed"
    elif share is not None and share > FAIL_SHARE:
        state = "failed"
    else:
        state = "gap"
    gaps = (
        [
            f"{n} rule(s) {reason.replace('_', ' ')}"
            for reason, n in sorted(by_reason.items())
        ]
        if unproven
        else []
    )
    if unreadable:
        gaps.append(f"{unreadable} rule(s) with unreadable text listed apart")
    return {
        "check": CHECK,
        "state": state,
        "counts": {
            "rules": len(rows),
            "proven": proven,
            "unproven": unproven,
            "unreadable_listed": unreadable,
            "unproven_share": None if share is None else round(share, 4),
            "by_reason": by_reason,
        },
        "gaps": gaps,
        "flags": flags,
    }


def run(conn: sqlite3.Connection, document_id: str) -> dict:
    """The check for one standard document, read-only."""
    return check(read_rows(conn, document_id), read_pages(conn, document_id))


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--document-id", action="append", default=[])
    args = p.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path) or not path.exists():
        raise SystemExit(
            f"refusing: {path} is a live database or does not exist. Use a copy."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ids = args.document_id or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT standard_document_id FROM standard_requirements"
                " WHERE superseded_at IS NULL"
            )
        ]
        report = {i: run(conn, i) for i in sorted(ids)}
    finally:
        conn.close()
    for result in report.values():
        result["flags"] = len(
            result["flags"]
        )  # ids stay in the database; the printout is counts only
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
