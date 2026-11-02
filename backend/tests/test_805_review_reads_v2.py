"""#805 plan change 6, "test before use": a review reads approved version 2 rules beside version 1. Invented rules and
values only; a temporary database copy; no model; `approved_rules` and `tier_for_approved` are fakes of their contracts
until the two pieces that hold them land."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import uuid

import openpyxl
import pytest

from app import (
    comparison,
    coverage_pair,
    crs_export,
    crs_reply,
    datasheet_checks,
    datasheets,
    db,
    degraded_read,
    review,
    review_audit_rows,
    rule_trust,
    rulebook_v2,
    rulebook_v2_crs,
    rulebook_v2_review,
    run_parts,
    schemas,
)
from app.config import settings
from app.rulebook_v2 import Reading
from app.rulebook_v2_review import (
    APPLIES_TO_NOT_VERIFIED,
    CONDITION_NOT_VERIFIED,
    EXCEPTION_NOT_RULED_OUT,
    LEFT_BLANK,
    NO_FIGURE,
    NO_SUCH_FIELD,
    NOT_BINDING,
    NOT_IN_SNAPSHOT,
    NOT_MENTIONED,
    NOT_OWNER_APPROVED,
    ONLY_UNDER_QUALIFIER,
    ORIGIN,
    PAIR_REFUSED,
    QUERY,
    QUOTE_HASH_MISMATCH,
    READING_INCOMPLETE,
    SCOPE_OUTSIDE_SENTENCE,
    SEVERAL_VALUES,
    SNAPSHOT_NOT_RECORDED,
    STATED_VALUE_NOT_A_LIMIT,
    TYPE_UNSURE,
    V1_DISAGREES,
    VALUE_NOT_TRUSTED,
    VALUE_UNCLEAR,
)
from tests.test_1584_standards_compiler import lane  # noqa: F401 - a temporary copy
from tests.test_field_naming import _world

TYPE = "Pressure Relief Valve"
ENGINEER = "user-eng"
SHEET, RUN_FACT_LABEL = "sub-1", "Set pressure"
SENTENCE = "The invented set pressure shall not exceed 10 barg."
V1_FIELD = "Maximum allowable working pressure"


@pytest.fixture(autouse=True)
def switched_on(lane, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "rulebook_v2_enabled", True)
    monkeypatch.setattr(settings, "rulebook_v2_review_enabled", True)
    monkeypatch.setattr(settings, "owner_approved_rules_decide_enabled", True)
    seen = []
    real = rule_trust.tier_for_approved

    def tier(approval, rule):
        seen.append(rule)
        return real(approval, rule)

    monkeypatch.setattr(rule_trust, "tier_for_approved", tier)
    return seen


def _plain_standard():
    """The rules' invented standard, as stored text with no Part or Appendix: its own scope holds (`rule_part_scope`)."""
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES ('std-1','std-1.pdf','sha-std-1',1,'x','ready','2026-11-02')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO pages (document_id,page_no,text,char_count,batch_no)"
            " VALUES ('std-1',3,'4.1 An invented clause of an invented standard.',47,1)"
        )


def _conn():
    return db.connect()


def _book():
    conn = _conn()
    rulebook_v2.ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,?,1,?)",
            (ENGINEER, "e@example.test", "E", "x", "2026-11-02"),
        )
    return conn


def _rule(field="Set pressure", comparator="<=", value=10.0, unit="barg", **over):
    """One rule in the contract's shape, with a real version and a person's approval in the book."""
    conn = _book()
    words = {"<=": "shall not exceed", ">=": "shall be at least"}.get(
        comparator, "shall be"
    )
    quote = over.pop(
        "quote", f"The invented {field.lower()} {words} {value or 0:g} {unit}."
    )
    digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    key = uuid.uuid4().hex
    need = {
        "kind": "limit" if value is not None else "no_figure",
        "field": field,
        "comparator": comparator if value is not None else None,
        "value": value,
        "unit": unit if value is not None else None,
    }
    if value is None:
        need["value_text"] = "words"
    reading = Reading(
        rule_key=key,
        standard="SAES-Z-901",
        requirement=need,
        strength="shall",
        sentence_strength="shall",
        context_flag=None,
        applicability=(),
        exceptions=(),
        provenance={
            "standard_document_id": "std-1",
            "edition": "2026",
            "clause": "4.1",
            "page": 3,
            "quote": quote,
            "quote_sha256": digest,
            "quote_start": 0,
            "quote_end": len(quote),
            "page_source": "text",
            "page_min_conf": None,
            "text_sha256": "a" * 64,
            "model": "fake",
            "prompt_version": "p1",
            "batch_id": None,
            "compile_run_id": f"compile-{key}",
        },
    )
    with conn:
        rulebook_v2.append_reading(conn, reading, "compile:test")
    row = conn.execute(
        "SELECT v.id, v.rule_id, p.id FROM rulebook_version v JOIN rulebook_rule r ON r.id = v.rule_id"
        " JOIN rulebook_provenance p ON p.rule_version_id = v.id WHERE r.rule_key = ?",
        (key,),
    ).fetchone()
    rulebook_v2.record_decision(
        conn,
        row[0],
        decision="approve",
        engineer_id=ENGINEER,
        tier="owner",
        equipment_type=TYPE,
        provenance_viewed=(row[2],),
        signed_content=rulebook_v2.content_to_sign(conn, row[0]),
    )
    rule = {
        "rule_id": row[1],
        "version": 1,
        "field": field,
        "comparator": need["comparator"],
        "value": value,
        "unit": need["unit"],
        "applies_to": TYPE,
        "conditions": [],
        "exceptions": [],
        "clause": "4.1",
        "page": 3,
        "quote": quote,
        "quote_sha256": digest,
        "standard": "SAES-Z-901",
        "document_id": "std-1",
        "edition": "2026",
        "context_flag": None,
        "strength": "shall",
        "approval": {"by": ENGINEER, "at": "2026-11-02", "tier": "owner"},
    }
    return {**rule, **over}


