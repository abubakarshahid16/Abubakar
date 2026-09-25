"""Mutations of `backend/app/schemas.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_1 -----------------------------------------------------
    Mutation(
        id="M8", phase=1,
        description="widen DocumentRole to a free string",
        path=APP / "schemas.py",
        anchor='DocumentRole = Literal[\n    "CONTRACTOR_SUBMITTAL",',
        replacement='DocumentRole = str\n_UNUSED_DocumentRole = Literal[\n    "CONTRACTOR_SUBMITTAL",',
        target="tests/test_submittal_review_foundation.py",
        keyword="invalid_document_role",
        tags=("validation",),
    ),
    Mutation(
        id="M9", phase=1,
        description="widen ComplianceStatus to a free string",
        path=APP / "schemas.py",
        anchor='ComplianceStatus = Literal[\n    "COMPLIANT",',
        replacement='ComplianceStatus = str\n_UNUSED_ComplianceStatus = Literal[\n    "COMPLIANT",',
        target="tests/test_submittal_review_foundation.py",
        keyword="invalid_compliance_status",
        tags=("validation",),
    ),
    # ---- from PHASE_2 -----------------------------------------------------
    Mutation(
        id="M12", phase=2,
        description="let an unknown document_role through the update boundary",
        path=APP / "schemas.py",
        anchor="    document_role: DocumentRole | None = None\n"
               "    document_number: str | None = None\n"
               "    title: str | None = None",
        replacement="    document_role: str | None = None\n"
                    "    document_number: str | None = None\n"
                    "    title: str | None = None",
        target="tests/test_document_metadata_filters.py",
        keyword="invalid_role_is_rejected",
        tags=("validation",),
    ),
    # ---- from MODEL_TIER --------------------------------------------------
    #: The model tier of the matcher. It may CHOOSE, never NAME.
    Mutation(
        id="M153", phase=11,
        description="TAKE THE CONFIRMER FROM THE REQUEST BODY, so one person "
                    "can sign a pairing in another's name",
        # THE PROTECTION IS THE SCHEMA, so that is what this mutates. The
        # route cannot read a confirmer out of a field that does not exist;
        # mutating the route alone proved nothing, because `getattr` on an
        # absent field is None whatever the client sent.
        path=APP / "schemas.py",
        anchor="    approved_at: str | None = None\n    #: CONFIRM THE PAIRING.",
        replacement="    approved_at: str | None = None\n    confirmed_by: str | None = None\n    #: CONFIRM THE PAIRING.",
        target="tests/test_model_matching.py",
        keyword="body_naming_a_confirmer",
        tags=("permission", "critical"),
    ),
)
