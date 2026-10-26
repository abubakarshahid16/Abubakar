"""#947 / PR #985: rule_trust wired into the review behind `rule_auto_use_enabled`.
Each entry deletes one control of the owner's decision (14 Oct);
backend/tests/test_947_rule_trust_wiring.py must notice. Ids M985-01..09,
named after the PR (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_947_rule_trust_wiring.py"
_TAG = ("rule_trust", "safety", "critical")


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(id=f"M985-{n:02d}", phase=985, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "the verdict skips rule_trust: an unproven rule decides",
       APP / "comparison.py",
       "            if trust is not None:\n                verdict = trust.label(verdict, requirement)\n",
       "            if False:\n                verdict = trust.label(verdict, requirement)\n",
       "unproven_rule_never_decides"),
    _m(2, "AI drafts are used with the switch OFF",
       APP / "ai_requirements.py",
       "    if not settings.rule_auto_use_enabled or standard_document_id not in allowed_document_ids:\n"
       "        return {}\n",
       "    if standard_document_id not in allowed_document_ids:\n        return {}\n",
       "off_uses_no_draft"),
    _m(3, "an UNPROVEN rule's COMPLIANT / NON_COMPLIANT stands (rule_trust.apply_trust)",
       APP / "rule_trust.py",
       "    if label == UNPROVEN and verdict.get(\"status\") in (COMPLIANT, NON_COMPLIANT):\n",
       "    if False:\n",
       "unproven_rule_never_decides"),
    _m(4, "the issue copy carries the safety tick row",
       APP / "crs_export.py",
       "                    and f.get(\"row_kind\") != ROW_KIND_SAFETY_TICK]\n",
       "                    ]\n",
       "gates_issue_until_ticked"),
    _m(5, "a safety tick row counts as confirmed before anyone ticked it",
       APP / "crs_mapping.py",
       "            \"row_kind\": ROW_KIND_SAFETY_TICK,\n            \"severity\": \"\",\n"
       "            \"engineer_confirmed\": _confirmed(f),\n",
       "            \"row_kind\": ROW_KIND_SAFETY_TICK,\n            \"severity\": \"\",\n"
       "            \"engineer_confirmed\": True,\n",
       "gates_issue_until_ticked"),
    _m(6, "an engineer's decision on a proven rule's finding is not an audit outcome",
       APP / "crs_issue.py",
       "        rule_trust.record_engineer_decision(\n            review.get(finding_id) or {}, decision, actor=actor, note=reason\n        )\n",
       "        pass\n",
       "tick_is_a_correct_audit or something_is_off"),
    _m(7, "a proof made under another revision of the standard still counts",
       APP / "comparison.py",
       "                model_id=model, standard_revision=self._revision(standard_id))\n",
       "                model_id=model, standard_revision=None)\n",
       "another_model_or_revision"),
    _m(8, "a run made with the switch OFF stores a rule_trust key",
       APP / "comparison.py",
       "                **({\"rule_trust\": rule_trust} if rule_trust is not None else {}),\n",
       "                \"rule_trust\": rule_trust or {},\n",
       "off_uses_no_draft"),
    _m(9, "the Review notes sheet drops the rule_trust notes (fields no rule checked, spot-check)",
       APP / "clause_coverage.py",
       "    if outcome:\n        from .rule_trust import review_notes as trust_notes\n",
       "    if False:\n        from .rule_trust import review_notes as trust_notes\n",
       "internal_crs_shows_the_trust"),
)
