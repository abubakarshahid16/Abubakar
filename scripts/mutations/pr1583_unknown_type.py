"""PR 1583 (part of #1478): with the equipment type waiting for the engineer, the review's
words say the type is unknown, never that no applicable standard asks anything.
backend/tests/test_title_block_scope.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_title_block_scope.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1583-01",
        phase=1583,
        description="the plain reason says no applicable standard while the type is unknown",
        path=APP / "comparison.py",
        anchor='        head = completeness.get("unknown_type_plain", head) if not required else head\n',
        replacement="",
        target=_T,
        keyword="plain_reason_says_the_type_is_unknown",
        tags=("honesty",),
    ),
    Mutation(
        id="M1583-02",
        phase=1583,
        description="the technical reason says no requirement applies while the type is unknown",
        path=APP / "comparison.py",
        anchor='        if not required and completeness.get("unknown_type_technical"):\n',
        replacement="        if False:\n",
        target=_T,
        keyword="technical_reason_says_the_type_is_unknown",
        tags=("honesty",),
    ),
    Mutation(
        id="M1583-03",
        phase=1583,
        description="the run's completeness does not carry the unknown-type words",
        path=APP / "comparison.py",
        anchor="        basis.update(kind_rules.unknown_type_words(submittal_document_id), **kw.run_words(submittal_document_id, required))\n",
        replacement="",
        target=_T,
        keyword="says_the_type_is_unknown",
        tags=("honesty",),
    ),
)
