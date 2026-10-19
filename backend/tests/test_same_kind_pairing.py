"""Order 139 fix 2: a requirement pairs only with a datasheet value of the SAME
QUANTITY KIND (`match_rules` rule 6 and `comparison._hold_unsure_kind`).

Found on a real pump review: a blank field printing "m3/h" was paired with
bearing-temperature and vibration clauses, a pump efficiency with weld joint
efficiency rules, and the process pumping temperature with a flush-liquid
temperature limit. Two different kinds are never paired; a kind that cannot be
shown the same is "engineer to check" (NEEDS_ENGINEER_REVIEW with the code
`quantity_kind_unsure`) - never Compliant, Non-compliant or the contractor's
blank. Made-up sample text and values only.
"""

from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, match_rules, standards, submittal_review
from app.config import settings

NOW = "2026-10-19T00:00:00Z"
STD, SUB = "std-kind", "sub-kind"
UNSURE = match_rules.QUANTITY_KIND_UNSURE


def _req(subject, value="85", unit="C", kind="numeric_limit", operator="<=", text=None):
    return {
        "id": "r",
        "requirement_type": kind,
        "subject": subject,
        "operator": operator,
        "raw_value": value,
        "raw_unit": unit,
        "unit": unit,
        "requirement_text": text
        or f"The {subject} shall not exceed {value} {unit or ''}.",
    }


def _fact(name, value=None, unit=None, *, printed=None, blank=False):
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name.upper(),
        "field_value": printed if printed is not None else f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "unit": unit,
        "is_blank": 1 if blank else 0,
    }


# ------------------------------------------------- the unit a blank prints
@pytest.mark.parametrize(
    "printed, unit",
    [
        ("_______________ m3/h", "m3/h"),
        ("________*_________ (%)", "%"),
        ("_________ bar g @ ________ C", "bar g"),  # the quantity, not its condition
        ("___*___", None),
        ("______/________", None),
    ],
)
def test_a_blank_cell_states_the_unit_it_prints(printed, unit):
    assert match_rules.printed_unit(_fact("x", printed=printed, blank=True)) == unit


# ------------------------------------------------- different kinds: refused
def test_a_flow_blank_never_pairs_with_a_bearing_temperature_limit():
    match = comparison.match_by_containment(
        _req("the bearing temperature"),
        [_fact("bearing", printed="_______ m3/h", blank=True)],
    )
    assert match["fact"] is None
    assert match["reason"] == comparison.REFUSED_BY_RULE
    assert [r["reason"] for r in match["refused"]] == [match_rules.QUANTITY_KIND]


def test_a_flow_never_pairs_with_a_vibration_clause_whose_unit_was_lost():
    """The clause's unit was not parsed (no unit column), so rule 1 has no
    opinion: the quantity it names - vibration - is what tells."""
    vibration = _req("the bearing vibration", value="4.5", unit=None)
    blank = comparison.match_by_containment(
        vibration, [_fact("bearing", printed="_______ m3/h", blank=True)]
    )
    assert (
        blank["fact"] is None
        and blank["refused"][0]["reason"] == match_rules.QUANTITY_KIND
    )
    filled = comparison.match_by_containment(
        vibration, [_fact("bearing", "120", "m3/h")]
    )
    assert (
        filled["fact"] is None
        and filled["refused"][0]["reason"] == match_rules.QUANTITY_KIND
    )


def test_a_statement_about_a_temperature_never_pairs_with_a_flow():
    statement = _req(
        "the bearing temperature",
        value=None,
        unit=None,
        kind="statement",
        text="The bearing temperature shall be monitored.",
    )
    match = comparison.match_by_containment(
        statement, [_fact("bearing", "120", "m3/h")]
    )
    assert match["fact"] is None
    assert [r["reason"] for r in match["refused"]] == [match_rules.QUANTITY_KIND]


def test_every_pairing_method_meets_rule_6():
    """The ONE gate: `match_rules.refusal`, which the containment, statement,
    field-name, AI-matcher and question paths all ask."""
    assert (
        match_rules.refusal(
            _req("the bearing temperature"),
            _fact("bearing", printed="___ m3/h", blank=True),
            sheet=None,
        )
        == match_rules.QUANTITY_KIND
    )
    names = {"requirements": {"r": "bearing"}, "facts": {"f-bearing": "bearing"}}
    assert (
        comparison.match_by_field_name(
            _req("the bearing temperature"),
            [_fact("bearing", printed="___ m3/h", blank=True)],
            names,
        )
        is None
    )


