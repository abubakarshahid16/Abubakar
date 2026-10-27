"""Order 252: the reader's PyMuPDF sites never run at the same time as each other.

MuPDF keeps one context per process and is not thread-safe; the review worker, the request threads
and the ingestion thread all open PDFs. Each site below is called from several threads on an
invented PDF while `pymupdf.open` is wrapped to count how many documents are open at once (and to
hold each open for a moment, so an overlap shows). With the lock the count never passes 1.
The model call of the vision reader must be OUTSIDE the lock. Invented data only."""

from __future__ import annotations

import threading
import time

import pymupdf
import pytest

from app import (
    claude_datasheet,
    datasheet_inputs,
    datasheets,
    pdf_guard,
    tables,
    vision_reader,
)

THREADS = 6


@pytest.fixture
def pdf_path(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Design pressure   10 barg")
    page.insert_text((72, 130), "Design temperature   120 C")
    path = tmp_path / "sheet.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def overlap(monkeypatch):
    """Wrap `pymupdf.open`: how many documents were open at once at the worst moment."""
    state = {"open": 0, "worst": 0}
    lock = threading.Lock()
    real = pymupdf.open

    class Tracked:
        def __init__(self, doc):
            self._doc = doc

        def __enter__(self):
            with lock:
                state["open"] += 1
                state["worst"] = max(state["worst"], state["open"])
            time.sleep(0.01)  # hold it open long enough for a second thread to arrive
            self._doc.__enter__()
            return self._doc

        def __exit__(self, *exc):
            try:
                return self._doc.__exit__(*exc)
            finally:
                with lock:
                    state["open"] -= 1

        def __getattr__(self, name):
            return getattr(self._doc, name)

    def tracked_open(*args, **kwargs):
        return Tracked(real(*args, **kwargs))

    monkeypatch.setattr(pymupdf, "open", tracked_open)
    return state


def _run_together(call):
    errors = []

    def work():
        try:
            for _ in range(3):
                call()
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors


#: Sites that take the lock page by page (`pdf_guard.per_page`).
PER_PAGE = frozenset({"inputs_read_pdf"})

SITES = {
    "pdf_condition": lambda p: datasheets.pdf_condition(p),
    "pairs": lambda p: datasheets._pairs_from_pdf_page(p, 1),
    "grid": lambda p: datasheets._grid_facts_from_pdf_page(p, 1),
    "geometry": lambda p: datasheets._geometry_rows_from_pdf_page(p, 1),
    "text_layer": lambda p: datasheets._text_layer_words(p, 1),
    "tables": lambda p: tables.parse_page_tables(p, 1),
    "claude_page_text": lambda p: claude_datasheet._pdf_page_text(p, 1),
    "inputs_read_pdf": lambda p: datasheet_inputs.read_pdf(p),
}


@pytest.mark.parametrize("name", sorted(SITES))
def test_the_site_never_has_two_documents_open_at_once(name, pdf_path, overlap):
    _run_together(lambda: SITES[name](pdf_path))
    # `read_pdf` opens its document with `pdf_guard.opened` (lock per page, not for the file), which
    # does not enter the wrapped `with`: it is counted 0 here and its lock is tested page by page in
    # `test_252_pdf_guard.py`.
    expected = (0, 1) if name in PER_PAGE else (1,)
    assert overlap["worst"] in expected, (
        f"{name}: {overlap['worst']} documents open at once"
    )


def test_different_sites_together_never_overlap_either(pdf_path, overlap):
    calls = [SITES[n] for n in sorted(SITES)]
    errors = []

    def one(call):
        try:
            call(pdf_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(c,)) for c in calls * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert overlap["worst"] == 1


def test_the_vision_model_call_is_outside_the_lock(pdf_path):
    """Another thread can take the lock while the (slow) model call runs."""
    seen = {}

    class Provider:
        def reason(self, packet):
            got = threading.Event()

            def other():
                with pdf_guard.held():
                    got.set()

            t = threading.Thread(target=other)
            t.start()
            seen["free"] = got.wait(timeout=5)
            t.join()
            raise RuntimeError("stop here: the answer does not matter")

    reading = datasheets._vision_reading(pdf_path, 1, [], Provider())
    assert seen.get("free") is True, "the lock was held across the model call"
    assert reading is not None and reading.refused


def test_the_pdf_guard_opened_gives_the_document_without_the_lock(pdf_path):
    with pdf_guard.opened(pdf_path) as doc:
        got = []

        def other():
            with pdf_guard.held():
                got.append(True)

        t = threading.Thread(target=other)
        t.start()
        t.join(timeout=5)
        assert got == [True], "the lock was held while the document was handed over"
        assert doc.page_count == 1


def test_vision_reader_takes_the_lock_for_its_page_reads(pdf_path, monkeypatch):
    """The render and the text read hold the lock; the model call between them does not."""
    owned = {}
    real_render = vision_reader.render
    real_of = vision_reader.PageText.of

    def render(page):
        owned["render"] = pdf_guard._lock._is_owned()
        return real_render(page)

    def of(page):
        owned["text"] = pdf_guard._lock._is_owned()
        return real_of(page)

    class Provider:
        def reason(self, packet):
            owned["model"] = pdf_guard._lock._is_owned()
            return type(
                "R",
                (),
                {
                    "text": '{"page_kind": "form", "fields": []}',
                    "model_tag": "t",
                    "schema_errors": None,
                    "truncated": False,
                },
            )()

    monkeypatch.setattr(vision_reader, "render", render)
    monkeypatch.setattr(vision_reader.PageText, "of", staticmethod(of))
    with pymupdf.open(pdf_path) as doc:
        vision_reader.read_page(doc[0], 1, Provider())
    assert owned == {"render": True, "model": False, "text": True}, owned


def test_read_page_of_gives_none_for_a_missing_page_and_leaves_the_lock_free(pdf_path):
    with pdf_guard.opened(pdf_path) as doc:
        assert vision_reader.read_page_of(doc, 9, object(), None) is None
    got = []

    def other():
        with pdf_guard.held():
            got.append(True)

    t = threading.Thread(target=other)
    t.start()
    t.join(timeout=5)
    assert got == [True]
