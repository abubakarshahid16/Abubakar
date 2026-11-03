"""Fail CI and pre-push when a change ADDS client data, or the tree holds it.

TWO LISTS. (1) SHAPES, `.github/client-identifier-patterns.txt`: generic
patterns (equipment tags, project document numbers, datasheet numbers) that
name nobody, read on ADDED lines and added paths only, because a shape also
fits harmless older text; plus `.githooks/client-identifiers.local` when it
exists (a developer's machine; never in git, so never in CI). (2) KNOWN DATA,
`.github/client-data-hashes.txt`: keyed hashes of the real names, document
numbers, filenames and tags and of every 8-word run of the client's documents.
Built on the owner's machine by scripts/build_client_data_list.py from data that
stays outside the repository, so the tracked file does not spell any of it.
Known data is read on the diff AND, with `--tree`, on every tracked text file.
A tracked salt means a stranger can test a guess against the list, not read it.

The pre-commit hook (.githooks/pre-commit section 2b) reads the local list; the
pre-push guard runs this script; CI is the copy `--no-verify` cannot skip.
`--text-env NAME` also reads an environment variable (the PR title and body),
`--commits` the messages of `--base..--head`.

Dependency-free (stdlib + git) so it runs on a bare runner.

    python scripts/check_client_identifiers.py --base <sha> [--head HEAD] [--commits]
    python scripts/check_client_identifiers.py --tree [--text-env PR_TITLE]

Exit 0: nothing new. Exit 1: hits, as `path:line:` and a MASKED token (digits to
9, letters to A) or the size of the listed run: this log is public, so it never
repeats what it found. Exit 2: usage or git error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATTERN_FILE = Path(".github") / "client-identifier-patterns.txt"
LOCAL_FILE = Path(".githooks") / "client-identifiers.local"
SYNTHETIC_MARKER = "client-id-scan: synthetic"
HASH_FILE = Path(".github") / "client-data-hashes.txt"
EXCEPTION_FILE = Path(".github") / "client-data-exceptions.txt"
DIGEST_BYTES = 6
NGRAM_WORDS = 8
_WORD = re.compile(r"[a-z0-9]+")


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


def mask(token: str) -> str:
    """The token's shape only: the CI log is public and must not repeat it."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"[0-9]", "9", token))


def digest(salt: bytes, words: list[str]) -> str:
    """The keyed hash of a run of normalized words (see normalized_words)."""
    joined = " ".join(words).encode("utf-8")
    return hashlib.blake2b(joined, digest_size=DIGEST_BYTES, key=salt).hexdigest()


def normalized_words(text: str) -> list[tuple[str, int]]:
    """(word, line) for each run of letters and digits, lower case: `EF/12-b` and
    `ef 12 B` read the same, so punctuation cannot hide a listed run."""
    found = []
    for lineno, line in enumerate(text.lower().split("\n"), start=1):
        found += [(m.group(0), lineno) for m in _WORD.finditer(line)]
    return found


class KnownData:
    """The hash list: `salt`, `lengths` (words per listed run), then one digest
    per line. Each digest is a whole token or an n-gram."""

    def __init__(
        self,
        salt: bytes,
        lengths: list[int],
        digests: set[str],
        exceptions: set[tuple[str, str]] | None = None,
    ) -> None:
        self.salt, self.lengths, self.digests = salt, lengths, digests
        self.exceptions = exceptions or set()

    def find(self, text: str, path: str = "") -> list[tuple[int, int]]:
        """(line, words in the run) of every listed run in `text`."""
        words = normalized_words(text)
        plain = [w for w, _ in words]
        hits = []
        for size in self.lengths:
            for i in range(len(plain) - size + 1):
                code = digest(self.salt, plain[i : i + size])
                if code not in self.digests or (path, code) in self.exceptions:
                    continue
                # A name is written on one line; only a long wording run wraps. Without
                # this, a short name is "found" across a line break in plain code.
                if size >= NGRAM_WORDS or words[i][1] == words[i + size - 1][1]:
                    hits.append((words[i][1], size))
        return hits


