"""PR 1644: which roles a reader can read. `reference/datasheet_checks.json` is in the danger zone (rule 6): a role wrongly
typed can fail a value nobody can read, and a material role wrongly free text loses a real Fail."""

from __future__ import annotations

from ._base import APP, Mutation

_JSON = APP / "reference" / "datasheet_checks.json"
_T = "tests/test_typed_check_scope_oneof.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1644-01",
        phase=1644,
        description="a material role reads as free text, so a real breach is only a Query",
        path=_JSON,
        anchor='    "body_material": {\n      "kind": "text",\n      "reads_as": "material",\n',
        replacement='    "body_material": {\n      "kind": "text",\n',
        target=_T,
        keyword="typed_field_still_fails",
        tags=_TAGS,
    ),
    Mutation(
        id="M1644-02",
        phase=1644,
        description="a free-text role reads as typed, so a fluid's name can fail",
        path=_JSON,
        anchor='    "fluid": {\n      "kind": "text",\n',
        replacement='    "fluid": {\n      "kind": "text",\n      "reads_as": "material",\n',
        target=_T,
        keyword="free_text_comes_from_the_role_table",
        tags=_TAGS,
    ),
    Mutation(
        id="M1644-03",
        phase=1644,
        description="rule ids and Part labels left out by a scope clause reach the issue copy",
        path=APP / "crs_export.py",
        anchor='                meta.get("rulebook_v2_internal_note") if copy == COPY_INTERNAL else "",\n',
        replacement='                meta.get("rulebook_v2_internal_note"),\n',
        target=_T,
        keyword="reach_the_internal_copy_only",
        tags=_TAGS,
    ),
)
