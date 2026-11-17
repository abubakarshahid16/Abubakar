"""Order 14 LPE (PR 1893): with `equipment_rule_books_enabled` ON, the rule check pairs a rule with a field only when
its equipment tag fits the paper (`equipment_rule_books.pairing_gate`). `comparison.py` is danger zone: every changed
line has an entry. Ids M1893-01 onwards, phase 1893."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_lpe_tag_pairing.py"
_TAGS = ("honesty", "lpe")


def _m(n, description, anchor, replacement, keyword):
    return Mutation(
        id=f"M1893-{n:02d}",
        phase=1893,
        description=description,
        path=APP / "comparison.py",
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the run never marks a rule whose equipment tag does not fit: every tier pairs it",
        "    requirements = erb.unpairable(connect(), submittal_id, review_run_id, requirements)\n",
        "",
        "containment_pairs_no_field",
    ),
    _m(
        2,
        "the loop ignores the mark: the AI matcher is asked about a rule that may not be paired",
        "match, model_reason = None, requirement.get(erb.NOT_PAIRED)",
        "match, model_reason = None, None",
        "never_asked",
    ),
    _m(
        3,
        "the field-name tier pairs a marked rule",
        "if field_names is not None and model_reason is None:",
        "if field_names is not None:",
        "field_name_tier",
    ),
    _m(
        4,
        "the AI matcher (model-choice tier) is asked about a marked rule",
        "            and is_matchable(requirement)\n            and model_reason is None\n",
        "            and is_matchable(requirement)\n",
        "never_asked",
    ),
    _m(
        5,
        "containment (`_resolve_hits`) pairs a marked rule: the live defect of 17 Nov",
        "refused, allowed, gated = [], [], requirement.get(erb.NOT_PAIRED)",
        "refused, allowed, gated = [], [], None",
        "containment_pairs_no_field or resolve_hits",
    ),
)
