"""#946, MEASUREMENT ONLY: `comparison.unscoped_statement_counts` counts, per
standard, how many STATEMENT-type requirements name neither a field nor a
subject this system recognises as ANY equipment's datasheet field at all
(`datasheet_checks.role_of`) - the planner's "requirements that belong to
another document" (procedures, fabrication, testing). Nothing here changes
what becomes a `review_findings` row; this is the tool to measure the real
share of `NO_FIELD_MATCHED` findings that ARE this kind, on a real PF1 sheet,
before anything suppresses a row on this signal (see the function's own
docstring for the `scope_ledger`/`requirement_split` coupling that fix would
need).

Invented requirements only.
"""
from __future__ import annotations

from app import comparison, requirements_3b


def _stmt(standard, **over):
    base = {"requirement_type": requirements_3b.STATEMENT, "standard_document_id": standard,
           "field": None, "subject": None}
    return {**base, **over}


def test_a_field_that_matches_a_known_role_is_not_counted():
    reqs = [_stmt("spec", field="Design pressure")]
    assert comparison.unscoped_statement_counts(reqs) == {}


def test_a_subject_that_matches_a_known_role_counts_even_with_no_field():
    reqs = [_stmt("spec", subject="hydrotest pressure")]
    assert comparison.unscoped_statement_counts(reqs) == {}


def test_a_procedure_clause_with_no_recognised_field_or_subject_is_counted():
    reqs = [_stmt("spec", subject="welding procedure qualification record"),
           _stmt("spec", subject="non-destructive examination report")]
    assert comparison.unscoped_statement_counts(reqs) == {"spec": 2}


def test_counts_are_per_standard():
    reqs = [_stmt("spec_a", subject="fabrication drawing approval"),
           _stmt("spec_b", subject="fabrication drawing approval"),
           _stmt("spec_b", subject="vendor data submission schedule")]
    assert comparison.unscoped_statement_counts(reqs) == {"spec_a": 1, "spec_b": 2}


def test_only_statement_type_requirements_are_considered():
    reqs = [{"requirement_type": "numeric_limit", "standard_document_id": "spec",
            "field": None, "subject": "unrecognised thing"}]
    assert comparison.unscoped_statement_counts(reqs) == {}


def test_empty_field_and_subject_counts_as_unscoped():
    reqs = [_stmt("spec")]
    assert comparison.unscoped_statement_counts(reqs) == {"spec": 1}
