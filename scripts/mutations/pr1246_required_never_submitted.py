"""#882: a value the reader recorded as the purchaser's requirement is never the
contractor's submitted value. The guard is `required_values.is_purchaser_kind`, read
by the review run (`comparison.run_comparison`), `match_rules.refusal` and
`comparison.candidate_facts`. Placeholder ids M1246-xx: the lead renames them
to the PR number."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_882_required_never_submitted.py"
_C = APP / "comparison.py"
_R = APP / "required_values.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1246-01",
        phase=1246,
        description="a required-kind value is no longer recognised as the purchaser's",
        path=_R,
        anchor='    return str((fact or {}).get("section") or "").strip().lower() == REQUIRED_SECTION\n',
        replacement="    return False\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1246-02",
        phase=1246,
        description="the review run keeps required-kind values in the pool the matchers draw from",
        path=_C,
        anchor="    facts, purchaser_facts = required_values.split(facts)\n",
        replacement="    purchaser_facts = []\n",
        target=_T,
        keyword="missing_information",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1246-03",
        phase=1246,
        description="a clause with only a required value is not reported as 'no offered value'",
        path=_R,
        anchor=(
            "        cmp.NOT_IN_DOCUMENT_SCOPE,\n    ):\n"
            "        return verdict\n    hits = "
        ),
        replacement="        cmp.NOT_IN_DOCUMENT_SCOPE,\n    ):\n"
        "        pass\n    return verdict\n    hits = ",
        target=_T,
        keyword="missing_information",
        tags=("honesty",),
    ),
    Mutation(
        id="M1246-04",
        phase=1246,
        description="the AI matcher's shortlist offers a required-kind value",
        path=_C,
        anchor='fact.get("is_blank") or required_values.is_purchaser_kind(fact):\n',
        replacement='fact.get("is_blank"):\n',
        target=_T,
        keyword="shortlist",
        tags=("honesty",),
    ),
)
