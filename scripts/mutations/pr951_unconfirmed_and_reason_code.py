"""PR #951 (#921): an unconfirmed pairing is not an answer; the CRS follows a
stored reason code. `comparison.py` and `crs_mapping.py` are in the danger zone
(rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T1 = "tests/test_921b_unconfirmed_pairing_is_not_answered.py"
_T2 = "tests/test_921c_reason_code_is_typed.py"
_C = APP / "comparison.py"
_M = APP / "crs_mapping.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M951-01", phase=951,
             description="a model-named (held) field pairing counts as an answer again",
             path=_C,
             anchor="    if method == METHOD_FIELD_NAME:\n        return True\n",
             replacement="    if method == METHOD_FIELD_NAME:\n        return False\n",
             target=_T1, keyword="model_named_field_pairing", tags=("honesty", "critical")),
    Mutation(id="M951-02", phase=951,
             description="a held AI-matcher pairing counts as an answer again",
             path=_C,
             anchor="    return method == METHOD_MODEL_CHOICE and finding.get(\"compliance_status\") == NEEDS_ENGINEER_REVIEW\n",
             replacement="    return False\n",
             target=_T1, keyword="held_ai_matcher_pairing", tags=("honesty", "critical")),
    Mutation(id="M951-03", phase=951,
             description="the CRS ignores the stored reason code",
             path=_M,
             anchor='    code = finding.get("reason_code")\n    if code:\n        return str(code)\n',
             replacement='    code = None\n',
             target=_T2, keyword="stored_code_decides", tags=("honesty", "critical")),
    Mutation(id="M951-04", phase=951,
             description="a row from before the column loses its words fallback",
             path=_M,
             anchor="        if text.startswith(marker):\n            return marker\n    return None\n",
             replacement="        pass\n    return None\n",
             target=_T2, keyword="before_the_column", tags=("honesty", "critical")),
)
