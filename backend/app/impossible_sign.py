"""A value that should not be negative, printed negative, never gives a Pass (#1607).

Every limit check here is one-sided: "at most 10% of the set pressure" holds for -0.5 barg,
and "is stated" holds for anything. The planted-defect scorer read such a sheet as a Pass.
A role marked `never_negative` in `reference/datasheet_checks.json` says a negative value is
not to be passed unread: nearly always an error, and where it is real (a vacuum relief set
pressure, CDTP or superimposed back pressure) the engineer confirms it. Hence a Query, never
a Fail. Why each kind is in or out is written beside the data.

PURELY STOPS A FALSE PASS, so no switch: COMPLIANT becomes NEEDS_ENGINEER_REVIEW and every
other status is left alone. A Fail stays a Fail. The arithmetic stays in the words. General:
it reads the role table and the printed sign, never a layout or a sheet (rule 13).

Two homes call the one test: `datasheet_checks.evaluate` (`hold_results`, reached through
`deferred_value.hold_results`, its one exit) and the library
standards' `comparison._hold_low_trust_breach` (`hold_pass`).
"""

from __future__ import annotations

from . import claims, hold_reason, numparse
from .deferred_value import CALC_INPUT_ROLES

_PASS = "COMPLIANT"
_QUERY = "NEEDS_ENGINEER_REVIEW"


def is_negative(fact: dict | None) -> bool:
    """The value as printed is a number below zero. A range, a word, a blank are not."""
    if not fact or fact.get("is_blank") or fact.get("raw_value") is None:
        return False
    text = str(fact["raw_value"]).strip()
    # Both readers: `as_number` reads a Unicode hyphen and "-.5" as the minus they are.
    readings = (claims.parse_value(text), numparse.as_number(text))
    return any(number is not None and number < 0 for number in readings)


def _glued_number(fact: dict | None) -> bool:
    """A number glued to a joining hyphen ("PN-16"), or after a label ("Note 5", "A5"), so no
    number can be read: not a negative, and not a value to pass unread on these roles either
    (#1619, #1640)."""
    raw = None if not fact or fact.get("is_blank") else fact.get("raw_value")
    return raw is not None and (
        numparse.has_joining_minus(str(raw)) or numparse.has_label_number(str(raw))
    )


def glued_doubt(fact: dict, role: str) -> str | None:
    """Why a bounded role's value cannot be checked, when it is a glued number (#1619)."""
    if not _glued_number(fact):
        return None
    from .datasheet_checks import _label, _said

    return (
        f"{_label(fact, role)} {_said(fact)} (page {fact.get('page')}) cannot be read "
        f"as a number; engineer to check the value"
    )


def _why(fact: dict, role: str) -> str:
    name = role.replace("_", " ")
    if _glued_number(fact):
        return (
            f"the sheet prints the {name} as {fact.get('raw_value')} (page {fact.get('page')}), "
            f"which cannot be read as a number"
        )
    return (
        f"the sheet prints the {name} as {fact.get('raw_value')} (page {fact.get('page')}), and a negative "
        f"value here is unusual (it fits only a case such as vacuum service)"
    )


def _roles_read(rules: dict) -> dict[str, set[str]]:
    """rule id -> the fields it reads, from the rule data."""
    out = {
        r["id"]: {r[k] for k in ("left", "right") if r.get(k)}
        for r in rules.get("consistency", [])
    }
    # Every kit card too: its pass is held, and its code routes it (PR 1733 review).
    from . import kit_core

    groups = [
        c.get("items", [])
        for c in (rules.get("checklists") or {}).values()
        if isinstance(c, dict)
    ]
    groups += [kit.cards() for kit in kit_core._kits()]
    for group in groups:
        for item in group:
            rule = item.get("rule") or {}
            read = {
                rule[k]
                for k in ("field", "left", "right", "percent_of_role")
                if rule.get(k)
            }
            out[item["id"]] = read | (
                set(CALC_INPUT_ROLES) if rule.get("kind") == "calc" else set()
            )
    return out


def _impossible(facts: list[dict], rules: dict, wanted) -> list[tuple[dict, str]]:
    from .datasheet_checks import role_of

    roles = rules.get("roles") or {}
    found = []
    for fact in facts:
        if not (is_negative(fact) or _glued_number(fact)):
            continue
        role = role_of(fact.get("field_name") or "", rules, wanted)
        if role and (roles.get(role) or {}).get("never_negative"):
            found.append((fact, role))
    return found


def hold_results(
    results: list[dict], facts: list[dict], rules: dict, wanted
) -> list[dict]:
    """The datasheet checks: every Pass that reads an impossible value becomes a Query."""
    found = _impossible(facts, rules, wanted)
    if not found:
        return results
    reads = _roles_read(rules)
    out = []
    for r in results:
        # A kit card's pass, already held by `kit_core.held`, is checked as the pass it was (PR 1733 review).
        kit = r if r.get("kit") and r.get("rule_said") == _PASS else None
        if kit is not None:
            r = {**r, "status": _PASS}
        hit = None
        if r.get("status") == _PASS:
            tag, read = r.get("equipment_tag"), reads.get(r.get("rule_id"), set())
            hit = next(
                (
                    (fact, role)
                    for fact, role in found
                    if fact.get("id") == r.get("fact_id")
                    or (role in read and fact.get("equipment_tag") in (tag, None))
                ),
                None,
            )
        if hit is None:
            out.append(kit or r)
            continue
        if (
            kit is not None
        ):  # its words and status stay; its code is this hold's, not "rule not proven"
            out.append({k: v for k, v in kit.items() if k != hold_reason.KEY})
            continue
        out.append(
            {
                **r,
                "status": _QUERY,
                "detail": f"Could not be judged: {_why(*hit)}. Engineer to check the value. "
                f"The numbers read {_PASS}: {r.get('detail') or ''}".strip(),
            }
        )
    return out


def impossible(fact: dict, rules: dict, wanted: frozenset | None) -> bool:
    """Is this one value impossible as read (`hold_results`'s own test)? `crs_routing` asks it of a stored fact,
    with the roles the check preferred (`checklist_scope.wanted`). None, those roles not found: a value that is
    negative or a glued number counts as impossible (the safe side; the role it was read as is unknown)."""
    if wanted is None:
        return is_negative(fact) or _glued_number(fact)
    return bool(_impossible([fact], rules, wanted))


def hold_pass(verdict: dict, fact: dict | None) -> dict:
    """A library standard's verdict on one value: a Pass on an impossible value is a Query."""
    if verdict.get("status") != _PASS or not (is_negative(fact) or _glued_number(fact)):
        return verdict
    from .datasheet_checks import load_rules

    found = _impossible([fact], load_rules(), frozenset())
    if not found:
        return verdict
    return {
        **verdict,
        "status": _QUERY,
        "rationale": f"{_why(*found[0])}, so no verdict is stated; the arithmetic on the value "
        f"as read: {verdict.get('rationale') or ''}",
    }
