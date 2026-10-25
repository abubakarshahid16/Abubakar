"""PostToolUse hook for Bash (order 145.7): show a test run's failures, not its progress.

Claude Code passes the finished tool call as JSON on stdin. When the command
was a pytest or vitest run, the model is shown the trimmed stdout instead
(`scripts/trim_test_output.py` does the trimming). Everything else - another
command, another tool, a result in a shape this does not know, any error of
its own - prints nothing, which leaves the real output exactly as it was.

LIMIT, stated plainly: Claude Code runs PostToolUse only for a command that
succeeded. A run with a failing test exits non-zero and goes through
PostToolUseFailure, which can add context but cannot rewrite the output. So
this hook shortens passing runs only. For a failing run, pipe the command
through `scripts/trim_test_output.py` (the test-runner agent does).
It never changes what ran, the exit code, or what is stored. Read only.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

_TEST_COMMAND = re.compile(r"(?<![\w-])(pytest|vitest)(?![\w-])")


def _trimmer():
    path = Path(__file__).resolve().parents[2] / "scripts" / "trim_test_output.py"
    spec = importlib.util.spec_from_file_location("trim_test_output", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decide(event: dict) -> dict | None:
    """The hook's JSON answer for one tool call, or None to change nothing."""
    if event.get("tool_name") != "Bash":
        return None
    command = str((event.get("tool_input") or {}).get("command") or "")
    response = event.get("tool_response")
    if not _TEST_COMMAND.search(command) or not isinstance(response, dict):
        return None
    stdout = response.get("stdout")
    if not isinstance(stdout, str) or not stdout.strip():
        return None
    trimmed = _trimmer().trim(stdout)
    if trimmed == stdout or len(trimmed) >= len(stdout):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": {**response, "stdout": trimmed},
        }
    }


def main() -> int:
    try:
        answer = decide(json.load(sys.stdin))
    except Exception:  # noqa: BLE001 - a broken hook must never break a run
        return 0
    if answer is not None:
        sys.stdout.write(json.dumps(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
