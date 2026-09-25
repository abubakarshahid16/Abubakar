"""Mutations of `backend/app/extraction_schema.py`."""

from __future__ import annotations

from ._base import APP, _B50_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B50_MODEL_SCHEMA --------------------------------------------
    #: B50: a model row that fails its schema is refused, never coerced. The two
    #: malformations these protect against are real - a 9B returned them on the
    #: frozen packet.
    Mutation(
        id="M348", phase=43,
        description="PUT B50 BACK: drop strict mode, so pydantic coerces the "
                    "string \"4\" into a page number",
        path=APP / "extraction_schema.py",
        anchor='    model_config = ConfigDict(extra="forbid", strict=True)\n\n'
               "    #: Verbatim as printed",
        replacement='    model_config = ConfigDict(extra="forbid")\n\n'
                    "    #: Verbatim as printed",
        target=_B50_TEST, keyword="page_that_is_not_a_real_integer",
        tags=("critical",),
    ),
    Mutation(
        id="M349", phase=43,
        description="accept page 0 and negative pages, which cite nothing",
        path=APP / "extraction_schema.py",
        anchor="        if page < 1:\n            raise ValueError",
        replacement="        if False:\n            raise ValueError",
        target=_B50_TEST, keyword="page_that_is_not_a_real_integer",
    ),
    Mutation(
        id="M350", phase=43,
        description="let a blank label, value or source span through, so a row "
                    "B23 can never check becomes a fact",
        path=APP / "extraction_schema.py",
        anchor='        if not text.strip():\n            raise ValueError',
        replacement="        if False:\n            raise ValueError",
        target=_B50_TEST, keyword="required_string_that_is_blank",
        tags=("critical",),
    ),
    Mutation(
        id="M351", phase=43,
        description="a response that will not parse becomes an empty page "
                    "instead of a page refusal",
        path=APP / "extraction_schema.py",
        anchor='        return [], [f"{PAGE_UNPARSEABLE}: {exc.msg} at position {exc.pos}"]',
        replacement="        return [], []",
        target=_B50_TEST, keyword="will_not_parse_is_a_page_refusal",
        tags=("honesty", "critical"),
    ),
)
