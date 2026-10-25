"""Order 145.7: trim a test run's output to what a reader needs - the failures.

A green pytest or vitest run prints hundreds of progress lines that tell the
reader nothing; a red one buries the failure in them. This filter reads the
run's output on stdin and DROPS ONLY KNOWN NOISE, keeping everything else:

  pytest   drops the progress lines, the session header (platform, rootdir,
           plugins, "collected N items"), the "warnings summary" and
           "slowest durations" sections and blank lines outside a failure.
           FAILURES, ERRORS and "short test summary info" are kept whole, so
           a line inside a failure that looks like a section header
           ("=== step 1 ===") stays, and so does any other text - a crash, a
           traceback, an xdist message - printed outside those sections;
  vitest   drops only the passing lines (" \u2713 ..."), so a failure keeps its
           whole block, "stderr |" blocks and the "Test Files" / "Tests" summary.

It NEVER hides what it does not recognise: output that is neither a pytest
nor a vitest run, or that holds BOTH (one command running both), is printed
unchanged, so a traceback or a collection error is always shown. The exit code
of the run is not this script's to touch: use it as

    <test command> 2>&1 | python scripts/trim_test_output.py ; test ${PIPESTATUS[0]} -eq 0   (bash; in zsh use `pipestatus[1]`)

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
#: pytest's own section titles. A line that looks like a header but is not one
#: of these (a test printing "=== step 1 ===") is ordinary content.
_KEEP_SECTIONS = ("FAILURES", "ERRORS", "short test summary info", "XFAILURES")
_DROP_SECTIONS = ("warnings summary", "slowest", "PASSES", "test session starts")
_PROGRESS = re.compile(
    r"^[.FEsxX]+(\s+\[\s*\d+%\])?$|^\S+\.py [.FEsxX]+(\s+\[\s*\d+%\])?$"
)
#: the header lines pytest prints before the first test, and nothing else
_SESSION_NOISE = re.compile(
    r"^(platform |rootdir:|configfile:|testpaths:|plugins:|cachedir:|collecting |collected |"
    r"Using --randomly|asyncio:|benchmark:)"
)
_VITEST_SUMMARY = re.compile(r"^\s*(Test Files|Tests)\s+\d+")
_VITEST_PASS = re.compile(r"^\s*(\u2713|\u221a)\s")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: what the body of a dropped section looks like (warning locations and text,
#: the docs link, a duration row). Any other line ends the section and is kept:
#: a plugin's own banner after the warnings must never be swallowed with them.
_DROP_BODY = re.compile(
    r"^(\s|\S+::\S|-- Docs:|\d+(\.\d+)?s (call|setup|teardown)|\(\d+ durations)"
)

_NEUTRAL, _KEEP, _DROP = "neutral", "keep", "drop"


def _is_pytest(lines: list[str]) -> bool:
    return any(_PYTEST_SUMMARY.match(line.strip()) for line in lines)


def _is_vitest(lines: list[str]) -> bool:
    return any(_VITEST_SUMMARY.match(line) for line in lines)


def trim_pytest(lines: list[str]) -> list[str]:
    """Drop only what pytest itself calls noise: progress lines, the session
    header, the warnings and durations sections. Everything else - a failure,
    a captured line that looks like a header, a crash before the summary, an
    xdist message - is kept."""
    out: list[str] = []
    state = _NEUTRAL
    for line in lines:
        text = line.strip()
        if _PYTEST_SUMMARY.match(text):
            out.append(line)
            state = _NEUTRAL
            continue
        section = _PYTEST_SECTION.match(text)
        title = section.group(1) if section else ""
        if state == _DROP and not section and (not text or _DROP_BODY.match(line)):
            continue
        if state == _DROP:
            state = _NEUTRAL
        if section and title.startswith(_KEEP_SECTIONS):
            state = _KEEP
            out.append(line)
        elif section and title.startswith(_DROP_SECTIONS):
            state = _DROP
        elif state == _KEEP or (
            state == _NEUTRAL
            and text
            and not (_PROGRESS.match(text) or _SESSION_NOISE.match(text))
        ):
            out.append(line)
    return out


def trim_vitest(lines: list[str]) -> list[str]:
    return [line for line in lines if not _VITEST_PASS.match(line)]


def trim(text: str) -> str:
    """The trimmed text, or the text unchanged when it is not a recognised run
    (or is two runs in one output)."""
    lines = _ANSI.sub("", text).splitlines()
    pytest_run, vitest_run = _is_pytest(lines), _is_vitest(lines)
    if pytest_run == vitest_run:  # neither, or both: do not guess
        return text
    kept = trim_pytest(lines) if pytest_run else trim_vitest(lines)
    return "\n".join(kept) + "\n" if kept else text


def main() -> int:
    sys.stdout.write(trim(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
