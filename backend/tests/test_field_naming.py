"""#193 plan B4 (orders 5.2 / 5.3): canonical field names, named by a model
under code gates, and pairing by field-name equality.

The model is FAKED here - these tests are about the gates, which must hold
whatever a model answers: an unverified quote is unmapped, a quote that does
not name the field is unmapped, an out-of-range answer is unmapped, and
nothing the model writes is stored as a value. Mutation proofs M590 and
M597-M599 (scripts/mutations/field_naming.py, comparison.py).
"""
from __future__ import annotations

import json

import pytest

from app import comparison, db, field_naming, submittal_review
from app.config import settings
from app.reasoning_provider import Response


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "names.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


class FakeProvider:
    """Answers every call with `answers(batch_items)`; records the packets."""

    name = "ollama"

    def __init__(self, answers):
        self.answers = answers
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        items = json.loads(packet.prompt)["items"]
        text = json.dumps({"names": self.answers(items)})
        return Response(text=text, provider="ollama", model_tag="fake:1", digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


DICTIONARY = ["sound pressure level", "maximum pump speed", "speed"]
LABEL = "MAX. ALLOW SOUND PRESS. LEVEL REQ'D"


def _one(answer: dict) -> dict:
    return field_naming.verify(answer, [("k", LABEL)], DICTIONARY)[1]


def test_a_verified_quote_that_names_the_field_is_kept():
    got = _one({"i": 0, "field": 0, "quote": "SOUND PRESS. LEVEL"})
    assert got == {"field_name": "sound pressure level", "quote": "SOUND PRESS. LEVEL"}


def test_an_unverified_quote_leaves_the_label_unmapped():
    """THE MUTATION TARGET (M597): the quote is not in the label - no name."""
    assert _one({"i": 0, "field": 0, "quote": "SOUND PRESSURE LEVEL"})["field_name"] is None


def test_a_quote_that_does_not_name_the_field_leaves_it_unmapped():
    """THE MUTATION TARGET (M598): "REQ'D" is on the label but names nothing."""
    assert _one({"i": 0, "field": 0, "quote": "REQ'D"})["field_name"] is None
    assert field_naming.names_the_field("SOUND PRESS. LEVEL", "sound pressure level")
    assert not field_naming.names_the_field("ALLOW", "maximum pump speed")
    # one shared word is not enough; a limit word never has to be quoted
    assert not field_naming.names_the_field("interpass temperature", "operating temperature")
    assert field_naming.names_the_field("pump speed shall not exceed", "maximum pump speed")


@pytest.mark.parametrize("field", [3, -1, True, "0", None, 1.0])
def test_an_answer_outside_the_dictionary_is_unmapped(field):
    assert _one({"i": 0, "field": field, "quote": "SOUND PRESS. LEVEL"})["field_name"] is None


def test_an_answer_for_no_item_is_ignored():
    assert field_naming.verify({"i": 5, "field": 0, "quote": "x"}, [("k", LABEL)], DICTIONARY) is None


def test_the_model_never_writes_a_value(tmp_path):
    """Whatever extra the model says ("value": 85) is not stored: the side
    table has no value column, and the row holds the entry and the quote."""
    provider = FakeProvider(lambda items: [
        {"i": 0, "field": 0, "quote": "SOUND PRESS. LEVEL", "value": "VALUE-XYZ-777", "unit": "dBA"}])
    got = field_naming.name_items(field_naming.LABEL, [("sound", LABEL)], DICTIONARY, provider)
    assert got == {"sound": {"field_name": "sound pressure level", "quote": "SOUND PRESS. LEVEL"}}
    columns = {r[1] for r in db.connect().execute("PRAGMA table_info(canonical_field_names)")}
    assert not columns & {"value", "raw_value", "unit"}
    row = dict(db.connect().execute("SELECT * FROM canonical_field_names").fetchone())
    assert "VALUE-XYZ-777" not in json.dumps(row) and "dBA" not in json.dumps(row)


def test_names_are_asked_once_per_dictionary():
    provider = FakeProvider(lambda items: [{"i": 0, "field": None, "quote": ""}])
    field_naming.name_items(field_naming.LABEL, [("x", "SPEED")], DICTIONARY, provider)
    field_naming.name_items(field_naming.LABEL, [("x", "SPEED")], DICTIONARY, provider)
    assert len(provider.packets) == 1
    assert provider.packets[0].step == field_naming.NAMING_STEP == "b4-naming2"
    assert "FIELD DICTIONARY" in provider.packets[0].system


def test_the_side_table_may_be_missing():
    assert field_naming.stored_names(field_naming.LABEL, ["x"], DICTIONARY) == {}


def _req(rid, text, *, rtype="numeric_limit", subject=None, value="5000", unit="rpm"):
    return {"id": rid, "requirement_type": rtype, "requirement_text": text,
            "subject": subject, "raw_value": value, "raw_unit": unit, "unit": unit,
            "value": float(value) if value else None, "operator": "<="}


def test_numeric_requirements_are_named_and_statements_are_not():
    """THE MUTATION TARGET (M590): each numeric requirement is named from its
    own text; a statement is never sent."""
    reqs = [_req("r1", "Maximum pump speed shall be 5,000 RPM", subject="Maximum pump speed"),
            _req("r2", "Pumps shall be painted", rtype="statement", subject=None, value=None)]
    facts = [{"id": "f1", "field_name": "pump speed", "field_label": "PUMP SPEED:", "raw_value": "2950"},
             {"id": "f2", "field_name": "pump type", "field_label": "PUMP TYPE:", "raw_value": None}]

    def answers(items):
        out = []
        for n, item in enumerate(items):
            if "Maximum pump speed" in item["text"]:
                # dictionary: ["pump speed", "maximum pump speed"] - entry 0
                out.append({"i": n, "field": 0, "quote": "pump speed"})
            elif item["text"] == "PUMP SPEED:":
                # label dictionary: only the requirement names - ["pump speed"]
                out.append({"i": n, "field": 0, "quote": "PUMP SPEED"})
            else:
                out.append({"i": n, "field": None, "quote": ""})
        return out

    provider = FakeProvider(answers)
    names = field_naming.ensure_names(reqs, facts, provider=provider)
    assert names["requirements"] == {"r1": "pump speed"}
    assert names["facts"] == {"f1": "pump speed"}
    sent = " ".join(p.prompt for p in provider.packets)
    assert "painted" not in sent           # a statement is never sent
    assert "PUMP TYPE" not in sent         # a label with no number is never asked
    assert names["requirements_asked"] == 1 and names["label_dictionary"] == 1
    # the label pass saw ONLY the requirement names as its dictionary
    assert provider.packets[-1].system.endswith("FIELD DICTIONARY:\n0: pump speed")


def test_labels_are_not_asked_when_no_requirement_was_named():
    reqs = [_req("r1", "Maximum pump speed shall be 5,000 RPM", subject="Maximum pump speed")]
    facts = [{"id": "f1", "field_name": "pump speed", "field_label": "PUMP SPEED:", "raw_value": "1"}]
    provider = FakeProvider(lambda items: [{"i": n, "field": None, "quote": ""}
                                           for n, _ in enumerate(items)])
    names = field_naming.ensure_names(reqs, facts, provider=provider)
    assert names["facts"] == {} and len(provider.packets) == 1


def test_the_dictionary_comes_from_the_extractor_then_the_requirements():
    reqs = [_req("r1", "t", subject="Maximum pump speed"), _req("r2", "t", subject="which"),
            _req("r3", "t", subject="Note 2: For gasoline services"),
            _req("r4", "t", rtype="statement", subject="Paint colour")]
    facts = [{"field_name": "speed", "raw_value": "1"}, {"field_name": "pump type", "raw_value": None},
             {"field_name": "1 2 3 data sheet no", "raw_value": "3"}]
    assert field_naming.build_dictionary(reqs, facts) == ["speed", "maximum pump speed"]


# ------------------------------------------------------------- pairing

def _fact(fid, name, value="2950", unit="rpm", page=2):
    return {"id": fid, "field_name": name, "field_label": name.upper(), "raw_value": value,
            "raw_unit": unit, "unit": unit, "page": page, "is_blank": 0,
            "submittal_document_id": "doc_s", "equipment_tag": None,
            "value_min": None, "value_max": None}


def test_equal_field_names_pair_before_containment():
    """THE MUTATION TARGET (M599): the requirement's words contain no fact
    name, so only field-name equality can pair it."""
    req = _req("r1", "Maximum pump speed shall be 5,000 RPM", subject="Maximum pump speed")
    facts = [_fact("f1", "rotative speed"), _fact("f2", "rated flow", "24", "m3/h")]
    names = {"requirements": {"r1": "maximum pump speed"}, "facts": {"f1": "maximum pump speed"}}
    got = comparison.match_by_field_name(req, facts, names)
    assert got["fact"]["id"] == "f1" and got["method"] == comparison.METHOD_FIELD_NAME
    assert comparison.match_by_containment(req, facts)["fact"] is None


def test_field_name_pairing_negatives():
    req = _req("r1", "Maximum pump speed shall be 5,000 RPM", subject="Maximum pump speed")
    one = {"requirements": {"r1": "maximum pump speed"}, "facts": {"f1": "maximum pump speed"}}
    # unnamed requirement -> fall through to containment
    assert comparison.match_by_field_name(req, [_fact("f1", "x")], {"requirements": {},
                                                                     "facts": one["facts"]}) is None
    # a blank / non-numeric fact never pairs
    assert comparison.match_by_field_name(req, [_fact("f1", "x", value=None)], one) is None
    # two facts under the name: a tie, never a pick
    two = {"requirements": one["requirements"],
           "facts": {"f1": "maximum pump speed", "f2": "maximum pump speed"}}
    tie = comparison.match_by_field_name(req, [_fact("f1", "a"), _fact("f2", "b", page=3)], two)
    assert tie["fact"] is None and tie["reason"] == comparison.AMBIGUOUS_MATCH
    # a unit in another dimension is refused by the match rules -> fall through
    kpa = _req("r1", "Discharge pressure shall not exceed 1,724 kPa", value="1724", unit="kPa")
    assert comparison.match_by_field_name(kpa, [_fact("f1", "a", "24", "mm")], one) is None
    assert comparison.match_by_field_name(kpa, [_fact("f1", "a", "12", "bar")], one)["fact"]


# ------------------------------------------------ through run_comparison

NOW = "2026-09-25T00:00:00Z"


def _world(fact_label: str, fact_value: str):
    """One standard with one numeric requirement, one submittal fact, one run."""
    import uuid

    from app import datasheets, standards
    std, sub = "std-1", "sub-1"
    with db.connect() as conn:
        for doc_id, role in ((std, "COMPANY_STANDARD"), (sub, "CONTRACTOR_SUBMITTAL")):
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                         "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                         (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))
            conn.execute("INSERT INTO document_classification (document_id,suggested_by,"
                         "document_role) VALUES (?,?,?)", (doc_id, "test", role))
        for chunk_id, doc_id in (("sc", std), ("fc", sub)):
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                         "section,kind,text,token_count,content_hash,retrievable) VALUES "
                         "(?,?,?,0,1,1,NULL,'prose','x',1,?,1)", (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"))
    req = standards.create_requirement(
        standard_document_id=std, chunk_id="sc",
        requirement_text="The maximum allowable working pressure shall be 10 bar.",
        source_text="The maximum allowable working pressure shall be 10 bar.", clause="6.4.1", page=1,
        structured={"subject": "the maximum allowable working pressure", "operator": "<=",
                    "raw_value": "10", "raw_unit": "bar", "requirement_type": "numeric_limit"})
    fact = datasheets.create_fact(submittal_document_id=sub, chunk_id="fc", field_label=fact_label,
                                  raw_value=fact_value, page=1)
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES (?,?,'pending',?,?)", (run_id, sub, NOW, NOW))
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                     "selection_reason,selection_method,included,created_at) VALUES "
                     "(?,?,?,'cited','referenced',1,?)", (str(uuid.uuid4()), run_id, std, NOW))
    return req, fact, run_id, frozenset({std, sub})


def test_a_field_name_pairing_never_carries_a_verdict(monkeypatch):
    """THE MUTATION TARGET (M590): the numbers read NON_COMPLIANT (12 > 10),
    but a model-named pairing is held for an engineer, with the arithmetic
    stated and model-assisted confidence."""
    req, fact, run, scope = _world("Shell working press.", "12 bar")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(field_naming, "ensure_names", lambda *_a, **_k: {
        "requirements": {str(req["id"]): "working pressure"},
        "facts": {str(fact["id"]): "working pressure"}})
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    found = result["findings"][0]
    assert found["match_method"] == comparison.METHOD_FIELD_NAME
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "read NON_COMPLIANT" in found["ai_rationale"]
    assert found["ai_rationale"].startswith(comparison.FIELD_NAME_PAIR_PREFIX)
    assert result["field_name_matches"] == 1 and result["matches_made"] == 0


def test_with_the_flag_off_no_naming_runs(monkeypatch):
    req, fact, run, scope = _world("Shell working press.", "12 bar")

    def explode(*_a, **_k):
        raise AssertionError("field naming ran with the flag off")

    monkeypatch.setattr(field_naming, "ensure_names", explode)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert "field_name_matches" not in result
    assert result["findings"][0]["match_method"] != comparison.METHOD_FIELD_NAME


def test_a_different_state_is_a_different_quantity():
    assert not field_naming.names_the_field("Normal operating pressure", "maximum operating pressure")
    assert field_naming.names_the_field("Maximum Operating Pressure (MOP)", "maximum operating pressure")
