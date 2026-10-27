"""Order 252: a native crash writes the stack of every thread to a file the server owns.

A child process turns the hook on and then kills itself with SIGBUS (the signal of
"zsh: bus error"); the file must hold the stack. Invented, no document."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

CHILD = """
import os, signal, sys
from pathlib import Path
from app import crash_log

def inside_the_reader():
    os.kill(os.getpid(), signal.SIGBUS)

crash_log.enable(Path(sys.argv[1]))
inside_the_reader()
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGBUS does not exist on Windows")
def test_a_bus_error_leaves_the_stack_in_the_file(tmp_path):
    log = tmp_path / "logs" / "native-crash.log"
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(log)],
        cwd=BACKEND,
        capture_output=True,
        timeout=60,
    )
    assert done.returncode != 0, "the child was meant to die from the signal"
    text = log.read_text(encoding="utf-8")
    assert "Bus error" in text
    assert "inside_the_reader" in text, text  # the Python frame that was running


def test_the_server_start_turns_it_on():
    """`run.py` calls `crash_log.enable` before uvicorn starts (a grep, not a launch)."""
    tree = ast.parse((BACKEND / "run.py").read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") == "enable"
        and getattr(getattr(n.func, "value", None), "id", "") == "crash_log"
    ]
    assert calls, "run.py must call crash_log.enable"


def test_enable_twice_keeps_one_open_file(tmp_path):
    import faulthandler

    from app import crash_log

    first = crash_log.enable(tmp_path / "a.log")
    second = crash_log.enable(tmp_path / "b.log")
    faulthandler.enable()  # back to the test runner's own stderr hook
    assert first.read_text().count("server started") == 1
    assert second.read_text().count("server started") == 1


def test_the_pdf_guard_lets_one_thread_in_at_a_time_and_is_reentrant():
    import threading
    import time

    from app import pdf_guard

    inside = 0
    worst = 0
    guard = threading.Lock()

    def work():
        nonlocal inside, worst
        with pdf_guard.held(), pdf_guard.held():  # re-entrant: no deadlock
            with guard:
                inside += 1
                worst = max(worst, inside)
            time.sleep(0.01)
            with guard:
                inside -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert worst == 1, f"{worst} threads were inside at once"
