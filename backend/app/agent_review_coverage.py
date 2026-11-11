"""Rule book coverage for the Rules used page (owner 11 Nov 2026, STATE 16.3 point 1).

A coverage file placed under the data directory (`<data dir>/coverage/coverage.json`, made by the free coverage check) says,
per rule book, how many requirement sentences (shall, must, should) its pages hold and how many of them a stored rule covers,
and how many pages could not be read or were read weakly. This module only READS it:

  * the file absent, unreadable or not the expected shape: nothing (an empty answer, never a zero);
  * a book with no row: every number None (the screen shows no percentage, never 0 per cent);
  * the percentage is NOT computed here: the screen computes it from the two integers, so the denominator is always shown.

Shape read (both spellings of a count are accepted): {"books": {<document id>: {"sentences" | "requirement_sentences": n,
"covered": n, "unreadable_pages": [..] | n, "weak_pages": [..] | n, "below_50": bool}}}.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .config import settings

FILE = Path("coverage") / "coverage.json"


def _count(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, list):
        return len(value)
    return None


def load(path: Path | None = None) -> dict[str, dict]:
    """{document id: row} from the coverage file; {} when it is absent or unreadable."""
    target = path or Path(settings.data_dir) / FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    books = raw.get("books") if isinstance(raw, dict) else None
    return (
        {str(k): v for k, v in books.items() if isinstance(v, dict)}
        if isinstance(books, dict)
        else {}
    )


def row_for(book: Mapping | None, rule_book: str) -> dict:
    """The contract's `AgentBookCoverage` fields for one book; every number None when there is no row."""
    out = {
        "rule_book": rule_book,
        "requirement_sentences": None,
        "covered_sentences": None,
        "unreadable_pages": None,
        "weak_pages": None,
        "below_half": None,
    }
    if not book:
        return out
    sentences = _count(book.get("requirement_sentences", book.get("sentences")))
    covered = _count(book.get("covered", book.get("covered_sentences")))
    if sentences is None or covered is None or covered > sentences:
        return out  # a row we cannot trust is no row
    out.update(
        requirement_sentences=sentences,
        covered_sentences=covered,
        unreadable_pages=_count(book.get("unreadable_pages")),
        weak_pages=_count(book.get("weak_pages")),
        below_half=bool(sentences and covered * 2 < sentences),
    )
    return out
