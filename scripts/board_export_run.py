"""The board's data for ONE finished review run (order 274.6: Tab 1 Reviews, Tab 4 Decisions).

    python scripts/board_export_run.py --db <copy of the database> --run <review_run_id> --out <folder>

READ-ONLY on a COPY (a live-shaped path is refused), no AI call, no network call. It writes four data
files into `--out` (the mirror's folder for the run), each a script the board loads by relative path
(a page opened from disk cannot fetch JSON): `run.js` (the run, its switches and model, every number with
the file it came from), `findings.js` (every finding), `decisions.js` (pairing, held and comparison, the
X-ray's own sections) and `xray.js` (all nine X-ray sections, so nothing is hidden). The data is
`backend/tools/review_xray.build`'s, not a second format.

A run is saved ONCE, when it has finished: an unfinished run is refused and an existing file is never
overwritten. The files hold document text and stay on this machine: `--out` must be outside the repository
or under `backend/data/` (git-ignored). Output of the command itself: counts only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

FINISHED = ("completed", "failed", "cancelled")
FILES = ("run.js", "findings.js", "decisions.js", "xray.js")
#: The X-ray sections that explain how each requirement was decided.
DECISION_SECTIONS = ("coverage", "pairing", "held", "comparison")
FINDING_COLUMNS = (
    "id",
    "requirement_id",
    "fact_id",
    "compliance_status",
    "reason_code",
    "match_method",
    "category",
    "severity",
    "standard_document_id",
    "standard_clause",
    "standard_page",
    "contractor_page",
    "contractor_section",
    "requirement",
    "requirement_source_text",
    "finding",
    "ai_rationale",
    "disposition",
    "origin",
    "equipment_tag",
)


def _json(raw: object) -> object:
    try:
        return json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}


def _script(run_id: str, key: str, payload: object) -> str:
    """One data file: `window.BOARD.runs[<run>].<key> = <payload>;`"""
    data = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    return (
        "// Saved once by scripts/board_export_run.py when the run finished. Holds document text: this machine only.\n"
        "window.BOARD = window.BOARD || { runs: {} };\n"
        f"window.BOARD.runs[{json.dumps(run_id)}] = window.BOARD.runs[{json.dumps(run_id)}] || {{}};\n"
        f"window.BOARD.runs[{json.dumps(run_id)}].{key} = {data};\n"
    )


def _number(label: str, value: object, source_file: str, source_path: str) -> dict:
    """A number never travels alone: the file and the place in it that it came from."""
    return {
        "label": label,
        "value": value,
        "source_file": source_file,
        "source_path": source_path,
    }


def _run_block(run: sqlite3.Row, outcome: dict, findings: list[dict]) -> dict:
    split = outcome.get("requirement_split")
    split = split if isinstance(split, dict) else {}
    numbers = [_number("findings", len(findings), "findings.js", "count of rows")]
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f["compliance_status"] or "none"] = (
            by_status.get(f["compliance_status"] or "none", 0) + 1
        )
    numbers += [
        _number(
            f"findings: {status}",
            n,
            "findings.js",
            f"count where compliance_status = {status}",
        )
        for status, n in sorted(by_status.items())
    ]
    numbers += [
        _number(k.replace("_", " "), v, "run.js", f"outcome.requirement_split.{k}")
        for k, v in split.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    keys = run.keys()
    return {
        "id": run["id"],
        "submittal_document_id": run["submittal_document_id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "model_name": run["model_name"] if "model_name" in keys else None,
        "config_version": run["config_version"] if "config_version" in keys else None,
        "run_settings": _json(run["run_settings"]) if "run_settings" in keys else None,
        "recommended_code": outcome.get("recommended_code"),
        "outcome": {
            k: outcome.get(k)
            for k in ("recommended_code", "reason", "requirement_split")
        },
        "numbers": numbers,
    }


def _findings(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    have = {r[1] for r in conn.execute("PRAGMA table_info(review_findings)")}
    cols = [c for c in FINDING_COLUMNS if c in have]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM review_findings WHERE review_run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return [{c: r[c] if c in have else None for c in FINDING_COLUMNS} for r in rows]


def export(db_path: Path, run_id: str, out_dir: Path) -> dict[str, int]:
    """Write the four files; return {file: rows} (counts only). Refuses an unfinished run and any
    existing file. The folder is made only when everything else is fine."""
    from tools import review_xray

    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        run = conn.execute(
            "SELECT * FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise LookupError(f"no review run {run_id!r} in this database")
        if run["status"] not in FINISHED:
            raise ValueError(
                f"the run is {run['status']!r}: a run is saved once, when it has finished"
            )
        findings = _findings(conn, run_id)
        outcome = _json(run["outcome_json"]) or {}
        block = _run_block(run, outcome if isinstance(outcome, dict) else {}, findings)
    finally:
        conn.close()
    xray = review_xray.build(db_path, run_id)
    decisions = [s for s in xray["sections"] if s["id"] in DECISION_SECTIONS]
    out_dir = Path(out_dir).expanduser().resolve()
    inside_repo = out_dir == REPO or REPO in out_dir.parents
    if inside_repo and not out_dir.is_relative_to(REPO / "backend" / "data"):
        raise ValueError(
            "the files hold document text: write them outside the repository or under backend/data/ (git-ignored)"
        )
    taken = [f for f in FILES if (out_dir / f).exists()]
    if taken:
        raise FileExistsError(
            f"{taken} already saved: a finished run is never overwritten"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "run.js": ("run", block),
        "findings.js": ("findings", findings),
        "decisions.js": ("decisions", decisions),
        "xray.js": ("xray", xray["sections"]),
    }
    counts = {}
    for name, (key, payload) in payloads.items():
        (out_dir / name).write_text(_script(run_id, key, payload), encoding="utf-8")
        counts[name] = (
            len(payload) if isinstance(payload, list) else len(payload["numbers"])
        )
    return counts


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True, type=Path, help="a COPY of the database")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    db = args.db.resolve()
    if live_guard.is_live_shaped(db) or not db.exists():
        print(f"refused: {db} is a live database or does not exist. Use a copy.")
        return 2
    try:
        counts = export(db, args.run, args.out)
    except (LookupError, ValueError, FileExistsError) as exc:
        print(f"refused: {exc}")
        return 1
    print(json.dumps({"run": args.run, "rows": counts}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
