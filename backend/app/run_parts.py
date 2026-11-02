"""What a review run states beside its three groups, and its door to the version 2 rulebook (#805 plan change 6).

The door is shut with RULEBOOK_V2_REVIEW_ENABLED off: `rulebook` is None, the module behind it is never imported, and
the other two functions hand back what they were given. Moved out of `comparison.py`, which may only shrink.
"""

from __future__ import annotations

from .config import settings
from .db import connect


def rulebook(
    run: tuple, stored: dict, facts: list, prepared: list[dict], findings: list[dict]
):
    """The run's approved version 2 rules, decided; None with the switch off. `run` starts (run id, submittal id). A
    version 1 row that disagrees with a rule on its field becomes a Query here, before it is written."""
    if not settings.rulebook_v2_review_enabled:
        return None
    from . import rulebook_v2_review

    reviewed = rulebook_v2_review.begin(connect(), run[0], run[1], stored, facts)
    reviewed.settle_with_findings(prepared, findings)
    return reviewed


def checks(reviewed, results: list[dict]) -> list[dict]:
    return reviewed.settle_with_checks(results) if reviewed else results


def written(reviewed) -> list[dict]:
    return reviewed.store(connect()) if reviewed else []


def stated(split: dict, cited: dict, coverage, divided: dict, reviewed) -> dict:
    """Each part only when it has something."""
    if cited["summary"]:  # #139: standards cited only for named clauses
        split = {**split, "cited_clauses": cited["summary"]}
    if coverage:
        split = {**split, "checklist_coverage": coverage}
    if divided["summary"]:  # #141: divisions limited by their own scope
        split = {**split, "division_scope": divided["summary"]}
    if reviewed:  # stated apart, never added
        split = {**split, "rulebook_v2": reviewed.summary()}
    return split