def _sheet(label=RUN_FACT_LABEL, value="9 barg", equipment_type=TYPE):
    """A datasheet of a known type and a run with no version 1 rule on the field."""
    _req, _fact, run, scope = _world(label, value)
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM review_applicable_standards WHERE review_run_id = ?", (run,)
        )
        conn.execute(
            "UPDATE document_classification SET equipment_type = ? WHERE document_id = ?",
            (equipment_type, SHEET),
        )
    return run, scope


def _review(monkeypatch, run, scope, *rules):
    _plain_standard()
    monkeypatch.setattr(
        rulebook_v2, "approved_rules", lambda _c, _t: list(rules), raising=False
    )
    return comparison.run_comparison(run, allowed_document_ids=scope)


def _ours(result):
    return [f for f in result["findings"] if f.get("origin") == ORIGIN]


def _one(result):
    rows = _ours(result)
    assert len(rows) == 1
    return rows[0]


def _reason(finding):
    return finding["finding"].removeprefix("Rulebook v2: ").split(":")[0].strip()


# ------------------------------------------------------------------------------------------ the planted set


def test_one_that_meets_and_one_that_breaks(monkeypatch):
    run, scope = _sheet(value="9 barg")
    meets = _rule(comparator="<=", value=10.0)
    breaks = _rule(
        comparator="<=",
        value=8.0,
        quote="The invented set pressure shall not exceed 8 barg.",
    )
    result = _review(monkeypatch, run, scope, meets, breaks)
    by_quote = {f["requirement"]: f["compliance_status"] for f in _ours(result)}
    assert by_quote == {
        meets["quote"]: "COMPLIANT",
        breaks["quote"]: "NON_COMPLIANT",
    }


def test_a_second_unit_of_one_quantity_goes_through_the_one_comparison(monkeypatch):
    run, scope = _sheet(value="9 barg")
    rule = _rule(comparator="<=", value=2000.0, unit="kPag")
    assert (
        _one(_review(monkeypatch, run, scope, rule))["compliance_status"] == "COMPLIANT"
    )


def test_the_contract_names_become_the_comparisons_once(switched_on, monkeypatch):
    run, scope = _sheet()
    _review(monkeypatch, run, scope, _rule(comparator="<=", value=10.0))
    seen = switched_on[0]
    assert seen["operator"] == "<=" and seen["raw_value"] == "10"
    assert seen["raw_unit"] == "barg" and seen["approval"]["tier"] == "owner"
    assert "confirmed_by" not in seen


def test_missing_is_never_compliant(monkeypatch):
    run, scope = _sheet(label="Inlet size", value="2 in")
    row = _one(_review(monkeypatch, run, scope, _rule()))
    assert row["compliance_status"] == QUERY and _reason(row) == NOT_MENTIONED


def test_a_field_the_project_does_not_know_stays_undecided(monkeypatch):
    run, scope = _sheet()
    row = _one(
        _review(
            monkeypatch, run, scope, _rule(field="Invented gadget thickness", unit="mm")
        )
    )
    assert row["compliance_status"] == QUERY and _reason(row) == NO_SUCH_FIELD


def test_a_field_with_a_qualifier_is_not_chosen(monkeypatch):
    run, scope = _sheet(label="Casing design pressure", value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _rule(field="Design pressure")))
    assert row["compliance_status"] == QUERY and _reason(row) == ONLY_UNDER_QUALIFIER


@pytest.mark.parametrize("value", ["see note 3", "TBD later"])
def test_an_unclear_value_is_a_query(monkeypatch, value):
    run, scope = _sheet(value=value)
    row = _one(_review(monkeypatch, run, scope, _rule()))
    assert row["compliance_status"] == QUERY
    assert _reason(row) in (VALUE_UNCLEAR, LEFT_BLANK)


def test_two_different_values_are_a_query(monkeypatch):
    run, scope = _sheet(value="9 barg")
    datasheets.create_fact(
        submittal_document_id=SHEET,
        chunk_id="fc",
        field_label=RUN_FACT_LABEL,
        raw_value="12 barg",
        page=1,
    )
    row = _one(_review(monkeypatch, run, scope, _rule()))
    assert row["compliance_status"] == QUERY and _reason(row) == SEVERAL_VALUES


@pytest.mark.parametrize("limit", [10.0, 8.0])
def test_a_low_trust_value_is_a_query_on_both_sides(monkeypatch, limit):
    run, scope = _sheet(value="9 barg")
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET validation_state = 'needs_engineer_review'"
        )
    row = _one(_review(monkeypatch, run, scope, _rule(value=limit)))
    assert row["compliance_status"] == QUERY and _reason(row) == VALUE_NOT_TRUSTED


def test_a_rule_with_no_figure_goes_to_the_engineer(monkeypatch):
    run, scope = _sheet()
    row = _one(_review(monkeypatch, run, scope, _rule(value=None)))
    assert row["compliance_status"] == QUERY and _reason(row) == NO_FIGURE


