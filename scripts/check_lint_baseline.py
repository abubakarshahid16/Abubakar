"""Order 55a (#692): the repo's own `ruff.toml` findings may only go DOWN.

CI ran ruff with fatal errors only (`--select E9,F63,F7,F82`), so the
~1,500 findings under `ruff.toml` (bugbear, blind except, pathlib, ...) were
never seen and could grow freely. Fixing them all at once would be a huge
diff touching the review path. This is the ratchet instead (the flags
register #1036 pattern):

  * `eval/quality/lint_baseline.json` stores, per file and rule, how many
    findings main has today;
  * `check` fails a PR when any (file, rule) count goes UP - a NEW finding -
    and names it; a count that went down is reported, never a failure;
  * `record` rewrites the baseline (run it after fixing findings, so the bar
    moves down and stays down).

Counts depend on the ruff version, so the baseline pins it; another version
is a named error, not a silently different count.

The whole-tree formatter count (`ruff format --check`) is a REPORT only: how
many files would be reformatted. The gate is per file and only for the files
a PR changes: `quality_ratchet.py format-check` (order 79d).

    python scripts/check_lint_baseline.py check
    python scripts/check_lint_baseline.py record
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "eval" / "quality" / "lint_baseline.json"
CONFIG = ROOT / "ruff.toml"
PATHS = ("backend", "scripts", "eval")


def _ruff(*args: str) -> subprocess.CompletedProcess:
    # UTF-8, not the locale: on Windows (cp1252) a byte ruff prints that the
    # locale cannot decode left stdout None, and the report crashed (order 133).
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def ruff_version() -> str:
    return _ruff("--version").stdout.strip().split()[-1]


def current_counts() -> dict[str, int]:
    """{"path::CODE": n} for every finding under ruff.toml."""
    proc = _ruff("check", "--config", str(CONFIG), "--output-format", "json",
                 "--exit-zero", "--no-cache", *PATHS)
    if proc.returncode != 0:
        raise SystemExit(f"ruff failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    counts: Counter = Counter()
    for item in json.loads(proc.stdout or "[]"):
        path = Path(item["filename"]).resolve().relative_to(ROOT).as_posix()
        counts[f"{path}::{item.get('code') or 'syntax'}"] += 1
    return dict(sorted(counts.items()))


def compare(baseline: dict[str, int], current: dict[str, int]) -> tuple[list[str], list[str]]:
    """(new findings, findings fixed): each line names the file, rule and counts."""
    new = [f"{key}: {baseline.get(key, 0)} -> {n}" for key, n in current.items()
           if n > baseline.get(key, 0)]
    fixed = [f"{key}: {n} -> {current.get(key, 0)}" for key, n in baseline.items()
             if current.get(key, 0) < n]
    return new, fixed


def format_report() -> str:
    proc = _ruff("format", "--check", "--config", str(CONFIG), "--no-cache", *PATHS)
    output = (proc.stdout or "") + (proc.stderr or "")
    summary = re.search(r"(\d+) files? would be reformatted", output)
    if summary is None:
        return "formatter (report only, never a gate): no file would be reformatted"
    return (f"formatter (report only, never a gate): {summary.group(1)} file(s)"
            " would be reformatted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "record"))
    args = parser.parse_args(argv)
    version = ruff_version()
    current = current_counts()
    if args.mode == "record":
        BASELINE.write_text(json.dumps({"ruff": version, "total": sum(current.values()),
                                        "counts": current}, indent=1) + "\n", encoding="utf-8")
        print(f"recorded {sum(current.values())} findings with ruff {version}")
        return 0
    stored = json.loads(BASELINE.read_text(encoding="utf-8"))
    if stored["ruff"] != version:
        print(f"FAIL: the baseline was recorded with ruff {stored['ruff']}, this is {version};"
              " counts differ between versions - pin ruff or re-record on main")
        return 1
    new, fixed = compare(stored["counts"], current)
    for line in new:
        print(f"NEW: {line}")
    for line in fixed:
        print(f"fixed: {line}")
    total = sum(current.values())
    print(f"ruff.toml findings: {total} (baseline {stored['total']});"
          f" {len(new)} new, {len(fixed)} fewer")
    if fixed and not new:
        print("the count went down: run `python scripts/check_lint_baseline.py record`"
              " in this PR so it cannot come back")
    print(format_report())
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
