"""Check every review playbook's source quotes on the stored pages of the held books (order 14 lane P). READ ONLY.

    python scripts/playbook_quote_check.py --db <COPY of the database> [--out FILE]

Per element of every playbook in `backend/app/reference/playbooks/`: the book is looked up in the library the way the review does
(`applicability.find_standard` over `standards.list_standards`), and its quote is checked on the cited page with THE quote check of
gate G1 (`compiled_rule_proof.quote_verified`), through `playbooks.source_quote_checks`. A book not held must carry no quote ("book
missing"); a held book's element must carry a quote found on its page, and its `verified` flag must say so. Prints one line per element:
ids, book, clause, page and PASS / FAIL with the state; never the quote or any page text. Exit 0 when every line passes, 1 on any FAIL,
2 when refused (the live database, or no --db)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"


def lines(db_path: Path) -> tuple[list[str], bool]:
    """(the report lines, every line passed). The copy is opened read-only."""
    from app import playbooks, standards
    from app.config import settings

    settings.data_dir, settings.db_path = db_path.parent, db_path
    from app import db

    db.reset_connection()
    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    ids = frozenset(r[0] for r in ro.execute("SELECT id FROM documents"))
    library = standards.list_standards(
        allowed_document_ids=ids, include_superseded=True
    )

    def page_text(document_id: str, page: int) -> str | None:
        row = ro.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (document_id, page),
        ).fetchone()
        return row[0] if row else None

    found, broken = playbooks.available()
    out, ok = [], not broken
    out += [f"UNUSABLE {b['file']}: {b['reason']}" for b in broken]
    for pb in sorted(found.values(), key=lambda p: p.id):
        results = playbooks.source_quote_checks(pb, library, page_text)
        passed = sum(r["passed"] for r in results)
        out.append(f"{pb.id}: {passed} of {len(results)} elements pass")
        for r in results:
            ok = ok and r["passed"]
            page = f"page {r['page']}" if r["page"] else "no page"
            out.append(
                f"  {r['element']} {r['standard']} {r['clause']} {page}: {'PASS' if r['passed'] else 'FAIL'} ({r['state']})"
            )
    return out, ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument("--out", help="also write the lines to this file")
    args = ap.parse_args(argv)
    db_path = Path(args.db).resolve()
    if db_path == LIVE.resolve() or not db_path.is_file():
        print("refused: pass an existing COPY of the database, never the live one")
        return 2
    out, ok = lines(db_path)
    text = "\n".join(out) + "\n"
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