def test_an_unverified_condition_or_exception_is_a_query(monkeypatch):
    run, scope = _sheet()
    cond = _rule(conditions=["where the invented flux capacitor is fitted"])
    exc = _rule(
        value=11.0,
        quote="The invented set pressure shall not exceed 11 barg.",
        exceptions=["unless the invented flux capacitor is fitted"],
    )
    rows = {
        f["requirement"]: _reason(f)
        for f in _ours(_review(monkeypatch, run, scope, cond, exc))
    }
    assert rows == {
        cond["quote"]: CONDITION_NOT_VERIFIED,
        exc["quote"]: EXCEPTION_NOT_RULED_OUT,
    }


def _with_material(words):
    datasheets.create_fact(
        submittal_document_id=SHEET,
        chunk_id="fc",
        field_label="Body material",
        raw_value=words,
        page=1,
    )


def test_a_condition_read_values_show_holding_lets_it_decide(monkeypatch):
    run, scope = _sheet()
    _with_material("carbon steel")
    rule = _rule(conditions=["for carbon steel"])
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == "COMPLIANT", row["finding"]


def test_a_condition_read_values_show_not_holding_is_a_query_not_a_pass(monkeypatch):
    run, scope = _sheet()
    _with_material("stainless steel")
    row = _one(_review(monkeypatch, run, scope, _rule(conditions=["for carbon steel"])))
    assert row["compliance_status"] == QUERY and _reason(row) == CONDITION_NOT_VERIFIED


def test_an_exception_read_values_rule_out_lets_it_decide(monkeypatch):
    run, scope = _sheet()
    _with_material("stainless steel")
    row = _one(_review(monkeypatch, run, scope, _rule(exceptions=["for carbon steel"])))
    assert row["compliance_status"] == "COMPLIANT", row["finding"]


def test_an_exception_read_values_show_holding_is_a_query(monkeypatch):
    run, scope = _sheet()
    _with_material("carbon steel")
    row = _one(_review(monkeypatch, run, scope, _rule(exceptions=["for carbon steel"])))
    assert row["compliance_status"] == QUERY and _reason(row) == EXCEPTION_NOT_RULED_OUT


def test_a_narrower_scope_than_the_type_is_a_query(monkeypatch):
    run, scope = _sheet()
    rule = _rule(applies_to="pressure relief valves in sour gas service")
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == APPLIES_TO_NOT_VERIFIED


def test_scope_from_outside_the_sentence_or_a_should_is_a_query(monkeypatch):
    run, scope = _sheet()
    flagged = _rule(context_flag="scope_elsewhere")
    advice = _rule(
        strength="should",
        value=9.5,
        quote="The invented set pressure should not exceed 9.5 barg.",
    )
    rows = {
        f["requirement"]: _reason(f)
        for f in _ours(_review(monkeypatch, run, scope, flagged, advice))
    }
    assert rows == {
        flagged["quote"]: SCOPE_OUTSIDE_SENTENCE,
        advice["quote"]: NOT_BINDING,
    }


def test_only_an_owner_approval_decides(monkeypatch):
    run, scope = _sheet()
    rule = _rule(approval={"by": ENGINEER, "at": "2026-11-02", "tier": "engineer"})
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == NOT_OWNER_APPROVED


def test_with_the_owners_switch_off_nothing_decides(monkeypatch):
    run, scope = _sheet()
    monkeypatch.setattr(settings, "owner_approved_rules_decide_enabled", False)
    row = _one(_review(monkeypatch, run, scope, _rule()))
    assert row["compliance_status"] == QUERY and _reason(row) == NOT_OWNER_APPROVED


def test_a_quote_that_does_not_hold_the_rules_number_does_not_decide(monkeypatch):
    run, scope = _sheet()
    rule = _rule(value=8.0, quote="The invented set pressure shall not exceed 10 barg.")
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == NOT_OWNER_APPROVED


def test_a_deferred_value_is_a_query_on_both_sides(monkeypatch):
    run, scope = _sheet(value="9 barg")
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET value_note = 'by vendor'")
    meets = _rule(value=10.0)
    breaks = _rule(value=8.0)
    rows = _ours(_review(monkeypatch, run, scope, meets, breaks))
    assert [(r["compliance_status"], _reason(r)) for r in rows] == [
        (QUERY, VALUE_NOT_TRUSTED),
        (QUERY, VALUE_NOT_TRUSTED),
    ]


def test_a_breach_reaches_the_crs_citing_its_rule_and_a_query_does_not_call_it_one(
    monkeypatch,
):
    from app import crs_mapping

    run, scope = _sheet(value="9 barg")
    breach = _rule(value=8.0)
    unsure = _rule(field="Invented gadget thickness", unit="mm", value=2.0)
    result = _review(monkeypatch, run, scope, breach, unsure)
    rows = crs_mapping.build_crs_rows(_ours(result), [], "sheet.pdf")
    said = json.dumps(rows, default=str)
    assert breach["quote"] in said and "SAES-Z-901" in said
    assert "Owner" in said or "owner" in said
    by_field = {f["contractor_section"]: f["compliance_status"] for f in _ours(result)}
    assert by_field == {
        "Set pressure": "NON_COMPLIANT",
        "Invented gadget thickness": QUERY,
    }


def test_a_stated_value_another_value_differs_from_is_a_query_never_a_breach(
    monkeypatch,
):
    run, scope = _sheet(value="9 barg")
    other = _rule(comparator="=", value=8.0)
    row = _one(_review(monkeypatch, run, scope, other))
    assert (
        row["compliance_status"] == QUERY and _reason(row) == STATED_VALUE_NOT_A_LIMIT
    )


def test_a_stated_value_the_sheet_states_meets(monkeypatch):
    run, scope = _sheet(value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _rule(comparator="=", value=9.0)))
    assert row["compliance_status"] == "COMPLIANT", row["finding"]


