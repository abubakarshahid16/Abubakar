"""Certificate check 7 (order 292.7): every stored rule's clause number is printed on the page it cites, in the
standard's own numbering style.

A rule's `clause` ("5.3.4", "UG-22") is a citation: a CRS row quotes it and an engineer looks it up. Two things
make it worth quoting. (1) The number is PRINTED at the start of a line on the cited page (or the page before
it: a heading that ends one page, a rule whose text starts the next). A number that is only inside a
sentence ("see 5.3") does not count. (2) It is written in the style the standard itself uses: the dominant
shape among its stored clauses (`clause_numbering_report.style_of`), so a heading number taken off a numbered
list or a page header ("2.", "1-1" in a decimal standard) is flagged. The style test needs a dominant style
(at least `DOMINANT_SHARE` of the clauses that carry one); without it the test is not run and the counts say so.

A rule with no clause is counted apart (`no_clause_listed`), not failed: it cites no number, so nothing false
is cited. A rule the extractor flagged as unreadable text is listed apart, as in check 8.

It lives in `scripts/` until the certificate store (cloud's item 7) reads it from the app.

    python scripts/certificate_clause.py --db <copy.sqlite> [--document-id ID ...]

Pure apart from `read_rows` / `read_pages`, which only SELECT. Counts, requirement ids and reason codes: no
sentence, clause value or page text leaves this module (CLAUDE.md rule 1). Result shape as every certificate
check: `{check, state, counts, gaps, flags}`. FAIL_SHARE and DOMINANT_SHARE are FIRST VALUES, not measured.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import clause_numbering_report as numbering  # noqa: E402

CHECK = "clause_printed"
NOT_PRINTED, NO_PAGE, WRONG_STYLE = (
    "clause_not_printed_on_page",
    "page_not_in_document",
    "clause_style_not_the_standards",
)
#: A standard where more than this share of its rules is unproven FAILS; fewer is a named gap. FIRST VALUE.
FAIL_SHARE = 0.10
#: The style the most clauses share counts as "the standard's own" only above this share. FIRST VALUE.
DOMINANT_SHARE = 0.6


def read_rows(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT id, page, clause, quality_reason FROM standard_requirements"
        " WHERE standard_document_id = ? AND superseded_at IS NULL",
        (document_id,),
    )
    return [
        {"id": r[0], "page": r[1], "clause": r[2], "quality_reason": r[3]} for r in cur
    ]


def read_pages(conn: sqlite3.Connection, document_id: str) -> dict[int, str]:
    """Raw page text (line breaks kept): the recognised text where OCR read the page, else the text layer."""
    pages: dict[int, str] = {}
    for number, text in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
    ):
        pages[number] = text or ""
    for number, text in conn.execute(
        "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL AND text != ''",
        (document_id,),
    ):
        pages[number] = text
    return pages


def _clean(clause: str | None) -> str:
    return (clause or "").strip().rstrip(".")


def printed_on(clause: str, text: str) -> bool:
    """The clause number starts a line of `text` and is not the front of a longer number ("7.1" in "7.16")."""
    pattern = r"(?m)^[ \t]*\(?" + re.escape(clause) + r"(?![0-9A-Za-z]|[.\-]\d)"
    return re.search(pattern, text) is not None


def dominant_style(rows: list[dict]) -> str | None:
    styles = Counter(
        s
        for s in (numbering.style_of(r.get("clause")) for r in rows)
        if s not in ("none", "other")
    )
    total = sum(styles.values())
    if not total:
        return None
    style, n = styles.most_common(1)[0]
    return style if n / total >= DOMINANT_SHARE else None


def _reason(row: dict, pages: dict[int, str], style: str | None) -> str | None:
    clause = _clean(row.get("clause"))
    page = row.get("page")
    if page is None or page not in pages:
        return NO_PAGE
    if not (
        printed_on(clause, pages[page]) or printed_on(clause, pages.get(page - 1, ""))
    ):
        return NOT_PRINTED
    if style is not None and numbering.style_of(clause) not in (style, "other"):
        return WRONG_STYLE
    return None


def check(rows: list[dict], pages: dict[int, str]) -> dict:
    style = dominant_style(rows)
    flags: list[tuple[str, str]] = []
    proven = unreadable = no_clause = 0
    for row in rows:
        if not _clean(row.get("clause")):
            no_clause += 1
            continue
        reason = _reason(row, pages, style)
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
    if not judged:
        state = "not_run"
    elif unproven == 0:
        state = "passed"
    elif share is not None and share > FAIL_SHARE:
        state = "failed"
    else:
        state = "gap"
    gaps = [f"{n} rule(s) {r.replace('_', ' ')}" for r, n in sorted(by_reason.items())]
    if unreadable:
        gaps.append(f"{unreadable} rule(s) with unreadable text listed apart")
    if no_clause:
        gaps.append(f"{no_clause} rule(s) cite no clause number")
    if style is None and judged:
        gaps.append("no dominant clause style: the style test was not run")
    return {
        "check": CHECK,
        "state": state,
        "counts": {
            "rules": len(rows),
            "proven": proven,
            "unproven": unproven,
            "no_clause_listed": no_clause,
            "unreadable_listed": unreadable,
            "dominant_style": style,
            "unproven_share": None if share is None else round(share, 4),
            "by_reason": by_reason,
        },
        "gaps": gaps,
        "flags": flags,
    }


def run(conn: sqlite3.Connection, document_id: str) -> dict:
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
        result["flags"] = len(result["flags"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
