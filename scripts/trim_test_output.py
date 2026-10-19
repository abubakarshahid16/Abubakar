"""Order 145.7: trim a test run's output to what a reader needs - the failures.

A green pytest or vitest run prints hundreds of progress lines that tell the
reader nothing; a red one buries the failure in them. This filter reads the
run's output on stdin and prints only:

  pytest   the FAILURES and ERRORS sections, "short test summary info", the
           warnings that name a file, and the final "N passed / failed" line;
           a green run is the final line plus any skipped / xfailed note;
  vitest   every line except the passing-file lines (" ✓ ...") and the
           passing-test lines, so a failure keeps its whole block, and the
           "Test Files" / "Tests" summary stays.

It NEVER hides what it does not recognise: output that is neither a pytest
nor a vitest run, or in which no summary line is found, is printed unchanged,
so a crash, a traceback or a collection error is always shown. The exit code
of the run is not this script's to touch: use it as

    <test command> 2>&1 | python scripts/trim_test_output.py ; test ${PIPESTATUS[0]} -eq 0

or let the hook in `.claude/settings.json` do it. Standard library only.
Read only; it prints what it was given, shorter. No network.
"""

from __future__ import annotations

import re
import sys

_PYTEST_SUMMARY = re.compile(
    r"^=+ .*\b(passed|failed|error|errors|skipped|xfailed|deselected|no tests ran)\b.* in [\d.]+s.*=+$"
    r"|^\d+ (passed|failed|skipped|error|errors)\b.* in [\d.]+s"
)
_PYTEST_SECTION = re.compile(r"^=+ (.+?) =+$")
_KEEP_SECTIONS = ("FAILURES", "ERRORS", "short test summary info")
_DROP_SECTIONS = ("warnings summary", "slowest", "test session starts", "PASSES")
_PROGRESS = re.compile(
    r"^[.FEsxX]+(\s+\[\s*\d+%\])?$|^\S+\.py [.FEsxX]+(\s+\[\s*\d+%\])?$"
)
_VITEST_SUMMARY = re.compile(r"^\s*(Test Files|Tests)\s+\d+")
_VITEST_PASS = re.compile(r"^\s*(✓|√)\s")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _is_pytest(lines: list[str]) -> bool:
    return any(_PYTEST_SUMMARY.match(line.strip()) for line in lines)


def _is_vitest(lines: list[str]) -> bool:
    return any(_VITEST_SUMMARY.match(line) for line in lines)


def trim_pytest(lines: list[str]) -> list[str]:
    out: list[str] = []
    keep = False
    for line in lines:
        section = _PYTEST_SECTION.match(line.strip())
        if section and not _PYTEST_SUMMARY.match(line.strip()):
            title = section.group(1)
            keep = any(title.startswith(k) for k in _KEEP_SECTIONS)
            if keep:
                out.append(line)
            continue
        if _PYTEST_SUMMARY.match(line.strip()):
            out.append(line)
            keep = False
            continue
        if keep or (not _PROGRESS.match(line.strip()) and _notable(line)):
            out.append(line)
    return out


def _notable(line: str) -> bool:
    """A line outside any kept section that a reader still needs: a skip /
    xfail note, or a line saying nothing was skipped."""
    text = line.strip().lower()
    return bool(text) and (
        text.startswith(("no tests were skipped", "skipped", "xfail", "xpass"))
        or ("skipped" in text and "reason" in text)
    )


def trim_vitest(lines: list[str]) -> list[str]:
    return [line for line in lines if not _VITEST_PASS.match(line)]


def trim(text: str) -> str:
    """The trimmed text, or the text unchanged when it is not a recognised run."""
    lines = _ANSI.sub("", text).splitlines()
    if _is_pytest(lines):
        kept = trim_pytest(lines)
    elif _is_vitest(lines):
        kept = trim_vitest(lines)
    else:
        return text
    return "\n".join(kept) + "\n" if kept else text


def main() -> int:
    sys.stdout.write(trim(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
