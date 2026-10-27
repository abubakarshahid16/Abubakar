"""A native crash leaves the stack of every thread in a file (order 252).

"zsh: bus error" (or a segfault) is the process dying inside C code: no Python exception, no
traceback, and the terminal shows one line. `faulthandler` is the standard-library hook that
prints the Python stack of every thread when the process gets SIGSEGV, SIGBUS, SIGFPE, SIGABRT
or SIGILL. It used to need `PYTHONFAULTHANDLER=1` in the environment of whoever started the
server; here the server turns it on itself and writes to a file under the data directory, so
the evidence outlives the terminal window.

The file holds frame names, file names and line numbers of OUR code, never document text.
"""

from __future__ import annotations

import faulthandler
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

#: Held open for the life of the process: faulthandler writes through this descriptor.
_open: TextIO | None = None


def enable(path: Path) -> Path:
    """Turn on crash stacks, appended to `path` (its folder is made). Returns `path`."""
    global _open
    path.parent.mkdir(parents=True, exist_ok=True)
    if _open is not None:
        faulthandler.disable()
        _open.close()
    _open = path.open("a", buffering=1, encoding="utf-8")
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    _open.write(f"--- server started {stamp} (native crash stacks go below) ---\n")
    faulthandler.enable(file=_open, all_threads=True)
    return path
