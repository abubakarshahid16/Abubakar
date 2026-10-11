"""PR #761: a standard an equipment type takes only in part applies only in
that part. The gate's call is in comparison.py (the danger zone)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_partial_standards.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M761-01", phase=761, description="the partial-standard gate is never applied in a review",
             path=APP / "comparison.py",
             anchor="    requirements = partial[\"kept\"]\n    extra_not_applied.extend(partial[\"items\"])\n",
             replacement="    pass\n",
             target=_T, keyword="relief_valve_review_does_not_check", tags=("applicability", "critical")),
    Mutation(id="M761-02", phase=761, description="every requirement of a partial standard is kept",
             path=APP / "subject_scope.py",
             anchor="        if any(re.search(r\"(?<![a-z0-9])\" + re.escape(_fold(w)) + r\"(?![a-z0-9])\", text) for w in e[\"words\"]):\n",
             replacement="        if True:\n",
             target=_T, keyword="only_the_parts", tags=("applicability",)),
    Mutation(id="M761-03", phase=761, description="a partial standard applies to every equipment type",
             path=APP / "subject_scope.py",
             anchor="    entries = [(kind, e) for kind in sorted(equipment) for e in partial_standards.get(kind, [])]\n",
             replacement="    entries = [(kind, e) for kind in partial_standards for e in partial_standards[kind]]\n",
             target=_T, keyword="no_entry_is_untouched", tags=("applicability",)),
)

MUTATIONS = MUTATIONS + (
    Mutation(id="M761-04", phase=761, description="the CRS prints a table number as an ASME clause again",
             path=APP / "crs_mapping.py",
             anchor="    if clause and finding.get(\"clause_identified\") is False:\n",
             replacement="    if False:\n",
             target=_T, keyword="never_prints_a_table_number", tags=("crs", "honesty", "critical")),
    Mutation(id="M761-05", phase=761, description="the CRS context never marks a standard's clauses as unidentified",
             path=APP / "comparison.py",
             anchor="            f[\"clause_identified\"] = known[f[\"standard_document_id\"]]\n",
             replacement="            pass\n",
             target="tests/test_partial_standards.py", keyword="attach_marks", tags=("crs", "honesty")),
)