# ------------------------------------------------- same kind, unsure: held
def test_pump_efficiency_is_not_weld_joint_efficiency():
    fact = _fact("efficiency", "82", "%")
    assert (
        match_rules.quantity_kind_doubt(
            _req("the weld joint efficiency", "85", "%"), fact
        )
        == UNSURE
    )
    assert (
        match_rules.quantity_kind_doubt(
            _req("the ligament efficiency", "80", "%"), fact
        )
        == UNSURE
    )
    assert (
        match_rules.quantity_kind_doubt(
            _req("the efficiency of the ligaments", "80", "%"), fact
        )
        == UNSURE
    )
    # the pump's own efficiency is the same quantity
    assert (
        match_rules.quantity_kind_doubt(_req("the pump efficiency", "70", "%"), fact)
        is None
    )
    assert (
        match_rules.quantity_kind_doubt(_req("the minimum efficiency", "70", "%"), fact)
        is None
    )


def test_process_temperature_is_not_flush_liquid_temperature():
    pumping = _fact("pumping temperature", "76.7", "°C")
    assert (
        match_rules.quantity_kind_doubt(
            _req("flushing liquid temperature", "60"), pumping
        )
        == UNSURE
    )
    assert (
        match_rules.quantity_kind_doubt(
            _req("sump oil temperature rise", "35"), pumping
        )
        == UNSURE
    )
    assert (
        match_rules.quantity_kind_doubt(
            _req("the maximum pumping temperature", "120"), pumping
        )
        is None
    )


def test_a_field_that_only_modifies_the_subject_is_unsure():
    flow = _fact("bearing", "120", "m3/h")
    assert (
        match_rules.quantity_kind_doubt(
            _req("the bearing blocks", None, None, kind="statement"), flow
        )
        == UNSURE
    )
    nameless = _fact("bearing", printed="____", blank=True)
    assert (
        match_rules.quantity_kind_doubt(_req("the bearing temperature"), nameless)
        == UNSURE
    )
    # two categorical words: not this rule's question
    assert (
        match_rules.quantity_kind_doubt(
            _req("spot radiography", None, None, kind="statement"),
            _fact("radiography", printed="YES"),
        )
        is None
    )


# ------------------------------------------------------------ end to end
@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "kind.sqlite")
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        for doc_id, role in ((STD, "COMPANY_STANDARD"), (SUB, "CONTRACTOR_SUBMITTAL")):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,"
                "document_role) VALUES (?,?,?)",
                (doc_id, "test", role),
            )
        for chunk_id, doc_id in (("sc", STD), ("fc", SUB)):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                "section,kind,text,token_count,content_hash,retrievable) VALUES "
                "(?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
                (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"),
            )
    yield
    db.reset_connection()


def _review(text, structured, facts):
    """One requirement, the given datasheet rows, one run. The finding."""
    req = standards.create_requirement(
        standard_document_id=STD,
        chunk_id="sc",
        requirement_text=text,
        source_text=text,
        clause="4.1",
        page=1,
        structured=structured,
    )
    stored = [
        datasheets.create_fact(
            submittal_document_id=SUB,
            chunk_id="fc",
            field_label=label,
            raw_value=raw,
            page=1,
            blank=blank,
        )
        for label, raw, blank in facts
    ]
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)",
            (run_id, SUB, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_reason,selection_method,included,"
            "created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run_id, STD, NOW),
        )
    findings = [
        f
        for f in comparison.run_comparison(
            run_id, allowed_document_ids=frozenset({STD, SUB})
        )["findings"]
        if f.get("requirement_id") == req["id"]
    ]
    assert len(findings) == 1, findings
    return req, stored, findings[0]


def _limit(subject, value, unit, operator="<="):
    return {
        "subject": subject,
        "operator": operator,
        "raw_value": value,
        "raw_unit": unit,
        "requirement_type": "numeric_limit",
    }


def _assert_engineer_to_check(found, fact):
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert found["reason_code"] == UNSURE
    assert found["fact_id"] == fact["id"]  # the suggested field stays visible
    rationale = found["ai_rationale"]
    assert rationale.startswith(f"{UNSURE}:")
    for verdict_words in (
        "COMPLIANT",
        "outside the required",
        "within the required",
        "leaves this field to be provided",
    ):
        assert verdict_words not in rationale


def test_weld_joint_efficiency_against_a_pump_efficiency_is_engineer_to_check(world):
    _req_row, [fact], found = _review(
        "The weld joint efficiency shall be not less than 85 %.",
        _limit("the weld joint efficiency", "85", "%", ">="),
        [("Efficiency", "82 %", None)],
    )
    _assert_engineer_to_check(found, fact)


def test_a_blank_pump_efficiency_is_not_the_contractors_omission_of_a_weld_value(world):
    _req_row, [fact], found = _review(
        "The weld joint efficiency shall be established by the examination.",
        {"subject": "The weld joint efficiency", "requirement_type": "statement"},
        [("Efficiency", "______ (%)", (True, "______"))],
    )
    _assert_engineer_to_check(found, fact)


def test_process_temperature_against_a_flush_liquid_limit_is_engineer_to_check(world):
    _req_row, [fact], found = _review(
        "The flushing liquid temperature shall not exceed 60 °C.",
        _limit("the flushing liquid temperature", "60", "°C"),
        [("Temperature", "76.7 °C", None)],
    )
    _assert_engineer_to_check(found, fact)


