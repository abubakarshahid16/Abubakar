"""Order 262.1: which field of an equipment type's form each numeric rule limits. Invented text only;
the model is a fake that answers a number of the type's own form."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import (
    comparison,
    db,
    field_naming,
    field_vocabulary,
    rule_roles,
    submittal_review,
)
from app.config import settings
from app.reasoning_provider import Response
from tests.test_field_naming import _world

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import propose_rule_roles

PUMP = "Centrifugal Pump"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "roles.sqlite")
    monkeypatch.setattr(rule_roles, "DIR", tmp_path / "rule_roles")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


class Fake:
    """Answers each item with the number, in `dictionary`, of `name_for(text)`, quoting `quote_for(text)`."""

    name = "ollama"

    def __init__(self, dictionary, name_for, quote_for):
        self.dictionary, self.name_for, self.quote_for = dictionary, name_for, quote_for
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        out = []
        for item in json.loads(packet.prompt)["items"]:
            name = self.name_for(item["text"])
            out.append(
                {
                    "i": item["i"],
                    "field": self.dictionary.index(name) if name else None,
                    "quote": self.quote_for(item["text"]) if name else "",
                }
            )
        return Response(
            text=json.dumps({"names": out}),
            provider="ollama",
            model_tag="fake:1",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


def rule(i, text, value, unit, clause="6.1"):
    return {
        "id": f"r{i}",
        "standard_document_id": "std-1",
        "clause": clause,
        "requirement_type": "numeric_limit",
        "raw_value": value,
        "raw_unit": unit,
        "requirement_text": text,
    }


def test_the_dictionary_is_the_forms_own_numeric_fields_with_a_checkable_unit():
    dictionary, roles, families = rule_roles.form(PUMP)
    assert dictionary == sorted(dictionary)
    for name in (
        "rated flow",
        "design pressure",
        "design temperature",
        "rated speed",
        "npsh required",
    ):
        assert name in dictionary, name
    for text_field in ("casing material", "seal plan", "bearing type"):
        assert text_field not in dictionary
    assert roles["rated speed"] == "rated_speed" and families["rated speed"] == (
        "rotation",
    )
    assert families["design pressure"] == ("pressure",)
    # another type has another list: a vessel has a test pressure and no rated flow
    vessel, _r, _f = rule_roles.form("Pressure Vessel")
    assert "test pressure" in vessel and "rated flow" not in vessel


def _propose(
    rules, name_for=lambda t: "design pressure", quote_for=lambda t: "design pressure"
):
    dictionary, _r, _f = rule_roles.form(PUMP)
    fake = Fake(dictionary, name_for, quote_for)
    return rule_roles.propose(rules, PUMP, fake), fake


def test_a_rule_whose_number_limits_the_named_field_is_mapped_and_a_wrong_one_is_not():
    rules = [
        rule(1, "The design pressure shall not exceed 25 bar.", "25", "bar"),
        rule(
            2,
            "The design pressure shall be held for at least 30 minutes.",
            "30",
            "minutes",
        ),
        rule(3, "The design pressure shall be 1.5 times the rated value.", "1.5", None),
    ]
    got, _fake = _propose(rules)
    assert got["r1"]["field_name"] == "design pressure"
    assert got["r2"]["field_name"] is None and got["r3"]["field_name"] is None


def test_the_unit_check_comes_from_the_fields_own_kind():
    rules = [rule(1, "The rated speed shall not exceed 3600 rpm.", "3600", "rpm")]
    got, _ = _propose(rules, lambda t: "rated speed", lambda t: "rated speed")
    assert got["r1"]["field_name"] == "rated speed"
    wrong = [rule(2, "The rated speed shall not exceed 3600 bar.", "3600", "bar")]
    got, _ = _propose(wrong, lambda t: "rated speed", lambda t: "rated speed")
    assert got["r2"]["field_name"] is None


def test_the_kept_file_is_a_draft_with_no_document_text(tmp_path):
    text = "The design pressure shall not exceed 25 bar."
    rules = [rule(1, text, "25", "bar", clause="6.4.2")]
    _propose(rules)
    kept = rule_roles.entries(rules, PUMP, lambda doc: "SAES-X-001")
    assert kept == [
        {
            "standard": "SAES-X-001",
            "clause": "6.4.2",
            "text_sha256": rule_roles.text_hash(text),
            "field": "design_pressure",
        }
    ]
    path = rule_roles.export(PUMP, kept, tmp_path / "pump.json")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["status"] == "draft" and body["equipment_type"] == PUMP
    raw = path.read_text(encoding="utf-8").lower()
    for word in ("shall not exceed", "design pressure shall", "25 bar"):
        assert word not in raw


def _reviewed(tmp_path, text="The design pressure shall not exceed 25 bar."):
    rules = [rule(1, text, "25", "bar")]
    _propose(rules)
    kept = rule_roles.entries(rules, PUMP, lambda doc: "SAES-X-001")
    return rules, [rule_roles.export(PUMP, kept, tmp_path / "pump.json")]


def test_a_reviewed_mapping_is_used_only_while_the_rule_text_and_unit_still_fit(
    tmp_path,
):
    rules, files = _reviewed(tmp_path)
    assert rule_roles.reviewed_names(rules, PUMP, files) == {"r1": "design pressure"}
    edited = [
        {**rules[0], "requirement_text": "The design pressure shall not exceed 30 bar."}
    ]
    assert rule_roles.reviewed_names(edited, PUMP, files) == {}
    other_unit = [{**rules[0], "raw_unit": "minutes"}]
    assert rule_roles.reviewed_names(other_unit, PUMP, files) == {}
    not_numeric = [{**rules[0], "requirement_type": "statement"}]
    assert rule_roles.reviewed_names(not_numeric, PUMP, files) == {}


def test_a_review_reads_the_reviewed_file_without_a_model_call(tmp_path, monkeypatch):
    rules, _files = _reviewed(
        tmp_path
    )  # export wrote into rule_roles.DIR? no: into tmp_path
    rule_roles.export(PUMP, rule_roles.entries(rules, PUMP, lambda d: "SAES-X-001"))
    monkeypatch.setattr(
        field_naming, "ensure_names", lambda *_a, **_k: pytest.fail("a model was asked")
    )
    out = field_vocabulary.names_for(rules, [], {"equipment_type": PUMP})
    assert out["requirements"] == {"r1": "design pressure"}
    assert "reviewed draft" in out["source"]


def test_a_reviewed_name_pairs_through_the_run_and_never_carries_a_verdict(monkeypatch):
    _req, fact, run, scope = _world("Design pressure", "12 bar")
    text = "The maximum allowable working pressure shall be 10 bar."
    entry = {
        "standard": "std-1",
        "clause": "6.4.1",
        "text_sha256": rule_roles.text_hash(text),
        "field": "design_pressure",
    }
    rule_roles.export(PUMP, [entry])
    monkeypatch.setattr(settings, "field_naming_enabled", True)
    monkeypatch.setattr(
        field_naming, "ensure_names", lambda *_a, **_k: pytest.fail("a model was asked")
    )

    def classify(equipment_type):
        with db.connect() as conn:
            conn.execute(
                "UPDATE document_classification SET equipment_type = ? WHERE document_id = 'sub-1'",
                (equipment_type,),
            )

    classify("Pressure Vessel")  # a pump file is not applied to a vessel review
    other = comparison.run_comparison(run, allowed_document_ids=scope)["findings"][0]
    assert other.get("match_method") != comparison.METHOD_FIELD_NAME
    classify(PUMP)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    found = result["findings"][0]
    assert found["match_method"] == comparison.METHOD_FIELD_NAME
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_the_script_proposes_for_chosen_standards_and_reports_counts_only(tmp_path):
    _world("Design pressure", "12 bar")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_number = 'SAES-X-001' WHERE document_id = 'std-1'"
        )
    from app import standards

    text = "The design pressure shall not exceed 25 bar."
    standards.create_requirement(
        standard_document_id="std-1",
        chunk_id="sc",
        requirement_text=text,
        source_text=text,
        clause="6.4.2",
        page=1,
        structured={
            "subject": "the design pressure",
            "operator": "<=",
            "raw_value": "25",
            "raw_unit": "bar",
            "requirement_type": "numeric_limit",
        },
    )
    dictionary, _r, _f = rule_roles.form(PUMP)
    fake = Fake(
        dictionary,
        lambda t: "design pressure" if "design pressure" in t else None,
        lambda t: "design pressure",
    )
    out_file = tmp_path / "out.json"
    # the invented world's first rule is about a working pressure: not a pump form field, so unmapped
    out = propose_rule_roles.run(
        tmp_path / "roles.sqlite",
        PUMP,
        ["SAES-X-001"],
        provider=fake,
        out_file=out_file,
    )
    assert out["standards_found"] == 1 and out["numeric_rules"] == 2
    assert out["mapped_numeric"] == 1 and out["mapped_statements"] == 0
    entries = json.loads(out_file.read_text(encoding="utf-8"))["entries"]
    assert [(e["standard"], e["clause"], e["field"]) for e in entries] == [
        ("SAES-X-001", "6.4.2", "design_pressure")
    ]
    none = propose_rule_roles.run(
        tmp_path / "roles.sqlite",
        PUMP,
        ["SAES-Z-999"],
        provider=fake,
        out_file=out_file,
    )
    assert none["standards_found"] == 0 and none["numeric_rules"] == 0
    assert "design pressure" not in json.dumps(out)


def test_a_pump_mapping_never_applies_on_another_type_or_an_unknown_one(tmp_path):
    # cloud-3 on #1397 / order 263.2: entries are keyed by (equipment type, text hash)
    rules, files = _reviewed(tmp_path)
    assert rule_roles.reviewed_names(rules, PUMP, files) == {"r1": "design pressure"}
    assert rule_roles.reviewed_names(rules, "Pressure Vessel", files) == {}
    assert rule_roles.reviewed_names(rules, "Heat Exchanger", files) == {}
    assert rule_roles.reviewed_names(rules, None, files) == {}
    assert rule_roles.reviewed_names(rules, "", files) == {}
    assert rule_roles.reviewed_names(rules, "Some Unlisted Machine", files) == {}
    # the engine's own spelling of the same type still matches
    assert rule_roles.reviewed_names(rules, "centrifugal pump", files) == {
        "r1": "design pressure"
    }


def test_a_review_of_another_type_reads_no_pump_file(tmp_path, monkeypatch):
    rules, _files = _reviewed(tmp_path)
    rule_roles.export(PUMP, rule_roles.entries(rules, PUMP, lambda d: "SAES-X-001"))
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    assert (
        field_vocabulary.names_for(rules, [], {"equipment_type": "Pressure Vessel"})[
            "requirements"
        ]
        == {}
    )
    assert field_vocabulary.names_for(rules, [], {"equipment_type": PUMP})[
        "requirements"
    ] == {"r1": "design pressure"}
