"""The verdict path: ONE list of the files where a wrong answer reaches an
engineer, the live data, the network or the budget (owner order, 12 Nov 2026,
point G: "style stops become warnings outside the verdict path").

The pre-push hook (`pre_push_guard.py`), the quality ratchet
(`quality_ratchet.py check` and `format-check`) and the lint baseline
(`check_lint_baseline.py`) all read THIS list, and CI runs those same scripts,
so there is no second copy to drift.

What the list decides, and only that:
  * a file ON the list that breaks a STYLE or SIZE check (formatting of the
    lines it touched, a file over 800 lines or a function over 80 lines that is
    new or longer, a worse complexity, a new ruff.toml finding) is a STOP;
  * any other file breaks the same check as a WARNING that names the file and
    the number, and the push or the merge goes on.
Checks that are not style (tests, mutation anchors, system map, unused modules,
flag register, no client data, no test-sheet names, no second number reader,
gitleaks, contract types) stop everywhere. This list never switches one off.

Start: CLAUDE.md rule 6's danger zone. Added: the code that decides or words a
verdict, or decides what leaves the machine. Keep it short enough to be honest:
a file goes on only with a one-line reason; `--list` prints the reasons.

    python scripts/verdict_path.py --list
    python scripts/verdict_path.py backend/app/comparison.py     # exit 0 if on it
"""

from __future__ import annotations

import os
import re
import sys

APP = "backend/app/"

#: (path, why it is here). A path ending in "/" is a whole folder.
VERDICT_PATH: tuple[tuple[str, str], ...] = (
    # --- CLAUDE.md rule 6, the danger zone ---
    (APP + "comparison.py", "rule 6: compares a value with a requirement"),
    (APP + "numparse.py", "rule 6: the one number and unit reader"),
    (APP + "claims.py", "rule 6: claims and their units"),
    (APP + "datasheet_checks.py", "rule 6: the approved datasheet checklist code"),
    (
        APP + "reference/datasheet_checks.json",
        "rule 6: the approved datasheet checklist",
    ),
    (APP + "crs_mapping.py", "rule 6: what a CRS line says"),
    (APP + "crs_export.py", "rule 6: what the CRS workbook says"),
    (APP + "crs_numbers.py", "rule 6: the numbers on the CRS"),
    (APP + "live_guard.py", "rule 6: keeps writers off the live database"),
    (APP + "heavy_lock.py", "rule 6: the one lock for heavy jobs"),
    ("scripts/rehearse_requirement_reextraction.py", "rule 6: its live-data guards"),
    (APP + "market_transport.py", "rule 6: opens a socket (market lane)"),
    (APP + "model_transport.py", "rule 6: opens a socket (local model)"),
    (APP + "reader_transport.py", "rule 6: opens a socket (Claude API)"),
    (APP + "notifications.py", "rule 6: opens a socket (mail)"),
    (APP + "claude_spend.py", "rule 6: the budget caps"),
    # --- added: decides or words a verdict, or what leaves the machine ---
    (APP + "agent_review_verdict.py", "the gate: when a line may be Pass or Fail"),
    (APP + "agent_review_decide.py", "the holds and the one exit that finishes a line"),
    (APP + "agent_review_reread.py", "the second reader before 'not stated'"),
    (APP + "agent_review_pair.py", "asks the class and word table"),
    (APP + "api/agent_review_schemas.py", "the one class, word and tier table"),
    (APP + "agent_review_wording.py", "the words of a verdict"),
    (APP + "agent_review_run.py", "runs the AI reviewer and charges its calls"),
    (APP + "rule_trust.py", "which AI-compiled rule may decide a verdict"),
    (APP + "agent_claude.py", "the Claude calls of the AI reviewer (egress, cost)"),
    (APP + "review_engine.py", "the resolver: which engine reads a paper, what leaves"),
    (
        APP + "review_engine_start.py",
        "queues what the plan allows; the AI review follow-up",
    ),
    (APP + "contract_yes.py", "the owner's yes that lets a contract go to Claude"),
    (APP + "review_points.py", "the points of a review: ranks, pills, counts, which quotes are shown"),
    (APP + "review_point_decisions.py", "keep, edit, remove and added points: what the CRS sheets hold"),
    (APP + "review_point_sync.py", "one transaction for both decision records; their agreement"),
    (APP + "review_code_proposal.py", "the proposed review code and its reason line"),
    (APP + "claude_approved.py", "the approved-document list and block list"),
    (APP + "claude_auto_approve.py", "automatic approval of what may be sent"),
    (APP + "crs_normal.py", "the normal reviewer's Status and Priority words"),
    (
        APP + "agent_review_pass_guards.py",
        "decides when a Pass of a rule without numbers may stand",
    ),
    (APP + "agent_review_two_reader.py", "the class 'AI verdict, two readers agree'"),
    (APP + "agent_review_two_reader_absence.py", "the word 'AI verdict: not stated'"),
    (APP + "agent_review_two_reader_other.py", "the class 'Not checked on this paper'"),
    (
        APP + "agent_review_equipment.py",
        "drops a rule before it is asked: a wrong drop hides a finding",
    ),
    (APP + "claude_api.py", "Claude calls: money and what leaves the machine"),
    (
        APP + "datasheet_ai.py",
        "the datasheet AI reader's Claude calls: money and egress",
    ),
    (APP + "reader_api.py", "the reader's Claude calls: money and egress"),
    (
        APP + "agent_review_two_reader_run.py",
        "asks the second reader and sets the class",
    ),
    (APP + "agent_review_absence.py", "decides a Fail by absence"),
    (APP + "crs_ai_words.py", "the fixed words a reader sees on the AI reviewer's CRS"),
    (APP + "crs_ai_workbook.py", "what the cells of the AI reviewer's CRS say"),
    (
        APP + "agent_review_reuse.py",
        "stands in for a reader's call: what is reused, and that no call is made",
    ),
)

