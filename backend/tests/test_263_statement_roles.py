"""Order 263.1: a statement rule limits a TEXT field of the form to a required value. Invented text only;
the model is a fake that answers a number of the type's own text fields and two quotes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import (
    db,
    field_naming,
    rule_roles,
    statement_roles,
    submittal_review,
)
from app.config import settings
from app.reasoning_provider import Response

PUMP = "Centrifugal Pump"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "stmt.sqlite")
    monkeypatch.setattr(rule_roles, "DIR", tmp_path / "rule_roles")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


class Fake:
    """Answers each sentence with `answer_for(text)` = (field name, field quote, value) or None."""

    name = "ollama"

    def __init__(self, answer_for):
        self.answer_for = answer_for
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        dictionary, _ = statement_roles.form(PUMP)
        out = []
        for item in json.loads(packet.prompt)["items"]:
            got = self.answer_for(item["text"])
            out.append(
                {
                    "i": item["i"],
                    "field": dictionary.index(got[0]) if got else None,
                    "field_quote": got[1] if got else "",
                    "value": got[2] if got else "",
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


def stmt(i, text, clause="6.1"):
    return {
        "id": f"s{i}",
        "standard_document_id": "std-1",
        "clause": clause,
        "requirement_type": "statement",
        "requirement_text": text,
    }


def ask(rules, answer):
    return statement_roles.propose(rules, PUMP, Fake(answer))


MAT = ("casing material", "casing material", "duplex stainless steel")


def test_the_dictionary_is_the_forms_text_fields():
    dictionary, roles = statement_roles.form(PUMP)
    for name in ("casing material", "mechanical seal", "bearing type"):
        assert name in dictionary
    assert "rated flow" not in dictionary  # a numeric field
    assert roles["mechanical seal"] == "seal_type"


@pytest.mark.parametrize(
    "text",
    [
        "The casing material shall be duplex stainless steel.",
        "Each pump casing material shall be duplex stainless steel.",
        "The casing material of the pump shall be duplex stainless steel.",
    ],
)
def test_a_plain_shall_be_sentence_maps_to_its_field_and_value(text):
    got = ask([stmt(1, text)], lambda t: MAT)
    assert got["s1"]["field_name"] == "casing material"
    assert json.loads(got["s1"]["quote"]) == {
        "f": "casing material",
        "v": "duplex stainless steel",
    }


@pytest.mark.parametrize(
    "text",
    [
        # negation, exception, condition, alternative, permission: the engineer's
        "The casing material shall not be duplex stainless steel.",
        "Except for sour service, the casing material shall be duplex stainless steel.",
        "Where the fluid is corrosive the casing material shall be duplex stainless steel.",
        "The casing material shall be duplex stainless steel or carbon steel.",
        "The casing material may be duplex stainless steel.",
        "Only the casing material shall be duplex stainless steel.",
        # a condition written BEFORE a colon or a semicolon is still the rule's condition (cloud)
        "When used in sour service: the casing material shall be duplex stainless steel.",
        "Unless the purchaser approves otherwise; the casing material shall be duplex stainless steel.",
        "If the fluid is sour, the casing material shall be duplex stainless steel.",
        # conditions with no cue word at all (cloud-3): refused by the SHAPE, not by a longer list
        "For sour service the casing material shall be duplex stainless steel.",
        "In pumps above 100 kW the casing material shall be duplex stainless steel.",
        "For vertical pumps the casing material shall be duplex stainless steel.",
        "The casing material shall be duplex stainless steel for pumps handling amine.",
        "The casing material shall be duplex stainless steel for all services.",
        "At the purchaser's option the casing material shall be duplex stainless steel.",
        "The casing material shall be selected by the vendor.",
        "Duplex stainless steel is what the casing material shall be.",
    ],
)
def test_a_negative_conditional_or_alternative_sentence_is_never_mapped(text):
    got = ask([stmt(1, text)], lambda t: MAT)
    assert got["s1"]["field_name"] is None


def test_a_value_or_field_not_in_the_sentence_is_refused():
    text = "The casing material shall be duplex stainless steel."
    for answer in (
        ("casing material", "casing material", "bronze"),  # value not in the sentence
        (
            "casing material",
            "shaft material",
            "duplex stainless steel",
        ),  # field quote not there
        (
            "shaft material",
            "casing material",
            "duplex stainless steel",
        ),  # quote names another field
        (
            "casing material",
            "casing material",
            "casing material",
        ),  # the value is the field's name
        ("casing material", "casing material", "the"),  # only neutral words
        (
            "casing material",
            "casing material",
            "a b c d e f g h",
        ),  # too long, not in the text
    ):
        got = ask([stmt(1, text)], lambda t, a=answer: a)
        assert got["s1"]["field_name"] is None, answer
        db.connect().execute("DELETE FROM canonical_field_names")


def test_the_kept_file_holds_hashes_and_no_document_text(tmp_path):
    text = "The casing material shall be duplex stainless steel."
    rules = [stmt(1, text, clause="6.4.2")]
    ask(rules, lambda t: MAT)
    kept = statement_roles.entries(rules, PUMP, lambda doc: "SAES-X-001")
    assert len(kept) == 1
    entry = kept[0]
    assert entry["kind"] == "statement" and entry["field"] == "casing_material"
    assert entry["expected_words"] == 3 and entry[
        "text_sha256"
    ] == rule_roles.text_hash(text)
    path = rule_roles.export(PUMP, kept, tmp_path / "pump.json")
    raw = path.read_text(encoding="utf-8").lower()
    for word in ("duplex", "stainless", "shall be"):
        assert word not in raw


def _reviewed(tmp_path, text="The casing material shall be duplex stainless steel."):
    rules = [stmt(1, text)]
    ask(rules, lambda t: MAT)
    kept = statement_roles.entries(rules, PUMP, lambda doc: "SAES-X-001")
    return rules, [rule_roles.export(PUMP, kept, tmp_path / "pump.json")]


def test_a_reviewed_statement_is_used_only_on_its_type_and_while_the_text_holds_the_value(
    tmp_path,
):
    rules, files = _reviewed(tmp_path)
    got = statement_roles.reviewed(rules, PUMP, files)
    assert got == {
        "s1": {
            "role": "casing_material",
            "name": "casing material",
            "expected": "duplex stainless steel",
        }
    }
    assert statement_roles.reviewed(rules, "Pressure Vessel", files) == {}
    assert statement_roles.reviewed(rules, None, files) == {}
    edited = [{**rules[0], "requirement_text": "The casing material shall be bronze."}]
    assert statement_roles.reviewed(edited, PUMP, files) == {}
    not_a_statement = [{**rules[0], "requirement_type": "numeric_limit"}]
    assert statement_roles.reviewed(not_a_statement, PUMP, files) == {}


def test_a_numeric_review_ignores_statement_entries(tmp_path):
    rules, files = _reviewed(tmp_path)
    numeric = [
        {
            **rules[0],
            "requirement_type": "numeric_limit",
            "raw_value": "10",
            "raw_unit": "bar",
        }
    ]
    assert rule_roles.reviewed_names(numeric, PUMP, files) == {}


@pytest.mark.parametrize(
    ("sheet", "expected"),
    [
        ("Duplex stainless steel, ASTM A890", True),
        ("DUPLEX STAINLESS STEEL", True),
        ("Carbon steel", False),
        ("stainless steel", False),
        ("not duplex stainless steel", False),
        ("Non duplex stainless steel", False),
        ("", False),
        (None, False),
    ],
)
def test_the_sheet_value_agrees_only_when_it_holds_the_whole_phrase(sheet, expected):
    assert statement_roles.value_agrees(sheet, "duplex stainless steel") is expected


def test_the_answer_is_stored_once_and_a_reply_that_cannot_be_read_is_asked_again():
    rules = [stmt(1, "The casing material shall be duplex stainless steel.")]
    fake = Fake(lambda t: MAT)
    statement_roles.propose(rules, PUMP, fake)
    statement_roles.propose(rules, PUMP, fake)
    assert len(fake.packets) == 1

    class Unreadable(Fake):
        def reason(self, packet):
            return Response(
                text="{",
                provider="ollama",
                model_tag="fake:1",
                digest="d",
                finish_reason="length",
                prompt_sha256=packet.sha256,
            )

    db.connect().execute("DELETE FROM canonical_field_names")
    stats = {}
    got = statement_roles.propose(rules, PUMP, Unreadable(lambda t: MAT), stats)
    assert got == {} and stats["unreadable"] == 1
    assert (
        field_naming.stored_names(
            statement_roles.KIND, ["s1"], statement_roles.form(PUMP)[0]
        )
        == {}
    )


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import propose_rule_roles  # noqa: E402


def test_the_script_maps_numeric_and_statement_rules_in_one_file_and_counts_only(
    tmp_path,
):
    from app import standards
    from tests.test_field_naming import _world

    _world("Casing material", "Duplex stainless steel")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_number = 'SAES-X-001' WHERE document_id = 'std-1'"
        )
    for text, kind, structured in (
        (
            "The casing material shall be duplex stainless steel.",
            "statement",
            {"subject": "the casing material", "requirement_type": "statement"},
        ),
        (
            "The design pressure shall not exceed 25 bar.",
            "numeric_limit",
            {
                "subject": "the design pressure",
                "operator": "<=",
                "raw_value": "25",
                "raw_unit": "bar",
                "requirement_type": "numeric_limit",
            },
        ),
    ):
        standards.create_requirement(
            standard_document_id="std-1",
            chunk_id="sc",
            requirement_text=text,
            source_text=text,
            clause="6.4.2",
            page=1,
            structured=structured,
        )

    class Both:
        name = "ollama"

        def reason(self, packet):
            kind = json.loads(packet.prompt)["kind"]
            numeric, _r, _f = rule_roles.form(PUMP)
            text_fields, _ = statement_roles.form(PUMP)
            out = []
            for item in json.loads(packet.prompt)["items"]:
                if kind == statement_roles.KIND and "casing material" in item["text"]:
                    out.append(
                        {
                            "i": item["i"],
                            "field": text_fields.index("casing material"),
                            "field_quote": "casing material",
                            "value": "duplex stainless steel",
                        }
                    )
                elif (
                    kind == field_naming.REQUIREMENT
                    and "design pressure" in item["text"]
                ):
                    out.append(
                        {
                            "i": item["i"],
                            "field": numeric.index("design pressure"),
                            "quote": "design pressure",
                        }
                    )
                else:
                    out.append(
                        {
                            "i": item["i"],
                            "field": None,
                            "quote": "",
                            "field_quote": "",
                            "value": "",
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

    out_file = tmp_path / "out.json"
    out = propose_rule_roles.run(
        tmp_path / "stmt.sqlite",
        PUMP,
        ["SAES-X-001"],
        provider=Both(),
        out_file=out_file,
    )
    assert (
        out["numeric_rules"] == 2 and out["statement_rules"] == 1
    )  # the world's own rule + mine
    assert out["mapped_numeric"] == 1 and out["mapped_statements"] == 1
    entries = json.loads(out_file.read_text(encoding="utf-8"))["entries"]
    assert sorted((e.get("kind") or "numeric", e["field"]) for e in entries) == [
        ("numeric", "design_pressure"),
        ("statement", "casing_material"),
    ]
    assert "duplex" not in out_file.read_text(encoding="utf-8").lower()
    assert "duplex" not in json.dumps(out)


def _statement_world(sheet_value):
    """One standard with a statement rule, one pump submittal with a casing-material fact, one run."""
    from app import standards
    from tests.test_field_naming import _world

    text = "The casing material shall be duplex stainless steel."
    _req, fact, run, scope = _world("Casing material", sheet_value)
    rule = standards.create_requirement(
        standard_document_id="std-1",
        chunk_id="sc",
        requirement_text=text,
        source_text=text,
        clause="6.4.2",
        page=1,
        structured={"subject": "the casing material", "requirement_type": "statement"},
    )
    entry = {
        "kind": "statement",
        "standard": "SAES-X-001",
        "clause": "6.4.2",
        "text_sha256": rule_roles.text_hash(text),
        "field": "casing_material",
        "expected_sha256": statement_roles._phrase_hash(
            statement_roles._tokens("duplex stainless steel")
        ),
        "expected_words": 3,
    }
    rule_roles.export(PUMP, [entry])
    return rule, fact, run, scope


def _classify(equipment_type):
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = ? WHERE document_id = 'sub-1'",
            (equipment_type,),
        )


def _finding_of(result, rule):
    return next(f for f in result["findings"] if f.get("requirement_id") == rule["id"])


@pytest.mark.parametrize(
    ("sheet", "words"),
    [
        ("Duplex stainless steel ASTM A890", "holds those words"),
        ("Carbon steel", "does not hold those words"),
    ],
)
def test_a_reviewed_statement_pairs_through_the_run_and_shows_both_sides_held_for_the_engineer(
    monkeypatch, sheet, words
):
    from app import comparison

    rule, fact, run, scope = _statement_world(sheet)
    monkeypatch.setattr(settings, "field_naming_enabled", True)
    monkeypatch.setattr(
        field_naming, "ensure_names", lambda *_a, **_k: pytest.fail("a model was asked")
    )
    _classify(PUMP)
    found = _finding_of(
        comparison.run_comparison(run, allowed_document_ids=scope), rule
    )
    assert found["match_method"] == comparison.METHOD_FIELD_NAME
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    why = found["ai_rationale"] or found["finding"]
    assert "the clause requires 'duplex stainless steel'" in why and words in why


def test_a_reviewed_statement_is_not_used_on_a_review_of_another_type(monkeypatch):
    from app import comparison

    rule, _fact, run, scope = _statement_world("Duplex stainless steel")
    monkeypatch.setattr(settings, "field_naming_enabled", True)
    _classify("Pressure Vessel")
    found = _finding_of(
        comparison.run_comparison(run, allowed_document_ids=scope), rule
    )
    assert found.get("match_method") != comparison.METHOD_FIELD_NAME


def test_a_statement_pairs_with_the_field_of_its_own_role_and_not_with_another_field(
    monkeypatch,
):
    from app import comparison, datasheets

    rule, fact, run, scope = _statement_world("Duplex stainless steel")
    datasheets.create_fact(
        submittal_document_id="sub-1",
        chunk_id="fc",
        field_label="Bearing type",
        raw_value="Ball bearing",
        page=1,
    )
    monkeypatch.setattr(settings, "field_naming_enabled", True)
    _classify(PUMP)
    found = _finding_of(
        comparison.run_comparison(run, allowed_document_ids=scope), rule
    )
    assert (
        found["match_method"] == comparison.METHOD_FIELD_NAME
        and found["fact_id"] == fact["id"]
    )
    assert "Ball bearing" not in (found["ai_rationale"] or "")


@pytest.mark.parametrize(
    ("text", "field_quote", "value", "expected"),
    [
        (
            "The casing material shall be duplex stainless steel.",
            "casing material",
            "duplex stainless steel",
            True,
        ),
        (
            "For sour service the casing material shall be duplex stainless steel.",
            "casing material",
            "duplex stainless steel",
            False,
        ),
        (
            "In pumps above 100 kW the bearing type shall be sleeve.",
            "bearing type",
            "sleeve",
            False,
        ),
        (
            "For vertical pumps the bearing type shall be sleeve.",
            "bearing type",
            "sleeve",
            False,
        ),
        (
            "The casing material shall be duplex stainless steel for pumps handling amine.",
            "casing material",
            "duplex stainless steel",
            False,
        ),
        (
            "At the purchaser's option the seal plan shall be plan 53B.",
            "seal plan",
            "plan 53B",
            False,
        ),
        (
            "The casing material shall be selected by the vendor.",
            "casing material",
            "selected by the vendor",
            False,
        ),
        (
            "The casing material shall be approved.",
            "casing material",
            "approved",
            False,
        ),
        (
            "The casing material shall be duplex stainless steel and shall be tested.",
            "casing material",
            "duplex stainless steel",
            False,
        ),
        (
            "Duplex stainless steel shall be the casing material.",
            "casing material",
            "duplex stainless steel",
            False,
        ),
        (
            "The casing material is duplex stainless steel.",
            "casing material",
            "duplex stainless steel",
            False,
        ),
        # the value itself holds a cue word / is the field's own name / only neutral words
        (
            "The casing material shall be duplex stainless steel or carbon steel.",
            "casing material",
            "duplex stainless steel or carbon steel",
            False,
        ),
        (
            "The casing material shall not be bronze.",
            "casing material",
            "bronze",
            False,
        ),
        (
            "The casing material shall be casing material.",
            "casing material",
            "casing material",
            False,
        ),
        ("The casing material shall be the.", "casing material", "the", False),
    ],
)
def test_the_shape_is_the_field_as_subject_a_modal_then_the_value_ending_the_rule(
    text, field_quote, value, expected
):
    name = field_quote
    assert statement_roles.value_fits(text, field_quote, value, name) is expected