def test_a_pass_on_an_incomplete_reading_is_held_and_a_breach_is_not(monkeypatch):
    run, scope = _sheet(value="9 barg")
    monkeypatch.setattr(
        degraded_read,
        "hold",
        lambda results, _doc: [{**r, "status": QUERY} for r in results],
    )
    meets, breaks = _rule(value=10.0), _rule(value=8.0)
    rows = {
        f["requirement"]: (f["compliance_status"], _reason(f))
        for f in _ours(_review(monkeypatch, run, scope, meets, breaks))
    }
    assert rows[meets["quote"]] == (QUERY, READING_INCOMPLETE)
    assert rows[breaks["quote"]][0] == "NON_COMPLIANT"


def test_every_condition_must_hold_not_only_the_first(monkeypatch):
    run, scope = _sheet()
    _with_material("carbon steel")
    rule = _rule(
        conditions=["for carbon steel", "where the invented flux capacitor is fitted"]
    )
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == CONDITION_NOT_VERIFIED


def test_a_pair_of_two_quantities_is_refused_by_name(monkeypatch):
    run, scope = _sheet(value="9 barg")
    row = _one(_review(monkeypatch, run, scope, _rule(value=2.0, unit="mm")))
    assert row["compliance_status"] == QUERY and _reason(row) == PAIR_REFUSED


def test_a_run_already_recorded_on_version_1_decides_nothing_on_version_2(monkeypatch):
    run, scope = _sheet(value="9 barg")
    rule = _rule(value=8.0)
    rulebook_v2.record_run(_conn(), run)
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == SNAPSHOT_NOT_RECORDED


def test_a_changed_quote_stops_that_rule_at_use(monkeypatch):
    run, scope = _sheet()
    rule = _rule()
    changed = {**rule, "quote": "The invented set pressure shall not exceed 99 barg."}
    row = _one(_review(monkeypatch, run, scope, changed))
    assert row["compliance_status"] == QUERY and _reason(row) == QUOTE_HASH_MISMATCH


def test_a_rule_outside_the_runs_snapshot_decides_nothing(monkeypatch):
    run, scope = _sheet()
    rule = {**_rule(), "version": 2}
    row = _one(_review(monkeypatch, run, scope, rule))
    assert row["compliance_status"] == QUERY and _reason(row) == NOT_IN_SNAPSHOT


def test_the_books_own_approved_rules_decide_end_to_end(monkeypatch):
    """No fake of `approved_rules`: a person's approval for this type, then a review."""
    run, scope = _sheet(value="9 barg")
    _plain_standard()
    _rule(value=8.0)
    row = _one(comparison.run_comparison(run, allowed_document_ids=scope))
    assert row["compliance_status"] == "NON_COMPLIANT"


def test_an_approval_for_another_type_gives_this_sheet_no_rule(monkeypatch):
    run, scope = _sheet(value="9 barg", equipment_type="Centrifugal Pump")
    _rule(value=8.0)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert not _ours(result)
    assert result["requirement_split"]["rulebook_v2"]["rules"] == 0


# ------------------------------------------------------------------------------------- the equipment type


def test_a_type_that_is_unsure_gets_no_rule_and_says_so(monkeypatch):
    run, scope = _sheet(equipment_type=None)
    asked = []

    def approved(_conn, equipment_type):
        asked.append(equipment_type)
        return [_rule()]

    monkeypatch.setattr(rulebook_v2, "approved_rules", approved, raising=False)
    _book()
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert not asked and not _ours(result)
    assert result["requirement_split"]["rulebook_v2"]["state"] == TYPE_UNSURE
    pair = coverage_pair.for_run(_conn(), run)
    assert pair["rulebook_v2"]["decided"] == 0
    assert TYPE_UNSURE in pair["rulebook_v2"]["line"]
    row = (
        _conn()
        .execute(
            "SELECT used_version, snapshot_id FROM rulebook_run WHERE review_run_id = ?",
            (run,),
        )
        .fetchone()
    )
    assert tuple(row) == (1, None)


# ------------------------------------------------------------------------------------- version 1 beside it


def _v1_world(limit_says):
    """The sheet with a version 1 limit on the same field. `_world`'s limit is at most 10 bar."""
    req, _fact, run, scope = _world(V1_FIELD, limit_says)
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = ? WHERE document_id = ?",
            (TYPE, SHEET),
        )
    return req, run, scope


def test_a_disagreement_with_version_1_makes_both_rows_a_query(monkeypatch):
    _req, run, scope = _v1_world("9 bar")
    alone = comparison.run_comparison(run, allowed_document_ids=scope)
    v1 = [f for f in alone["findings"] if f.get("requirement_id")]
    assert [f["compliance_status"] for f in v1] == ["COMPLIANT"]
    rule = _rule(
        field=V1_FIELD,
        value=8.0,
        unit="bar",
        quote="The invented working pressure shall not exceed 8 bar.",
    )
    result = _review(monkeypatch, run, scope, rule)
    row = _one(result)
    assert row["compliance_status"] == QUERY and _reason(row) == V1_DISAGREES
    assert row["rule_said"] == "NON_COMPLIANT"
    held = [f for f in result["findings"] if f.get("requirement_id")]
    assert [f["compliance_status"] for f in held] == [QUERY]
    assert (
        held[0]["rule_said"] == "COMPLIANT" and V1_DISAGREES in held[0]["ai_rationale"]
    )
    stored = (
        _conn()
        .execute(
            "SELECT compliance_status FROM review_findings WHERE id = ?",
            (held[0]["id"],),
        )
        .fetchone()[0]
    )
    assert stored == QUERY


