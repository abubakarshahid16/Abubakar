"""Order 264.4 / 260 change 5: how many "requires another document" verdicts were sent away wrongly.

`comparison.compare` sends a requirement to NOT_IN_DOCUMENT_SCOPE ("requires_other_document")
when `requirements_3b.required_evidence_type` finds a submission verb AND a document noun in its
sentence, with no check that the noun is what must be handed over. This reads the stored findings
of ONE review run on a COPY, takes a fixed sample (first N by a hash of the finding id), and puts
each row in exactly one class by re-reading its sentence in memory:

  noun_inside_longer_word   the noun is only part of another word ("plan" in "planetary")
  fitment_provided_with     "provided / supplied with ..." names a part of the equipment
  noun_far_from_verb        the noun is more than WINDOW words from every submission verb
  weak_noun_only            only plan / record / report / procedure matched
  plausible_deliverable     none of the above: a document really is asked for

The first four are the ways it is sent away wrongly; the last is the only one that should stay.
Counts only: no sentence, filename, page or clause number is printed (CLAUDE.md rule 1). With
`--ids-out FILE` the finding ids per class go to a local file, so an engineer can open the rows
on screen; ids are not document text. Read-only, and on a COPY only (a live-shaped path is refused).

    python scripts/sample_other_document_gate.py --db <copy.sqlite> --review-run <id> [--sample 30]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

MARK = "requires_other_document"
STATUS = "NOT_IN_DOCUMENT_SCOPE"
WINDOW = 8
WEAK = frozenset(["plan", "record", "report", "procedure"])
CLASSES = (
    "noun_inside_longer_word",
    "fitment_provided_with",
    "noun_far_from_verb",
    "weak_noun_only",
    "plausible_deliverable",
)
_WITH = re.compile(r"^\s*(?:\w+\s+){0,4}?(?:with|in)\b", re.IGNORECASE)


def classify(sentence: str) -> str | None:
    """The class of one sentence, or None when the current rule would not send it away at all."""
    from app import requirements_3b as r3

    text = sentence or ""
    if r3.required_evidence_type(text) in (None, r3.DATA_SHEET_EVIDENCE):
        return None
    low = text.lower()
    nouns = [n for n, _kind in r3._EVIDENCE_NOUNS if n in low]
    whole = [n for n in nouns if re.search(rf"\b{re.escape(n)}s?\b", low)]
    if not whole:
        return "noun_inside_longer_word"
    verbs = list(r3._EVIDENCE_VERB.finditer(text))
    words = [
        (m.start(), m.group().lower()) for m in re.finditer(r"[A-Za-z0-9'-]+", text)
    ]

    def gap(noun_at: int, verb) -> int:
        a, b = sorted((noun_at, verb.start()))
        return sum(1 for s, _w in words if a < s < b)

    near = [n for n in whole if any(gap(low.index(n), v) <= WINDOW for v in verbs)]
    if not near:
        return "noun_far_from_verb"
    fit = [
        v
        for v in verbs
        if _WITH.match(text[v.end() :])
        and v.group().lower().startswith(("provid", "suppl", "furnish"))
    ]
    if (
        fit
        and all(
            any(gap(low.index(n), v) <= WINDOW and v in fit for v in verbs)
            for n in near
        )
        and not any(
            any(gap(low.index(n), v) <= WINDOW and v not in fit for v in verbs)
            for n in near
        )
    ):
        return "fitment_provided_with"
    if all(n in WEAK for n in near):
        return "weak_noun_only"
    return "plausible_deliverable"


def sample_rows(
    conn: sqlite3.Connection, review_run: str, size: int
) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT id, COALESCE(requirement_source_text, requirement, '') FROM review_findings "
        "WHERE review_run_id = ? AND compliance_status = ? AND ai_rationale LIKE ?",
        (review_run, STATUS, f"%{MARK}%"),
    ).fetchall()
    rows.sort(key=lambda r: hashlib.sha1(str(r[0]).encode()).hexdigest())
    return [(str(i), t) for i, t in rows[:size]]


def count(conn: sqlite3.Connection, review_run: str, size: int):
    counts = dict.fromkeys(CLASSES, 0)
    ids: dict[str, list[str]] = {c: [] for c in CLASSES}
    sample = sample_rows(conn, review_run, size)
    for fid, text in sample:
        kind = classify(text) or "not_sent_away_by_current_rule"
        counts[kind] = counts.get(kind, 0) + 1
        ids.setdefault(kind, []).append(fid)
    total = conn.execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ? AND compliance_status = ? "
        "AND ai_rationale LIKE ?",
        (review_run, STATUS, f"%{MARK}%"),
    ).fetchone()[0]
    return {"sent_away_in_run": total, "sampled": len(sample), "classes": counts}, ids


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--review-run", required=True)
    p.add_argument("--sample", type=int, default=30)
    p.add_argument("--ids-out", type=Path)
    args = p.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path) or not path.exists():
        raise SystemExit(
            f"refusing: {path} is a live database or does not exist. Use a copy."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        report, ids = count(conn, args.review_run, args.sample)
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.ids_out:
        args.ids_out.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
