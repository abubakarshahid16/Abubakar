"""#1612: a review reads approved version 2 rules: the four hooks in `comparison.py`, the danger-zone module it touches."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_805_review_reads_v2.py"
_M = APP / "comparison.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1612-01",
        phase=1612,
        description="the review never reads the approved rules",
        path=_M,
        anchor="    rulebook = run_parts.rulebook(\n        run, stored, facts, prepared_rows, findings, allowed_document_ids\n    )\n",
        replacement="    rulebook = None\n",
        target=_T,
        keyword="one_that_meets_and_one_that_breaks",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-02",
        phase=1612,
        description="a checklist item that disagrees with a rule keeps its verdict",
        path=_M,
        anchor="    check_results = run_parts.checks(rulebook, check_results)\n",
        replacement="",
        target=_T,
        keyword="review_settles_its_checks",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-03",
        phase=1612,
        description="a version 2 breach is left out of the recommended code",
        path=_M,
        anchor="    findings.extend(run_parts.written(rulebook))\n",
        replacement="    run_parts.written(rulebook)\n",
        target=_T,
        keyword="v2_breach_counts_in_the_recommended_code",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-05",
        phase=1612,
        description="a version 2 Pass leaves no row on the internal CRS",
        path=APP / "crs_export.py",
        anchor='        findings = [*findings, *(meta.get("rulebook_v2_rows") or [])]\n',
        replacement="        pass\n",
        target=_T,
        keyword="internal_copy_has_a_row_per_tag",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-06",
        phase=1612,
        description="version 2's rows reach the issue copy too",
        path=APP / "crs_export.py",
        anchor=(
            '        raise ValueError(f"unknown CRS copy {copy!r}")\n'
            "    if copy == COPY_INTERNAL:\n"
        ),
        replacement=(
            '        raise ValueError(f"unknown CRS copy {copy!r}")\n    if True:\n'
        ),
        target=_T,
        keyword="issue_copy_rows_do_not_change",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-07",
        phase=1612,
        description="the note on a decided rule leaves both copies of the CRS",
        path=APP / "crs_export.py",
        anchor='                meta.get("rulebook_v2_note"),\n',
        replacement='                "",\n',
        target=_T,
        keyword="short_note_is_on_both_copies",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-08",
        phase=1612,
        description="the note moves into column A, where a reply reads an Item No",
        path=APP / "crs_export.py",
        anchor="    put(row, 3, note, wrap=True)\n",
        replacement="    put(row, 1, note, wrap=True)\n",
        target=_T,
        keyword="note_leaves_rows_numbers_and_reply_import_alone",
        tags=_TAGS,
    ),
    Mutation(
        id="M1612-04",
        phase=1612,
        description="the run stops stating the rulebook part",
        path=_M,
        anchor="    split = run_parts.stated(split, cited_scope, checklist_coverage, divided, rulebook)\n",
        replacement="    split = run_parts.stated(split, cited_scope, checklist_coverage, divided, None)\n",
        target=_T,
        keyword="states_version_2_apart",
        tags=_TAGS,
    ),
)
