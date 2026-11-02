"""#805 plan change 6: a rule with no figure checked by words, and a sheet of several tagged valves. Invented text only."""

from __future__ import annotations

import json

import pytest

from app import (
    comparison,
    coverage_pair,
    crs_mapping,
    datasheets,
    db,
    material_reference,
    rule_trust,
    rule_typed_check,
    rulebook_v2_review,
)
from app.config import settings
from app.rule_typed_check import (
    AT_LEAST_CLASS,
    DIRECTION_DISAGREES,
    IS_NOT,
    IS_ONE_OF,
    LIST_NOT_PLAIN,
    NO_CHECK,
    NOT_A_CLASS,
    NOT_A_TEXT_FIELD,
    UNVERIFIED,
    VALUE_NOT_IN_QUOTE,
    VERIFIED,
    decide,
    plain_words,
    verify,
)
from tests.test_805_review_reads_v2 import (
    QUERY,
    SHEET,
    _one,
    _ours,
    _plain_standard,
    _reason,
    _review,
    _rule,
    _sheet,
    switched_on,  # noqa: F401
)
from tests.test_805_rule_field_naming import Roles
from tests.test_1584_standards_compiler import lane  # noqa: F401

FIELDS = {"body_material": "text", "inlet_rating": "text", "set_pressure": "pressure"}
NOT_COPPER = "The invented body shall not be cast iron."
CLASS = "The invented inlet rating shall be Class 300 or higher."
EITHER = "The invented body shall be carbon steel or stainless steel."


def _row(quote, role="body_material"):
    return {"id": "r", "quote": quote, "field_role": role}


@pytest.mark.parametrize(
    ("quote", "role", "answer", "state", "reason"),
    [
        (
            NOT_COPPER,
            "body_material",
            {"op": IS_NOT, "values": ["cast iron"]},
            VERIFIED,
            None,
        ),
        (
            CLASS,
            "inlet_rating",
            {"op": AT_LEAST_CLASS, "values": ["Class 300"]},
            VERIFIED,
            None,
        ),
        (
            EITHER,
            "body_material",
            {"op": IS_ONE_OF, "values": ["carbon steel", "stainless steel"]},
            VERIFIED,
            None,
        ),
        (
            NOT_COPPER,
            "body_material",
            {"op": IS_NOT, "values": ["bronze"]},
            UNVERIFIED,
            VALUE_NOT_IN_QUOTE,
        ),
        (
            NOT_COPPER,
            "set_pressure",
            {"op": IS_NOT, "values": ["cast iron"]},
            UNVERIFIED,
            NOT_A_TEXT_FIELD,
        ),
        (
            EITHER,
            "body_material",
            {"op": IS_NOT, "values": ["carbon steel"]},
            UNVERIFIED,
            DIRECTION_DISAGREES,
        ),
        (
            NOT_COPPER,
            "body_material",
            {"op": IS_ONE_OF, "values": ["cast iron"]},
            UNVERIFIED,
            DIRECTION_DISAGREES,
        ),
        (
            EITHER,
            "body_material",
            {"op": IS_ONE_OF, "values": ["carbon steel"]},
            UNVERIFIED,
            LIST_NOT_PLAIN,
        ),
        (
            EITHER,
            "inlet_rating",
            {"op": AT_LEAST_CLASS, "values": ["carbon steel"]},
            UNVERIFIED,
            NOT_A_CLASS,
        ),
        (EITHER, "body_material", {"op": None, "values": []}, NO_CHECK, None),
    ],
)
def test_code_verifies_every_proposal(quote, role, answer, state, reason):
    _op, _values, got, why = verify(_row(quote, role), answer, FIELDS)
    assert (got, why) == (state, reason)