def test_both_rulebooks_agreeing_keep_their_verdicts_and_count_apart(monkeypatch):
    monkeypatch.setattr(
        rule_trust, "tier", lambda _r, **_k: (rule_trust.STANDARD, None)
    )
    _req, run, scope = _v1_world("9 bar")
    rule = _rule(
        field=V1_FIELD,
        value=10.0,
        unit="bar",
        quote="The invented working pressure shall not exceed 10 bar.",
    )
    result = _review(monkeypatch, run, scope, rule)
    assert _one(result)["compliance_status"] == "COMPLIANT"
    pair = coverage_pair.for_run(_conn(), run)
    assert pair["decided"] == 1 and pair["rulebook_v2"]["decided"] == 1
    assert pair["pass"] == 1, "one version 1 rule: the version 2 row is not added to it"


def test_agreeing_with_version_1_keeps_both_verdicts():
    rule = rulebook_v2_review.Row({}, "COMPLIANT", None, "", fact_ids={"f"})
    reviewed = rulebook_v2_review.Review("r", "d", "used", rows=[rule])
    row = {"id": "x", "compliance_status": "COMPLIANT", "fact_id": "f"}
    reviewed.settle_with_findings([row], [])
    assert row["compliance_status"] == "COMPLIANT" and rule.status == "COMPLIANT"


def test_a_query_on_version_1_is_not_a_disagreement():
    rule = rulebook_v2_review.Row({}, "COMPLIANT", None, "", fact_ids={"f"})
    reviewed = rulebook_v2_review.Review("r", "d", "used", rows=[rule])
    row = {"id": "x", "compliance_status": QUERY, "fact_id": "f"}
    reviewed.settle_with_findings([row], [])
    assert rule.status == "COMPLIANT"


def test_a_review_settles_its_checks_before_they_are_stored(monkeypatch):
    run, scope = _sheet()
    order = []
    real_store = datasheet_checks.store
    real_settle = rulebook_v2_review.Review.settle_with_checks

    def settle(self, results):
        order.append("settled")
        return real_settle(self, results)

    def store(*args, **kwargs):
        order.append("stored")
        return real_store(*args, **kwargs)

    monkeypatch.setattr(rulebook_v2_review.Review, "settle_with_checks", settle)
    monkeypatch.setattr(datasheet_checks, "store", store)
    _review(monkeypatch, run, scope, _rule())
    assert order == ["settled", "stored"]


def test_a_checklist_item_that_disagrees_is_held_with_the_rule():
    rule = rulebook_v2_review.Row({}, "NON_COMPLIANT", None, "", fact_ids={"f"})
    reviewed = rulebook_v2_review.Review("r", "d", "used", rows=[rule])
    held, other = reviewed.settle_with_checks(
        [
            {"status": "COMPLIANT", "fact_id": "f", "checklist": True, "detail": "d"},
            {
                "status": "COMPLIANT",
                "fact_id": "f",
                "detail": "the sheet against itself",
            },
        ],
    )
    assert held["status"] == QUERY and held["rule_said"] == "COMPLIANT"
    assert other["status"] == "COMPLIANT"
    assert rule.status == QUERY and rule.reason == V1_DISAGREES


# ------------------------------------------------------------------------------------- recorded and stated


def test_a_rule_whose_source_this_reader_may_not_read_is_dropped_and_counted(
    monkeypatch,
):
    run, scope = _sheet()
    secret = {**_rule(), "document_id": "std-this-reader-has-no-grant-on"}
    missing = {k: v for k, v in _rule().items() if k != "document_id"}
    result = _review(monkeypatch, run, scope, secret, missing, _rule())
    assert len(_ours(result)) == 1
    part = coverage_pair.for_run(_conn(), run)["rulebook_v2"]
    assert part["rules"] == 1
    assert "2 this reader may not read" in part["line"]


def test_the_stated_part_and_the_review_name_one_origin():
    from app import rulebook_v2_stated

    assert rulebook_v2_stated.ORIGIN == ORIGIN


def test_a_rule_the_book_withholds_is_stated_as_a_count(monkeypatch):
    run, scope = _sheet()
    monkeypatch.setattr(
        rulebook_v2, "withheld_rules", lambda _c, _t: [{"rule_id": "r"}]
    )
    _review(monkeypatch, run, scope, _rule())
    line = coverage_pair.for_run(_conn(), run)["rulebook_v2"]["line"]
    assert "1 withheld by the rulebook" in line


def test_every_rule_withheld_or_ungranted_still_says_so(monkeypatch):
    run, scope = _sheet()
    _review(monkeypatch, run, scope, {**_rule(), "document_id": "std-no-grant"})
    part = coverage_pair.for_run(_conn(), run)["rulebook_v2"]
    assert part["rules"] == 0 and "1 this reader may not read" in part["line"]


def test_each_finding_cites_its_rule_and_the_run_records_its_snapshot(monkeypatch):
    run, scope = _sheet()
    rule = _rule()
    row = _one(_review(monkeypatch, run, scope, rule))
    for said in (rule["rule_id"], "version 1", "clause 4.1", "page 3", SENTENCE):
        assert said in row["requirement_source_text"]
    conn = _conn()
    used = conn.execute(
        "SELECT used_version, snapshot_id FROM rulebook_run WHERE review_run_id = ?",
        (run,),
    ).fetchone()
    assert used[0] == 2 and used[1]
    assert (rule["rule_id"], 1) in rulebook_v2.in_force_versions(conn, used[1])


