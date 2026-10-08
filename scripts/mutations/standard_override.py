"""Mutations of P2: the engineer's add/remove-standard control."""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_p2_standard_override.py"
_M = APP / "main.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M870", phase=76, description="P2: an automatic selection replaces the engineer's row",
             path=APP / "applicability.py",
             anchor="        if (existing is not None and existing[\"selection_method\"] == METHOD_MANUAL\n                and method != METHOD_MANUAL):\n",
             replacement="        if False:\n", target=_T, keyword="never_replaces", tags=("audit", "critical")),
    Mutation(id="M871", phase=76, description="P2: the findings are not recomputed after an override",
             path=_M, anchor="    comparison_mod.run_comparison(\n        review_run_id, allowed_document_ids=scope.allowed_document_ids,\n        reference_coverage=(outcome.get(\"completeness\") or {}).get(\"reference_coverage\"),\n",
             replacement="    (lambda *a, **k: None)(\n        review_run_id, allowed_document_ids=scope.allowed_document_ids,\n        reference_coverage=(outcome.get(\"completeness\") or {}).get(\"reference_coverage\"),\n",
             target=_T, keyword="findings_follow or removes_a_standard", tags=("honesty",)),
    Mutation(id="M872", phase=76, description="P2: missing standards are dropped on recompute",
             path=_M, anchor="        missing_references=[m[\"identifier\"] for m in outcome.get(\"missing_references\") or []])\n    return _run_standards_payload(",
             replacement="        missing_references=[])\n    return _run_standards_payload(",
             target=_T, keyword="stay_missing", tags=("honesty", "critical")),
    Mutation(id="M873", phase=76, description="P2: a caller who cannot see every standard in use may recompute",
             path=_M, anchor="    if not in_use <= scope.allowed_document_ids:\n",
             replacement="    if False:\n", target=_T, keyword="every_standard_in_use", tags=("privacy",)),
    Mutation(id="M874", phase=76, description="P2: an override needs no named engineer",
             path=_M, anchor="    if not scope.user_id:\n        raise HTTPException(status_code=401, detail=errors.safe_error(\n            errors.UNAUTHENTICATED, \"an override must name the engineer who made it\"))\n",
             replacement="", target=_T, keyword="no_engineer_can_be_named", tags=("audit",)),
    Mutation(id="M875", phase=76, description="P2: a run with an engineer's final code is changed anyway",
             path=_M, anchor="    if run.get(\"engineer_final_code\"):\n        raise HTTPException(status_code=409, detail=errors.safe_error(\n            errors.INVALID_PARAMETER,\n            \"this run carries",
             replacement="    if False:\n        raise HTTPException(status_code=409, detail=errors.safe_error(\n            errors.INVALID_PARAMETER,\n            \"this run carries",
             target=_T, keyword="decided_run", tags=("audit",)),
    Mutation(id="M876", phase=76, runner="vitest", description="P2 UI: an override may be sent with no reason",
             path=FRONTEND_SRC / "components" / "review" / "StandardOverrideControl.tsx",
             anchor="disabled={busy || reason.trim().length < 3}", replacement="disabled={busy}",
             target="src/components/review/StandardOverrideControl.test.tsx", keyword="only with a reason",
             tags=("audit", "ui")),
    Mutation(id="M877", phase=76, runner="vitest", description="P2 UI: a refusal is swallowed and reported as a change",
             path=FRONTEND_SRC / "components" / "review" / "StandardOverrideControl.tsx",
             anchor="    if (!result.ok) {\n      setError(result.error.message);\n      return;\n    }\n",
             replacement="    if (!result.ok) {\n      onChanged([], []);\n      return;\n    }\n",
             target="src/components/review/StandardOverrideControl.test.tsx", keyword="server's refusal",
             tags=("honesty", "ui")),
    Mutation(id="M878", phase=76, runner="vitest", description="P2 UI: a decided review still offers changes",
             path=FRONTEND_SRC / "components" / "review" / "StandardOverrideControl.tsx",
             anchor="  if (decided) {\n", replacement="  if (false) {\n",
             target="src/components/review/StandardOverrideControl.test.tsx", keyword="decided the code",
             tags=("audit", "ui")),
    Mutation(id="M879", phase=76, runner="vitest", description="P2 UI: remove sends include=true",
             path=FRONTEND_SRC / "components" / "review" / "StandardOverrideControl.tsx",
             anchor="setTarget({ id: s.standard_document_id, include: false })",
             replacement="setTarget({ id: s.standard_document_id, include: true })",
             target="src/components/review/StandardOverrideControl.test.tsx", keyword="removes a standard",
             tags=("ui",)),
)
