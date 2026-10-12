"""Turn an engineer-checked question sheet into the JSON `eval/run_eval.py` reads.

WHY A SHEET AND NOT HAND-WRITTEN JSON. The shipped question set was written
against a reference corpus that is not in the owner's database: on 2026-09-29
only 4 of its 18 questions could run there (13 blocked, 1 stale), so a
prompt change could not be judged at all. A set for the real corpus has to
come from the real documents, and the eval's own rule is that the system's
author does not choose the questions (eval/questions.schema.json). So the
work is split: candidates are pulled from the documents (a page, a clause and
a verbatim line holding a value), and an ENGINEER writes each question in
their own words and marks the line verified. Only verified lines become
questions; everything else is refused with its line number, never guessed.

The sheet and the JSON quote client documents. Both stay out of git
(`gold/*.csv`, `gold/*.json`, `Claude outputs/`): CLAUDE.md rule 1.

    python scripts/questions_from_csv.py gold/QUESTIONS-real.csv gold/QUESTIONS-real.json
    python eval/run_eval.py --questions gold/QUESTIONS-real.json --tier generated
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

COLUMNS = ("id", "question", "answerable", "expected_document", "expected_pages",
           "expected_clause", "expected_answer_contains", "source_line",
           "engineer_verified", "note")


class SheetError(ValueError):
    """The sheet cannot be turned into questions honestly. Names the line."""


def _bool(text: str, where: str) -> bool:
    t = text.strip().lower()
    if t in ("true", "yes", "y", "1"):
        return True
    if t in ("false", "no", "n", "0"):
        return False
    raise SheetError(f"{where}: answerable must be true or false, not {text!r}")


def convert(rows: list[dict], corpus: str, author: str) -> tuple[dict, dict]:
    """(question set, counts). Unverified lines are skipped and counted, never
    included; a verified line that cannot be scored is an error."""
    questions, skipped, seen = [], 0, set()
    for number, row in rows:
        where = f"line {number}"
        if (row.get("engineer_verified") or "").strip().lower() not in ("yes", "y", "true"):
            skipped += 1
            continue
        qid = (row.get("id") or "").strip()
        text = (row.get("question") or "").strip()
        if not qid or qid in seen:
            raise SheetError(f"{where}: id is empty or repeated")
        if not text:
            raise SheetError(f"{where}: verified but the question is empty")
        seen.add(qid)
        answerable = _bool(row.get("answerable") or "", where)
        q = {"id": qid, "question": text, "answerable": answerable}
        if answerable:
            doc = (row.get("expected_document") or "").strip()
            contains = [c.strip() for c in (row.get("expected_answer_contains") or "").split("|")
                        if c.strip()]
            if not doc or not contains:
                raise SheetError(f"{where}: an answerable question needs expected_document "
                                 "and expected_answer_contains")
            pages = []
            for p in (row.get("expected_pages") or "").replace(";", ",").split(","):
                if p.strip():
                    if not p.strip().isdigit():
                        raise SheetError(f"{where}: expected_pages must be numbers")
                    pages.append(int(p))
            q.update(expected_document=doc, expected_answer_contains=contains)
            if pages:
                q["expected_pages"] = pages
            if (row.get("expected_clause") or "").strip():
                q["expected_clause"] = row["expected_clause"].strip()
        if (row.get("note") or "").strip():
            q["note"] = row["note"].strip()
        questions.append(q)
    if not questions:
        raise SheetError("no line is marked engineer_verified = yes")
    return ({"corpus": corpus, "author": author, "questions": questions},
            {"questions": len(questions), "unverified_skipped": skipped,
             "answerable": sum(q["answerable"] for q in questions)})


def read_sheet(path: Path) -> list[tuple[int, dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SheetError(f"line 1: missing columns {', '.join(missing)}")
        return [(n, row) for n, row in enumerate(reader, start=2)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--corpus", default="owner's live database")
    ap.add_argument("--author", default="engineer-verified sheet")
    args = ap.parse_args(argv)
    try:
        data, counts = convert(read_sheet(args.sheet), args.corpus, args.author)
    except SheetError as exc:
        print(f"STOP - {exc}")
        return 2
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{counts['questions']} questions ({counts['answerable']} answerable), "
          f"{counts['unverified_skipped']} unverified lines left out -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
