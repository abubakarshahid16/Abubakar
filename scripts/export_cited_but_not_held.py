"""Export `standards_inventory.cited_but_not_held` to an Excel workbook for
the owner (owner order, 2026-09-24). Deliberately written to .cowork\\, never
committed - it is a working export of live data, not a source artifact, and
CLAUDE.md rule 1 keeps document-derived content off any tracked path.

One row per missing standard: family, number, cited edition (if the citing
text names one - blank otherwise, never guessed), times cited, whether a
submittal cites it, whether a SAES requirement cites it. Sorted by times
cited, most-cited first. A second sheet summarises by family.

Read-only against a `mode=ro` connection - this script never writes.

    python scripts/export_cited_but_not_held.py --db backend/data/rag_intelligence.sqlite --out .cowork/cited-but-not-held.xlsx
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

#: An edition/revision mentioned NEAR a citation in the citing text - "API
#: 610 11th Edition", "ASME B31.3-2020", "Rev. C" immediately after the
#: standard's own name. Searched only in a short window right after the
#: identifier, so an edition belonging to a DIFFERENT, later-mentioned
#: standard in the same sentence is never attributed to this one.
#: THE HYPHEN ALTERNATIVE STANDS OUTSIDE THE LEADING `\b`, deliberately. The
#: search runs on a SNIPPET sliced right after the identifier - "ASME
#: B31.3-2020" becomes the snippet "-2020...", and a `\b` anchored before a
#: non-word character like "-" can never match at position 0 of a sliced
#: string (there is no earlier character left for it to see). The other
#: alternatives all start with a word character, where `\b` at position 0
#: is meaningful and correct.
_EDITION_NEAR = re.compile(
    r"(?:\b(?:\d{4}\s*Edition|\d{1,2}(?:st|nd|rd|th)\s+Edition"
    r"|Edition\s+\d{1,2}|Rev(?:ision)?\.?\s*[A-Z0-9]{1,3})"
    r"|-\s?\d{4}\b)",
    re.IGNORECASE)
_EDITION_WINDOW = 30


def _edition_near(text: str, identifier: str) -> str | None:
    idx = text.find(identifier)
    if idx == -1:
        return None
    snippet = text[idx + len(identifier):idx + len(identifier) + _EDITION_WINDOW]
    match = _EDITION_NEAR.search(snippet)
    return match.group(0).strip() if match else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app import db, live_guard
    from app.config import settings
    from app.standards_inventory import cited_but_not_held

    target = args.db.resolve()
    # READ-ONLY, ALWAYS VIA A DIAGNOSTIC COPY when the target is the live
    # database - `db.connect()` refuses a live-shaped path outright, and
    # this script has no business asking for write clearance since it never
    # writes. A non-live path (a disposable test copy) is opened directly.
    if live_guard.is_live_shaped(target):
        target = live_guard.diagnostic_copy(target)
    settings.db_path = target
    db.reset_connection()
    conn = db.connect()
    all_ids = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))

    rows = cited_but_not_held(allowed_document_ids=all_ids)

    # Re-fetch each citing source's text once, to look for a nearby edition
    # mention - `cited_but_not_held` itself discards the surrounding text
    # once it has extracted the bare identifier, so this is a second,
    # read-only pass over the same rows, never a guess from the identifier
    # alone.
    text_cache: dict[str, str] = {}

    def _text_for(citation: dict) -> str:
        if citation["source_type"] == "submittal":
            key = f"sub:{citation['document_id']}"
            if key not in text_cache:
                chunks = conn.execute(
                    "SELECT text FROM chunks WHERE document_id = ?",
                    (citation["document_id"],)).fetchall()
                text_cache[key] = " ".join(c["text"] or "" for c in chunks)
            return text_cache[key]
        key = f"req:{citation['document_id']}:{citation.get('clause')}:{citation.get('page')}"
        if key not in text_cache:
            row = conn.execute(
                "SELECT COALESCE(source_text, requirement_text) AS text"
                " FROM standard_requirements WHERE standard_document_id = ?"
                " AND clause IS ? AND page IS ? LIMIT 1",
                (citation["document_id"], citation.get("clause"),
                 citation.get("page"))).fetchone()
            text_cache[key] = (row["text"] if row else "") or ""
        return text_cache[key]

    export_rows = []
    for r in rows:
        cited_by_submittal = any(
            c["source_type"] == "submittal" for c in r["cited_by"])
        cited_by_requirement = any(
            c["source_type"] == "requirement" for c in r["cited_by"])
        edition = None
        for citation in r["cited_by"]:
            edition = _edition_near(_text_for(citation), r["identifier"])
            if edition:
                break
        export_rows.append({
            "family": r["standard_family"],
            "number": r["identifier"],
            "edition": edition or "",
            "times_cited": len(r["cited_by"]),
            "by_submittal": "Y" if cited_by_submittal else "N",
            "by_requirement": "Y" if cited_by_requirement else "N",
        })
    export_rows.sort(key=lambda d: -d["times_cited"])

    wb = Workbook()
    ws = wb.active
    ws.title = "Missing Standards"
    headers = ["Family", "Number", "Cited Edition", "Times Cited",
               "Cited by Submittals", "Cited by SAES Requirements"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for d in export_rows:
        ws.append([d["family"], d["number"], d["edition"], d["times_cited"],
                  d["by_submittal"], d["by_requirement"]])
    for column_cells in ws.columns:
        width = max(len(str(c.value or "")) for c in column_cells) + 2
        ws.column_dimensions[column_cells[0].column_letter].width = min(width, 40)

    summary = wb.create_sheet("Summary by Family")
    summary.append(["Family", "Missing Standards", "Total Citations"])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    fam_counts: Counter = Counter()
    fam_citations: Counter = Counter()
    for d in export_rows:
        fam_counts[d["family"]] += 1
        fam_citations[d["family"]] += d["times_cited"]
    for family in sorted(fam_counts):
        summary.append([family, fam_counts[family], fam_citations[family]])
    for column_cells in summary.columns:
        width = max(len(str(c.value or "")) for c in column_cells) + 2
        summary.column_dimensions[column_cells[0].column_letter].width = width

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    db.reset_connection()
    print(f"wrote {len(export_rows)} missing standards to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
