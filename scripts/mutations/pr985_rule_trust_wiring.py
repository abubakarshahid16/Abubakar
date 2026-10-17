"""PR #985 (#947), second set: every rule labelled (planner answer on #985)
and the controls `rule_trust_wiring.py` (M985-01..09) does not already
delete. `comparison.py`, `crs_mapping.py`, `crs_export.py` and
`datasheet_checks.py` are in the danger zone (rule 6). Ids M985-10 onwards."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_947_rule_trust_wiring.py"
_C = APP / "comparison.py"
_M = APP / "crs_mapping.py"
_X = APP / "crs_export.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M985-10", phase=985,
             description="the switch is ignored: a review labels findings with it OFF",
             path=_C,
             anchor='    trust = _RuleTrust(stored.get("equipment_type")) if settings.rule_auto_use_enabled else None\n',
             replacement='    trust = _RuleTrust(stored.get("equipment_type"))\n',
             target=_T, keyword="off_uses_no_draft", tags=("honesty", "critical")),
    Mutation(id="M985-11", phase=985,
             description="the AI-compiled draft is not compared in its sentence's place",
             path=_C,
             anchor='            if r["id"] in auto_rules:\n                r = {**r, **auto_rules[r["id"]]}\n',
             replacement="",
             target=_T, keyword="an_unproven_rule_never_decides or a_proof_covers_ai_compiled_rules_only",
             tags=("honesty",)),
    Mutation(id="M985-12", phase=985,
             description="a proof under one model covers a rule another model compiled",
             path=_C,
             anchor='        model = rule.get("model") or settings.ai_task_model\n',
             replacement="        model = settings.ai_task_model\n",
             target=_T, keyword="proven_family_keeps_the_verdict", tags=("honesty", "critical")),
    Mutation(id="M985-13", phase=985,
             description="the datasheet checks are not labelled: an unsigned checklist still decides",
             path=_C,
             anchor="        label=rule_trust_mod.label_check if trust is not None else None))\n",
             replacement="        label=None))\n",
             target=_T, keyword="every_datasheet_check_is_labelled_too", tags=("honesty", "critical")),
    Mutation(id="M985-14", phase=985,
             description="datasheet_checks.store ignores the label it is given",
             path=_D,
             anchor="        if label is not None:\n            r = label(r)\n",
             replacement="",
             target=_T, keyword="every_datasheet_check_is_labelled_too or signed_checklist_item",
             tags=("honesty", "critical")),
    Mutation(id="M985-15", phase=985,
             description="a datasheet check's label is not stored with its finding",
             path=_D,
             anchor='            "trust_label": r.get("trust_label"), "tier": r.get("tier"),\n',
             replacement='            "trust_label": None, "tier": r.get("tier"),\n',
             target=_T, keyword="every_datasheet_check_is_labelled_too or signed_checklist_item",
             tags=("honesty",)),
    Mutation(id="M985-16", phase=985,
             description="a held datasheet check silently leaves the CRS",
             path=_M,
             anchor='                   or f.get("rule_said"))\n',
             replacement="                   )\n",
             target=_T, keyword="every_datasheet_check_is_labelled_too", tags=("honesty", "critical")),
    Mutation(id="M985-17", phase=985,
             description="no safety-tick row: a safety-tier automatic 'meets' goes unchecked",
             path=_M,
             anchor='        if not f.get("show_for_engineer_tick") or status(f) != "COMPLIANT":\n            continue\n',
             replacement="        continue\n",
             target=_T, keyword="internal_crs_shows_the_trust or safety_tick_gates_issue",
             tags=("honesty", "critical")),
    Mutation(id="M985-18", phase=985,
             description="the CRS rows carry no trust words",
             path=_M,
             anchor="                # rule_trust (#947): who stands behind the rule, in words.\n"
                    "                \"rule_trust\": trust_words(f),\n",
             replacement="",
             target=_T, keyword="every_datasheet_check_is_labelled_too", tags=("honesty",)),
    Mutation(id="M985-19", phase=985,
             description="the internal copy has no Rule trust column",
             path=_X,
             anchor="                   + ([AI_COLUMN, REASONING_COLUMN, TRUST_COLUMN]\n",
             replacement="                   + ([AI_COLUMN, REASONING_COLUMN]\n",
             target=_T, keyword="internal_crs_shows_the_trust", tags=("honesty",)),
    Mutation(id="M985-20", phase=985,
             description="'something is off' is recorded as a correct audit",
             path=APP / "rule_trust.py",
             anchor='correct=decision == "accept",',
             replacement="correct=True,",
             target=_T, keyword="something_is_off", tags=("honesty", "critical")),
)