#: A file `agent_review_*.py` or `crs_ai_*.py` that is NOT on the list must be
#: here with a reason (a test enforces it, so a new verdict file cannot slip by).
OFF_ON_PURPOSE: dict[str, str] = {
    "agent_review_book_table.py": "reads which rule books were candidates, for display; decides nothing",
    "agent_review_context.py": "builds the page context a reader sees; decides nothing",
    "agent_review_coverage.py": "counts coverage for display",
    "agent_review_crs.py": "places a line on a sheet; words are in crs_ai_words",
    "agent_review_gate.py": "the on/off switch only",
    "agent_review_items.py": "builds the item list",
    "agent_review_jobs.py": "job plumbing",
    "agent_review_kind.py": "names the paper kind",
    "agent_review_pages.py": "page lookup",
    "agent_review_request.py": "request and reason-code shapes",
    "agent_review_rule_rows.py": "reads rule rows from the database",
    "agent_review_rules.py": "rule selection by paper kind",
    "agent_review_schema.py": "database tables",
    "agent_review_standards.py": "standard text lookup",
    "agent_review_steady.py": "counts changed lines between two runs for display; no call",
    "agent_review_text.py": "text helpers",
    "crs_ai_cell.py": "cell layout",
    "crs_ai_drafts.py": "draft handling",
    "crs_ai_header.py": "sheet header",
    "crs_ai_review_view.py": "screen view of a stored review",
}

#: Not listed, on purpose: `config.py` holds `check_model_url` (a network gate),
#: but the file is large and mostly plain settings; it is guarded by its own
#: tests and by rule 1. Add it here if the owner wants the whole file stopped.

_PATHS = tuple(p for p, _ in VERDICT_PATH)
_FILE_IN_LINE = re.compile(r"[\w./-]+\.(?:py|tsx|ts|json)")


def normalise(path: str) -> str:
    one = path.replace("\\", "/")
    return one[2:] if one.startswith("./") else one


def is_verdict_path(path: str) -> bool:
    """True when `path` (repo-relative, with or without `::function`) is on the list."""
    one = normalise(path.split("::", 1)[0])
    return any(one == p or (p.endswith("/") and one.startswith(p)) for p in _PATHS)


def file_in(line: str) -> str | None:
    """The first file named in a ratchet message ('NEW: a/b.py::f is 90 lines ...')."""
    found = _FILE_IN_LINE.search(line)
    return found.group(0) if found else None


def split(lines: list[str]) -> tuple[list[str], list[str]]:
    """(stops, warnings): a message about a verdict-path file stops; any other
    warns. A message that names no file stops (never guessed to be harmless)."""
    stops, warns = [], []
    for line in lines:
        name = file_in(line)
        (warns if name is not None and not is_verdict_path(name) else stops).append(
            line
        )
    return stops, warns


def warn(line: str) -> None:
    """Print one warning that names the file and the number; on GitHub also as
    an annotation so it shows on the PR, not only in the log."""
    print(f"  WARNING (not a stop, off the verdict path): {line}")
    if os.environ.get("GITHUB_ACTIONS"):
        name = file_in(line)
        where = f" file={name}" if name else ""
        print(f"::warning{where}::{line}")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--list":
        for path, why in VERDICT_PATH:
            print(f"{path}  -  {why}")
        return 0
    return 0 if argv and is_verdict_path(argv[0]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
