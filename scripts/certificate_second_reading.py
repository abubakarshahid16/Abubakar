"""Certificate check 10 (order 292.10): a second, independent reading of a sample of pages, compared rule by rule.

The extractor that stored a standard's rules (`standards.extract_requirements`) is one reader. This is a second one
that shares none of its code: it takes the text of a page, joins hyphenated line ends, cuts it into sentences at the
full stop, and keeps the sentences that carry a normative word (shall, must, should, is required, may not ...). It
then compares the two readings rule by rule on the SAME pages:

  * a stored rule with a normative word that the second reader did not see      -> `second_reading_unseen`
  * a normative sentence the second reader saw that no stored rule covers       -> counted as `missed_by_store`

Two sentences are the same when one contains the other after the project's folding (`standards._fold_for_page`:
letters and digits only). The disagreement rate is (unseen + missed) over (agreed + unseen + missed): a rate is
always printed with that denominator. Above `FAIL_RATE` (2 percent, the planner's number in the order) the
standard FAILS; any disagreement below it is a named gap; none passes.

The sample is every `k`-th page that has text, evenly spaced and the same on every run (no random draw: the same
pages are compared again after a re-extraction). `--pages N` sets the size (default 30; all pages when fewer).

Boundary, said where the result is read: this second reader is a rule-based one, so it can only disagree about
sentences with a normative word. A stored rule WITHOUT a normative word (a definition, a table value, a nominal
value) is out of its scope and is counted apart (`out_of_scope_listed`), not as agreement and not as a
disagreement. A reader that is a model (the order allows "different method or model") would widen that scope; it
is the engine's run, not this script's, and its result would go through the same `check()`.

It lives in `scripts/` until the certificate store (cloud's item 7) reads it from the app.

    python scripts/certificate_second_reading.py --db <copy.sqlite> [--document-id ID ...] [--pages 30]

Pure apart from `read_rows` / `read_pages`, which only SELECT. Counts, requirement ids and reason codes: no
sentence, filename or page text leaves this module (CLAUDE.md rule 1). Result shape as every certificate check:
`{check, state, counts, gaps, flags}`.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import standards  # noqa: E402

CHECK = "second_reading"
UNSEEN = "second_reading_unseen"
#: Above this share of disagreement the standard FAILS (the order: "above 2% = the standard fails").
FAIL_RATE = 0.02
#: Pages compared per standard. A FIRST VALUE, not measured.
SAMPLE_PAGES = 30
#: A sentence shorter than this (folded letters and digits) is not a rule and would match anywhere.
MIN_FOLDED_CHARS = 20
_NORMATIVE = re.compile(
    r"\b(shall|must|should|is required|are required|required to|may not|is not permitted|are not permitted|"
    r"is prohibited|are prohibited)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9(])")


def read_rows(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT id, page, source_text FROM standard_requirements"
        " WHERE standard_document_id = ? AND superseded_at IS NULL",
        (document_id,),
    )
    return [{"id": r[0], "page": r[1], "source_text": r[2]} for r in cur]


def read_pages(conn: sqlite3.Connection, document_id: str) -> dict[int, str]:
    """Raw page text: the recognised text where OCR read the page, else the text layer (as check 8)."""
    pages: dict[int, str] = {}
    for number, text in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
    ):
        pages[number] = text or ""
    for number, text in conn.execute(
        "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL AND text != ''",
        (document_id,),
    ):
        pages[number] = text
    return pages


def sentences(page_text: str) -> list[str]:
    """The second reader: normative sentences of one page, hyphenation repaired, cut at the full stop."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", page_text or "")
    text = re.sub(r"\s*\n\s*", " ", text)
    out = []
    for piece in _SENTENCE_END.split(text):
        piece = piece.strip()
        if (
            _NORMATIVE.search(piece)
            and len(standards._fold_for_page(piece)) >= MIN_FOLDED_CHARS
        ):
            out.append(piece)
    return out


def sample(pages: dict[int, str], size: int = SAMPLE_PAGES) -> list[int]:
    """Evenly spaced pages that have text; the same pages on every run."""
    have = sorted(n for n, t in pages.items() if (t or "").strip())
    if size <= 0 or len(have) <= size:
        return have
    step = len(have) / size
    return sorted({have[int(i * step)] for i in range(size)})


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a in b or b in a)


def check(rows: list[dict], pages: dict[int, str], size: int = SAMPLE_PAGES) -> dict:
    chosen = sample(pages, size)
    flags: list[tuple[str, str]] = []
    agreed = missed = out_of_scope = stored_in_scope = 0
    for number in chosen:
        second = [standards._fold_for_page(s) for s in sentences(pages[number])]
        stored = [r for r in rows if r.get("page") == number]
        used = set()
        for row in stored:
            text = row.get("source_text") or ""
            folded = standards._fold_for_page(text)
            if not _NORMATIVE.search(text) or len(folded) < MIN_FOLDED_CHARS:
                out_of_scope += 1
                continue
            stored_in_scope += 1
            hit = next((i for i, s in enumerate(second) if _same(folded, s)), None)
            if hit is None:
                flags.append((row["id"], UNSEEN))
            else:
                agreed += 1
                used.add(hit)
        missed += sum(1 for i in range(len(second)) if i not in used)
    unseen = len(flags)
    union = agreed + unseen + missed
    rate = (unseen + missed) / union if union else None
    if not chosen or not union:
        state = "not_run"
    elif rate and rate > FAIL_RATE:
        state = "failed"
    elif unseen or missed:
        state = "gap"
    else:
        state = "passed"
    gaps = []
    if unseen:
        gaps.append(f"{unseen} stored rule(s) the second reading did not see")
    if missed:
        gaps.append(
            f"{missed} normative sentence(s) the second reading saw that no stored rule covers"
        )
    if out_of_scope:
        gaps.append(
            f"{out_of_scope} stored rule(s) without a normative word are out of the second reader's scope"
        )
    return {
        "check": CHECK,
        "state": state,
        "counts": {
            "pages_compared": len(chosen),
            "pages_with_text": sum(1 for t in pages.values() if (t or "").strip()),
            "agreed": agreed,
            "unseen_by_second_reading": unseen,
            "missed_by_store": missed,
            "out_of_scope_listed": out_of_scope,
            "stored_in_scope": stored_in_scope,
            "disagreement_rate": None if rate is None else round(rate, 4),
            "of": union,
        },
        "gaps": gaps,
        "flags": flags,
    }


def run(conn: sqlite3.Connection, document_id: str, size: int = SAMPLE_PAGES) -> dict:
    return check(read_rows(conn, document_id), read_pages(conn, document_id), size)


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--document-id", action="append", default=[])
    p.add_argument("--pages", type=int, default=SAMPLE_PAGES)
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
        report = {i: run(conn, i, args.pages) for i in sorted(ids)}
    finally:
        conn.close()
    for result in report.values():
        result["flags"] = len(result["flags"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
