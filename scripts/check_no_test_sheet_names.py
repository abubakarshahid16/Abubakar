"""Order 201 / #805 rule 4: no program file names a test sheet.

A fix written for one datasheet ("if the sheet is 216400C ...") is exactly what
the owner forbade, and a name in the code is how it creeps in. This check fails
when a program file - `backend/app/` or `frontend/src/`, not the tests - holds
the id or the name of a test sheet:

* the real test sheets: 216400C, EF1975, M-03, I-06;
* every invented sheet of the PF1 set (`backend/tests/fixtures/synthetic/pf1/`):
  its id, its datasheet and standard numbers, its tag - read from `spec.json`, so
  a new invented sheet is covered the day it is added;
* the HELD-OUT ids, kept in a local file that is never committed:
  `$PF1_HELDOUT_IDS` (a path), else `backend/data/heldout_ids.txt` (that folder
  is git-ignored). One id per line; `#` starts a comment. Absent: skipped, and the
  run says so (GitHub cannot hold it; the Mac and the PC can).

HOW A RECORD OF WHERE A BUG WAS FOUND IS TOLD FROM A RULE FOR ONE SHEET.
A name in CODE (an `if`, a dictionary key, a string a program compares, any
data file) always fails. A name in a COMMENT or a DOCSTRING is allowed only when
the same line carries the mark `[found-on]`, which says "this records where the
bug was seen; no behaviour depends on it". Python is read with `tokenize`, so a
name inside a string a program uses is never mistaken for a comment; TypeScript
lines are comments when they start with `//`, `/*` or `*`, or the name follows
`//`.

Run: python scripts/check_no_test_sheet_names.py   (exit 1 with file:line)
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tokenize
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = "[found-on]"
SCAN = ((ROOT / "backend" / "app", (".py", ".json")), (ROOT / "frontend" / "src", (".ts", ".tsx", ".json")))
PF1_SPEC = ROOT / "backend" / "tests" / "fixtures" / "synthetic" / "pf1" / "spec.json"
HELDOUT_DEFAULT = ROOT / "backend" / "data" / "heldout_ids.txt"
#: The real sheets the owner named (a real client document number is one of them).
REAL = ("216400C", "EF1975", "M-03", "I-06")


def _is_test_file(path: Path) -> bool:
    name = path.name
    return (
        ".test." in name
        or name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in path.parts
        or "__tests__" in path.parts
    )


def pf1_names(spec: Path = PF1_SPEC) -> list[str]:
    """Every id, number and tag of the invented sheets (empty if no set)."""
    if not spec.is_file():
        return []
    names: list[str] = []
    for doc in json.loads(spec.read_text(encoding="utf-8")).get("documents", []):
        sheet, standard = doc.get("sheet") or {}, doc.get("standard") or {}
        names += [doc.get("id"), sheet.get("document_number"), sheet.get("tag"), standard.get("number")]
    return [n for n in names if n]


def heldout_names(path: Path | None = None) -> tuple[list[str], str | None]:
    """(ids, None) or ([], why they were not read)."""
    chosen = path or Path(os.environ.get("PF1_HELDOUT_IDS") or HELDOUT_DEFAULT)
    if not chosen.is_file():
        return [], f"held-out ids not checked: no local list at {chosen} (set PF1_HELDOUT_IDS)"
    lines = (ln.split("#", 1)[0].strip() for ln in chosen.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln], None


def build_pattern(names: Iterable[str]) -> re.Pattern[str]:
    """Each name as a whole token, any case ('pf1-t01-pump' also 'PF1-T01-PUMP').
    A hyphen does NOT end a token: a longer document number built from
    'EF1975' and 'M-03' holds both, and is caught on both halves."""
    unique = sorted({n for n in names if n}, key=len, reverse=True)
    body = "|".join(re.escape(n) for n in unique)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{body})(?![A-Za-z0-9_])", re.IGNORECASE)


def _python_non_code_lines(text: str) -> set[int]:
    """Line numbers that hold ONLY a comment or a docstring (names there may be a
    record). A string a program uses is code and is not in this set."""
    comment_or_doc: set[int] = set()
    code: set[int] = set()
    previous_significant = None
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        return set()
    for tok in tokens:
        kind = tok.type
        if kind == tokenize.COMMENT:
            comment_or_doc.update(range(tok.start[0], tok.end[0] + 1))
        elif kind == tokenize.STRING:
            is_doc = previous_significant in (None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
            (comment_or_doc if is_doc else code).update(range(tok.start[0], tok.end[0] + 1))
        elif kind not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            code.update(range(tok.start[0], tok.end[0] + 1))
        if kind not in (tokenize.NL, tokenize.COMMENT):
            previous_significant = kind
    return comment_or_doc - code


def _is_ts_comment(line: str, hit_at: int) -> bool:
    stripped = line.lstrip()
    if stripped.startswith(("//", "/*", "*")):
        return True
    cut = line.find("//")
    return 0 <= cut < hit_at


def violations_in(path: Path, text: str, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """[(line number, name)] of every name that is not an allowed, marked record."""
    out: list[tuple[int, str]] = []
    lines = text.splitlines()
    suffix = path.suffix
    non_code = _python_non_code_lines(text) if suffix == ".py" else set()
    for number, line in enumerate(lines, start=1):
        for hit in pattern.finditer(line):
            if suffix == ".py":
                record = number in non_code
            elif suffix in (".ts", ".tsx"):
                record = _is_ts_comment(line, hit.start())
            else:
                record = False  # a data file is code
            if record and MARK in line:
                continue
            out.append((number, hit.group(0)))
    return out


def files() -> Iterable[Path]:
    for base, suffixes in SCAN:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in suffixes and not _is_test_file(path):
                yield path


def main() -> int:
    names = list(REAL) + pf1_names()
    held, note = heldout_names()
    names += held
    pattern = build_pattern(names)
    bad: list[str] = []
    for path in files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, name in violations_in(path, text, pattern):
            bad.append(f"{path.relative_to(ROOT)}:{number}: {name}")
    if note:
        print(f"note: {note}")
    if bad:
        print("A program file names a test sheet (order 201, #805 rule 4):")
        for line in bad:
            print(f"  {line}")
        print(
            f"\nA rule for one sheet is not allowed. A comment or docstring that only RECORDS "
            f"where a bug was found may keep the name if its line carries {MARK}."
        )
        return 1
    print(f"OK: no program file names a test sheet ({len(set(names))} names checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
