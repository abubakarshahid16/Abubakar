"""#882: a value the reader recorded as the purchaser's requirement is never the
contractor's submitted value. The guard is `match_rules.is_purchaser_kind`, read
by the review run (`comparison.run_comparison`), `match_rules.refusal` and
`comparison.candidate_facts`. Placeholder ids M882R-xx: the lead renames them
to the PR number."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_882_required_never_submitted.py"
_C = APP / "comparison.py"
_R = APP / "match_rules.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M882R-01",
        phase=882,
        description="a required-kind value is no longer recognised as the purchaser's",
        path=_R,
        anchor='    return str((fact or {}).get("section") or "").strip().lower() == "model:required"\n',
        replacement="    return False\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M882R-02",
        phase=882,
        description="the review run keeps required-kind values in the pool the matchers draw from",
        path=_C,
        anchor="    facts = [f for f in facts if not match_rules.is_purchaser_kind(f)]\n",
        replacement="",
        target=_T,
        keyword="missing_information",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M882R-03",
        phase=882,
        description="a clause with only a required value is not reported as 'no offered value'",
        path=_C,
        anchor=(
            '    if verdict.get("status") not in (MISSING_INFORMATION, NOT_IN_DOCUMENT_SCOPE):\n'
            "        return verdict\n    seen = "
        ),
        replacement="    return verdict\n    seen = ",
        target=_T,
        keyword="missing_information",
        tags=("honesty",),
    ),
    Mutation(
        id="M882R-04",
        phase=882,
        description="the AI matcher's shortlist offers a required-kind value",
        path=_C,
        anchor="        if match_rules.is_purchaser_kind(fact):\n            continue  # #882: what the purchaser requires is not a submitted value\n",
        replacement="",
        target=_T,
        keyword="shortlist",
        tags=("honesty",),
    ),
)
