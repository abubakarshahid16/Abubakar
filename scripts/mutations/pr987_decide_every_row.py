"""PR #987 (#986): a decision on a grouped CRS row covers every finding behind
it. `crs_mapping.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M987-01", phase=987,
             description="a grouped row names only its first finding, so a decision leaves the rest open",
             path=APP / "crs_mapping.py",
             anchor='                "finding_ids": [g["id"] for g in group if g.get("id")],\n',
             replacement='                "finding_ids": [f["id"]] if f.get("id") else [],\n',
             target="tests/test_986_crs_decide_every_row.py",
             keyword="one_decision_on_a_grouped_row", tags=("honesty", "critical")),
)
