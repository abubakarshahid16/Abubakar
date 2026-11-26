"""The way back per live update (owner via the planner, 26 Nov 2026 03:25, item 1): updates 6b, 7b and 8 go live with their
review-changing parts OFF, so one credit top-up and one quick score can switch them on the same day. With all three off a
review sends the same prompts and reaches the same lines and comments as main 475adb91 (`tests/test_aim_updates_off.py`).
Code-only and screen-only parts stay on.

  * AIM_U6B_ENABLED: the whole-paper check's guard v3 (`answered`; off: `answered_v0`, main's, and its prompt).
  * AIM_U7B_ENABLED: the gas-group checklist item and its method version, a specification's scope rule, the judge's
    component and vendor-field rules, the pass-as-Question fix (converted figures, an unproven Met), one point one comment
    (the editor's groups in the merge keys) and the upload-time picture stage.
  * AIM_U8_ENABLED: the second-model rule approvals in the rule pool, the cross-document check.
  * AIM_FORMULA_CHECKS_ENABLED (update 9, ON by default): the formula checks, out of AIM_U8_ENABLED.
  * AIM_U13_ENABLED: the always-on items G2 and G3 read the app's own consistency pairs and form entries (planner, 26 Nov 2026).
  * AGENT_REVIEW_NINE_ROLES_ENABLED: the nine-role record on the general review (`roles`); off: nothing imported."""

from __future__ import annotations

from app.config import settings


def u6b() -> bool:
    return bool(settings.aim_u6b_enabled)


def u7b() -> bool:
    return bool(settings.aim_u7b_enabled)


def u8() -> bool:
    return bool(settings.aim_u8_enabled)


def u13() -> bool:
    """Update 13's method part, OFF until a quick score: G2 is given the app's consistency pairs and G3 the entries this kind of
    paper must state (`always.form_context`); off: G2 and G3 exactly as main."""
    return bool(settings.aim_u13_enabled)


def formula_checks() -> bool:
    """The formula checks (`formulas.add_lines`), their own switch, ON (lead-4, update 9: proven by the free code-only replay);
    off: no formula lines, as main."""
    return bool(settings.aim_formula_checks_enabled)


def group_mark(p: dict) -> int | None:
    """The editor's (S5) group mark of a line for the merge keys (`aim_review_view.editor_group`); 7b off: None, as main."""
    group = p.get("same_point_as")
    if not u7b() or isinstance(group, bool) or not isinstance(group, int):
        return None
    return group


def s4b():
    """The whole-paper check to run: 6b's guard v3, or main's (`answered_v0`)."""
    from . import answered, answered_v0

    return (answered if u6b() else answered_v0).s4b_answered


def second_sql(conn, held, labels):
    """The second-model approvals' part of the rule pool's SQL (`rule_second_approval.review_sql`); update 8 off: None."""
    from app import rule_second_approval

    return rule_second_approval.review_sql(conn, held, labels) if u8() else None


def formula_lines(conn, paper, state) -> None:
    """The formula checks' lines after every AI stage (`formulas.add_lines`), only while their switch is on."""
    if formula_checks():
        from .formulas import add_lines

        add_lines(conn, paper, state)


def checklist_method() -> str:
    """The checklist method version a run builds and reuses with: 7b's, or main's (`checklist.CHECKLIST_METHOD_MAIN`)."""
    from . import checklist

    return checklist.CHECKLIST_METHOD if u7b() else checklist.CHECKLIST_METHOD_MAIN


def nine_roles() -> bool:
    return bool(settings.agent_review_nine_roles_enabled)


def nine_wrap(model, run_id: str, paper_id: str):
    """The run's model with the nine-role record around it (`roles.wrap`); off: the model as given, nothing imported."""
    if not nine_roles():
        return model
    from . import roles

    return roles.wrap(model, run_id, paper_id)


def nine_end(run_id: str, result: dict) -> None:
    """Each role's row at the run's end (`roles.finish`); off: nothing."""
    if nine_roles():
        from . import roles

        roles.finish(run_id, result)
