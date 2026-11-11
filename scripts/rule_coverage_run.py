#!/usr/bin/env python
"""Coverage of numeric requirements by compiled rules, for every standard of the private copy. Read only.

    python scripts/rule_coverage_run.py [--db agent-copy.sqlite] [--rules-db psv-all.sqlite]

Pages and the list of standards come from `--db` (document found by file name = rulebook_rule.standard). A standard that
`--rules-db` also holds takes its rules from there (the newer compile). Writes ~/project/mirror/trace/coverage/<standard>.json
(sentence text stays in those local files) and _summary.json. Prints counts only, never a sentence.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import rule_coverage as rc  # noqa: E402
from app import rule_finish_guard as guard  # noqa: E402
from app import rule_finish_store as st  # noqa: E402
from app.compiled_rule_report import pages_of  # noqa: E402

HOME = Path.home()
DB = HOME / "project/mirror/proof/agent-test/db/agent-copy.sqlite"
RULES_DB = HOME / "project/mirror/proof/db/compile/psv-all.sqlite"
OUT = HOME / "project/mirror/trace/coverage"
RED, RESET = "\033[31m", "\033[0m"
FIRST = "SAES-J-600.pdf"
REGISTRY = HOME / "project/mirror/checklists/.index-registry.json"


def partly_compiled() -> set[str]:
    """File names the checklist registry marks compile_status = partial (not every page answered)."""
    try:
        rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["standards"]
    except (OSError, ValueError, KeyError):
        return set()
    rows = rows.values() if isinstance(rows, dict) else rows
    return {
        r["file_name"]
        for r in rows
        if isinstance(r, dict) and r.get("compile_status") == "partial"
    }


def write_private(path: Path, text: str) -> None:
    """A local file that only the owner reads (it holds sentence text for the later compile step): mode 0600."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(0o600)


def ro(path: Path) -> sqlite3.Connection:
    conn = guard.open_read_only(path)
    conn.row_factory = sqlite3.Row
    return conn


def standards_of(conn) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT standard FROM rulebook_rule ORDER BY standard"
        )
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--rules-db", type=Path, default=RULES_DB)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if not args.out.resolve().is_relative_to(OUT.parent.resolve()):
        raise SystemExit(f"refused: --out must be inside {OUT.parent}")
    conn, newer = ro(args.db), ro(args.rules_db)
    newer_standards = set(standards_of(newer))
    names = sorted(
        set(standards_of(conn)) | newer_standards, key=lambda s: (s != FIRST, s)
    )
    args.out.mkdir(parents=True, exist_ok=True)
    summary, errors = [], []
    partial = partly_compiled()
    for name in names:
        try:
            doc = conn.execute(
                "SELECT id, page_count, pages_done, status FROM documents WHERE filename = ?",
                (name,),
            ).fetchone()
            if doc is None:
                summary.append(
                    {
                        "standard": name,
                        "document": None,
                        "problem": "document_not_found",
                    }
                )
                print(f"{RED}{name} | document not found{RESET}")
                continue
            pages = pages_of(conn, doc["id"])
            rules = st.load_rules(
                newer if name in newer_standards else conn, standard=name
            )
            result = rc.numeric_clause_coverage(pages, rules)
            read = len(pages) == (doc["page_count"] or len(pages)) and all(
                (t or "").strip() for t in pages.values()
            )
            row = {
                "standard": name,
                "document": doc["id"],
                "rules": len(rules),
                "rules_from": args.rules_db.name
                if name in newer_standards
                else args.db.name,
                "pages": len(pages),
                "page_count": doc["page_count"],
                "all_pages_read": read,
                "partly_read": not read,
                "partly_compiled": name in partial,
                "numeric": result["numeric"],
                "covered": result["covered"],
                "uncovered": result["uncovered"],
            }
            write_private(
                args.out / f"{name}.json",
                json.dumps(
                    {**row, "items": [i for i in result["items"] if not i["covered"]]},
                    indent=1,
                ),
            )
            summary.append(row)
            note = ("" if read else " | PAGES NOT ALL READ") + (
                " | PARTLY COMPILED" if name in partial else ""
            )
            print(
                f"{name} | numeric {row['numeric']} | covered {row['covered']} | uncovered {row['uncovered']}{note}"
            )
        except Exception as exc:  # noqa: BLE001 - printed in red, counted, exit code 1
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"{RED}{name} | error {type(exc).__name__}: {exc}{RESET}")
    ok = [s for s in summary if "numeric" in s]
    total = {k: sum(s[k] for s in ok) for k in ("numeric", "covered", "uncovered")}
    top = sorted(ok, key=lambda s: -s["uncovered"])[:5]
    write_private(
        args.out / "_summary.json",
        json.dumps(
            {
                "total": total,
                "standards": len(names),
                "errors": errors,
                "top_uncovered": [(s["standard"], s["uncovered"]) for s in top],
                "rows": summary,
            },
            indent=1,
        ),
    )
    print(f"TOTAL standards {len(names)} | {total}")
    for s in top:
        print(f"  top uncovered: {s['standard']} {s['uncovered']}")
    if errors:
        print(f"{RED}Problems: {len(errors)} standard(s) raised an error{RESET}")
        return 1
    print("Problems: none (no standard raised an error)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
