"""Fail CI when a pull request or push ADDS a client-identifier-shaped token.

WHY DIFF-ONLY. The repository already tracks files that carry client
identifiers; removing them is an owner decision (history clean-up), not
something a CI job can do. Scanning the whole tree would fail every build
until then, and a check that is always red is a check people learn to ignore.
So this reads only the lines ADDED (and the paths added or renamed) between
`--base` and `--head`: an existing occurrence is not re-reported, a new one is.
The pre-commit hook (.githooks/pre-commit section 2b) does the same locally;
this is the copy that cannot be skipped with `--no-verify`.

WHAT IT MATCHES. The patterns in `.github/client-identifier-patterns.txt` -
GENERIC SHAPES ONLY (equipment tags, project document numbers, datasheet
numbers), because that file is tracked and a list naming the client publishes
it - plus `.githooks/client-identifiers.local` when it exists (a developer's
machine; never in git, so never in CI).

Dependency-free (stdlib + git) so it runs on a bare runner.

    python scripts/check_client_identifiers.py --base <sha> [--head HEAD]

Exit 0: nothing new. Exit 1: hits, printed as `path:line: token` - the token
only, never the whole line, so the CI log does not republish surrounding text.
Exit 2: usage or git error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATTERN_FILE = Path(".github") / "client-identifier-patterns.txt"
LOCAL_FILE = Path(".githooks") / "client-identifiers.local"
SYNTHETIC_MARKER = "client-id-scan: synthetic"


def load_patterns(root: Path) -> tuple[list[re.Pattern], list[re.Pattern]]:
    """(block patterns, allow patterns) from the tracked file and the local one."""
    block: list[re.Pattern] = []
    allow: list[re.Pattern] = []
    for path in (root / PATTERN_FILE, root / LOCAL_FILE):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("allow:"):
                allow.append(re.compile(line[len("allow:"):]))
            else:
                block.append(re.compile(line))
    return block, allow


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return done.stdout


def _range(root: Path, base: str, head: str) -> list[str]:
    """`base...head` (changes since the merge base) when both are commits with
    one; otherwise the plain two-point diff (e.g. against the empty tree)."""
    probe = subprocess.run(["git", "merge-base", base, head], cwd=root,
                           capture_output=True, text=True)
    return [f"{base}...{head}"] if probe.returncode == 0 else [base, head]


def added_lines(root: Path, base: str, head: str):
    """Yield (path, line number in head, text) for every added line."""
    diff = _git(root, "diff", "--no-color", "--no-ext-diff", "-U0",
                "--diff-filter=ACMR", *_range(root, base, head))
    path = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and path is not None:
            yield path, lineno, line[1:]
            lineno += 1


def added_paths(root: Path, base: str, head: str) -> list[str]:
    out = _git(root, "diff", "--name-only", "--diff-filter=AR", *_range(root, base, head))
    return [p for p in out.splitlines() if p]


def hits_in(text: str, block, allow) -> list[str]:
    if SYNTHETIC_MARKER in text:
        return []
    found = []
    for pattern in block:
        for m in pattern.finditer(text):
            token = m.group(0)
            if any(a.fullmatch(token) for a in allow):
                continue
            found.append(token)
    return found


def scan(root: Path, base: str, head: str) -> list[str]:
    block, allow = load_patterns(root)
    if not block:
        raise RuntimeError(f"no patterns in {PATTERN_FILE} - refusing to pass vacuously")
    # The pattern file itself is made of these shapes by design.
    skip = {PATTERN_FILE.as_posix()}
    report = []
    for path in added_paths(root, base, head):
        if path in skip:
            continue
        for token in hits_in(path, block, allow):
            report.append(f"{path}: (file name) {token}")
    for path, lineno, text in added_lines(root, base, head):
        if path in skip:
            continue
        for token in hits_in(text, block, allow):
            report.append(f"{path}:{lineno}: {token}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", default=str(REPO))
    args = ap.parse_args(argv)
    try:
        report = scan(Path(args.root), args.base, args.head)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if report:
        print("Client-identifier-shaped tokens ADDED in this change:")
        for item in report:
            print(f"  {item}")
        print("\nWrite the ROLE the document plays instead, or a made-up fixture "
              "(see the allow: lines in .github/client-identifier-patterns.txt).")
        return 1
    print("OK: no client-identifier-shaped token added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
