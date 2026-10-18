"""Order 117 item 4: `standard_requirements.chunk_id` is still declared
ON DELETE CASCADE, so deleting a chunk deletes the requirements read from
it - engineer-confirmed ones included. Since #659 the one place that deletes
chunks, `chunker.chunk_document`, detaches the requirements first and
re-points or supersedes them after (`orphan_guard`). This test keeps it the
one place: any other `DELETE FROM chunks` in `app/` - in a function or a
module-level constant - or a detach that no longer comes before the delete,
fails here instead of losing data.

Deleting a whole DOCUMENT is out of scope on purpose: `DELETE FROM documents`
cascades through its chunks to that standard's requirements, which is
intended when the standard itself goes. This test is about re-chunking a
document that stays.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
DELETE_CHUNKS = re.compile(r"\bDELETE\s+FROM\s+chunks\b", re.IGNORECASE)


def _deletes() -> list[tuple[str, str, int]]:
    """(file, innermost enclosing function or `<module>`, line) of every SQL
    string deleting chunks - module-level constants included."""
    found = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and DELETE_CHUNKS.search(node.value)
            ):
                continue
            around = [
                f for f in funcs if f.lineno <= node.lineno <= (f.end_lineno or 0)
            ]
            name = max(around, key=lambda f: f.lineno).name if around else "<module>"
            found.append((path.relative_to(APP).as_posix(), name, node.lineno))
    return found


def test_only_chunk_document_deletes_chunks():
    places = {(f, fn) for f, fn, _ in _deletes()}
    assert places == {("chunker.py", "chunk_document")}, places


def test_chunk_document_detaches_requirements_before_it_deletes_chunks():
    source = (APP / "chunker.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    [func] = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "chunk_document"
    ]
    detach = [
        n.lineno
        for n in ast.walk(func)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", getattr(n.func, "id", ""))
        == "detach_requirements_for_rechunk"
    ]
    [delete_line] = [line for f, fn, line in _deletes() if fn == "chunk_document"]
    assert detach, "chunk_document no longer detaches requirements before re-chunking"
    assert min(detach) < delete_line
