"""What a standard SAYS versus what the system STORED, page by page.

THE QUESTION THIS ANSWERS: "how do I know it did not miss anything?"

Today a missed requirement is silent. The extractor reads a page, matches
the phrasings it knows, and says nothing at all about the sentences it
walked past. A standard written with wording nobody listed produces fewer
rules and looks exactly like a standard that genuinely had fewer rules.
That is the failure mode that cost this corpus its primary noise limit:
SAES-A-105 5.3.3 states "shall not generate noise in excess of 90 dB(A)"
and its four exceptions as "may not exceed 105/97/105/115 dB(A)". Only the
exceptions parsed. The database held the exceptions to a rule it did not
hold, and nothing anywhere said so.

This does not fix extraction. It makes the gap VISIBLE and countable, so a
newly uploaded standard can be checked in seconds instead of trusted.

IT IS DELIBERATELY CRUDE, and reads high. A sentence is called a candidate
when it carries a mandatory verb, a number and a unit. Plenty of those are
cross-references ("shall be in accordance with SAEP-35"), process
instructions ("shall be reviewed with the operating organization") or
table headers, and the extractor is RIGHT to skip them. So the miss count
is an upper bound on what was lost, never a defect count. Its value is
comparative: a standard reporting 40 of 45 unmatched deserves a look, one
reporting 3 of 45 does not, and the same standard's number moving after a
parser change tells you the change worked.

Read-only. Takes a database path so it runs against a copy.

    python scripts/coverage_report.py backend/data/rag_intelligence.sqlite
    python scripts/coverage_report.py <db> --standard SAES-A-105 --show 20
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys

MANDATORY = re.compile(
    r"\b(shall|must|may\s+not|shall\s+not|must\s+not|is\s+required\s+to"
    r"|are\s+required\s+to|is\s+to\s+be|are\s+to\s+be)\b", re.I)
NUMBER = re.compile(r"\d")
UNIT = re.compile(
    r"\b(mm|cm|m|km|kg|g|bar|psi|psig|kPa|MPa|dB|dBA|°C|°F|%|mA|V|kV"
    r"|Hz|micron|um|in|ft|gpm|NPS|lux|fc)\b", re.I)
#: Phrasings that carry a number but state no limit of their own.
DEFERRAL = re.compile(
    r"\b(in\s+accordance\s+with|as\s+specified\s+in|refer\s+to|as\s+per"
    r"|conform\s+to|comply\s+with|as\s+defined\s+in|see\s+(table|figure))\b",
    re.I)


def sentences(text: str):
    for raw in re.split(r"(?<=[.;])\s+", text or ""):
        one = " ".join(raw.split())
        if one:
            yield one


def candidates(conn, document_id: str):
    """Sentences that LOOK like a numeric obligation, per page."""
    out = []
    rows = conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,))
    for row in rows:
        for one in sentences(row["text"]):
            if (MANDATORY.search(one) and NUMBER.search(one)
                    and UNIT.search(one) and not DEFERRAL.search(one)):
                out.append((row["page_no"], one))
    return out


def stored_texts(conn, document_id: str) -> set[str]:
    """The first 60 characters of every source_text already extracted.

    Matching on a prefix rather than the whole string because the stored
    text is a trimmed span of the sentence, not the sentence.
    """
    return {
        " ".join((r["source_text"] or "").split())[:60]
        for r in conn.execute(
            "SELECT source_text FROM standard_requirements"
            " WHERE standard_document_id = ?", (document_id,))
        if r["source_text"]}


def report(db_path: str, only: str | None, show: int) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT d.id, d.filename FROM documents d"
           " JOIN document_classification k ON k.document_id = d.id"
           " WHERE k.document_role = 'COMPANY_STANDARD'")
    args: tuple = ()
    if only:
        sql += " AND d.filename LIKE ?"
        args = (f"%{only}%",)
    docs = conn.execute(sql + " ORDER BY d.filename", args).fetchall()
    if not docs:
        print("no standards matched")
        return 1

    print(f"{'standard':34} {'candidates':>10} {'unmatched':>10} {'rules':>7}")
    print("-" * 66)
    worst = []
    tot_c = tot_u = 0
    for doc in docs:
        cands = candidates(conn, doc["id"])
        stored = stored_texts(conn, doc["id"])
        missed = [(p, s) for p, s in cands if s[:60] not in stored]
        rules = conn.execute(
            "SELECT COUNT(*) FROM standard_requirements"
            " WHERE standard_document_id = ? AND requirement_type IN"
            " ('numeric_limit','table_row','relative_limit')",
            (doc["id"],)).fetchone()[0]
        tot_c += len(cands)
        tot_u += len(missed)
        worst.append((len(missed), len(cands), doc["filename"], missed))
        print(f"{doc['filename'][:34]:34} {len(cands):10} "
              f"{len(missed):10} {rules:7}")

    print("-" * 66)
    print(f"{'TOTAL':34} {tot_c:10} {tot_u:10}")
    print()
    print("A candidate is a mandatory sentence with a number and a unit,")
    print("excluding cross-references. Unmatched is an UPPER BOUND on what")
    print("was lost: many are process instructions the parser rightly skips.")

    if show:
        worst.sort(reverse=True)
        print(f"\n--- the {show} least-covered sentences ---")
        shown = 0
        for _, _, name, missed in worst:
            for page, text in missed:
                print(f"\n{name[:30]} p{page}:\n  {text[:190]}")
                shown += 1
                if shown >= show:
                    return 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("database")
    ap.add_argument("--standard", default=None,
                    help="filename fragment, e.g. SAES-A-105")
    ap.add_argument("--show", type=int, default=0,
                    help="print this many unmatched sentences")
    args = ap.parse_args()
    return report(args.database, args.standard, args.show)


if __name__ == "__main__":
    sys.exit(main())
