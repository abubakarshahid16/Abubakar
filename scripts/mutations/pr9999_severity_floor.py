"""Order 152.2 (severity): a failed requirement is never filed minor. Ids M9999-01 to M9999-05."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_9999_severity.py"
_R = APP / "severity_rule.py"
_TAG = ("severity", "crs")


def _m(n, desc, path, anchor, repl, kw=None):
    return Mutation(
        id=f"M9999-{n:02d}",
        phase=9999,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a failed finding is read as stored: no floor on the read side",
        _R,
        "    if status == FAILED:\n        return _at_least(word, FLOOR_FAILED)\n",
        "    if status == FAILED:\n        return word\n",
        "old_stored_minor",
    ),
    _m(
        2,
        "the write side ignores the rule and stores the item's own severity",
        APP / "datasheet_checks.py",
        '            "severity": severity_rule.stored_severity(\n'
        '                status, r["severity"] if r.get("checklist") else None),\n',
        '            "severity": (r["severity"] if r.get("checklist") and status == NON_COMPLIANT\n'
        '                         else "major" if status == NON_COMPLIANT else "minor"),\n',
        "stored_major",
    ),
    _m(
        3,
        "the row severity is read from the stored word, not the effective one",
        APP / "crs_mapping.py",
        "    found = {severity_rule.effective_severity(g) for g in group}",
        '    found = {str(g.get("severity") or "").lower() for g in group}',
        "old_stored_minor",
    ),
    _m(
        4,
        "the floor for a failed requirement is lowered to minor",
        _R,
        'FLOOR_FAILED = "major"',
        'FLOOR_FAILED = "minor"',
        "at_least_major",
    ),
    _m(
        5,
        "the better severity is kept instead of the worse",
        _R,
        "    return min(word, floor, key=ORDER.index)",
        "    return max(word, floor, key=ORDER.index)",
        "critical_item_stays",
    ),
)
