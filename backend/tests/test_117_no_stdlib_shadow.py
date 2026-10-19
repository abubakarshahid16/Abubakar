"""Order 117 item 8: no module of the app shares a name with the standard library.

`app/keyword.py` did. A Python started inside `backend/app` puts that folder
first on the path, and unless the interpreter had already loaded the standard
`keyword` at startup, `collections` imported the FTS5 index in its place: with
`python -S` there, `import dataclasses` failed with a circular-import
ImportError before any app code ran (checked 2026-10-18). The module is
`fts_index.py` now; this keeps the next one out of the same trap.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_no_app_module_is_named_like_a_standard_library_module():
    shadowing = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path.stem in sys.stdlib_module_names
    )
    assert shadowing == [], f"these hide a standard-library module: {shadowing}"
