"""One process-wide lock for PyMuPDF (order 252).

PyMuPDF documents itself as not thread-safe: MuPDF keeps one context for the whole process, so
two threads inside it at the same time, even on different files, can corrupt memory. The symptom
is a native crash with no Python traceback. The review worker reads a datasheet page by page
while request threads draw page images and evidence boxes and the ingestion thread extracts text,
all in this one process; nothing kept them apart.

USE. Take `held()` around a SHORT block of PyMuPDF calls (open, read a page, draw a page, close):

    with pdf_guard.held():
        with pymupdf.open(path) as pdf:
            text = pdf[page].get_text()

It is re-entrant, so a guarded function may call another guarded one. NEVER hold it across a
model call, a network call, a wait, or a whole reading pass: a pass is minutes long and would
freeze every page image meanwhile. Split the open from the slow work and take the lock twice.

The process pools (`extract`, `ocr`) run in other processes with their own MuPDF context and need
no lock.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from contextlib import contextmanager

_lock = threading.RLock()


@contextmanager
def held():
    """The lock for one short block of PyMuPDF calls."""
    with _lock:
        yield


@contextmanager
def opened(path):
    """A PyMuPDF document opened under the lock and closed under it, handed over WITHOUT the lock:
    for a caller that must do slow work (a model call) between page reads. Every page read in
    that caller takes `held()` itself."""
    import pymupdf

    with _lock:
        doc = pymupdf.open(path)
    try:
        yield doc
    finally:
        with _lock:
            doc.close()


@contextmanager
def open_pdf(*args, **kwargs):
    """`pymupdf.open(*args, **kwargs)` as a context manager that holds the lock exactly while the
    document is open: the short form of `held()` + `pymupdf.open` for a block that reads pages and
    nothing slow. For slow work in between use `opened()`."""
    import pymupdf

    with _lock, pymupdf.open(*args, **kwargs) as doc:
        yield doc


def guarded(fn: Callable) -> Callable:
    """Run the whole function under the lock: for an export that builds a document from nothing
    (`pymupdf.open()` with no file) in a long body that is not worth re-indenting. It must not call
    a model or wait on another thread."""

    @functools.wraps(fn)
    def inside_the_lock(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)

    return inside_the_lock