@pytest.mark.parametrize(
    ("op", "values", "stated", "status"),
    [
        (IS_NOT, ["cast iron"], "cast iron", "NON_COMPLIANT"),
        (IS_NOT, ["cast iron"], "stainless steel", "COMPLIANT"),
        (IS_NOT, ["invented alloy"], "another invented alloy", None),
        (IS_NOT, ["cast iron"], "see note 4", None),
        (IS_ONE_OF, ["carbon steel", "stainless steel"], "carbon steel", "COMPLIANT"),
        (IS_ONE_OF, ["carbon steel", "stainless steel"], "cast iron", "NON_COMPLIANT"),
        (IS_ONE_OF, ["type a", "type b"], "type c", None),
        (IS_ONE_OF, ["type a", "type b"], "Type B", "COMPLIANT"),
        (AT_LEAST_CLASS, ["Class 300"], "Class 600", "COMPLIANT"),
        (AT_LEAST_CLASS, ["Class 300"], "Class 150", "NON_COMPLIANT"),
        (AT_LEAST_CLASS, ["Class 300"], "see note 4", None),
    ],
)
def test_code_decides_only_what_it_can_prove(op, values, stated, status):
    assert decide(op, values, stated)[0] == status


@pytest.mark.parametrize(
    ("op", "values", "stated", "status"),
    [
        (
            IS_ONE_OF,
            ["carbon steel", "stainless steel"],
            "carbon steel / cast iron",
            "NON_COMPLIANT",
        ),
        (
            IS_ONE_OF,
            ["carbon steel", "stainless steel"],
            "cast iron / carbon steel",
            "NON_COMPLIANT",
        ),
        (
            IS_ONE_OF,
            ["carbon steel", "stainless steel"],
            "carbon steel / invented alloy",
            None,
        ),
        (
            IS_ONE_OF,
            ["carbon steel", "stainless steel"],
            "carbon steel / stainless steel",
            "COMPLIANT",
        ),
        (IS_NOT, ["cast iron"], "stainless steel / invented alloy", None),
        (IS_NOT, ["cast iron"], "stainless steel / cast iron", "NON_COMPLIANT"),
        (AT_LEAST_CLASS, ["Class 300"], "Class 600 / Class 150", "NON_COMPLIANT"),
        (AT_LEAST_CLASS, ["Class 300"], "Class 600 / see note 4", None),
    ],
)
def test_every_listed_part_must_meet_the_rule(op, values, stated, status):
    assert decide(op, values, stated)[0] == status


@pytest.mark.parametrize(
    "stated",
    [
        "carbon steel with cast iron bonnet",
        "carbon steel or cast iron",
        "carbon steel + cast iron",
        "not carbon steel",
        "carbon steel lined",
        "mostly carbon steel",
    ],
)
@pytest.mark.parametrize(
    ("op", "values"),
    [
        (IS_ONE_OF, ["carbon steel", "stainless steel"]),
        (IS_NOT, ["cast iron"]),
    ],
)
def test_any_other_word_beside_an_entry_is_a_query(op, values, stated):
    assert decide(op, values, stated)[0] is None


@pytest.mark.parametrize(
    "stated",
    [
        "not cast iron",
        "A216 WCB or cast iron",
        "A216 WCB + A351 CF8M",
        "A216 WCB with liner",
    ],
)
def test_the_signed_table_takes_no_other_word_either(stated):
    table = material_reference.Table(
        "v",
        (
            material_reference.Entry("A216", "WCB", "carbon steel", False),
            material_reference.Entry("A351", "CF8M", "stainless steel", False),
        ),
    )
    assert decide(IS_NOT, ["cast iron"], stated, table)[0] is None


def test_a_listed_part_that_is_the_forbidden_word_fails_under_the_table():
    table = material_reference.Table(
        "v", (material_reference.Entry("A216", "WCB", "carbon steel", False),)
    )
    assert (
        decide(IS_NOT, ["cast iron"], "A216 WCB / cast iron", table)[0]
        == "NON_COMPLIANT"
    )


@pytest.mark.parametrize("words", ["unless", "where", "except", "when", "if"])
def test_a_check_on_a_conditional_sentence_is_refused_and_a_stored_one_does_not_decide(
    monkeypatch, words
):
    quote = (
        f"The invented body shall not be cast iron {words} the invented thing is so."
    )
    _op, _values, state, why = verify(
        _row(quote), {"op": IS_NOT, "values": ["cast iron"]}, FIELDS
    )
    assert (state, why) == (UNVERIFIED, rule_typed_check.CONDITIONAL_SENTENCE)
    run, scope = _material_sheet("cast iron")
    row = _one(_review(monkeypatch, run, scope, _typed(quote, IS_NOT, ["cast iron"])))
    assert row["compliance_status"] == QUERY and _reason(row) == "no_figure"


