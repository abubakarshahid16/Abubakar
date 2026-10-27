"""Order 252: PyMuPDF is used by one thread at a time, and no new unguarded `pymupdf.open(` appears.

Invented PDFs only."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pymupdf
import pytest

from app import pdf_guard

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def pdf(tmp_path):
    doc = pymupdf.open()
    for n in range(3):
        doc.new_page().insert_text((72, 72), f"Invented page {n + 1}")
    path = tmp_path / "invented.pdf"
    doc.save(path)
    doc.close()
    return path


def test_two_threads_are_never_inside_the_guard_at_once(pdf):
    inside = 0
    worst = 0
    lock = threading.Lock()
    errors: list[BaseException] = []

    def work() -> None:
        nonlocal inside, worst
        try:
            for _ in range(25):
                with pdf_guard.open_pdf(pdf) as doc:
                    with lock:
                        inside += 1
                        worst = max(worst, inside)
                    doc[0].get_text("text")
                    doc[1].get_pixmap()
                    time.sleep(0.001)
                    with lock:
                        inside -= 1
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert worst == 1, f"{worst} threads were inside PyMuPDF at the same time"


def test_the_guard_is_reentrant_on_one_thread(pdf):
    with (
        pdf_guard.open_pdf(pdf) as outer,
        pdf_guard.open_pdf(pdf) as inner,
        pdf_guard.held(),
    ):
        assert outer.page_count == inner.page_count == 3


def test_held_blocks_another_thread_until_it_leaves(pdf):
    order: list[str] = []
    entered = threading.Event()

    def other() -> None:
        entered.wait()
        with pdf_guard.held():
            order.append("other")

    t = threading.Thread(target=other)
    t.start()
    with pdf_guard.held():
        entered.set()
        time.sleep(0.05)
        order.append("first")
    t.join()
    assert order == ["first", "other"]


#: Files that still call `pymupdf.open(` directly. This list may only SHRINK: each file moves to
#: `pdf_guard.open_pdf` and leaves the list. A file not on it may never call `pymupdf.open(`.
UNGUARDED = frozenset(
    {
        # these two BUILD a new document (`pymupdf.open()` with no file) in a long export function;
        # still to be wrapped in `pdf_guard.held()` (a block of about 40 lines each)
        "deliverables.py",
        "review.py",
    }
)


def test_no_program_file_opens_a_pdf_outside_the_guard():
    offenders = {}
    for path in sorted(APP.rglob("*.py")):
        if path.name == "pdf_guard.py":
            continue
        n = len(
            re.findall(r"\b(?:pymupdf|fitz)\.open\(", path.read_text(encoding="utf-8"))
        )
        if n:
            offenders[path.relative_to(APP).as_posix()] = n
    new = sorted(set(offenders) - UNGUARDED)
    assert not new, f"opens a PDF outside pdf_guard.open_pdf: {new}"
