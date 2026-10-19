"""PR #1177 (order 139 fix 3, #882): a code cited for one item applies through
the cited clauses only, and a standard's question with no datasheet field and
no datasheet page behind it is a Review note, never a CRS line.
`crs_mapping.py` and `comparison.py` are in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_139_citation_scope.py"
_M = APP / "crs_mapping.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1177-01",
        phase=1177,
        description="a question with no datasheet field is a CRS line again",
        path=_M,
        anchor="            and not _no_datasheet_field(f)\n",
        replacement="",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1177-02",
        phase=1177,
        description="a question taken off the CRS is not noted for the engineer (silent loss)",
        path=_M,
        anchor="        if not _rejected(f) and _no_datasheet_field(f):\n",
        replacement="        if False:\n",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs", "honesty", "critical"),
    ),
    Mutation(
        id="M1177-03",
        phase=1177,
        description="an engineer-confirmed question with no page is dropped from the CRS",
        path=_M,
        anchor="        and not _page_reader_only(finding)\n        and not _confirmed(finding)\n",
        replacement="        and not _page_reader_only(finding)\n",
        target=_T,
        keyword="engineer_confirmed_question",
        tags=("crs",),
    ),
    Mutation(
        id="M1177-04",
        phase=1177,
        description="a question paired with a datasheet field leaves the CRS too",
        path=_M,
        anchor='        and not (finding.get("fact_id") or finding.get("contractor_page"))\n',
        replacement="",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs",),
    ),
    Mutation(
        id="M1177-05",
        phase=1177,
        description="a verdict held for an unproven rule leaves the CRS",
        path=_M,
        anchor='        and not finding.get("rule_said")\n',
        replacement="",
        target=_T,
        keyword="held_for_an_unproven_rule",
        tags=("crs",),
    ),
    Mutation(
        id="M1177-06",
        phase=1177,
        description="the review checks the whole of a code the datasheet cited for one item",
        path=APP / "comparison.py",
        anchor='    requirements = cited_scope["kept"]\n',
        replacement="",
        target=_T,
        keyword="applies_only_the_cited_clause",
        tags=("scope",),
    ),
    Mutation(
        id="M1177-07",
        phase=1177,
        description="an unsure reading's outside requirements get no decision (lost)",
        path=APP / "comparison.py",
        anchor='    held_items.extend(cited_scope["unsure"])',
        replacement="    pass",
        target=_T,
        keyword="unsure_reading_leaves_the_rest",
        tags=("scope", "honesty"),
    ),
    Mutation(
        id="M1177-08",
        phase=1177,
        description="the manual-review reason blames 'no matching field' for unsure citations",
        path=APP / "comparison.py",
        anchor="    unsure = min(counts.get(",
        replacement="    unsure = 0 * min(counts.get(",
        target=_T,
        keyword="manual_review_reason_names",
        tags=("honesty",),
    ),
    Mutation(
        id="M1177-09",
        phase=1177,
        description="the run does not hand the unsure-citation count to the review code",
        path=APP / "comparison.py",
        anchor='        "unsure_citation": len(cited_scope["unsure"])}',
        replacement='        "unsure_citation": 0}',
        target=_T,
        keyword="unsure_reading_leaves_the_rest",
        tags=("honesty",),
    ),
)
