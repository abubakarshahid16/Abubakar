"""#1837: an approval's equipment type is compared through the one registry of equipment names; labels reconcilable by code."""

from __future__ import annotations

from ._base import APP, REPO, Mutation

_TA = "tests/test_n1_approval_type_registry.py"
_TB = "tests/test_n1_label_reconcile.py"
_LABELS = APP / "rule_labels.py"
_SCOPE = APP / "subject_scope.py"
_SCRIPT = REPO / "scripts" / "reconcile_rule_labels.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1837-01",
        phase=1837,
        description="an approval's type and the asked type are compared by spelling again (the approval never reaches the review)",
        path=_LABELS,
        anchor='    return ("type", key) if key else ("name", folded)',
        replacement='    return ("name", folded)',
        target=_TA,
        keyword="same_type",
        tags=_TAGS,
    ),
    Mutation(
        id="M1837-02",
        phase=1837,
        description="a name listed under several types (valve) counts as one of them: an approval for another type applies",
        path=_SCOPE,
        anchor="return next(iter(types)) if types and len(types) == 1 else None",
        replacement="return next(iter(types)) if types else None",
        target=_TA,
        keyword="registry_key",
        tags=_TAGS,
    ),
    Mutation(
        id="M1837-03",
        phase=1837,
        description="a quote with a negation or exception word is reconciled by code",
        path=_SCRIPT,
        anchor="    if NEGATION.search(quote):\n",
        replacement="    if False:\n",
        target=_TB,
        keyword="held",
        tags=_TAGS,
    ),
    Mutation(
        id="M1837-04",
        phase=1837,
        description="a strength difference takes the stronger word instead of the weaker",
        path=_SCRIPT,
        anchor="key=lambda s: WEAKER[s]",
        replacement="key=lambda s: -WEAKER[s]",
        target=_TB,
        keyword="weaker",
        tags=_TAGS,
    ),
    Mutation(
        id="M1837-05",
        phase=1837,
        description="a lab answer that is not the stored answer is trusted",
        path=_SCRIPT,
        anchor='return "lab_answer_differs_from_stored_hash", None',
        replacement="pass",
        target=_TB,
        keyword="stored_answer",
        tags=_TAGS,
    ),
)