def test_the_run_says_it_used_version_2_and_not_version_1(monkeypatch):
    run, scope = _sheet()
    _review(monkeypatch, run, scope, _rule())
    outcome = (
        _conn()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run,))
        .fetchone()[0]
    )
    assert json.loads(outcome)["rule_version"]["used"] == 2


def test_a_rerun_reads_the_same_snapshot_and_replaces_its_rows(monkeypatch):
    run, scope = _sheet()
    rule = _rule()
    _review(monkeypatch, run, scope, rule)
    conn = _conn()
    first = conn.execute("SELECT snapshot_id FROM rulebook_run").fetchone()[0]
    again = _review(monkeypatch, run, scope, rule)
    assert _one(again)["compliance_status"] == "COMPLIANT"
    assert conn.execute("SELECT snapshot_id FROM rulebook_run").fetchone()[0] == first
    stored = conn.execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ? AND origin = ?",
        (run, ORIGIN),
    ).fetchone()[0]
    assert stored == 1


def test_coverage_states_version_2_apart_with_its_denominator(monkeypatch):
    monkeypatch.setattr(
        rule_trust, "tier", lambda _r, **_k: (rule_trust.STANDARD, None)
    )
    run, scope = _sheet(value="9 barg")
    meets = _rule(value=10.0)
    breaks = _rule(
        value=8.0, quote="The invented set pressure shall not exceed 8 barg."
    )
    missing = _rule(
        field="Design pressure",
        quote="The invented design pressure shall be at least 2 barg.",
        comparator=">=",
        value=2.0,
    )
    _review(monkeypatch, run, scope, meets, breaks, missing)
    pair = coverage_pair.for_run(_conn(), run)
    part = pair["rulebook_v2"]
    assert (
        part["rules"],
        part["decided"],
        part["pass"],
        part["fail"],
        part["query"],
    ) == (3, 2, 1, 1, 1)
    assert "2 of 3" in part["line"] and part["reasons"] == {NOT_MENTIONED: 1}
    assert part["line"] in pair["line"], "the headline is not 0 of N alone"
    assert part["wrong"] is None and "not measured" in part["line"]
    assert pair["decided"] == 0, "never added to the version 1 count"
    assert SENTENCE not in json.dumps(coverage_pair.public_view(pair))


def test_a_v2_breach_counts_in_the_recommended_code(monkeypatch):
    run, scope = _sheet(value="9 barg")
    result = _review(monkeypatch, run, scope, _rule(value=8.0))
    assert result["recommended_code"]["blocking"] == 1


def test_a_run_with_the_tables_gone_reads_nothing_and_says_so(monkeypatch):
    run, scope = _sheet()
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert result["requirement_split"]["rulebook_v2"]["state"] == "rulebook_not_ready"
    assert not rulebook_v2.has_schema(_conn()), "a review creates no table"


# ---------------------------------------------------------------------------------- the pairing, read only


def _read_only():
    _plain_standard()
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    return conn


def test_pair_rule_to_document_says_what_the_review_would_pair_and_writes_nothing():
    _sheet(value="9 barg")
    rule = {
        "field": "Set pressure",
        "quote": SENTENCE,
        "unit": "barg",
        "document_id": "std-1",
    }
    conn = _read_only()
    said = rulebook_v2_review.pair_rule_to_document(conn, SHEET, rule)
    assert said["role"] == "set_pressure" and said["tags"] == 1
    assert {k: said[k] for k in ("paired", "reason", "value_read", "page")} == {
        "paired": True,
        "reason": None,
        "value_read": "9 barg",
        "page": 1,
    }


def test_pair_rule_to_document_names_the_reason_and_needs_no_approval_and_gives_no_verdict():
    _sheet(label="Inlet size", value="2 in")
    conn = _read_only()
    for field, reason in (
        ("Set pressure", NOT_MENTIONED),
        ("Invented gadget thickness", NO_SUCH_FIELD),
    ):
        said = rulebook_v2_review.pair_rule_to_document(
            conn,
            SHEET,
            {"field": field, "quote": "Invented sentence.", "document_id": "std-1"},
        )
        assert {k: said[k] for k in ("paired", "reason", "value_read", "page")} == {
            "paired": False,
            "reason": reason,
            "value_read": None,
            "page": None,
        }


def test_the_review_and_the_checklist_share_one_pairing(monkeypatch):
    run, scope = _sheet(value="9 barg")
    calls = []
    real = rulebook_v2_review.pair

    def spy(*args):
        calls.append(args[0]["field"])
        return real(*args)

    monkeypatch.setattr(rulebook_v2_review, "pair", spy)
    _review(monkeypatch, run, scope, _rule())
    rulebook_v2_review.pair_rule_to_document(
        _read_only(), SHEET, {"field": "Set pressure", "quote": SENTENCE}
    )
    assert calls == ["Set pressure", "Set pressure"]


# ----------------------------------------------------------------------------------------- switch off


def _everything(run):
    keep_out = {"id", "review_run_id", "created_at", "updated_at"}
    conn = _conn()
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    findings = sorted(
        json.dumps(
            {k: r[k] for k in r.keys() if k not in keep_out},
            sort_keys=True,
            default=str,
        )
        for r in cursor.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ?", (run,)
        )
    )
    outcome = conn.execute(
        "SELECT outcome_json FROM review_runs WHERE id = ?", (run,)
    ).fetchone()[0]
    return findings, outcome


