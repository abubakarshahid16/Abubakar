"""Order 301.3: the clause-shape count reads clauses by shape and prints counts only. Invented clauses."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "clause_shape_count",
    Path(__file__).resolve().parents[2] / "scripts" / "clause_shape_count.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_counts_each_shape_per_document_and_in_total():
    rows = [
        ("d1", "UG-125"),
        ("d1", "UW-12(b)"),
        ("d1", "7.16"),
        ("d1", "7.16"),
        ("d1", ""),
        ("d1", None),
        ("d2", "Appendix 1"),
        ("d2", "3"),
    ]
    out = mod.count(rows)
    assert out["documents"]["d1"] == {
        "own_numbering": 2,
        "plain_dotted_number": 2,
        "no_clause": 2,
    }
    assert out["documents"]["d2"] == {"other": 2}
    assert out["total"] == {
        "own_numbering": 2,
        "plain_dotted_number": 2,
        "no_clause": 2,
        "other": 2,
    }


def test_the_own_pattern_decides_what_counts_as_own():
    rows = [("d", "7.16"), ("d", "UG-125")]
    out = mod.count(rows, r"^\d+(?:\.\d+)+$")
    assert out["total"] == {"own_numbering": 1, "other": 1}
