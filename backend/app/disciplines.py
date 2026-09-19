"""Raw discipline spellings, and the canonical value they collapse to.

WHY BOTH ARE KEPT. `discipline` is what the standard's own cover page says.
It is evidence, and this system does not rewrite evidence - the same rule that
keeps a recommendation beside an engineer's final code rather than replacing
it. `discipline_canonical` is the editorial answer to "are these two the same
discipline", derived from the raw value and stored beside it.

So: the raw column is NEVER written by this module. A migration that
normalised it in place would destroy the only record of what the document
actually said, and there would be no way back - "Non-metallic" and
"Nonmetallic" are indistinguishable once merged.

A RAW VALUE ABSENT FROM THE MAPPING COPIES THROUGH UNCHANGED. Never NULL. A
value nobody has reviewed is still the document's own answer, and blanking it
would turn "not yet reviewed" into "has no discipline", which is a different
and false claim. The mapping is an editorial overlay, not a whitelist.

`backend/app/reference/discipline_aliases.json` was generated for review and
sat unapplied because collapsing spellings is a person's decision. It has now
been made, and this module is where it takes effect.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .db import add_column_if_missing, connect

ALIASES_PATH = Path(__file__).parent / "reference" / "discipline_aliases.json"


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """The raw -> canonical map, read once.

    Cached because it is a static reference file read on every classification
    write; `cache_clear()` is available to a test that rewrites it.
    """
    data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    return dict(data.get("aliases") or {})


def canonical(raw: str | None) -> str | None:
    """The canonical spelling for a raw discipline.

    None and blank stay as they are: a document with no discipline recorded
    has no canonical one either, and inventing one would be a claim the
    cover page did not make.

    An UNMAPPED value returns itself. That is the rule that keeps this an
    overlay rather than a whitelist - see the module docstring.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return aliases().get(text, text)


def ensure_schema() -> None:
    """Add `discipline_canonical` beside `discipline`. Race-safe.

    `add_column_if_missing` rather than a check-then-ALTER: two requests
    arriving together both saw the column missing and the second died with
    `duplicate column name` (honesty audit entry 40).
    """
    add_column_if_missing(
        connect(), "document_classification", "discipline_canonical", "TEXT")


def backfill() -> dict:
    """Populate `discipline_canonical` from `discipline`, for every row.

    Returns what it did, in numbers a person can check: how many rows carry a
    discipline at all, how many now read differently from their raw value, and
    how many raw spellings that covers. A migration that reported only
    "done" would be asking to be trusted.

    Idempotent: running it twice changes nothing the second time, because it
    derives the canonical value from the raw one every time rather than from
    the previous canonical.
    """
    ensure_schema()
    conn = connect()
    rows = conn.execute(
        "SELECT document_id, discipline FROM document_classification"
    ).fetchall()

    changed_values: set[tuple[str, str]] = set()
    written = 0
    with conn:
        for row in rows:
            raw = row["discipline"]
            value = canonical(raw)
            conn.execute(
                "UPDATE document_classification SET discipline_canonical = ?"
                " WHERE document_id = ?", (value, row["document_id"]))
            written += 1
            if raw and value and raw.strip() != value:
                changed_values.add((raw.strip(), value))

    with_discipline = sum(
        1 for r in rows if (r["discipline"] or "").strip())
    changed_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM document_classification"
        " WHERE discipline IS NOT NULL AND TRIM(discipline) <> ''"
        " AND discipline_canonical <> TRIM(discipline)").fetchone()["n"]
    return {
        "rows": written,
        "with_discipline": with_discipline,
        "rows_changed": changed_rows,
        "spellings_changed": sorted(changed_values),
    }