def test_switch_off_a_review_with_a_full_book_is_byte_identical(monkeypatch):
    monkeypatch.setattr(settings, "rulebook_v2_review_enabled", False)
    _req, run, scope = _v1_world("9 barg")
    comparison.run_comparison(run, allowed_document_ids=scope)
    before = _everything(run)
    rule = _rule(value=8.0)
    called = []
    monkeypatch.setattr(
        rulebook_v2,
        "approved_rules",
        lambda *_a: called.append(1) or [rule],
        raising=False,
    )
    monkeypatch.setattr(
        rulebook_v2_review, "begin", lambda *_a: called.append(1), raising=True
    )
    conn = _conn()
    read = set()

    def spy(code, first, _second, _db, _trigger):
        if code == sqlite3.SQLITE_READ and first:
            read.add(first)
        return sqlite3.SQLITE_OK

    conn.set_authorizer(spy)
    try:
        comparison.run_comparison(run, allowed_document_ids=scope)
    finally:
        conn.set_authorizer(None)
    assert _everything(run) == before
    # the run's own record of which book it used is all it touches: no rule is read
    assert read and {t for t in read if t.startswith("rulebook_")} <= {
        "rulebook_run",
        "rulebook_snapshot",
        "rulebook_event",
    }
    assert not called
    assert "rulebook_v2" not in before[1]
    assert "rulebook_v2" not in coverage_pair.for_run(_conn(), run)
    assert "Rulebook version 2" not in coverage_pair.for_run(_conn(), run)["line"]


def test_the_two_switches_are_off_by_default():
    from app.config import Settings

    assert Settings.model_fields["rulebook_v2_review_enabled"].default is False


# ------------------------------------------------------------------------------------------------- the CRS


def _four_passes(monkeypatch, *rules, level=rule_trust.STANDARD):
    monkeypatch.setattr(rule_trust, "tier", lambda _r, **_k: (level, None))
    run, scope = _sheet(value="9 barg")
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET equipment_tag = 'TAG-1'")
    for n in (2, 3, 4):
        datasheets.create_fact(
            submittal_document_id=SHEET,
            chunk_id="fc",
            field_label=RUN_FACT_LABEL,
            raw_value="9 barg",
            page=1,
            equipment_tag=f"TAG-{n}",
        )
    _review(monkeypatch, run, scope, *rules)
    return run


def _view(run, copy, allowed=frozenset({"std-1", SHEET})):
    meta = {"copy": copy, "review_notes": [], "submittal": "s", "recommended_code": "x"}
    told = run_parts.crs_part(meta, _conn(), run, allowed)
    return told, crs_export.build_crs_view([], told)


def test_the_internal_copy_has_a_row_per_tag_and_the_note_has_the_line_and_labels(
    monkeypatch,
):
    run = _four_passes(monkeypatch, _rule())
    _told, view = _view(run, crs_export.COPY_INTERNAL)
    rows = [r for r in view["rows"] if r["row_kind"] == rulebook_v2_crs.ROW_KIND]
    assert len(rows) == 4
    assert {r["rule_trust"] for r in rows} == {
        "AI-built, quote-verified, owner-approved"
    }
    assert all("Meets, TAG-" in r["comment"] for r in rows)
    note = next(n for n in view["review_notes"] if n["note"] == rulebook_v2_crs.NOTE)
    assert "1 of 1 approved rules" in note["detail"]
    assert "AI-built, quote-verified, owner-approved" in note["detail"]


