"""Order 14 lane D, review of #1849: what a checklist card may NOT decide (CLAUDE.md rule 4).

Two general rules, read from the card and the sheet, never from a card id or a layout (rule 13):

1. A QUESTION ONLY card (`question_only`): its limit is an AI draft no engineer has
   confirmed, carried under `limit_draft`. It asks for its values and decides nothing on any
   switch: a Pass or Fail it would give is held for the engineer (hold code
   `limit_not_confirmed`) with no `rule_said`, so no draft pass takes it off the CRS
   (`compliance_list`, `crs_routing`). A card with two sides asks for the second value too.
   `decide_nothing` is applied to every checklist result in ONE place (`kit_core.rows`).
2. A condition value that rules nothing out never says "does not apply"
   (`not_matched`): a placeholder ("*", "TBA", "HOLD", "-"; `blank_markers`, the one home)
   is held as a deferred value; a value naming one of the condition's `may_be_any` words
   (a stated liquid "water" is not a stated firewater service) is held for the engineer.

Pure: no model, no network, no database.
"""

from __future__ import annotations

from . import blank_markers
from . import hold_reason as why_held

#: The key under which a card carries a limit no engineer has confirmed.
QUESTION_ONLY_KEY = "limit_draft"
_DECIDED = ("COMPLIANT", "NON_COMPLIANT")
_HELD = "NEEDS_ENGINEER_REVIEW"


def question_only(item: dict) -> bool:
    """Is this card QUESTION ONLY (its limit not confirmed by an engineer)?"""
    return bool(item.get(QUESTION_ONLY_KEY))


def _names(fact: dict, words) -> bool:
    from .datasheet_checks import _fold, _shown

    stated = _fold(_shown(fact))
    return any(_fold(word) in stated for word in words or [])


def not_matched(fact: dict, condition: dict, res, held) -> dict:
    """The result for a stated condition value naming none of the condition's words:
    "does not apply" only when the value rules the condition out."""
    from .datasheet_checks import NOT_APPLICABLE, _label, _pretty, _said, _sentence

    role, page = condition["role"], fact.get("page")
    about = f"whether it applies depends on the {_pretty(role).lower()}"
    if blank_markers.fact_is_placeholder(fact):
        marker = _said(fact) or fact.get("blank_marker")
        return held(
            why_held.DEFERRED_MARKER,
            _sentence(f"{about}, and the sheet marks it '{marker}' (page {page})"),
            fact,
            role,
        )
    if _names(fact, condition.get("may_be_any")):
        wanted = " or ".join(repr(w) for w in condition["any"])
        return held(
            why_held.OTHER,
            _sentence(
                f"{about}: '{_said(fact)}' (page {page}) does not name {wanted} but "
                "does not rule it out; engineer to check"
            ),
            fact,
            role,
        )
    return res(
        NOT_APPLICABLE,
        f"Does not apply: {_label(fact, role)} is '{_said(fact)}' (page {page}).",
        fact,
        role,
    )


def _value(role: str, roles: dict, common: dict):
    from .datasheet_checks import _one

    return _one(roles.get(role) or common.get(role) or [])


def decide_nothing(item: dict, result: dict, roles: dict, common: dict) -> dict:
    """`result` as it stands, unless the card is QUESTION ONLY and the result decided: then it
    is held, the words saying what was read and that nothing was compared."""
    if not question_only(item) or result.get("status") not in _DECIDED:
        return result
    from .datasheet_checks import _pretty, _quoted, _said, _sentence

    out = {k: v for k, v in result.items() if k != "rule_said"}
    read = result.get("detail") or ""
    right = (item.get("rule") or {}).get("right")
    other, why = _value(right, roles, common) if right else (None, None)
    if right and (
        other is None or blank_markers.fact_is_placeholder(other, figure_wins=True)
    ):
        if other is None:
            state = "is not given" if why == "absent" else "is stated twice"
            code = why_held.checked_against(None, why)
        else:
            marker = _said(other) or other.get("blank_marker")
            state = f"is marked '{marker}' on page {other.get('page')}"
            code = why_held.DEFERRED_MARKER
        words = f"the {_pretty(right).lower()} the clause's limit needs {state}"
        return {
            **out,
            "status": _HELD,
            why_held.KEY: code,
            "detail": f"{_sentence(words)} Read: {read}",
        }
    also = f" Also stated: {_quoted(other, right)}." if right else ""
    return {
        **out,
        "status": _HELD,
        why_held.KEY: why_held.LIMIT_NOT_CONFIRMED,
        "detail": (
            "Not decided: the limit is an AI draft no engineer has confirmed, so code "
            f"compared nothing; engineer to check against the clause. Read: {read}{also}"
        ),
    }
