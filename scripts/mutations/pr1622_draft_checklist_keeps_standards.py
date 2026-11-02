"""PR #1622, Lock 2: a draft checklist leaves its standards in scope, each rule under its own label."""

from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "comparison.py"
_S = APP / "checklist_scope.py"
_T = "tests/test_draft_checklist_keeps_standards.py"
_TAG = ("checklist", "rule_trust", "honesty")


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1622-{n:02d}",
        phase=1622,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a kept rule is not labelled, so an unproven rule decides",
        _C,
        '        always = rule.get("standard_document_id") in self.kept\n',
        "        always = False\n",
        "kept_unproven_rule_never_decides",
    ),
    _m(
        2,
        "a signed checklist also gives up its standards",
        _S,
        '    return settings.draft_checklist_keeps_standards_enabled and bool(\n        checklist.get("draft")\n    )\n',
        "    return settings.draft_checklist_keeps_standards_enabled\n",
        "signed_checklist_still_governs",
    ),
    _m(
        3,
        "the switch is ignored: a draft keeps its standards with it off",
        _S,
        '    return settings.draft_checklist_keeps_standards_enabled and bool(\n        checklist.get("draft")\n    )\n',
        '    return bool(checklist.get("draft"))\n',
        "off_a_draft_checklist_still_sets",
    ),
    _m(
        4,
        "the standards stay set aside with the switch on",
        _C,
        "            trust.kept, covered_ids = covered_ids, set()\n",
        "            trust.kept = covered_ids\n",
        "leaves_its_standards_in_scope",
    ),
    _m(
        5,
        "the checklist says it is signed when it is a draft",
        _S,
        '        "draft": checklist["draft"],\n',
        '        "draft": False,\n',
        "leaves_its_standards_in_scope",
    ),
)
