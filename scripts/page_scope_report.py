"""Which pages of a standard are not main body, and how many stored limits are fragments or range ends? (order 305.3)
READ ONLY, counts only.

    python scripts/page_scope_report.py --like ASME [--pages 192,510,547,581] [--db PATH]

Takes a disposable copy of the database (`live_guard.diagnostic_copy`), reads the pages of each standard document
whose filename or document number contains `--like`, tags every page with `app.page_scope.tag_pages`, and counts:
pages per scope; the scope and region label of the pages named in `--pages`; and, over the document's current
numeric-limit requirement rows, how many sit on a page that is not main body, how many are fragments, and how many
have their limit at the end of a range. It prints counts and region labels ("Appendix 9", "Part UHT"), never a
sentence."""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


_KEEP = r"(?i:non-?\s?mandatory|mandatory|normative|informative|appendix|annex|part|example)"


def _mask(line: str) -> str:
    """The SHAPE of a heading line: its region words are kept, every other letter becomes a / A and every digit 9,
    so a post can show which line shapes open regions without quoting the standard."""
    import re

    out, pos = [], 0
    for m in re.finditer(_KEEP, line):
        out.append(
            re.sub(
                r"\d",
                "9",
                re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", line[pos : m.start()])),
            )
        )
        out.append(m.group(0))
        pos = m.end()
    out.append(
        re.sub(r"\d", "9", re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", line[pos:])))
    )
    return "".join(out)[:60]


def _accepted(page_scope, lines: list[str]) -> dict[int, str | None]:
    """For each line of a page that matches a region pattern: why did the tagger NOT accept it (None = accepted) (same rules as
    `tag_pages`: heading-shaped line, not on a contents page, `_is_region_heading`)?"""
    found = {
        i: page_scope._APPENDIX.match(ln) or page_scope._PART.match(ln)
        for i, ln in enumerate(lines)
        if page_scope._is_heading_line(ln)
    }
    found = {i: m for i, m in found.items() if m}
    if len(found) >= page_scope._CONTENTS_PAGE_HEADINGS:
        return dict.fromkeys(found, "contents_page")
    return {
        i: page_scope.heading_rejection(m, lines[i], i, lines[i - 1] if i else "")
        for i, m in found.items()
    }


def _region_openers(page_scope, pages: dict, tags: dict) -> collections.Counter:
    """For each page where the region changes, the mask of the line the tagger accepted as the heading, counted by
    (mask, top or low on the page)."""
    shapes: collections.Counter = collections.Counter()
    previous = None
    for number in sorted(tags):
        region = (tags[number]["scope"], tags[number]["region"])
        if region != previous and region[0] != "main_body":
            lines = [ln for ln in (pages.get(number) or "").splitlines() if ln.strip()]
            for i, why in sorted(_accepted(page_scope, lines).items()):
                if why is None:
                    shapes[
                        (
                            _mask(lines[i]),
                            "top" if i < page_scope._TOP_LINES else "low",
                        )
                    ] += 1
                    break
        previous = region
    return shapes


def _near_misses(page_scope, pages: dict) -> collections.Counter:
    """Lines that carry a region word (appendix / annex / part / mandatory ...) near the start of a line but were
    NOT accepted as a heading, counted by (mask, top or low, why). This is where a heading shape the tagger does not know
    shows up (a qualifier alone on its line, a label split over two lines, a heading with a lower-case title)."""
    import re

    word = re.compile(
        r"^\s*(?:non-?\s?mandatory\s+|mandatory\s+|normative\s+|informative\s+)?(?:appendix|annex|part|subsection)\b|^\s*(?:non-?\s?mandatory|mandatory)\s*$",
        re.IGNORECASE,
    )
    out: collections.Counter = collections.Counter()
    for number in sorted(pages):
        lines = [ln for ln in (pages.get(number) or "").splitlines() if ln.strip()]
        accepted = _accepted(page_scope, lines)
        for i, ln in enumerate(lines):
            why = accepted.get(i, "label_shape_not_known")
            if word.match(ln) and why is not None:
                where = "top" if i < page_scope._TOP_LINES else "low"
                out[(_mask(ln), where, why)] += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--like", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument(
        "--shapes",
        action="store_true",
        help="also print the masked shapes of the lines that open regions",
    )
    args = parser.parse_args()
    from app import db, live_guard, page_scope
    from app.config import settings

    settings.db_path = live_guard.diagnostic_copy(args.db or settings.db_path)
    db.reset_connection()
    conn = db.connect()
    like = f"%{args.like}%"
    docs = [
        r["id"]
        for r in conn.execute(
            "SELECT d.id FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id"
            " WHERE d.filename LIKE ? OR c.document_number LIKE ?",
            (like, like),
        )
    ]
    named = {int(p) for p in args.pages.split(",") if p.strip().isdigit()}
    for doc in sorted(docs):
        pages = {
            r["page_no"]: r["text"]
            for r in conn.execute(
                "SELECT page_no, text FROM pages WHERE document_id = ?", (doc,)
            )
        }
        for r in conn.execute(  # a scanned page has no text layer: its headings are in the recognised text
            "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL AND text != ''",
            (doc,),
        ):
            pages[r["page_no"]] = r["text"]
        tags = page_scope.tag_pages(pages)
        by_scope = collections.Counter(t["scope"] for t in tags.values())
        print(doc, "pages", len(tags), dict(sorted(by_scope.items())))
        print(
            "  pages with a worked example:", sum(t["example"] for t in tags.values())
        )
        if args.shapes:
            for (mask, where), n in _region_openers(
                page_scope, pages, tags
            ).most_common(25):
                print(f"  opener x{n} ({where}): {mask!r}")
            for (mask, where, why), n in _near_misses(page_scope, pages).most_common(
                30
            ):
                print(f"  not a heading x{n} ({where}, {why}): {mask!r}")
        for number in sorted(named & set(tags)):
            t = tags[number]
            print(
                f"  page {number}: {t['scope']} {t['region'] or ''} example={t['example']}"
            )
        rows = conn.execute(
            "SELECT page, value, raw_value, COALESCE(source_text, requirement_text) AS t"
            " FROM standard_requirements WHERE standard_document_id = ? AND superseded_at IS NULL"
            " AND requirement_type = 'numeric_limit'",
            (doc,),
        ).fetchall()
        off_main = sum(
            1
            for r in rows
            if tags.get(r["page"], {}).get("scope", "main_body") != "main_body"
        )
        fragments = sum(1 for r in rows if page_scope.fragment_reasons(r["t"]))
        ranges = sum(
            1
            for r in rows
            if r["raw_value"] and page_scope.range_boundary(r["t"], r["raw_value"])
        )
        print(
            f"  numeric-limit rows {len(rows)}: on a page that is not main body {off_main}, fragments {fragments}, range ends {ranges}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
