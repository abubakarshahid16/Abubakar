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


#: These two files BUILD a document from nothing (`pymupdf.open()`, no file) inside a long export
#: function that carries `@pdf_guard.guarded` instead.
BUILDS_A_DOCUMENT = frozenset({"deliverables.py", "review.py"})


def test_no_program_file_opens_a_pdf_outside_the_guard():
    """Every `pymupdf.open(` is on a line that also takes `pdf_guard.held()`, or builds a document
    inside a function marked `@pdf_guard.guarded`. The process-pool children of `extract` and
    `ocr` go through `open_pdf` too (cheap, and one rule for everyone)."""
    bare, builders = [], {}
    for path in sorted(APP.rglob("*.py")):
        if path.name == "pdf_guard.py":
            continue
        name = path.relative_to(APP).as_posix()
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not re.search(r"\b(?:pymupdf|fitz)\.open\(", line):
                continue
            if "pdf_guard.held()" in line:
                continue
            if name in BUILDS_A_DOCUMENT and "pymupdf.open()" in line:
                builders[name] = text
                continue
            bare.append(f"{name}:{number}")
    assert not bare, f"opens a PDF outside the guard: {bare}"
    for name, text in builders.items():
        assert "@pdf_guard.guarded" in text, f"{name} builds a document unguarded"


def test_a_guarded_function_runs_under_the_lock(pdf):
    """The two exports that build a document from nothing are wrapped whole by `guarded`."""
    from app import deliverables, review

    for fn in (review.render_report, deliverables.render_management_report):
        assert getattr(fn, "__wrapped__", None) is not None, (
            f"{fn.__name__} is not guarded"
        )

    seen = []

    @pdf_guard.guarded
    def build():
        seen.append(threading.get_ident())
        time.sleep(0.05)
        return "built"

    result = []
    t = threading.Thread(target=lambda: result.append(build()))
    with pdf_guard.held():
        t.start()
        time.sleep(0.05)
        assert not seen, "the guarded function ran while another thread held the lock"
    t.join()
    assert result == ["built"]


def test_threads_rendering_pages_while_a_reader_runs_on_the_same_pdf(
    pdf, tmp_path, monkeypatch
):
    """The planner's test (order 252): page images from several threads while another thread runs
    a reader function on the same file. Under the lock nothing crashes and every image served is
    a complete PNG (the file is written to a temp name and moved into place)."""
    from app import datasheet_inputs, pageimage
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    document = {"sha256": "ab" * 32, "stored_path": str(pdf)}
    errors: list[BaseException] = []
    served: list[Path] = []

    def render() -> None:
        try:
            for _ in range(6):
                for page in (1, 2, 3):
                    for dpi in (72, 96):
                        served.append(pageimage.render_page(document, page, dpi))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    def read() -> None:
        try:
            for _ in range(10):
                assert len(datasheet_inputs.page_texts(pdf)) == 3
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=render) for _ in range(6)] + [
        threading.Thread(target=read)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert served
    for path in set(served):
        pix = pymupdf.Pixmap(str(path))  # raises on a truncated or half-written PNG
        assert pix.width > 0
    assert not list((tmp_path / "data").rglob("*.tmp")), "a temp file was left behind"