def test_a_safety_pass_stores_its_open_tick_and_holds_an_approved_code(monkeypatch):
    run, scope = _material_sheet("stainless steel")
    monkeypatch.setattr(
        rule_trust, "tier", lambda _r, **_k: (rule_trust.SAFETY, "invented")
    )
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == "COMPLIANT" and row["tier"] == rule_trust.SAFETY
    assert row["show_for_engineer_tick"] == 1
    codes = ("A", "B", "C", "MANUAL")
    held = rule_trust.hold_open_ticks({"code": "A", "reason": "r"}, [row], codes)
    assert held["code"] == "MANUAL"
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert (part["decided"], part["pass"], part["query"]) == (0, 0, 1)


def test_a_breach_opens_no_tick(monkeypatch):
    run, scope = _material_sheet("cast iron")
    monkeypatch.setattr(
        rule_trust, "tier", lambda _r, **_k: (rule_trust.SAFETY, "invented")
    )
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert (
        row["compliance_status"] == "NON_COMPLIANT"
        and row["show_for_engineer_tick"] == 0
    )


def test_a_note_rules_safety_pass_is_held_too(monkeypatch):
    row = {
        "trust_label": rule_trust.OWNER_NOTE_CONTEXT,
        "show_for_engineer_tick": 1,
        "compliance_status": "COMPLIANT",
    }
    held = rule_trust.hold_open_ticks(
        {"code": "A", "reason": "r"}, [row], ("A", "B", "C", "MANUAL")
    )
    assert held["code"] == "MANUAL"


def test_a_rule_whose_signed_content_changed_stops(monkeypatch):
    run, scope = _material_sheet("cast iron")
    rule = {**_typed(NOT_COPPER, IS_NOT, ["cast iron"]), "signed_matches": False}
    row = _one(_review(monkeypatch, run, scope, rule))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "signed_content_changed"
    )


def test_the_checklist_reads_the_check_in_plain_words():
    assert "must not be: cast iron" in plain_words(IS_NOT, ["cast iron"])


def _typed(quote, op, values, role_field="Body material"):
    rule = _rule(field=role_field, value=None, quote=quote)
    return {
        **rule,
        "field_role": role_field.lower().replace(" ", "_"),
        "field_role_state": "verified",
        "check_op": op,
        "check_values": json.dumps(values),
        "check_state": VERIFIED,
    }


def _material_sheet(words):
    return _sheet(label="Body material", value=words)


def test_a_typed_rule_breaks_end_to_end(monkeypatch):
    run, scope = _material_sheet("cast iron")
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == "NON_COMPLIANT", row["finding"]


def test_a_typed_rule_meets_end_to_end(monkeypatch):
    run, scope = _material_sheet("stainless steel")
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == "COMPLIANT", row["finding"]


def test_a_typed_rule_on_a_missing_value_is_a_query_never_compliant(monkeypatch):
    run, scope = _sheet(label="Inlet size", value="2 in")
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == QUERY


def test_a_typed_rule_on_an_unclear_value_is_a_query(monkeypatch):
    run, scope = _material_sheet("see note 4")
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == QUERY


def test_a_typed_rule_on_a_low_trust_value_is_a_query(monkeypatch):
    run, scope = _material_sheet("cast iron")
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET validation_state = 'needs_engineer_review'"
        )
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == QUERY and _reason(row) == "value_not_trusted"


def test_a_typed_rule_on_a_deferred_value_is_a_query(monkeypatch):
    run, scope = _material_sheet("cast iron")
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET value_note = 'by vendor'")
    row = _one(
        _review(monkeypatch, run, scope, _typed(NOT_COPPER, IS_NOT, ["cast iron"]))
    )
    assert row["compliance_status"] == QUERY and _reason(row) == "value_not_trusted"


