"""LANE G (order 14): the contract's edition cutoff replayed on a STORED review run. READ ONLY, no model, no network.

    EDITION_CUTOFF_FILE=<local cutoff file> python scripts/edition_replay.py <run id> --db <COPY> [--contract <name>] [--json <file>]

The contract's cutoff is read from the local file EDITION_CUTOFF_FILE names (values read from a contract never go in git).

For every rule book the run cites (its lines' rule books and its missing-book list): the held document, the issue date the
book PRINTS (`agent_edition.issue_date`: a labelled line on its first pages, verified on the page, else the year in its file
name), and what the contract's cutoff says of it (`standard_editions.against_cutoff`): the held
edition binds, is later (for information only), cannot be told, or is not known. Prints ids, book names, dates and pages.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))


def cited_books(conn, run_id: str) -> tuple[list[str], list[str]]:
    """(books the run's lines cite, books the run lists as not held), each once, in order."""
    cited = [r[0] for r in conn.execute(
        "SELECT rule_book, COUNT(*) FROM agent_review_line WHERE run_id = ? AND COALESCE(rule_book, '') <> ''"
        " GROUP BY rule_book ORDER BY COUNT(*) DESC, rule_book", (run_id,))]  # fmt: skip
    missing = [r[0] for r in conn.execute(
        "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name", (run_id,))]  # fmt: skip
    return cited, missing


def paper_cites(conn, run_id: str) -> dict[str, tuple[str, str | None]]:
    """{key: (identifier as printed, the edition year printed after it or None)} over the paper's own pages."""
    from app import cited_edition

    paper = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    text = "\n".join(r[0] or "" for r in conn.execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no", (paper[0] if paper else "",)))  # fmt: skip
    return cited_edition.cited_years(text)


def _cited_year(cites: dict, name: str) -> str | None:
    from app import standard_ids

    years = {
        y
        for ident, y in cites.values()
        if y and standard_ids.same_standard(name, ident)
    }
    return next(iter(years)) if len(years) == 1 else None


def replay(db: str, run_id: str, contract: str = "project-contract") -> dict:
    from app import agent_edition, applicability
    from app import standard_editions as se
    from app.agent_review_rules import library_of

    conn = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    policy = se.load_policies()[contract]
    library = library_of(conn)
    cited, missing = cited_books(conn, run_id)
    cites = paper_cites(conn, run_id)
    rows = []
    for name in dict.fromkeys([*cited, *missing]):
        entry = applicability.find_standard(library, name)
        if entry is None:
            rows.append({"book": name, "paper_cites": _cited_year(cites, name), "held_document": None, "printed": None,
                         "status": "book not held: edition not known", "binding": None, "caveat": "", "reason": ""})  # fmt: skip
            continue
        doc = entry.get("id") or entry.get("document_id")
        printed = agent_edition.issue_date(conn, doc)
        judged = se.against_cutoff(
            {"edition": printed["date"], "date": printed["date"]}, policy, name
        )
        rows.append(
            {
                "book": name,
                "paper_cites": _cited_year(cites, name),
                "held_document": doc,
                "printed": printed,
                **judged,
            }
        )
    conn.close()
    return {"run_id": run_id, "contract": contract, "cutoff": policy["date"], "rule": policy["rule"],
            "source": policy.get("source"), "books": rows,
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in dict.fromkeys(r["status"] for r in rows)}}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_id")
    ap.add_argument("--db", required=True)
    ap.add_argument("--contract", default="project-contract")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = replay(a.db, a.run_id, a.contract)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(
        f"run {a.run_id}  cutoff {rep['cutoff']} ({rep['rule']})  books {len(rep['books'])}  {rep['counts']}"
    )
    for r in rep["books"]:
        p = r["printed"] or {}
        where = f"p.{p['page']}" if p.get("page") else (p.get("source") or "")
        print(f"  {r['book']:<34} paper cites {r['paper_cites'] or '-':<5} held {r['held_document'] or '-':<20} printed {p.get('date') or '-':<11} {where:<30} -> {r['status']}"
              + (f"; binds: {r['binding']}" if r.get("binding") and r["status"] != "held edition binds" else ""))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