def test_the_issue_copy_rows_do_not_change(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    told, view = _view(run, crs_export.COPY_ISSUE)
    assert view["rows"] == []
    plain = crs_export.build_crs_view(
        [], {"copy": crs_export.COPY_ISSUE, "review_notes": []}
    )
    assert view["rows"] == plain["rows"]
    # the guard itself, whatever else would drop such a row
    confirmed = [{**r, "engineer_confirmed": True} for r in told["rulebook_v2_rows"]]
    again = crs_export.build_crs_view([], {**told, "rulebook_v2_rows": confirmed})
    assert again["rows"] == []


def test_a_breach_makes_no_second_row_and_an_open_tick_makes_no_second_row(monkeypatch):
    run = _four_passes(monkeypatch, _rule(value=8.0))
    assert _view(run, crs_export.COPY_INTERNAL)[0]["rulebook_v2_rows"] == []


def test_an_open_tick_makes_no_second_row(monkeypatch):
    run = _four_passes(monkeypatch, _rule(), level=rule_trust.SAFETY)
    told = _view(run, crs_export.COPY_INTERNAL)[0]
    assert told["rulebook_v2_rows"] == []


def test_a_rule_on_the_owners_note_carries_both_labels_and_the_reference_says_whose():
    words = rulebook_v2_crs.labels_of(
        {
            "trust_label": rule_trust.OWNER_NOTE_CONTEXT,
            "finding": "family by the owner-signed reference, not engineer-confirmed, version a",
        }
    )
    assert words == [
        "AI-built, quote-verified, owner-approved; owner note: context confirmed",
        "owner-signed reference, not engineer-confirmed",
    ]


def test_switch_off_the_crs_meta_is_what_it_was(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    monkeypatch.setattr(settings, "rulebook_v2_review_enabled", False)
    meta = {"copy": crs_export.COPY_INTERNAL, "review_notes": []}
    assert run_parts.crs_part(meta, _conn(), run, frozenset()) is meta


def test_a_reader_with_no_grant_on_the_standard_gets_no_row_and_no_quote(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    told, view = _view(run, crs_export.COPY_INTERNAL, frozenset({SHEET}))
    assert told["rulebook_v2_rows"] == []
    assert [r for r in view["rows"] if r["row_kind"] == rulebook_v2_crs.ROW_KIND] == []
    assert "shall not exceed" not in json.dumps(view, default=str)


def test_a_finding_names_its_standard_so_a_narrower_reader_is_not_shown_its_words(
    monkeypatch,
):
    run, scope = _sheet()
    rule = _rule()
    _review(monkeypatch, run, scope, rule)
    wide = review.list_findings(review_run_id=run, allowed_document_ids=scope)
    wide = [f for f in wide if f.get("origin") == ORIGIN]
    assert wide[0]["standard_document_id"] == "std-1" and wide[0]["standard_page"] == 3
    narrow = review.list_findings(
        review_run_id=run, allowed_document_ids=frozenset({SHEET})
    )
    narrow = [f for f in narrow if f.get("origin") == ORIGIN]
    assert narrow[0]["standard_withheld"] is True
    assert rule["quote"] not in json.dumps(narrow, default=str)


def test_the_internal_copys_audit_adds_up_with_the_rows_it_adds(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    told, _view_of = _view(run, crs_export.COPY_INTERNAL)
    assert len(told["rulebook_v2_rows"]) == 4
    said = review_audit_rows.crs_reconciliation([], told)
    assert said["audit_rows"] == said["exported_rows"] == 4 and said["adds_up"] is True


def _cells(data):
    book = openpyxl.load_workbook(io.BytesIO(data))
    return [
        str(c.value) for line in book.worksheets[0].iter_rows() for c in line if c.value
    ]


def test_the_short_note_is_on_both_copies(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    for copy in (crs_export.COPY_INTERNAL, crs_export.COPY_ISSUE):
        told, view = _view(run, copy)
        assert view["rulebook_v2_note"].startswith(
            "Rulebook version 2: 1 of 1 approved rules decided by code."
        )
        assert "Not yet confirmed by an engineer." in view["rulebook_v2_note"]
        assert "AI-built, quote-verified, owner-approved" in view["rulebook_v2_note"]
        assert RUN_FACT_LABEL not in view["rulebook_v2_note"]
        assert view["rulebook_v2_note"] in _cells(crs_export.build_crs([], told))


def test_the_note_leaves_rows_numbers_and_reply_import_alone(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    told = _view(run, crs_export.COPY_ISSUE)[0]
    assert told["rulebook_v2_note"]
    numbered = [
        {
            "comment": "An invented comment.",
            "engineer_confirmed": True,
            "crs_ref": "CRS-INVENTED-001",
            "document_name": "d",
            "page_section": "p",
            "comment_by": "b",
        }
    ]
    without = {k: v for k, v in told.items() if k != "rulebook_v2_note"}
    assert (
        crs_export.build_crs_view(numbered, told)["rows"]
        == crs_export.build_crs_view(numbered, without)["rows"]
    )
    replies = crs_reply.read_replies(crs_export.build_crs(numbered, told))
    assert replies == crs_reply.read_replies(crs_export.build_crs(numbered, without))
    assert [r["item"] for r in replies if r["item"].startswith("CRS-")] == [
        "CRS-INVENTED-001"
    ]


def test_not_yet_confirmed_prints_only_while_it_is_true(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    with db.connect() as conn:
        one = conn.execute(
            "SELECT id FROM review_findings WHERE origin = ? ORDER BY id LIMIT 1",
            (ORIGIN,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE review_findings SET confirmed_by = NULL WHERE origin = ?", (ORIGIN,)
        )
    assert (
        "Not yet confirmed"
        in _view(run, crs_export.COPY_INTERNAL)[1]["rulebook_v2_note"]
    )
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "UPDATE review_findings SET confirmed_by = 'x' WHERE id = ?", (one,)
        )
    partly, view = _view(run, crs_export.COPY_INTERNAL)
    assert "Not yet confirmed" in view["rulebook_v2_note"], "three of four still wait"
    assert sorted(r["engineer_confirmed"] for r in partly["rulebook_v2_rows"]) == [
        False,
        False,
        False,
        True,
    ]
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET confirmed_by = 'x' WHERE origin = ?", (ORIGIN,)
        )
    _done, view = _view(run, crs_export.COPY_INTERNAL)
    assert (
        view["rulebook_v2_note"]
        and "confirmed" not in view["rulebook_v2_note"].split(".")[-2]
    )
    assert "Not yet confirmed" not in view["rulebook_v2_note"]
    assert not [r for r in view["rows"] if "not confirmed" in r["comment_by"]]
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")


def test_the_preview_keeps_the_note(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    _told, view = _view(run, crs_export.COPY_ISSUE)
    assert view["rulebook_v2_note"]
    fields = schemas.CrsPreview.model_fields
    assert "rulebook_v2_note" in fields
    kept = {k: v for k, v in view.items() if k in fields}
    kept.setdefault("recommended_code_label", "x")
    assert (
        schemas.CrsPreview.model_validate(kept).rulebook_v2_note
        == view["rulebook_v2_note"]
    )


def test_no_decided_rule_no_note(monkeypatch):
    run, scope = _sheet()
    _review(
        monkeypatch,
        run,
        scope,
        _rule(field="Invented gadget thickness", unit="mm", value=2.0),
    )
    told = run_parts.crs_part(
        {"review_notes": []}, _conn(), run, frozenset({"std-1", SHEET})
    )
    assert told["rulebook_v2_note"] == ""


def test_a_reader_with_no_grant_gets_no_note(monkeypatch):
    run = _four_passes(monkeypatch, _rule())
    assert (
        _view(run, crs_export.COPY_ISSUE, frozenset({SHEET}))[0]["rulebook_v2_note"]
        == ""
    )


def test_switch_off_no_note():
    assert crs_export.build_crs_view([], {"review_notes": []})["rulebook_v2_note"] == ""