def test_a_typed_rule_with_an_unverifiable_condition_is_a_query(monkeypatch):
    run, scope = _material_sheet("cast iron")
    rule = {
        **_typed(NOT_COPPER, IS_NOT, ["cast iron"]),
        "conditions": ["where the invented flux capacitor is fitted"],
    }
    row = _one(_review(monkeypatch, run, scope, rule))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "condition_not_verified"
    )


def test_only_an_owner_signature_decides_a_typed_rule(monkeypatch):
    run, scope = _material_sheet("cast iron")
    rule = {
        **_typed(NOT_COPPER, IS_NOT, ["cast iron"]),
        "approval": {"by": "x", "at": "2026-11-02", "tier": "engineer"},
    }
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == "not_owner_approved"


def test_a_check_not_verified_never_decides(monkeypatch):
    run, scope = _material_sheet("cast iron")
    rule = {**_typed(NOT_COPPER, IS_NOT, ["cast iron"]), "check_state": UNVERIFIED}
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == "no_figure"


# ------------------------------------------------------------------------------------------- the owner's note


def _flagged(note="Applies to every valve on this job."):
    rule = _rule(
        value=8.0,
        strength="context_dependent",
        sentence_strength="shall",
        context_flag="scope_elsewhere",
    )
    return {**rule, "approval": {**rule["approval"], "note": note}}


def test_a_note_does_nothing_with_the_switch_off(monkeypatch):
    run, scope = _sheet(value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _flagged()))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "scope_outside_sentence"
    )


def test_with_the_switch_on_a_note_lets_it_decide_and_the_finding_says_so(monkeypatch):
    monkeypatch.setattr(settings, "owner_note_lifts_context_flag_enabled", True)
    run, scope = _sheet(value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _flagged()))
    assert row["compliance_status"] == "NON_COMPLIANT", row["finding"]
    assert "owner note: context confirmed: Applies to every valve" in row["finding"]
    assert row["trust_label"] == rule_trust.OWNER_NOTE_CONTEXT
    rows = crs_mapping.build_crs_rows([row], [], "sheet.pdf")
    assert rows and {r["rule_trust"] for r in rows} == {
        "AI-built, quote-verified, owner-approved; owner note: context confirmed"
    }


@pytest.mark.parametrize("note", [None, "", "   "])
def test_no_note_or_a_blank_one_lifts_nothing(monkeypatch, note):
    monkeypatch.setattr(settings, "owner_note_lifts_context_flag_enabled", True)
    run, scope = _sheet(value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _flagged(note)))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "scope_outside_sentence"
    )


def test_a_note_never_overrides_an_unverifiable_condition(monkeypatch):
    monkeypatch.setattr(settings, "owner_note_lifts_context_flag_enabled", True)
    run, scope = _sheet(value="9 barg")
    rule = {**_flagged(), "conditions": ["where the invented flux capacitor is fitted"]}
    row = _one(_review(monkeypatch, run, scope, rule))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "condition_not_verified"
    )


def test_a_note_does_not_lift_a_low_reading_confidence(monkeypatch):
    monkeypatch.setattr(settings, "owner_note_lifts_context_flag_enabled", True)
    run, scope = _sheet(value="9 barg")
    rule = {**_flagged(), "context_flag": "low_ocr_confidence"}
    row = _one(_review(monkeypatch, run, scope, rule))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == "scope_outside_sentence"
    )


# ------------------------------------------------------------------------------------- a sheet of several valves


def _tagged(values):
    run, scope = _sheet(label="Set pressure", value=values[0])

    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET equipment_tag = 'TAG-1'")
    for n, value in enumerate(values[1:], 2):
        datasheets.create_fact(
            submittal_document_id=SHEET,
            chunk_id="fc",
            field_label="Set pressure",
            raw_value=value,
            page=1,
            equipment_tag=f"TAG-{n}",
        )
    return run, scope


def test_each_tag_is_judged_on_its_own_value_and_a_rule_fails_if_one_fails(monkeypatch):
    run, scope = _tagged(["9 barg", "12 barg"])
    result = _review(monkeypatch, run, scope, _rule(value=10.0))
    assert sorted(f["compliance_status"] for f in _ours(result)) == [
        "COMPLIANT",
        "NON_COMPLIANT",
    ]
    assert {f["equipment_tag"] for f in _ours(result)} == {"TAG-1", "TAG-2"}
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert (part["rules"], part["decided"], part["fail"], part["pass"]) == (1, 1, 1, 0)


