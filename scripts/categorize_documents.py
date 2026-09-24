"""Suggest a discipline for every ingested document, from its own text.

WHAT THIS DOES NOT DO: grant anything. Execution plan section 5, line 1010 is
explicit -

    "Do not infer authorization from discipline tags alone. Access comes from
     explicit role or user grants. Discipline is many-to-many metadata used for
     organization, routing and administrative access suggestions. An
     AI-suggested discipline never grants access until an authorized
     administrator approves the grant."

So this script writes SUGGESTIONS with the evidence behind each one, and an
administrator applies them with `seed_access.py --grant`. A classifier that
wrote to `document_role_access` would be deciding who may read what on the
strength of a 4B model's opinion, which is the one thing the plan forbids.

EVERY SUGGESTION CARRIES ITS EVIDENCE - the filename, page and section of the
chunks the model was shown, and the model's stated reason. A category with no
evidence behind it is an opinion wearing a decision's clothes, and an
administrator approving it would have nothing to check.

Usage, from `backend/`:

    python ../scripts/categorize_documents.py
    python ../scripts/categorize_documents.py --out suggestions.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402

#: The four disciplines seeded by seed_access.py, plus the escape hatch.
#: `general` is not a fifth discipline - it is the honest answer for a document
#: that belongs to no single one, and the plan's own example is a mathematics
#: textbook that every discipline uses and none owns.
CATEGORIES = ("Civil Engineering", "Mechanical", "Chemical-Process", "IT", "general")

SYSTEM = (
    "You categorise engineering documents by the discipline that owns them. "
    "You answer only with the JSON object asked for, and nothing else."
)

PROMPT = """Categorise this document into exactly one category.

Categories:
  Civil Engineering  - site, structural, geotechnical, buildings, drawings, BIM
  Mechanical         - machinery, piping, coatings, materials, corrosion
  Chemical-Process   - process design, reactions, process control, emissions
  IT                 - software, security controls, networks, incident response
  general            - genuinely belongs to no single discipline, e.g. a
                       mathematics textbook or a professional-ethics text that
                       every discipline uses and none owns

Document filename: {filename}

Section headings found in it:
{sections}

Opening text:
{opening}

Further excerpts:
{excerpts}

Answer with this JSON and nothing else:
{{"category": "<one of the categories exactly as written above>",
  "confidence": "<low|medium>",
  "reason": "<one sentence, citing what in the text decided it>"}}

Use "general" when the document does not belong to one discipline. Do not force
a discipline onto a document that spans all of them."""


def _connect() -> sqlite3.Connection:
    # READ-ONLY by URI: this report only SELECTs (live_guard, 2026-09-25).
    conn = sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def evidence_for(conn: sqlite3.Connection, doc_id: str) -> dict:
    """The text the model is shown, and where each piece came from.

    Sampled across the document rather than taken from the front: front matter
    is a publisher address and a table of contents, which describes the format
    of a document and not its subject.
    """
    rows = list(conn.execute(
        """SELECT id, page_start, section, text FROM chunks
           WHERE document_id = ? AND retrievable = 1
           ORDER BY ordinal""", (doc_id,)))
    if not rows:
        return {"opening": "", "excerpts": "", "sections": "", "cited": []}

    opening = rows[0]
    # Three samples from the body, evenly spaced, skipping the front matter.
    body = rows[len(rows) // 10:] or rows
    step = max(1, len(body) // 4)
    picks = body[::step][:3]

    sections = []
    for r in conn.execute(
            """SELECT DISTINCT section FROM chunks
               WHERE document_id = ? AND section IS NOT NULL LIMIT 12""",
            (doc_id,)):
        sections.append(r["section"])

    cited = [{"chunk_id": r["id"], "page": r["page_start"], "section": r["section"]}
             for r in [opening, *picks]]
    return {
        "opening": opening["text"][:700],
        "excerpts": "\n---\n".join(r["text"][:450] for r in picks),
        "sections": "\n".join(f"  {s}" for s in sections) or "  (none recorded)",
        "cited": cited,
    }


def classify(filename: str, ev: dict, model: str | None = None,
             num_ctx: int = 4096) -> dict:
    prompt = PROMPT.format(filename=filename, sections=ev["sections"],
                           opening=ev["opening"], excerpts=ev["excerpts"])
    r = httpx.post(
        f"{settings.ollama_url}/api/chat",
        json={
            "model": model or settings.answer_model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt}],
            "stream": False,
            # Deterministic: a category that changes between runs is not a
            # category, and an administrator re-running this must see the same
            # suggestion to be able to trust the previous one.
            # num_ctx is raised above the app's 1536: that value is tuned for
            # an ANSWER prompt, and this one carries four excerpts plus the
            # heading list. A prompt longer than the window is silently
            # truncated by ollama, which would classify a document on the part
            # of itself that happened to fit.
            "options": {"temperature": 0, "num_ctx": num_ctx},
        },
        timeout=1800.0,
    )
    r.raise_for_status()
    text = r.json()["message"]["content"].strip()
    # The model is asked for bare JSON; a fenced block is the common deviation.
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return {"category": None, "confidence": None,
                "reason": f"model did not return JSON: {text[:160]!r}"}
    if out.get("category") not in CATEGORIES:
        return {"category": None, "confidence": out.get("confidence"),
                "reason": f"model returned an unknown category "
                          f"{out.get('category')!r}: {out.get('reason', '')}"}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="document-categories.json")
    ap.add_argument("--model", default=None,
                    help="ollama model; defaults to settings.answer_model. On a "
                         "memory-constrained host the smaller model is the one "
                         "that finishes - classification is far easier than "
                         "synthesis and does not need the larger one.")
    ap.add_argument("--num-ctx", type=int, default=4096)
    args = ap.parse_args()

    conn = _connect()
    docs = list(conn.execute(
        "SELECT id, filename FROM documents ORDER BY filename"))
    if not docs:
        print("no documents ingested - nothing to categorise")
        return

    print(f"Categorising {len(docs)} documents with "
          f"{args.model or settings.answer_model}.")
    print("These are SUGGESTIONS. Nothing is granted by this script.\n")

    results = []
    for d in docs:
        ev = evidence_for(conn, d["id"])
        if not ev["cited"]:
            print(f"  {d['filename']:44} SKIPPED - no retrievable text")
            results.append({"document_id": d["id"], "filename": d["filename"],
                            "category": None, "reason": "no retrievable chunks"})
            continue
        out = classify(d["filename"], ev, args.model, args.num_ctx)
        results.append({
            "document_id": d["id"],
            "filename": d["filename"],
            "category": out.get("category"),
            "confidence": out.get("confidence"),
            "reason": out.get("reason"),
            "evidence": ev["cited"],
        })
        label = out.get("category") or "UNDECIDED"
        print(f"  {d['filename']:44} -> {label}")
        print(f"      {out.get('reason', '')[:150]}")

    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten to {args.out}")
    print("\nApply them with, for each document:")
    print('  python ../scripts/seed_access.py --grant "<category>" --document <id>')
    print("\n`general` belongs to no discipline. Decide deliberately who reads it;")
    print("the plan requires an administrator's approval, not this script's.")


if __name__ == "__main__":
    main()
