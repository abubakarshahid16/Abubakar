"""The board's Plan tab: how many PLAN ONE tasks are done, counted from GitHub (order 314.2).

    python scripts/board_plan_counts.py --out ~/project/mirror/plan [--repo OWNER/NAME]

No hand count. PLAN ONE (#805) keeps its tasks as issues in nine stage milestones (S, A, B, C, D, C2, E, F, G); a
closed issue is a done task (the plan's own rule 10: an issue closes only with a one-line proof). This asks GitHub
(`gh api`, read-only) for every issue of those milestones and writes `plan.js` for the board:

  * per stage: done, open, total and the share, with the milestone link;
  * overall: done of total across the nine stages;
  * `counted_at`: the time of the count, so a stale board says it is stale.

Honesty lines (each one is a test):
  * a share is always written with its denominator ("12 of 41"), never alone;
  * an issue closed as NOT PLANNED is listed apart and is neither done nor open;
  * pull requests that share the milestone are not tasks and are never counted;
  * a stage whose count could not be read is listed as unread, never as zero;
  * the count says "closed", not "proven": GitHub cannot see the proof line, the closing comment holds it.

The file holds issue numbers and counts only (no document text). The command prints counts only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

#: PLAN ONE's stage milestones (#805): (stage, milestone number).
STAGES = (
    ("S", 45),
    ("A", 46),
    ("B", 47),
    ("C", 48),
    ("D", 49),
    ("C2", 50),
    ("E", 51),
    ("F", 52),
    ("G", 53),
)
DEFAULT_REPO = "abubakarshahid16/Abubakar"
NOT_PLANNED = "not_planned"

Runner = Callable[[list[str]], str]


def gh_runner(args: list[str]) -> str:
    """`gh` with the given arguments (read-only calls only); the output text."""
    done = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, timeout=120
    )
    return done.stdout


def fetch_issues(repo: str, milestone: int, run: Runner = gh_runner) -> list[dict]:
    """Every issue (not pull request) of one milestone, open and closed."""
    out = run(
        [
            "api",
            "--paginate",
            f"repos/{repo}/issues?milestone={milestone}&state=all&per_page=100",
        ]
    )
    # `gh --paginate` prints one JSON array per page back to back.
    items: list[dict] = []
    decoder = json.JSONDecoder()
    text, at = out.strip(), 0
    while at < len(text):
        chunk, at = decoder.raw_decode(text, at)
        items.extend(chunk if isinstance(chunk, list) else [chunk])
        while at < len(text) and text[at].isspace():
            at += 1
    return [i for i in items if isinstance(i, dict) and "pull_request" not in i]


def count_stage(issues: list[dict]) -> dict:
    """done / open / not planned for one stage's issues."""
    done = sum(
        1
        for i in issues
        if i.get("state") == "closed" and i.get("state_reason") != NOT_PLANNED
    )
    dropped = sum(
        1
        for i in issues
        if i.get("state") == "closed" and i.get("state_reason") == NOT_PLANNED
    )
    opened = sum(1 for i in issues if i.get("state") == "open")
    total = done + opened
    return {
        "done": done,
        "open": opened,
        "not_planned": dropped,
        "total": total,
        "share": f"{done} of {total}" if total else None,
    }


def build(
    per_stage: dict[str, list[dict] | None], repo: str, now: datetime | None = None
) -> dict:
    """The Plan tab's payload from {stage: issues, or None when that stage could not be read}."""
    now = now or datetime.now(UTC)
    stages, done, total = [], 0, 0
    unread = []
    for stage, number in STAGES:
        issues = per_stage.get(stage)
        link = f"https://github.com/{repo}/milestone/{number}"
        if issues is None:
            unread.append(stage)
            stages.append({"stage": stage, "milestone": link, "unread": True})
            continue
        c = count_stage(issues)
        done += c["done"]
        total += c["total"]
        stages.append({"stage": stage, "milestone": link, **c})
    return {
        "counted_at": now.isoformat(timespec="seconds"),
        "source": f"GitHub, {repo}, milestones {STAGES[0][1]} to {STAGES[-1][1]} (PLAN ONE #805)",
        "boundary": (
            "issues of the nine stage milestones; closed = done (not planned and pull requests excluded); "
            "'closed' is not 'proven': the proof line is in each closing comment"
        ),
        "overall": {
            "done": done,
            "total": total,
            "share": f"{done} of {total}" if total else None,
            "stages_unread": unread,
        },
        "stages": stages,
    }


def collect(repo: str, run: Runner = gh_runner) -> dict[str, list[dict] | None]:
    per_stage: dict[str, list[dict] | None] = {}
    for stage, number in STAGES:
        try:
            per_stage[stage] = fetch_issues(repo, number, run)
        except (subprocess.SubprocessError, OSError, ValueError):
            per_stage[stage] = None
    return per_stage


def write(out_dir: Path, payload: dict) -> Path:
    """`plan.js` in `out_dir` (replaced on every refresh: that is the point of an automatic count)."""
    folder = Path(out_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "plan.js"
    text = (
        "// Written by scripts/board_plan_counts.py from GitHub. Counts and issue numbers only.\n"
        "window.BOARD = window.BOARD || {};\n"
        f"window.BOARD.plan = {json.dumps(payload, indent=1)};\n"
    )
    tmp = target.with_suffix(".js.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target


def main(argv: list[str] | None = None, run: Runner = gh_runner) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    args = ap.parse_args(argv)
    payload = build(collect(args.repo, run), args.repo)
    write(args.out, payload)
    print(
        json.dumps(
            {"overall": payload["overall"], "counted_at": payload["counted_at"]},
            indent=1,
        )
    )
    return 0 if not payload["overall"]["stages_unread"] else 3


if __name__ == "__main__":
    sys.exit(main())
