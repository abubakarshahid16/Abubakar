"""Certificate check 9 (order 292.9): which stored rules sit outside the main body of their standard.

A limit under an appendix, a special-construction part or a worked example does not apply to every piece of
equipment, so such a rule cannot decide a verdict on its own: it needs an engineer-approved card (order 302.4).
This check reads each active rule's cited page, tags the page with `app.page_scope.tag_pages` (headings and running
headers, no standard named), and flags every rule whose page is not main body, or whose page holds a worked example.

It is a GAP, never a FAIL, for a rule to be outside the main body: nothing is wrong with the rule, it is held. What
makes the check unreliable is a rule whose page has no text to tag (a scanned page with no recognised text): those
are counted apart as `no_page_text`, because their scope is unknown, not main body. When more than `UNKNOWN_FAIL_SHARE`
of a standard's rules are in that state the check FAILS: it could not do its job.

It lives in `scripts/` until the certificate store (cloud's item 7) reads it from the app; then it moves into
`backend/app` (a module nothing in the app imports fails the unused-module check).

    python scripts/certificate_scope.py --db <copy.sqlite> [--document-id ID ...]

Pure apart from `read_rows` / `read_pages`, which only SELECT. Counts, requirement ids, region labels ("Appendix 9",
"Part UHT") and reason codes: no sentence, filename or page text leaves this module (CLAUDE.md rule 1). The result has
the shape of every certificate check (cloud's contract, #1309): `{check, state, counts, gaps}` plus `flags`, the
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

from app import page_scope  # noqa: E402

CHECK = "scope"
#: Reasons a rule is flagged. Codes, never text.
OUTSIDE = "outside_main_body"
IN_EXAMPLE = "in_worked_example"
NO_PAGE_TEXT = "no_page_text"
#: Above this share of rules with no page text to tag, the check could not do its job and FAILS. A FIRST VALUE, not
#: measured (the planner's number, like `certificate_words.FAIL_SHARE`).
UNKNOWN_FAIL_SHARE = 0.25


def read_rows(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT id, page FROM standard_requirements WHERE standard_document_id = ? AND superseded_at IS NULL",
        (document_id,),
    )
    return [{"id": r[0], "page": r[1]} for r in cur]


def read_pages(conn: sqlite3.Connection, document_id: str) -> dict[int, str]:
    """Page text with its line breaks (headings are read by line): the recognised text where OCR read the page,
    else the text layer."""
    pages: dict[int, str] = {}
    for number, text in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
    ):
        pages[number] = text or ""
    for number, text in conn.execute(
        "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL AND text != ''",
        (document_id,),
    ):  # a page whose recognition FAILED keeps its (empty) row: it is not recognised text
        pages[number] = text
    return pages


def check(rows: list[dict], pages: dict[int, str]) -> dict:
    """The check's result for the rules of ONE standard over its page texts."""
    tags = page_scope.tag_pages({n: t for n, t in pages.items() if (t or "").strip()})
    flags: list[tuple[str, str]] = []
    by_region: dict[str, int] = {}
    main = example = unknown = 0
    for row in rows:
        tag = tags.get(row.get("page"))
        if tag is None:
            unknown += 1
            flags.append((row["id"], NO_PAGE_TEXT))
        elif tag["example"]:
            example += 1
            flags.append((row["id"], IN_EXAMPLE))
        elif tag["scope"] != page_scope.MAIN:
            label = tag["region"] or tag["scope"]
            by_region[label] = by_region.get(label, 0) + 1
            flags.append((row["id"], OUTSIDE))
        else:
            main += 1
    outside = sum(by_region.values())
    judged = len(rows)
    unknown_share = (unknown / judged) if judged else None
    if not rows:
        state = "not_run"
    elif unknown_share is not None and unknown_share > UNKNOWN_FAIL_SHARE:
        state = "failed"
    elif outside or example or unknown:
        state = "gap"
    else:
        state = "passed"
    gaps = []
    for label, n in sorted(by_region.items()):
        gaps.append(f"{n} rule(s) under {label}")
    if example:
        gaps.append(f"{example} rule(s) in a worked example")
    if unknown:
        gaps.append(f"{unknown} rule(s) on a page with no text to tag")
    return {
        "check": CHECK,
        "state": state,
        "counts": {
            "rules": len(rows),
            "main_body": main,
            "outside_main_body": outside,
            "in_worked_example": example,
            "no_page_text": unknown,
            "no_page_text_share": None
            if unknown_share is None
            else round(unknown_share, 4),
            "by_region": by_region,
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
        result["flags"] = len(result["flags"])  # ids stay in the database; counts only
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
