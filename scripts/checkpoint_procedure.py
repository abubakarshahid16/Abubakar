"""The checkpoint's procedure-type document (W5b-09, #533; extends #468).

Reviews ONE invented procedure end to end - upload, extract, chunk, review
against its playbook - in a TEMPORARY data directory (never the live
database), and records the result against the answer key in
`eval/checkpoint/procedure.json`: per element, the expected state, the state
the review gave, and pass/fail; and the sample's boundary.

    python scripts/checkpoint_procedure.py [--out results.json]

Counts and element ids only; the invented text is never printed. A missing or
unreadable key is a named error (exit 2). A document the review could not read
in full makes every element "not checked" and the run INCOMPLETE - never a
pass. Exit 0 when every element matches the key, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

KEY_PATH = REPO / "eval" / "checkpoint" / "procedure.json"
FORMAT = "checkpoint-procedure/1"


class CheckpointError(Exception):
    """The checkpoint cannot run; the message says why."""


def load_key(path: Path = KEY_PATH) -> dict:
    try:
        key = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointError(f"{Path(path).name}: the checkpoint answer key is missing") from exc
    except (OSError, ValueError) as exc:
        raise CheckpointError(f"{Path(path).name}: cannot be read as JSON ({type(exc).__name__})") from exc
    if not isinstance(key, dict) or key.get("format") != FORMAT:
        raise CheckpointError(f"{Path(path).name}: must have format {FORMAT!r}")
    for field in ("playbook", "filename", "sections", "expected"):
        if not key.get(field):
            raise CheckpointError(f"{Path(path).name}: {field} is missing or empty")
    return key


def _pdf(sections: list) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page, y = None, 800
    for title, text in sections:
        if y > 720:
            page, y = doc.new_page(), 72
        page.insert_text((72, y), title, fontsize=12)
        rect = pymupdf.Rect(72, y + 6, 523, y + 70)
        page.insert_textbox(rect, text, fontsize=10)
        y += 78
    out = doc.tobytes()
    doc.close()
    return out


def score(review: dict, expected: dict) -> dict:
    """Per element: expected, got, pass. An element the review did not report,
    or could not check, is never a pass."""
    got = {e["id"]: e["state"] for e in review.get("elements", [])}
    read = bool(review.get("document", {}).get("read_in_full"))
    rows = []
    for element_id, want in expected.items():
        state = got.get(element_id)
        rows.append({"id": element_id, "expected": want, "got": state,
                     "pass": read and state is not None and state == want})
    passed = sum(1 for r in rows if r["pass"])
    return {"elements": rows, "passed": passed, "total": len(rows),
            "status": ("incomplete" if not read else "pass" if passed == len(rows) else "fail"),
            "not_read_reason": None if read else review.get("document", {}).get("not_read_reason")}


def run_checkpoint(work_dir: Path, key: dict | None = None) -> dict:
    """Run the procedure review in `work_dir` (a fresh data directory)."""
    import io

    from app import access, chunker, db, extract, keyword, playbooks, upload
    from app.config import settings
    from app.search import every_document_id

    key = key or load_key()
    work_dir = Path(work_dir)
    settings.data_dir = work_dir
    settings.upload_dir = work_dir / "uploads"
    settings.db_path = work_dir / "checkpoint.sqlite"
    settings.auth_mode = access.AUTH_DISABLED
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()

    found, _problems = playbooks.available()
    playbook = found.get(key["playbook"])
    if playbook is None:
        raise CheckpointError(f"playbook {key['playbook']!r} is not available")
    for i, std in enumerate(key.get("library") or [], start=1):
        with db.connect() as conn:
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                         "uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-10-09T00:00:00Z')",
                         (f"std_{i}", std["filename"], f"sha-std-{i}", f"std_{i}.pdf"))
            conn.execute("INSERT INTO document_classification (document_id,suggested_by,document_role,"
                         "document_number) VALUES (?,?,?,?)",
                         (f"std_{i}", "checkpoint", "COMPANY_STANDARD", std["document_number"]))
    row, _job, _dup = upload.ingest(io.BytesIO(_pdf(key["sections"])), key["filename"])
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    # The keyword index is the last stage this run builds (no embedding model
    # is assumed); a document that got there is read in full. Any other
    # status is left as it is, and the review then says it was not read.
    keyword.index_document(row["id"])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ? AND status = 'indexing_keyword'",
                     (row["id"],))
    review = playbooks.review(row["id"], playbook, allowed_document_ids=every_document_id())
    result = score(review, key["expected"])
    result["boundary"] = (f"1 invented procedure ({len(key['sections'])} sections), playbook "
                          f"{playbook.id} v{playbook.version} ({'signed off' if playbook.signed_off else 'DRAFT'}), "
                          f"library: {len(key.get('library') or [])} invented stand-in standard(s); "
                          "keyword index only (no embeddings); invented sample, not the client's documents")
    result["counts"] = review["counts"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the result JSON here")
    args = parser.parse_args(argv)
    try:
        key = load_key()
        with tempfile.TemporaryDirectory(prefix="checkpoint-") as tmp:
            result = run_checkpoint(Path(tmp), key)
    except CheckpointError as exc:
        print(f"checkpoint not run: {exc}", file=sys.stderr)
        return 2
    print(f"procedure checkpoint: {result['status']} - {result['passed']} of {result['total']} elements "
          f"as the key expects ({result['boundary']})")
    for r in result["elements"]:
        print(f"  {r['id']}: expected {r['expected']}, got {r['got'] or 'not reported'}"
              f"{'' if r['pass'] else '  <- differs'}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