def test_a_rule_passes_only_if_every_tag_passes(monkeypatch):
    monkeypatch.setattr(
        rule_trust, "tier", lambda _r, **_k: (rule_trust.STANDARD, None)
    )
    run, scope = _tagged(["9 barg", "8 barg"])
    _review(monkeypatch, run, scope, _rule(value=10.0))
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert (part["rules"], part["decided"], part["pass"], part["fail"]) == (1, 1, 1, 0)


def test_one_tag_unclear_keeps_the_rule_from_passing(monkeypatch):
    run, scope = _tagged(["9 barg", "see note 4"])
    _review(monkeypatch, run, scope, _rule(value=10.0))
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert (part["rules"], part["decided"], part["query"]) == (1, 0, 1)


def test_two_values_inside_one_tag_stay_a_query(monkeypatch):
    run, scope = _tagged(["9 barg", "8 barg"])

    datasheets.create_fact(
        submittal_document_id=SHEET,
        chunk_id="fc",
        field_label="Set pressure",
        raw_value="12 barg",
        page=1,
        equipment_tag="TAG-1",
    )
    rows = _ours(_review(monkeypatch, run, scope, _rule(value=10.0)))
    assert {_reason(f) for f in rows if f["compliance_status"] == QUERY} == {
        "several_values"
    }


def _four_valves(words):
    run, scope = _sheet(label="Body material", value=words[0])
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET equipment_tag = 'TAG-1'")
    for n, value in enumerate(words[1:], 2):
        datasheets.create_fact(
            submittal_document_id=SHEET,
            chunk_id="fc",
            field_label="Body material",
            raw_value=value,
            page=1,
            equipment_tag=f"TAG-{n}",
        )
    return run, scope


def _body_rule():
    rule = _typed(NOT_COPPER, IS_NOT, ["cast iron"])
    return {
        **rule,
        "strength": "context_dependent",
        "sentence_strength": "shall",
        "context_flag": "scope_elsewhere",
        "approval": {**rule["approval"], "note": "Applies to these valves."},
    }


def test_the_first_rule_gets_its_own_row_on_each_of_four_valves(monkeypatch):
    monkeypatch.setattr(settings, "owner_note_lifts_context_flag_enabled", True)
    run, scope = _four_valves(
        ["stainless steel", "stainless steel", "cast iron", "stainless steel"]
    )
    rows = _ours(_review(monkeypatch, run, scope, _body_rule()))
    by_tag = {f["equipment_tag"]: f["compliance_status"] for f in rows}
    assert by_tag == {
        "TAG-1": "COMPLIANT",
        "TAG-2": "COMPLIANT",
        "TAG-3": "NON_COMPLIANT",
        "TAG-4": "COMPLIANT",
    }
    assert {f["trust_label"] for f in rows} == {rule_trust.OWNER_NOTE_CONTEXT}
    part = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]
    assert (part["rules"], part["fail"], part["pass"]) == (1, 1, 0)


def test_the_first_rule_with_the_switch_off_is_a_query_on_every_valve(monkeypatch):
    run, scope = _four_valves(["cast iron", "cast iron", "cast iron", "cast iron"])
    rows = _ours(_review(monkeypatch, run, scope, _body_rule()))
    assert len(rows) == 4 and {f["compliance_status"] for f in rows} == {QUERY}
    assert {_reason(f) for f in rows} == {"scope_outside_sentence"}


def test_the_checklist_is_told_each_tags_value():
    _tagged(["9 barg", "12 barg"])
    _plain_standard()
    said = rulebook_v2_review.pair_rule_to_document(
        db.connect(),
        SHEET,
        {"field": "Set pressure", "quote": "Invented.", "document_id": "std-1"},
    )
    assert said["paired"] and said["tags_paired"] == said["tags"] == 2
    assert said["values_read"] == ["12 barg", "9 barg"] and said["value_read"] is None


# ------------------------------------------------------------------------------------------------- the step


