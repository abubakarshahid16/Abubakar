"""PR #1282: a document a review is run on gets its equipment type and title from
its own heading when empty (order 206.1). backend/tests/test_196_fill_classification.py
must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_196_fill_classification.py"
_FILL = APP / "submittal_fill.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1282-01",
        phase=1282,
        description="the review no longer fills the sheet's type and title before it reads them",
        path=APP / "comparison.py",
        anchor="    classification_mod.submittal_fill.ensure(submittal_id)  # order 196: type, title",
        replacement="    pass  # order 196: type, title",
        target=_T,
        keyword="a_review_fills_the_type_and_title or without_the_fill",
        tags=("pr1282", "comparison"),
    ),
    Mutation(
        id="M1282-02",
        phase=1282,
        description="any role is taken for a submittal when a review is run (a company standard gets a type)",
        path=_FILL,
        anchor='return role == "CONTRACTOR_SUBMITTAL" or (reviewed and not role)',
        replacement='return role == "CONTRACTOR_SUBMITTAL" or reviewed',
        target=_T,
        keyword="another_role_is_never_taken_for_a_submittal",
        tags=("pr1282", "submittal_fill"),
    ),
    Mutation(
        id="M1282-03",
        phase=1282,
        description="a document with no role is filled without any review being run on it",
        path=_FILL,
        anchor='return role == "CONTRACTOR_SUBMITTAL" or (reviewed and not role)',
        replacement='return role == "CONTRACTOR_SUBMITTAL" or not role',
        target=_T,
        keyword="without_a_review_a_document_with_no_role_is_left_alone",
        tags=("pr1282", "submittal_fill"),
    ),
    Mutation(
        id="M1282-04",
        phase=1282,
        description="a long line with no field label is taken for the sheet's title (prose)",
        path=_FILL,
        anchor="        parts = parts[: labels[0]] if labels else []",
        replacement="        parts = parts[: labels[0]] if labels else parts[:words]",
        target=_T,
        keyword="heading_lead_cuts_at_a_field_label",
        tags=("pr1282", "submittal_fill"),
    ),
)
