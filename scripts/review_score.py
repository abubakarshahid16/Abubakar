"""Score a review run against an answer key (#676). Counts, never document text.

    python scripts/review_score.py export --db COPY.sqlite --run RUN_ID --out run.findings.json [--model NAME]
    python scripts/review_score.py score  --key eval/review/keys/K.json --findings run.findings.json [--json]
    python scripts/review_score.py check  --key K.json --findings F.json [--baseline eval/review/baseline.json]
    python scripts/review_score.py record-baseline --key K.json --findings F.json
    python scripts/review_score.py weekly --keys-dir eval/review/keys --runs-dir DIR [--out report.md]

Formats and the procedure: eval/review/README.md.

* `export` reads a COPY of the database read-only (never the live file) and
  writes the findings, with each citation's verdict as a boolean. The export
  holds requirement text: keep it on this machine. The report never does.
* `check` exits 1 when the score must block a merge: any false compliant, or
  recall / precision / citation validity more than the margin below the baseline.
* `weekly` scores every key in a folder against `<runs-dir>/<key name>.findings.json`
  and prints a counts-only report to post as the tracking comment. It never
  reads a hidden-exam key or folder: those are scored only by the merger
  session, by passing the key to `score` themselves (#650).
"""
from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import review_score as rs  # noqa: E402

DEFAULT_BASELINE = REPO / "eval" / "review" / "baseline.json"
DEFAULT_KEYS = REPO / "eval" / "review" / "keys"


def pct(n: int, d: int) -> str:
    return f"{n} of {d}" + (f" ({round(100 * n / d)}%)" if d else "")


# ------------------------------------------------------------------ the database

def _open_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def export_findings(conn: sqlite3.Connection, run_id: str, model: str | None = None) -> dict:
    """The run's findings in `review-findings/1`, each citation's verdict computed
    here against the stored page text (a boolean; null when the page is absent)."""
    rows = conn.execute(
        "SELECT f.id, f.standard_document_id, f.standard_clause, f.standard_page, f.matched_phrase,"
        " f.compliance_status, f.requirement_source_text, d.filename AS std_name,"
        " c.document_number AS std_number"
        " FROM review_findings f LEFT JOIN documents d ON d.id = f.standard_document_id"
        " LEFT JOIN document_classification c ON c.document_id = f.standard_document_id"
        " WHERE f.review_run_id = ? ORDER BY f.created_at, f.id", (run_id,)).fetchall()

    def page_text(doc_id, page):
        if not doc_id or page is None:
            return None
        row = conn.execute("SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
                           (doc_id, page)).fetchone()
        return row["text"] if row else None

    findings = []
    for r in rows:
        f = {"id": r["id"], "standard": r["std_name"], "standard_number": r["std_number"],
             "standard_document_id": r["standard_document_id"], "clause": r["standard_clause"],
             "page": r["standard_page"], "field": r["matched_phrase"],
             "compliance_status": r["compliance_status"], "requirement_text": r["requirement_source_text"]}
        f["citation_valid"] = rs.citation_valid(f, page_text(r["standard_document_id"], r["standard_page"]))
        findings.append(f)
    return {"format": rs.FINDINGS_FORMAT, "model": model, "run_id": run_id, "findings": findings}


# ---------------------------------------------------------------------- reporting

def text_report(r: dict, bar: dict | None = None) -> str:
    status = rs.bar_status(r, bar)
    mark = {True: "meets", False: "BELOW", None: "cannot tell"}
    lines = [
        f"Key: {r['key']} ({r['source']})   Model: {r['model'] or 'not stated'}",
        f"  findings in the run: {r['findings']}",
        f"  recall:            {pct(r['defects_found'], r['defects'])}   [{mark[status['recall']]} the proposed bar]",
        f"  precision:         {pct(r['correct_findings'], r['judged_findings'])}"
        + ("" if r["complete_for_flags"] else f"   ({r['findings_not_judged_by_key']} flagged finding(s) are not judged by this key)"),
        f"  false compliant:   {r['false_compliant']}   [{mark[status['false_compliant']]}; the limit is 0]",
        f"  false not-applic.: {r['false_not_applicable']}",
        f"  trap false flags:  {pct(r['traps_flagged'], r['traps'])}   [{mark[status['trap_false_flag_rate']]} the proposed bar]",
        "  citation validity: " + (pct(r["citations_valid"], r["citations_checked"]) if r["citations_checked"]
                                   else "NOT CHECKED (" + (r["citations_checked_note"] or "") + ")"),
    ]
    if r["missed_ids"]:
        lines.append(f"  missed defects: {', '.join(r['missed_ids'])}")
    if r["false_compliant_ids"]:
        lines.append(f"  called COMPLIANT: {', '.join(r['false_compliant_ids'])}")
    return "\n".join(lines)


