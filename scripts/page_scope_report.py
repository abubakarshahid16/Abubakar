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
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--like", required=True)
    parser.add_argument("--pages", default="")
    args = parser.parse_args()
    import page_scope

    from app import db, live_guard
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
        tags = page_scope.tag_pages(pages)
        by_scope = collections.Counter(t["scope"] for t in tags.values())
        print(doc, "pages", len(tags), dict(sorted(by_scope.items())))
        print(
            "  pages with a worked example:", sum(t["example"] for t in tags.values())
        )
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
