"""No stray control characters in source. This is a tooling guard, not style.

Three times in this build a shell heredoc silently turned a regex escape into
the literal byte it names. `\\b` became 0x08, a backspace. Each time the result
was a pattern that could never match anything, in a rule that looked fully
implemented and had never fired once:

  * the definitional word-boundary check, so the abbreviations promotion
    silently never ran
  * the footer detection pattern
  * compound-question detection, so two-passage answers never triggered

None of the three failed loudly. Two were caught by a behavioural test that
happened to cover them; one was caught by reading a `repr()` on a hunch. A
0x08 is invisible in an editor, invisible in `sed` output, invisible in a diff,
and syntactically valid inside a string literal. Nothing else in the toolchain
looks for it.

The permanent fixes are both here: this scan fails the build, and regex
patterns are written with the file-editing tools rather than piped through a
shell. The second is a discipline; this is the enforcement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

#: Directories worth scanning. Deliberately explicit rather than "everything
#: minus ignores", so a new source tree has to be added consciously.
SOURCE_TREES = (
    ROOT / "backend" / "app",
    ROOT / "backend" / "tests",
    ROOT / "frontend" / "src",
    ROOT / "contracts",
    ROOT / "eval",
    ROOT / "scripts",
    ROOT / "docs",
    ROOT / ".github",
)

#: Files at the repository root, which no tree above covers.
ROOT_FILES = ("README.md", "CLAUDE.md", ".gitleaks.toml")

SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".md", ".yml", ".yaml"}

#: Tab, newline and carriage return are the only control characters that
#: belong in source. Everything else in the C0 range, plus DEL, is a mistake
#: or a corruption - there is no legitimate reason to type one into code.
ALLOWED = {0x09, 0x0A, 0x0D}
SUSPECT = {c for c in range(0x00, 0x20) if c not in ALLOWED} | {0x7F}

#: Names, so a failure says what the byte IS rather than printing its number.
NAMES = {
    0x00: "NUL", 0x07: "BEL", 0x08: "BACKSPACE (an eaten \\b)",
    0x09: "TAB", 0x0B: "VERTICAL TAB (an eaten \\v)",
    0x0C: "FORM FEED (an eaten \\f)", 0x1B: "ESCAPE", 0x7F: "DEL",
}


def source_files() -> list[Path]:
    files: list[Path] = []
    for tree in SOURCE_TREES:
        if not tree.exists():
            continue
        for path in tree.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if any(part in {"node_modules", "__pycache__", "dist", ".venv"}
                   for part in path.parts):
                continue
            files.append(path)
    for name in ROOT_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    return sorted(files)


def scan(path: Path) -> list[tuple[int, int, str]]:
    """Every suspect control character: (line number, codepoint, the line)."""
    found: list[tuple[int, int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return found
    for lineno, line in enumerate(text.splitlines(), 1):
        for ch in line:
            if ord(ch) in SUSPECT:
                found.append((lineno, ord(ch), line))
                break
    return found


def test_the_scan_actually_finds_files():
    """A scan over nothing passes vacuously. This build has already shipped
    three verifications that verified nothing, so the guard is guarded."""
    files = source_files()
    assert len(files) > 40, f"only {len(files)} source files found - scan is broken"
    assert any(f.suffix == ".py" for f in files)
    assert any(f.suffix == ".tsx" for f in files)


def test_the_scan_detects_a_planted_backspace(tmp_path):
    """And it fails when it should. The whole point of this file is that a
    check nobody has seen fail is not a check."""
    planted = tmp_path / "planted.py"
    planted.write_text('PATTERN = r"' + chr(8) + 'word' + chr(8) + '"\n', encoding="utf-8")
    hits = scan(planted)
    assert hits, "the scan missed a planted backspace byte"
    assert hits[0][1] == 0x08


def test_no_source_file_contains_a_stray_control_character():
    offences: list[str] = []
    for path in source_files():
        for lineno, code, line in scan(path):
            name = NAMES.get(code, f"U+{code:04X}")
            shown = "".join(
                f"<{NAMES.get(ord(c), hex(ord(c)))}>" if ord(c) in SUSPECT else c
                for c in line
            )
            offences.append(
                f"{path.relative_to(ROOT)}:{lineno}  {name}\n      {shown.strip()[:110]}"
            )
    assert not offences, (
        "stray control characters in source - almost certainly a regex escape "
        "eaten by a shell heredoc:\n  " + "\n  ".join(offences)
    )


@pytest.mark.parametrize(
    "escape,byte",
    [("\\b", 0x08), ("\\a", 0x07), ("\\v", 0x0B), ("\\f", 0x0C)],
)
def test_the_escapes_a_heredoc_eats_are_all_covered(escape, byte):
    """\\b is the one that bit three times, but it is not special - a heredoc
    will eat any of these, and each produces a pattern that cannot match."""
    assert byte in SUSPECT, f"{escape} eaten into {hex(byte)} would not be caught"
