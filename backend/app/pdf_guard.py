"""One process-wide lock around PyMuPDF (order 252: the live backend died of a native bus error
while a review was reading a datasheet).

PyMuPDF documents that it is not thread-safe: MuPDF keeps one process-wide context, so two threads
inside it at once, even on two different files and two different `Document` objects, can corrupt
memory, and the result is a native crash with no Python traceback. This server runs several threads
that open PDFs: the review worker, the ingestion worker, the watch-folder thread and every request
thread that renders a page image, a highlight or an evidence box.

`open_pdf` opens a document and holds the lock for exactly the time the block is open; `held` takes
the lock for a block that builds or saves a document without opening a file. The lock is re-entrant
(a block may call another that also opens a PDF on the same thread). KEEP THE BLOCKS SHORT: read
what you need inside, then leave the block before any model call or other slow wait, so a page
image is never held up behind a reading pass.

`backend/tests/test_252_pdf_guard.py` fails when a program file calls `pymupdf.open(` outside this
module, other than the files listed there (which may only shrink).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_LOCK = threading.RLock()


@contextmanager
def held() -> Iterator[None]:
    """The lock, for a block that uses PyMuPDF without `open_pdf` (a new document, a pixmap)."""
    with _LOCK:
        yield


@contextmanager
def open_pdf(*args, **kwargs) -> Iterator:
    """`pymupdf.open(*args, **kwargs)` as a context manager, holding the lock while it is open."""
    import pymupdf

    with _LOCK, pymupdf.open(*args, **kwargs) as doc:
        yield doc
