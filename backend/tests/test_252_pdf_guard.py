"""Order 252: PyMuPDF is used by one thread at a time, and no new unguarded `pymupdf.open(` appears.

Invented PDFs only."""

from __future__ import annotations

import ast
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


#: PyMuPDF names that are plain value types (pure Python, no MuPDF context): not guarded.
VALUE_TYPES = frozenset(
    {"Rect", "IRect", "Point", "Matrix", "Quad", "paper_rect", "paper_size"}
)
#: Lock-taking context managers of `pdf_guard` (`opened` hands the document out WITHOUT the lock,
#: so a call under it is not covered by it).
LOCKS = frozenset({"held", "open_pdf"})


def _module_names(tree: ast.AST) -> set[str]:
    """Every name `pymupdf` / `fitz` is bound to in the file (`import pymupdf as pm` too)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {
                a.asname or a.name for a in node.names if a.name in ("pymupdf", "fitz")
            }
    return names


def _is_guard_call(expr: ast.AST, names: frozenset[str]) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr in names
        and (
            (
                isinstance(expr.func.value, ast.Name)
                and expr.func.value.id == "pdf_guard"
            )
            # `datasheets.pdf_guard.held()`: the module reached through another module
            or (
                isinstance(expr.func.value, ast.Attribute)
                and expr.func.value.attr == "pdf_guard"
            )
        )
    )


def _covered(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """The call sits under `with pdf_guard.held()/open_pdf(...)` or in a `@pdf_guard.guarded`
    function (or one decorated with the bare name `guarded`)."""
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.With, ast.AsyncWith)) and any(
            _is_guard_call(item.context_expr, LOCKS) for item in current.items
        ):
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in current.decorator_list:
                if (isinstance(deco, ast.Attribute) and deco.attr == "guarded") or (
                    isinstance(deco, ast.Name) and deco.id == "guarded"
                ):
                    return True
        current = parents.get(current)
    return False


def unguarded_calls(source: str) -> list[int]:
    """Line numbers of calls into PyMuPDF (any alias) that are not under the lock, plus any
    `from pymupdf import ...` (which would hide the module name)."""
    tree = ast.parse(source)
    names = _module_names(tree)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    bad = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in ("pymupdf", "fitz")
    ]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in names
            and node.func.attr not in VALUE_TYPES
            and not _covered(node, parents)
        ):
            bad.append(node.lineno)
    return sorted(bad)


def test_no_program_file_calls_pymupdf_outside_the_guard():
    """An AST scan, not a text search: `pymupdf.open`, `Document`, `Story`, `get_text_length`, any
    alias (`import pymupdf as pm`) and `from pymupdf import ...` are all found. Every such call must
    sit under `with pdf_guard.held()` / `open_pdf(...)` or in a `@pdf_guard.guarded` function (the
    exemption is per function, not per file).

    What this does NOT check (said, not hidden): the order of the items of ONE `with` (`with
    pymupdf.open(p), pdf_guard.held():` would pass), and methods called on a page or pixmap OBJECT
    (`page.get_text()`) after the block that made it: `test_the_page_and_pixmap_are_dropped_while_
    the_lock_is_held` and the site tests cover the objects the web renders make."""
    offenders = {}
    for path in sorted(APP.rglob("*.py")):
        if path.name == "pdf_guard.py":
            continue
        bad = unguarded_calls(path.read_text(encoding="utf-8"))
        if bad:
            offenders[path.relative_to(APP).as_posix()] = bad
    assert not offenders, f"PyMuPDF used outside pdf_guard: {offenders}"


def test_the_scan_finds_what_a_text_search_would_miss():
    assert unguarded_calls("import pymupdf\ndoc = pymupdf.open(p)\n") == [2]
    assert unguarded_calls("import pymupdf as pm\ndoc = pm.open(p)\n") == [2]
    assert unguarded_calls("import pymupdf\nstory = pymupdf.Story(html=h)\n") == [2]
    assert unguarded_calls("from pymupdf import open\n") == [1]
    assert unguarded_calls("import pymupdf\nx = pymupdf.get_text_length('a')\n") == [2]
    # a value type and covered calls are fine
    assert unguarded_calls("import pymupdf\nr = pymupdf.Rect(0, 0, 1, 1)\n") == []
    held = "import pymupdf\nwith pdf_guard.held():\n    d = pymupdf.open(p)\n"
    assert unguarded_calls(held) == []
    multi = "import pymupdf\nwith (\n    pdf_guard.held(),\n    pymupdf.open(p) as d,\n):\n    pass\n"
    assert unguarded_calls(multi) == []
    deco = "import pymupdf\n@pdf_guard.guarded\ndef f():\n    return pymupdf.open()\n"
    assert unguarded_calls(deco) == []
    other = "import pymupdf\n@pdf_guard.guarded\ndef f():\n    return 1\n\ndef g():\n    return pymupdf.open()\n"
    assert unguarded_calls(other) == [7], "the exemption is per function"
    opened = "import pymupdf\nwith pdf_guard.opened(p) as d:\n    x = pymupdf.get_text_length('a')\n"
    assert unguarded_calls(opened) == [3], (
        "opened() hands the document out without the lock"
    )


def test_a_guarded_function_runs_under_the_lock(pdf):
    """The two exports that build a document from nothing do the building in a guarded function
    (the data is read before, outside the lock)."""
    from app import deliverables, review_report_pdf

    for fn in (review_report_pdf.write, deliverables._write_management_report):
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


def test_a_whole_file_read_lets_other_threads_in_between_pages(tmp_path, monkeypatch):
    """`datasheet_inputs.read_pdf` takes the lock page by page: while it reads a 30-page file
    another thread can get the lock long before the read ends (before, it held it for the whole
    file and every page image waited)."""
    from app import datasheet_inputs, quality

    doc = pymupdf.open()
    for n in range(30):
        doc.new_page().insert_text((72, 72), f"Invented page {n + 1}")
    path = tmp_path / "long.pdf"
    doc.save(path)
    doc.close()

    def slow_normalise(text):  # runs outside the lock, once per page
        time.sleep(0.02)
        return text

    monkeypatch.setattr(quality, "normalise_text", slow_normalise)
    done = threading.Event()
    reader = threading.Thread(
        target=lambda: (datasheet_inputs.read_pdf(path), done.set())
    )
    reader.start()
    time.sleep(0.05)
    got = threading.Event()

    def take_the_lock():
        with pdf_guard.held():
            got.set()

    taker = threading.Thread(target=take_the_lock)
    taker.start()
    assert got.wait(timeout=0.3), "the lock was held for the whole file"
    taker.join()
    reader.join()
    assert done.is_set()


def _spy(owned: dict, name: str, result=None):
    """A stand-in that records whether the lock was held when it was called."""

    def spy(*_args, **_kwargs):
        owned[name] = pdf_guard._lock._is_owned()
        return result

    return spy


def _watch_open(module, owned: dict, monkeypatch) -> None:
    real_open = pymupdf.open

    def watching(*args, **kwargs):
        owned["build"] = pdf_guard._lock._is_owned()
        return real_open(*args, **kwargs)

    monkeypatch.setattr(module.pymupdf, "open", watching)


def test_the_management_report_reads_its_data_before_the_lock(tmp_path, monkeypatch):
    """The lock must never wait on SQLite: every data read happens with the lock NOT held, and the
    document is built with it held."""
    from app import deliverables
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    owned: dict = {}
    for name in ("list_items", "alerts", "reminder_events"):
        monkeypatch.setattr(deliverables, name, _spy(owned, name, []))
    _watch_open(deliverables, owned, monkeypatch)
    assert deliverables.render_management_report().exists()
    assert owned == {
        "list_items": False,
        "alerts": False,
        "reminder_events": False,
        "build": True,
    }


def test_the_review_report_reads_its_data_before_the_lock(tmp_path, monkeypatch):
    from app import export_status, review
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    owned: dict = {}

    class Conn:
        def execute(self, *_args, **_kwargs):
            owned["connect"] = pdf_guard._lock._is_owned()
            return self

        def fetchone(self):
            return {"filename": "invented.pdf"}

    header = ({"status": "completed", "reason": None}, [])
    monkeypatch.setattr(review, "ensure_schema", _spy(owned, "schema"))
    monkeypatch.setattr(review, "connect", lambda: Conn())
    monkeypatch.setattr(review, "list_findings", _spy(owned, "findings", []))
    monkeypatch.setattr(
        export_status, "pdf_header_lines", _spy(owned, "header", header)
    )
    from app import review_report_pdf

    _watch_open(review_report_pdf, owned, monkeypatch)
    assert review.render_report("doc1").exists()
    assert owned == {
        "schema": False,
        "connect": False,
        "findings": False,
        "header": False,
        "build": True,
    }


def test_the_page_and_pixmap_are_dropped_while_the_lock_is_held(
    pdf, tmp_path, monkeypatch
):
    """`del pix, page` runs INSIDE the lock: when the open block is left, nothing the page and the
    pixmap held is still alive (freed after the lock they would be freed unguarded)."""
    import contextlib
    import weakref

    from app import pageimage
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    refs: list[weakref.ref] = []
    seen: dict = {}
    real_open = pageimage.open_pdf

    @contextlib.contextmanager
    def watching(path):
        with real_open(path) as doc:
            real_load = doc.load_page

            def load(index):
                page = real_load(index)
                refs.append(weakref.ref(page))
                return page

            doc.load_page = load
            try:
                yield doc
            finally:  # still inside the lock
                seen["owned"] = pdf_guard._lock._is_owned()
                seen["alive"] = [r() is not None for r in refs]

    monkeypatch.setattr(pageimage, "open_pdf", watching)
    pageimage.render_page({"sha256": "cd" * 32, "stored_path": str(pdf)}, 1, 72)
    assert seen["owned"] is True
    assert refs and seen["alive"] == [False] * len(refs), (
        "the page was still alive after the block"
    )
