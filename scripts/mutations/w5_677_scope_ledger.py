"""#677 (with #638, #647, #669): every requirement in a review's scope ends in
exactly one state with a stored reason. M4501 onward. M1446 re-anchored.
M4501-M4504 are RETIRED: they mutated per-gate reason code that #685 (#678)
replaced; #685's own mutations M4418-M4437 cover those reasons."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5_677_scope_ledger.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4505", phase=4505, description="#638 is back: a declared non-sour sheet still gets sour requirements",
             path=APP / "service_scope.py",
             # Re-anchored 2026-10-09 (#725 F6): the call now also passes the clause heading.
             anchor="            if d is not None and d[\"present\"] is False and specific_to(\n",
             replacement="            if False and specific_to(\n",
             target=_T, keyword="declared_not_sour or exactly_one_stored", tags=("honesty", "critical")),
    Mutation(id="M4506", phase=4506, description="an unknown or present service drops sour requirements too",
             path=APP / "service_scope.py",
             # Re-anchored 2026-10-09 (#725 F6), same mutation.
             anchor="            if d is not None and d[\"present\"] is False and specific_to(\n",
             replacement="            if specific_to(\n",
             target=_T, keyword="declared_sour_or_unknown", tags=("honesty", "critical")),
    Mutation(id="M4507", phase=4507, description="the requirement's standard does not make it service-specific",
             path=APP / "service_scope.py",
             anchor="    if any(standard_ids.same_standard(standard_label, s) or any(\n",
             replacement="    if False and any(standard_ids.same_standard(standard_label, s) or any(\n",
             target=_T, keyword="declared_not_sour or exactly_one_stored", tags=("honesty",)),
    Mutation(id="M4508", phase=4508, description="a ledger that does not add up is accepted",
             path=APP / "scope_ledger.py",
             anchor="    if missing or extra or repeated or len(got) != len(wanted):\n",
             replacement="    if False:\n",
             target=_T, keyword="fails_loudly", tags=("honesty", "critical")),
    Mutation(id="M4509", phase=4509, description="an unknown finding status is read as checked",
             path=APP / "scope_ledger.py",
             anchor="    code = STATUS_REASON.get(status or \"\", \"needs_engineer\")\n",
             replacement="    code = STATUS_REASON.get(status or \"\", \"compared\")\n",
             target=_T, keyword="maps_to_one_state", tags=("honesty", "critical")),
    Mutation(id="M4510", phase=4510, description="held-back definitions get no decision (the review fails its ledger)",
             path=APP / "comparison.py",
             anchor="                extra_not_applied.append({\"requirement\": dict(r), \"code\": \"definition\",\n",
             replacement="                (lambda *a: None)({\"requirement\": dict(r), \"code\": \"definition\",\n",
             target=_T, keyword="exactly_one_stored", tags=("honesty",)),
    Mutation(id="M4511", phase=4511, description="the service gate's decisions are dropped from the ledger",
             path=APP / "comparison.py",
             anchor="    extra_not_applied.extend(serviced[\"items\"])\n",
             replacement="",
             target=_T, keyword="exactly_one_stored", tags=("honesty",)),
    Mutation(id="M4512", phase=4512, description="an AI 'does not apply' is taken without code's confirmation",
             path=APP / "ai_applicability.py",
             anchor="        if (data.get(\"applies\") == \"no\" and in_clause and reason in scope_ledger.REASONS\n",
             replacement="        if (data.get(\"applies\") in (\"no\", \"unsure\") and reason in scope_ledger.REASONS\n",
             target=_T, keyword="code_cannot_confirm or unsure_stays or not_in_the_clause",
             tags=("honesty", "critical")),
    Mutation(id="M4513", phase=4513, description="'other equipment' is confirmed without the vocabulary",
             path=APP / "ai_applicability.py",
             anchor="        return bool(subject) and bool(equipment) and not (subject & equipment)\n",
             replacement="        return True\n",
             target=_T, keyword="code_cannot_confirm", tags=("honesty", "critical")),
    Mutation(id="M4514", phase=4514, description="the model's unconfirmed suggestion does not reach the engineer",
             path=APP / "scope_ledger.py",
             anchor="            decided = {**decided, \"reason\": f\"{decided['reason']}; {notes[rid]}\"}\n",
             replacement="            pass\n",
             target=_T, keyword="models_note", tags=("honesty",)),
)

MUTATIONS = MUTATIONS + (
    Mutation(id="M4520", phase=4520, description="#678's counts leave out the service gate, AI and definitions (two sources)",
             path=APP / "comparison.py",
             # re-anchored 2026-10-10 (#746 part 2): the call also passes covered_items
             anchor="        scoped[\"not_applied_items\"] + extra_not_applied,\n        covered_items)\n",
             replacement="        scoped[\"not_applied_items\"],\n        covered_items)\n",
             target=_T, keyword="exactly_one_stored", tags=("honesty", "critical")),
)