def load_known_data(root: Path) -> KnownData:
    """Raises when the list is missing or empty: the check never passes vacuously."""
    path = root / HASH_FILE
    if not path.is_file():
        raise RuntimeError(f"no list at {HASH_FILE} - refusing to pass vacuously")
    salt, lengths, digests = b"", [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("salt "):
            salt = bytes.fromhex(line.split()[1])
        elif line.startswith("lengths "):
            lengths = [int(n) for n in line.split()[1:]]
        elif line and not line.startswith("#"):
            digests.add(line.strip())
    if not salt or not lengths or not digests:
        raise RuntimeError(f"{HASH_FILE} is incomplete - refusing to pass vacuously")
    exceptions = set()
    if (root / EXCEPTION_FILE).is_file():
        for line in (root / EXCEPTION_FILE).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                where, code = line.split()[:2]
                exceptions.add((where, code))
    return KnownData(salt, lengths, digests, exceptions)


def _known_report(where: str, hits: list[tuple[int, int]]) -> list[str]:
    return [f"{where}:{line}: known client data ({size} words)" for line, size in hits]


def scan(root: Path, base: str, head: str, known: KnownData | None = None) -> list[str]:
    block, allow = load_patterns(root)
    if not block:
        raise RuntimeError(f"no patterns in {PATTERN_FILE} - refusing to pass vacuously")
    # The pattern file itself is made of these shapes by design.
    skip = {PATTERN_FILE.as_posix(), HASH_FILE.as_posix(), EXCEPTION_FILE.as_posix()}
    report = []
    for path in added_paths(root, base, head):
        if path in skip:
            continue
        for token in hits_in(path, block, allow):
            report.append(f"{path}: (file name) {mask(token)}")
        if known:
            report += _known_report(path, known.find(path, path))
    by_path: dict[str, list[tuple[int, str]]] = {}
    for path, lineno, text in added_lines(root, base, head):
        if path in skip:
            continue
        by_path.setdefault(path, []).append((lineno, text))
        for token in hits_in(text, block, allow):
            report.append(f"{path}:{lineno}: {mask(token)}")
    if known:
        for path, rows in by_path.items():
            # Added lines read as one text, so a run split over two lines is seen.
            for row, size in known.find("\n".join(t for _, t in rows), path):
                report += _known_report(path, [(rows[row - 1][0], size)])
    return report


def scan_tree(root: Path, known: KnownData) -> list[str]:
    """Known data in any tracked text file. Binary files are not read."""
    skip = {HASH_FILE.as_posix(), EXCEPTION_FILE.as_posix()}
    report = []
    for path in _git(root, "ls-files").splitlines():
        if path in skip or not (root / path).is_file():
            continue
        report += _known_report(path, known.find(path, path))
        data = (root / path).read_bytes()
        if b"\0" not in data[:8000]:
            report += _known_report(
                path, known.find(data.decode("utf-8", "replace"), path)
            )
    return report


def scan_text(label: str, text: str, root: Path, known: KnownData) -> list[str]:
    """Both lists over one piece of free text (a PR title or body, a commit message)."""
    block, allow = load_patterns(root)
    report = [f"{label}: {mask(token)}" for token in hits_in(text, block, allow)]
    return report + _known_report(label, known.find(text))


def scan_commits(root: Path, base: str, head: str, known: KnownData) -> list[str]:
    report = []
    for sha in _git(root, "rev-list", f"{base}..{head}").split():
        message = _git(root, "log", "-1", "--format=%B", sha)
        report += scan_text(f"commit {sha[:10]}", message, root, known)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="diff this commit against --head")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument(
        "--tree", action="store_true", help="read every tracked file for known data"
    )
    ap.add_argument(
        "--commits", action="store_true", help="also read the messages of base..head"
    )
    ap.add_argument(
        "--text-env",
        action="append",
        default=[],
        metavar="NAME",
        help="also read this environment variable (a PR title or body)",
    )
    args = ap.parse_args(argv)
    if not args.base and not args.tree:
        ap.error("give --base or --tree")
    root = Path(args.root)
    try:
        known = load_known_data(root)
        report = scan(root, args.base, args.head, known) if args.base else []
        if args.commits and args.base:
            report += scan_commits(root, args.base, args.head, known)
        if args.tree:
            report += scan_tree(root, known)
        for name in args.text_env:
            report += scan_text(name, os.environ.get(name) or "", root, known)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if report:
        print("Client data found (shapes and sizes only; this log is public):")
        for item in report:
            print(f"  {item}")
        print(
            "\nWrite the ROLE the document plays instead, or a made-up fixture "
            "(see the allow: lines in .github/client-identifier-patterns.txt). "
            "A hit may never be pasted into an issue, a PR or a commit message."
        )
        return 1
    print(f"OK: no client data found ({len(known.digests)} listed entries read).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