def _with_a_role(monkeypatch):
    from tests.test_805_rule_field_naming import _compiled, _name

    monkeypatch.setattr(settings, "rule_field_naming_engine", "claude")
    conn = _compiled()
    _name(conn, Roles({"field_role": None, "reason": "design_method"}))
    rule_typed_check.ensure_columns(conn)
    with conn:
        conn.execute(
            "UPDATE compiled_rules SET limit_value = NULL, comparator = NULL,"
            " field_role = 'body_material', field_role_state = 'verified', check_prompt = NULL"
        )
    return conn


def _check_step(conn, client, **kw):
    from tests.test_1584_standards_compiler import DOC, LABEL

    return rule_typed_check.name_checks(
        conn,
        {DOC: LABEL},
        "Pressure Safety Valve",
        client=client,
        sleep=lambda _s: None,
        **kw,
    )


def test_the_step_estimates_without_a_send_or_a_key(monkeypatch):
    conn = _with_a_role(monkeypatch)
    monkeypatch.setattr(settings, "rule_field_naming_engine", "off")
    client = Roles({"op": None, "values": []})
    report = _check_step(conn, client, estimate_only=True)[0]
    assert client.created == [] and report["status"] == "estimate"
    assert report["estimate"]["model"] == "claude-haiku-5-5"


def test_the_step_stores_what_code_kept_once(monkeypatch):
    monkeypatch.setattr(settings, "rule_field_naming_engine", "claude")
    conn = _with_a_role(monkeypatch)
    report = _check_step(
        conn, Roles({"op": IS_NOT, "values": ["not on the page at all"]})
    )[0]
    assert report["stored"][UNVERIFIED] == 1
    row = conn.execute(
        "SELECT check_state, check_reason, check_op, check_prompt FROM compiled_rules"
    ).fetchone()
    assert tuple(row) == (
        UNVERIFIED,
        VALUE_NOT_IN_QUOTE,
        None,
        rule_typed_check.PROMPT_VERSION,
    )
    again = Roles({"op": None, "values": []})
    _check_step(conn, again)
    assert again.created == []


def test_the_check_step_sends_its_rules(monkeypatch):
    conn = _with_a_role(monkeypatch)
    client = Roles({"op": None, "values": []})
    report = _check_step(conn, client)[0]
    assert len(client.created) == 1 and len(client.created[0]) == report["rules"] == 1
    assert report["status"] == "done" and report["answered"] == 1


def test_a_limit_already_spent_sends_nothing_and_never_reads_as_done(monkeypatch):
    """The real run: 13 rules, --max-usd below today's spend: no batch, and it said "done, answered 0"."""
    conn = _with_a_role(monkeypatch)
    client = Roles({"op": None, "values": []})
    report = _check_step(conn, client, max_usd=0.0)[0]
    assert client.created == []
    assert report["status"] == "over_budget" and report["answered"] == 0
    assert report["not_sent_over_budget"] == report["rules"] == 1
    assert "--max-usd" in report["why"]
    state = conn.execute("SELECT check_prompt FROM compiled_rules").fetchone()[0]
    assert state is None, "nothing stored: run it again with room, and it asks"
    again = Roles({"op": None, "values": []})
    assert _check_step(conn, again)[0]["status"] == "done" and len(again.created) == 1


def test_the_script_exits_non_zero_when_nothing_could_be_sent(monkeypatch):
    import name_rule_fields

    from tests.test_1584_standards_compiler import DOC

    _with_a_role(monkeypatch)
    said = []
    code = name_rule_fields.run(
        settings.db_path,
        "Pressure Safety Valve",
        [DOC],
        emit=said.append,
        checks=True,
        client=Roles({"op": None, "values": []}),
        max_usd=0.0,
        sleep=lambda _s: None,
    )
    assert code == name_rule_fields.EXIT_REFUSED
    assert json.loads(said[0])["reports"][0]["status"] == "over_budget"


def test_comparison_module_is_untouched_by_a_typed_rule_with_the_switch_off(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rulebook_v2_review_enabled", False)
    run, scope = _material_sheet("cast iron")
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert not _ours(result) and rule_trust.owner_signed(None) is False
