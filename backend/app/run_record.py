"""Order 109: the stored JSON columns of ONE review run row, parsed.

The caller has already read the row under its grants (`submittal_review`'s
scoped reads). The runs list used to re-read every run by id, scoped with
`IN` every readable document, three times per row, only to parse these two
columns. `comparison.run_outcome` and `ai_engineering_check.ai_check_status`
are a scoped read plus these.
"""

from __future__ import annotations

import json


def outcome_of(run: dict) -> dict:
    """The stored recommendation and decision; {} when none or malformed."""
    try:
        return json.loads(run.get("refusal_reason") or "{}")
    except (TypeError, ValueError):
        return {}


def ai_check_status_of(run: dict) -> dict | None:
    """The AI check's own stored outcome; None when it never ran or is malformed."""
    raw = run.get("ai_check_status")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
