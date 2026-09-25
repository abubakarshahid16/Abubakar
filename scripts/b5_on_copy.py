"""B5 acceptance: the live review's selection and code on the real datasheets, on a COPY.

WHAT IT DOES, IN ORDER (the owner's B5 steps 8 and 9, before any live run):

  1. BACKUP FIRST: `live_guard.verified_rollback_point` (backup, integrity,
     comparison, restore drill). Nothing else runs if it fails.
  2. One disposable copy of a consistent snapshot; `settings.db_path` points
     at the copy, so nothing here can reach the live file.
  3. Each document is found by a filename fragment (passed with --doc;
     no default); a fragment matching none or several stops the run.
  4. For each, exactly what `POST /api/reviews/run` does: create the run,
     `applicability.select(persist=True)`, then `comparison.run_comparison`
     with the selection's reference coverage and missing references.
  5. It then reads back what the live screens read - the run's standards
     rows (applied / considered, method, evidence), the stored outcome
     (code, reason, MISSING_LOCALLY list) and the CRS 'Applicable standards'
     rows - and checks the B5 invariants on them:
       * no run is Approved with a MISSING_LOCALLY standard or no finding;
       * every applied row has a method that is evidence and a reason;
       * every considered row has an exclusion reason;
       * every citation row with a page has its line.

OUTPUT: document ids and counts per document, and PASS/FAIL per invariant.
Standard identifiers are printed only with --show (local use: they come from
the document). The copy under --scratch holds document text: delete it when
done, never commit or paste it (CLAUDE.md rules 1 and 3).

    mkdir C:\\b5-backups
    python scripts/b5_on_copy.py --backup-dir C:\\b5-backups --scratch C:\\b5-scratch \\
        --doc <fragment 1> --doc <fragment 2> --doc <fragment 3>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))



def find_documents(db_path: Path, fragments: list[str]) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    out, problems = {}, []
    for fragment in fragments:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM documents WHERE filename LIKE ? ORDER BY id", (f"%{fragment}%",))]
        if len(ids) != 1:
            problems.append(f"{fragment!r} matches {len(ids)} documents: {ids}")
        else:
            out[fragment] = ids[0]
    conn.close()
    if problems:
        raise SystemExit("stopping - each fragment must match exactly one document:\n  "
                         + "\n  ".join(problems))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", type=Path,
                    default=REPO / "backend" / "data" / "rag_intelligence.sqlite")
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--backup-dir", type=Path, default=None)
    ap.add_argument("--doc", action="append", required=True,
                    help="filename fragment (repeatable, required); document names are never stored in the repo")
    ap.add_argument("--show", action="store_true",
                    help="also print standard identifiers (local use only)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from app import live_guard  # noqa: E402
    from reextract_on_copy import copy_database  # noqa: E402

    live = args.live.resolve()
    proof = live_guard.verified_rollback_point(live, backup_dir=args.backup_dir)
    print("backup:", json.dumps({k: str(v) for k, v in proof.items()}, indent=2))
    snapshot = live_guard.diagnostic_copy(live)
    copy = copy_database(snapshot, args.scratch)
    docs = find_documents(copy, args.doc)

    from app import (access, applicability, comparison, db,  # noqa: E402
                     submittal_review)
    from app.config import settings  # noqa: E402
    import app.main as main_mod  # noqa: E402

    settings.db_path = copy
    db.reset_connection()
    submittal_review.ensure_schema()
    everything = frozenset(r[0] for r in db.connect().execute("SELECT id FROM documents"))
    scope = access.AccessScope(user_id=None, allowed_document_ids=everything)

    report: dict = {"backup": {k: str(v) for k, v in proof.items()}, "documents": {}}
    all_pass = True
    for fragment, doc_id in docs.items():
        run_id = submittal_review.create_review_run(
            submittal_document_id=doc_id, allowed_document_ids=everything)
        selection = applicability.select(doc_id, allowed_document_ids=everything,
                                         review_run_id=run_id, persist=True)
        missing = [m["identifier"] for m in selection["missing_references"]]
        result = comparison.run_comparison(
            run_id, allowed_document_ids=everything,
            reference_coverage=selection.get("reference_coverage"),
            missing_references=missing)
        rows = submittal_review.list_applicable_standards(
            run_id, allowed_document_ids=everything, include_excluded=True)
        outcome = comparison.run_outcome(run_id, allowed_document_ids=everything) or {}
        _rows, meta, _name, _stamp = main_mod._crs_content(run_id, scope)
        crs_standards = meta["applicable_standards"]

        applied = [r for r in rows if r["included"]]
        considered = [r for r in rows if not r["included"]]
        checks = {
            "never Approved with a MISSING_LOCALLY standard or no finding": not (
                outcome.get("recommended_code") in (comparison.CODE_APPROVED,
                                                     comparison.CODE_APPROVED_WITH_COMMENTS)
                and (missing or not result["findings"])),
            "every applied row has an evidence method and a reason": all(
                r["selection_method"] in applicability.INCLUDING_METHODS
                and (r["selection_reason"] or "").strip() for r in applied),
            "every considered row says why": all(
                (r["exclusion_reason"] or "").strip() for r in considered),
            "every paged citation has its line": all(
                r["evidence_quote"] for r in applied
                if r["selection_method"] == "referenced" and r["evidence_page"] is not None),
            "the CRS lists every MISSING_LOCALLY standard": sum(
                1 for s in crs_standards if s["status"] == comparison.MISSING_LOCALLY)
                == len(missing),
        }
        all_pass &= all(checks.values())
        entry = {
            "document_id": doc_id, "review_run_id": run_id,
            "applied_by_method": dict(Counter(r["selection_method"] for r in applied)),
            "considered_by_method": dict(Counter(r["selection_method"] for r in considered)),
            "applied_with_evidence_line": sum(1 for r in applied if r["evidence_quote"]),
            "missing_locally": len(missing),
            "requirements_evaluated": result["requirements_evaluated"],
            "findings_by_status": {k: v for k, v in result["by_status"].items() if v},
            "recommended_code": outcome.get("recommended_code"),
            "scope_decision_not_run": selection.get("scope_decision_not_run"),
            "checks": {k: "PASS" if v else "FAIL" for k, v in checks.items()},
        }
        if args.show:
            entry["missing_identifiers"] = missing
            entry["reason"] = outcome.get("reason")
        report["documents"][fragment] = entry
        print(f"\n== {fragment} ({doc_id})")
        for key, value in entry.items():
            print(f"  {key}: {value}")

    report["all_checks_pass"] = all_pass
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nALL B5 CHECKS PASS" if all_pass else "\nB5 CHECKS FAILED - see FAIL lines")
    print("The copy under", args.scratch, "contains document text - delete it when done.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