def weekly_report(keys_dir: Path, runs_dir: Path, baseline: dict, week: str) -> tuple[str, int]:
    """(markdown, exit code). Counts only: key names, item ids, numbers."""
    bar = baseline.get("bar") or rs.PROPOSED_BAR
    keys, skipped_hidden, unreadable = [], [], []
    for path in sorted(keys_dir.glob("*.json")):
        try:
            key = rs.load_key(path)
        except rs.KeyError_ as exc:
            unreadable.append(f"{path.name}: {exc}")
            continue
        (skipped_hidden if key["source"] == "hidden_exam" else keys).append((path, key))
    rows, no_run, failures = [], [], []
    for path, key in keys:
        findings_path = runs_dir / f"{key.get('name') or path.stem}.findings.json"
        if not findings_path.exists():
            no_run.append(key.get("name") or path.stem)
            continue
        result = rs.score(key, rs.load_findings(findings_path))
        rows.append(result)
        failures += [f"{result['key']}: {why}" for why in rs.check(result, baseline)]
    by_source: dict[str, int] = {}
    for _, key in keys:
        by_source[key["source"]] = by_source.get(key["source"], 0) + 1
    out = [f"## Review score, week {week}", "",
           f"Proposed bar (owner to confirm, not measured): recall >= {bar['recall']:.0%}, trap false flags <= "
           f"{bar['trap_false_flag_rate']:.0%}, false compliant = {bar['false_compliant']}, citations valid = "
           f"{bar['citations_valid']:.0%}.", ""]
    if rows:
        out += ["| key (source) | model | recall | precision | false compliant | false n/a | trap false flags | citations valid |",
                "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append("| {} ({}) | {} | {} | {} | {} | {} | {} | {} |".format(
                r["key"], r["source"], r["model"] or "not stated", pct(r["defects_found"], r["defects"]),
                pct(r["correct_findings"], r["judged_findings"]), r["false_compliant"], r["false_not_applicable"],
                pct(r["traps_flagged"], r["traps"]),
                pct(r["citations_valid"], r["citations_checked"]) if r["citations_checked"] else "not checked"))
    else:
        out.append("No key was scored this week.")
    out.append("")
    out.append("Answer keys scored: " + (", ".join(f"{n} {s}" for s, n in sorted(by_source.items())) or "none")
               + ". Keys from a named engineer (engineer_confirmed) are what makes this number mean something; "
               "invented keys prove the scorer, not the system.")
    if no_run:
        out.append(f"Keys with no run this week (not scored, no number given): {', '.join(no_run)}.")
    if skipped_hidden:
        out.append(f"{len(skipped_hidden)} hidden-exam key(s) skipped: scored only by the merger session (#650).")
    for note in unreadable:
        out.append(f"Key not usable: {note}")
    out.append("")
    out.append("Gate: " + ("**FAIL** - " + "; ".join(failures) if failures else
                            ("pass" if rows else "nothing scored, so nothing passes or fails")))
    return "\n".join(out) + "\n", (1 if failures else 0)


# ------------------------------------------------------------------------- main

def _hidden_exam_path(p: Path) -> bool:
    return "hidden-exam" in str(p).replace("\\", "/").lower()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", required=True)
    e.add_argument("--run", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--model")
    for name in ("score", "check", "record-baseline"):
        sp = sub.add_parser(name)
        sp.add_argument("--key", required=True)
        sp.add_argument("--findings", required=True)
        sp.add_argument("--baseline", default=str(DEFAULT_BASELINE))
        sp.add_argument("--json", action="store_true")
    w = sub.add_parser("weekly")
    w.add_argument("--keys-dir", default=str(DEFAULT_KEYS))
    w.add_argument("--runs-dir", required=True)
    w.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    w.add_argument("--week")
    w.add_argument("--out")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "export":
            conn = _open_readonly(args.db)
            doc = export_findings(conn, args.run, args.model)
            Path(args.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            print(f"{len(doc['findings'])} finding(s) written to {args.out} (holds requirement text: keep it on this machine)")
            return 0
        if args.cmd == "weekly":
            keys_dir = Path(args.keys_dir)
            if _hidden_exam_path(keys_dir):
                print("REFUSED: the hidden exam is scored only by the merger session (#650), not by the weekly report.")
                return 2
            week = args.week or "{}-W{:02d}".format(*datetime.date.today().isocalendar()[:2])
            text, code = weekly_report(keys_dir, Path(args.runs_dir), rs.load_baseline(args.baseline), week)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(text)
            return code
        key = rs.load_key(args.key)
        findings = rs.load_findings(args.findings)
        result = rs.score(key, findings)
        baseline = rs.load_baseline(args.baseline)
        if args.cmd == "record-baseline":
            baseline["baselines"][rs.baseline_key(result)] = rs.baseline_entry(
                result, datetime.date.today().isoformat())
            baseline["format"] = rs.BASELINE_FORMAT
            Path(args.baseline).write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(f"baseline recorded for {rs.baseline_key(result)} in {args.baseline}")
            return 0
        print(json.dumps(result, indent=1) if args.json else text_report(result, baseline.get("bar")))
        if args.cmd == "check":
            reasons = rs.check(result, baseline)
            if reasons:
                print("BLOCKED: " + "; ".join(reasons))
                return 1
            has = rs.baseline_key(result) in baseline["baselines"]
            print("OK" if has else "OK (no baseline stored for this key and model yet; only the false-compliant rule was checked)")
        return 0
    except (rs.KeyError_, sqlite3.Error, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