def test_the_ai_matchers_pair_meets_the_same_gate(world, monkeypatch):
    """The AI matcher proposed the process pumping temperature for a
    flush-liquid limit: held with the plain reason, the arithmetic not shown."""
    monkeypatch.setattr(settings, "match_enabled", True)
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)

    def proposed(requirement, facts, **_kw):
        [fact] = [f for f in facts if f["field_name"] == "pumping temperature"]
        return {
            "fact": fact,
            "matched_phrase": fact["field_name"],
            "method": comparison.METHOD_MODEL_CHOICE,
            "reason": "same temperature",
            "candidates": [],
        }

    monkeypatch.setattr(comparison, "match_by_model", proposed)
    _req_row, [fact], found = _review(
        "The flushing liquid temperature shall not exceed 60 °C.",
        _limit("flushing liquid temperature", "60", "°C"),
        [("Pumping temperature", "76.7 °C", None)],
    )
    assert found["match_method"] == comparison.METHOD_MODEL_CHOICE
    _assert_engineer_to_check(found, fact)


def test_a_flow_blank_is_not_paired_with_a_bearing_temperature_limit(world):
    _req_row, [_fact_row], found = _review(
        "The bearing temperature shall not exceed 85 °C.",
        _limit("the bearing temperature", "85", "°C"),
        [("Bearing", "_______ m3/h", (True, "______"))],
    )
    assert found["fact_id"] is None
    assert found["compliance_status"] not in (
        comparison.COMPLIANT,
        comparison.NON_COMPLIANT,
        comparison.MISSING_INFORMATION,
    )


# ------------------------------------------- the same kind still decides
@pytest.mark.parametrize(
    "value, status", [("120", comparison.COMPLIANT), ("60", comparison.NON_COMPLIANT)]
)
def test_a_same_kind_pair_still_pairs_and_decides(world, value, status):
    _req_row, [fact], found = _review(
        f"The maximum pumping temperature shall not exceed {value} °C.",
        _limit("the maximum pumping temperature", value, "°C"),
        [("Pumping temperature", "76.7 °C", None)],
    )
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == status
    assert found["reason_code"] is None


def test_a_same_kind_blank_is_still_the_contractors_to_provide(world):
    _req_row, [fact], found = _review(
        "The bearing temperature shall not exceed 85 °C.",
        _limit("the bearing temperature", "85", "°C"),
        [("Bearing temperature", "______ °C", (True, "______"))],
    )
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.MISSING_INFORMATION


# ------------------------- a noun naming several kinds never refuses one of them
def test_vibration_is_a_velocity_or_a_displacement():
    """A vibration limit in um against a field "Vibration" that prints no unit
    (or a lost-unit clause against a field in um) is one quantity; a noun
    alone never refuses a unit that gives one of its kinds. Against a flow it
    is still refused."""
    in_um = _req("the maximum vibration", "50", "µm")
    blank = _fact("vibration", printed="____", blank=True)
    assert match_rules.refusal(in_um, blank, sheet=None) is None
    lost = _req("the maximum vibration", "50", None)
    assert match_rules.refusal(lost, _fact("vibration", "30", "µm"), sheet=None) is None
    assert (
        match_rules.refusal(lost, _fact("vibration", "2.5", "mm/s"), sheet=None) is None
    )
    assert (
        match_rules.refusal(lost, _fact("vibration", "120", "m3/h"), sheet=None)
        == match_rules.QUANTITY_KIND
    )


def test_flow_is_a_volume_or_a_mass_per_time():
    blank = _fact("flow", printed="____", blank=True)
    assert (
        match_rules.refusal(_req("the minimum flow", "500", "kg/h"), blank, sheet=None)
        is None
    )
    assert (
        match_rules.refusal(_req("the minimum flow", "5", "m3/h"), blank, sheet=None)
        is None
    )
    assert (
        match_rules.refusal(_req("the minimum flow", "5", "°C"), blank, sheet=None)
        == match_rules.QUANTITY_KIND
    )


def test_a_percentage_never_refuses_a_kind_named_only_by_a_noun():
    """'3 % of the impeller diameter' is relative to any quantity."""
    blank = _fact("clearance", printed="____", blank=True)
    assert (
        match_rules.refusal(_req("the minimum clearance", "3", "%"), blank, sheet=None)
        is None
    )
    # two units still decide: a percentage is not a flow in m3/h (rule 1)
    filled = _fact("clearance", "5", "m3/h")
    assert match_rules.refusal(
        _req("the minimum clearance", "3", "%"), filled, sheet=None
    )


def test_a_vibration_limit_in_um_pairs_and_decides_against_a_blank(world):
    _req_row, [fact], found = _review(
        "The maximum vibration shall not exceed 50 µm.",
        _limit("the maximum vibration", "50", "µm"),
        [("Vibration", "______", (True, "______"))],
    )
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
