"""PR 1844 (order 14 lane B): the rule check's CRS rows never print the old clause of a superseded requirement: they run the clause
re-read first (`crs_mapping.build_crs_rows` -> `review_points.reread_clauses`, danger zone). Ids M1844-01.. (rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1844-01",
        phase=1844,
        description="the rule check's CRS rows skip the clause re-read, so a superseded requirement's old (false) clause is printed again",
        path=APP / "crs_mapping.py",
        anchor="    _rp.reread_clauses(findings)  # lane B: a superseded clause is never shown",
        replacement="    pass",
        target="tests/test_o14_b_crs_writer.py",
        keyword="pass_through_the_re_read",
        tags=("honesty",),
    ),
)
