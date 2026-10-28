"""The board's row-by-row before / after of two saved runs (order 274.6, Tab 1).

    python scripts/board_run_diff.py --before <run folder> --after <run folder> --out <folder> [--fixes <file>]

Reads the `findings.js` that `board_export_run.py` saved for each run (no database, no AI call, no network
call) and writes `diff.js`: every requirement present in both runs whose verdict changed, the requirements
only one run has, and the counts of each change ("MISSING_INFORMATION -> COMPLIANT: 12"). Findings are
matched by the REQUIREMENT they answer, never by position: first by `requirement_id`, then (the ids change
when a standard is re-extracted) by standard, clause and the requirement's own words. Several findings for
one requirement (one per equipment tag) are paired in id order.

THE FIX BEHIND A CHANGE is never guessed. `--fixes` names a file the planner keeps:
    {"by_requirement": {"<after finding id>": {"pr": "#1399", "line": "..."}},
     "by_transition": {"MISSING_INFORMATION -> COMPLIANT": {"pr": "#1399", "line": "..."}}}
A change with no entry has `fix: null`. Every number in `diff.js` names the file and place it came from.
The files hold document text: `--out` must be outside the repository or under `backend/data/` (git-ignored).
Output of the command itself: counts only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read_run_file(folder: Path, name: str, key: str) -> object:
    """The payload a board data file assigns to `.<key>` (see `board_export_run._script`)."""
    text = (Path(folder) / name).read_text(encoding="utf-8")
    marker = f".{key} = "
    start = text.index(marker) + len(marker)
    return json.loads(text[start : text.rindex(";")])


def _words(text: object) -> str:
    return " ".join(re.findall(r"[a-z0-9.]+", str(text or "").lower()))


def text_key(finding: dict) -> tuple[str, str, str]:
    """(standard, clause, hash of the requirement's words): identity that survives a re-extraction."""
    words = _words(finding.get("requirement_source_text") or finding.get("requirement"))
    return (
        str(finding.get("standard_document_id") or ""),
        _words(finding.get("standard_clause")),
        hashlib.sha1(words.encode()).hexdigest()[:16],
    )


def match(
    before: list[dict], after: list[dict]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """(pairs, only in before, only in after). One finding pairs at most once."""
    pairs: list[tuple[dict, dict]] = []
    left = sorted(before, key=lambda f: str(f["id"]))
    right = sorted(after, key=lambda f: str(f["id"]))
    for keyer in (
        lambda f: ("req", f.get("requirement_id")) if f.get("requirement_id") else None,
        lambda f: (
            ("text", *text_key(f))
            if _words(f.get("requirement_source_text") or f.get("requirement"))
            else None
        ),
    ):
        index: dict[tuple, list[dict]] = defaultdict(list)
        for f in right:
            if (k := keyer(f)) is not None:
                index[k].append(f)
        still_left = []
        used: set[str] = set()
        for f in left:
            k = keyer(f)
            bucket = index.get(k) if k is not None else None
            if bucket:
                partner = bucket.pop(0)
                used.add(str(partner["id"]))
                pairs.append((f, partner))
            else:
                still_left.append(f)
        left = still_left
        right = [f for f in right if str(f["id"]) not in used]
    return pairs, left, right


def _short(f: dict) -> dict:
    return {
        "finding_id": f["id"],
        "status": f.get("compliance_status"),
        "reason_code": f.get("reason_code"),
        "clause": f.get("standard_clause"),
        "page": f.get("contractor_page"),
        "requirement": f.get("requirement"),
    }


def _fix(after: dict, transition: str, fixes: dict) -> dict | None:
    entry = (fixes.get("by_requirement") or {}).get(str(after["id"])) or (
        fixes.get("by_transition") or {}
    ).get(transition)
    return entry if isinstance(entry, dict) else None


def build(before_dir: Path, after_dir: Path, fixes: dict | None = None) -> dict:
    fixes = fixes or {}
    b_run, a_run = (
        read_run_file(before_dir, "run.js", "run"),
        read_run_file(after_dir, "run.js", "run"),
    )
    b_find, a_find = (
        read_run_file(before_dir, "findings.js", "findings"),
        read_run_file(after_dir, "findings.js", "findings"),
    )
    pairs, only_before, only_after = match(b_find, a_find)
    changes, unchanged = [], 0
    for b, a in pairs:
        if (b.get("compliance_status"), b.get("reason_code")) == (
            a.get("compliance_status"),
            a.get("reason_code"),
        ):
            unchanged += 1
            continue
        transition = f"{b.get('compliance_status')} -> {a.get('compliance_status')}"
        changes.append(
            {
                "transition": transition,
                "before": _short(b),
                "after": _short(a),
                "fix": _fix(a, transition, fixes),
            }
        )
    by_transition = Counter(c["transition"] for c in changes)
    numbers = [
        {"label": label, "value": value, "source_file": "diff.js", "source_path": path}
        for label, value, path in (
            ("matched", len(pairs), "count of pairs"),
            ("changed", len(changes), "changes"),
            ("unchanged", unchanged, "pairs with the same status and reason"),
            ("only in the earlier run", len(only_before), "only_before"),
            ("only in the later run", len(only_after), "only_after"),
        )
    ] + [
        {
            "label": t,
            "value": n,
            "source_file": "diff.js",
            "source_path": f"changes where transition = {t}",
        }
        for t, n in sorted(by_transition.items())
    ]
    return {
        "before_run": b_run["id"],
        "after_run": a_run["id"],
        "numbers": numbers,
        "changes": sorted(
            changes, key=lambda c: (c["transition"], str(c["after"]["finding_id"]))
        ),
        "only_before": [_short(f) for f in only_before],
        "only_after": [_short(f) for f in only_after],
    }


def export(
    before_dir: Path, after_dir: Path, out_dir: Path, fixes_file: Path | None = None
) -> dict[str, int]:
    fixes = (
        json.loads(Path(fixes_file).read_text(encoding="utf-8")) if fixes_file else {}
    )
    diff = build(Path(before_dir), Path(after_dir), fixes)
    out_dir = Path(out_dir).expanduser().resolve()
    if (out_dir == REPO or REPO in out_dir.parents) and not out_dir.is_relative_to(
        REPO / "backend" / "data"
    ):
        raise ValueError(
            "the files hold document text: write them outside the repository or under backend/data/ (git-ignored)"
        )
    target = out_dir / "diff.js"
    if target.exists():
        raise FileExistsError("diff.js is already saved: a diff is never overwritten")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = json.dumps(f"{diff['before_run']}..{diff['after_run']}")
    target.write_text(
        "// Saved by scripts/board_run_diff.py. Holds document text: this machine only.\n"
        "window.BOARD = window.BOARD || { runs: {} };\n"
        "window.BOARD.diffs = window.BOARD.diffs || {};\n"
        f"window.BOARD.diffs[{name}] = {json.dumps(diff, ensure_ascii=False, indent=1, default=str)};\n",
        encoding="utf-8",
    )
    return {
        "changed": len(diff["changes"]),
        "only_before": len(diff["only_before"]),
        "only_after": len(diff["only_after"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--before", required=True, type=Path)
    ap.add_argument("--after", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fixes", type=Path)
    args = ap.parse_args(argv)
    try:
        counts = export(args.before, args.after, args.out, args.fixes)
    except (ValueError, FileExistsError, FileNotFoundError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
