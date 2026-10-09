"""#677: every requirement in a review's scope ends in exactly ONE state, with a reason.

States: checked / applies but not checked / does not apply (`scope_ledger`).
Each gate returns its own per-requirement decisions (owner: "per-requirement
states and reasons belong in table_gate and subject_scope outputs, not just
grouped lines"); the review adds the comparison's, checks the whole set adds
up (exactly one decision per requirement in scope, or it fails loudly), and
stores it per requirement. #638: a service-condition requirement does not
apply only when the datasheet DECLARES the condition absent.

Invented documents only. Mutations M4501-M4514.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app import (comparison, datasheets, db, scope_ledger, service_scope, standards,
                 submittal_review, subject_scope, table_gate)
from app.config import settings

NOW = "2026-10-09T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "scope.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


# ------------------------------------------------- the gates' own decisions

def cell(rid, row, column, *, chunk="c1", std="s1"):
    return {"id": rid, "standard_document_id": std, "chunk_id": chunk, "page": 1,
            "requirement_type": "table_value", "condition": row, "field": column}


FACTS = [{"field_label": "Material", "field_value": "S31600"},
         {"field_label": "Set pressure", "field_value": "9 barg"}]


def test_table_gate_gives_every_requirement_it_does_not_keep_a_reason():
    reqs = [
        {"id": "d1", "requirement_type": "definition"},
        {"id": "q1", "requirement_type": "numeric_limit", "quality_reason": "text_quality"},
        cell("kept", "UNS S31600", "Max hardness"),                 # row label on the sheet
        cell("row", "UNS N08825", "Max hardness", chunk="c2"),      # row label not on the sheet
        cell("other", "UNS N06625", "Max hardness"),                # same table, another row matched
        cell("col", "", "Bolt torque", chunk="c3"),                 # no row label, column absent
        cell("none", "", "", chunk="c4"),                           # nothing to match
        {"id": "prose", "requirement_type": "numeric_limit"},       # not a table cell: kept
    ]
    out = table_gate.gate(reqs, FACTS)
    assert {r["id"] for r in out["kept"]} == {"kept", "prose"}
    by_id = {d["requirement_id"]: d for d in out["decisions"]}
    assert {k: (v["state"], v["reason_code"]) for k, v in by_id.items()} == {
        "d1": (scope_ledger.DOES_NOT_APPLY, "definition"),
        "q1": (scope_ledger.APPLIES_NOT_CHECKED, "unreadable_text"),
        "row": (scope_ledger.APPLIES_NOT_CHECKED, "row_label_not_on_sheet"),
        "other": (scope_ledger.APPLIES_NOT_CHECKED, "other_row_matched"),
        "col": (scope_ledger.APPLIES_NOT_CHECKED, "column_not_on_sheet"),
        "none": (scope_ledger.APPLIES_NOT_CHECKED, "no_label"),
    }
    # #669: the grouped line counts them by reason too
    [line] = out["not_compared"]
    assert line["reasons"] == {"row_label_not_on_sheet": 1, "other_row_matched": 1,
                               "column_not_on_sheet": 1, "no_label": 1}


def test_subject_scope_gives_each_requirement_it_sets_aside_a_reason():
    reqs = [{"id": "pump", "requirement_text": "Pump bearings shall be rated for 25000 hours.",
             "clause": "5.1", "standard_document_id": "s1"},
            {"id": "general", "requirement_text": "Nameplates shall be stainless steel.",
             "clause": "5.2", "standard_document_id": "s1"}]
    out = subject_scope.gate(reqs, classification={"equipment_type": "Pressure Safety Valve"},
                             facts=[])
    assert [r["id"] for r in out["kept"]] == ["general"]
    [d] = out["decisions"]
    assert (d["requirement_id"], d["state"], d["reason_code"]) == (
        "pump", scope_ledger.DOES_NOT_APPLY, "other_equipment")
    assert "pump" in d["reason"].lower()


# ------------------------------------------------- service condition (#638)

SOUR_REQ = {"id": "s", "standard_document_id": "nace",
            "requirement_text": "Hardness shall not exceed 22 HRC."}
MARKED = {"id": "m", "standard_document_id": "other",
          "requirement_text": "Materials for sour service shall resist cracking."}
PLAIN = {"id": "p", "standard_document_id": "other",
         "requirement_text": "The body shall be cast steel."}
LABELS = {"nace": "NACE MR0175 ISO 15156-2", "other": "SPEC-X Valves"}


def _service(facts):
    return service_scope.gate([SOUR_REQ, MARKED, PLAIN], facts=facts, standard_labels=LABELS)


def test_declared_not_sour_sets_sour_requirements_aside_with_the_citation():
    out = _service([{"field_label": "H2S service", "field_value": "No", "page": 2}])
    assert [r["id"] for r in out["kept"]] == ["p"]
    assert {d["requirement_id"] for d in out["decisions"]} == {"s", "m"}
    assert all(d["reason_code"] == "service_condition_not_met"
               and "H2S service: No, page 2" in d["reason"] for d in out["decisions"])


@pytest.mark.parametrize("facts", [
    [{"field_label": "H2S service", "field_value": "Yes"}],      # declared present
    [{"field_label": "Service", "field_value": "Gas"}],          # not declared
    [],                                                          # nothing on the sheet
])
def test_declared_sour_or_unknown_keeps_them_checks(facts):
    out = _service(facts)
    assert [r["id"] for r in out["kept"]] == ["s", "m", "p"]
    assert out["decisions"] == []


def test_service_conditions_come_from_the_editable_file(tmp_path):
    data = json.loads(service_scope.VOCABULARY_PATH.read_text(encoding="utf-8"))
    data["conditions"].append({"name": "cryogenic service", "standards": [],
                               "requirement_markers": ["cryogenic"], "field_labels": ["cryogenic"],
                               "declared_present": ["yes"], "declared_absent": ["no"]})
    edited = tmp_path / "service_conditions.json"
    edited.write_text(json.dumps(data), encoding="utf-8")
    req = {"id": "c", "standard_document_id": "x",
           "requirement_text": "Cryogenic valves shall have extended bonnets."}
    out = service_scope.gate([req], facts=[{"field_label": "Cryogenic", "field_value": "No"}],
                             path=edited)
    assert [d["requirement_id"] for d in out["decisions"]] == ["c"]
    assert service_scope.gate([req], facts=[{"field_label": "Cryogenic", "field_value": "No"}]
                              )["decisions"] == []


# ------------------------------------------------- the ledger's invariant

def test_the_ledger_fails_loudly_when_it_does_not_add_up():
    reqs = [{"id": "a"}, {"id": "b"}]
    ok = scope_ledger.check_complete(reqs, [scope_ledger.decision(r, "compared") for r in reqs])
    assert ok["in_scope"] == 2 and ok[scope_ledger.CHECKED] == 2
    with pytest.raises(scope_ledger.IncompleteScope, match="1 without a decision"):
        scope_ledger.check_complete(reqs, [scope_ledger.decision(reqs[0], "compared")])
    with pytest.raises(scope_ledger.IncompleteScope, match="1 decided twice"):
        scope_ledger.check_complete(reqs, [scope_ledger.decision(reqs[0], "compared"),
                                           scope_ledger.decision(reqs[0], "definition"),
                                           scope_ledger.decision(reqs[1], "compared")])


@pytest.mark.parametrize(("status", "state", "code"), [
    ("COMPLIANT", scope_ledger.CHECKED, "compared"),
    ("NON_COMPLIANT", scope_ledger.CHECKED, "compared"),
    ("MISSING_INFORMATION", scope_ledger.APPLIES_NOT_CHECKED, "missing_information"),
    ("NEEDS_ENGINEER_REVIEW", scope_ledger.APPLIES_NOT_CHECKED, "needs_engineer"),
    ("NOT_IN_DOCUMENT_SCOPE", scope_ledger.APPLIES_NOT_CHECKED, "needs_other_document"),
    ("NOT_APPLICABLE", scope_ledger.DOES_NOT_APPLY, "not_applicable"),
    ("SOMETHING_NEW", scope_ledger.APPLIES_NOT_CHECKED, "needs_engineer"),
])
def test_a_finding_status_maps_to_one_state(status, state, code):
    d = scope_ledger.from_finding({"id": "r"}, status)
    assert (d["state"], d["reason_code"]) == (state, code)


# ------------------------------------------------- end to end, through the review

def _doc(doc_id, filename, role, **meta):
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                     (doc_id, filename, f"sha-{doc_id}", filename, NOW))
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(f"INSERT INTO document_classification ({','.join(cols)})"
                     f" VALUES ({','.join('?' * len(cols))})", [doc_id, "test", role, *meta.values()])
    return doc_id


def _chunk(chunk_id, doc_id, text="x"):
    with db.connect() as conn:
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "section,kind,text,token_count,content_hash,retrievable)"
                     " VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)",
                     (chunk_id, doc_id, "f.pdf", text, f"h-{chunk_id}"))
    return chunk_id


def _req(std, chunk, text, **structured):
    return standards.create_requirement(
        standard_document_id=std, chunk_id=chunk, clause="5.1", page=1,
        requirement_text=text, source_text=text, structured=structured or None)["id"]


@pytest.fixture
def review_run():
    spec = _doc("spec", "SPEC-X-valves.pdf", "COMPANY_STANDARD")
    nace = _doc("nace", "NACE-MR0175-ISO-15156-2.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv-sheet.pdf", "CONTRACTOR_SUBMITTAL",
               equipment_type="Pressure Safety Valve")
    sc, nc, fc = _chunk("sc", spec), _chunk("nc", nace), _chunk("fc", sub)
    ids = {
        "compared": _req(spec, sc, "The set pressure shall not exceed 10 barg.",
                         requirement_type="numeric_limit", operator="<=", value=10.0,
                         unit="barg", raw_value="10", raw_unit="barg", field="set pressure",
                         subject="set pressure"),
        "definition": _req(spec, sc, "Set pressure means the inlet gauge pressure.",
                           requirement_type="definition"),
        "cell": _req(spec, sc, "UNS N08825 - Max hardness: 35", requirement_type="table_value",
                     condition="UNS N08825", field="Max hardness", raw_value="35"),
        "pump": _req(spec, sc, "Pump bearings shall be rated for 25000 hours.",
                     requirement_type="statement"),
        "sour": _req(nace, nc, "Hardness shall not exceed 22 HRC.", requirement_type="statement"),
    }
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc, field_label="Set pressure",
                           raw_value="9 barg", page=1)
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc, field_label="H2S service",
                           raw_value="No", page=1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
                     "updated_at) VALUES (?,?,'pending',?,?)", (run, sub, NOW, NOW))
        for std in (spec, nace):
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,"
                         "standard_document_id,selection_method,included,created_at)"
                         " VALUES (?,?,?,'rule',1,?)", (str(uuid.uuid4()), run, std, NOW))
    return run, ids, frozenset({spec, nace, sub})


def test_every_requirement_in_scope_has_exactly_one_stored_decision(review_run):
    run, ids, scope = review_run
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    assert set(stored) == set(ids.values())          # every one, once
    got = {name: (stored[rid]["state"], stored[rid]["reason_code"]) for name, rid in ids.items()}
    assert got == {
        "compared": (scope_ledger.CHECKED, "compared"),
        "definition": (scope_ledger.DOES_NOT_APPLY, "definition"),
        "cell": (scope_ledger.APPLIES_NOT_CHECKED, "row_label_not_on_sheet"),
        "pump": (scope_ledger.DOES_NOT_APPLY, "other_equipment"),
        "sour": (scope_ledger.DOES_NOT_APPLY, "service_condition_not_met"),
    }
    assert all(d["reason"] for d in stored.values())
    s = result["scope"]
    assert s["in_scope"] == 5
    assert (s[scope_ledger.CHECKED], s[scope_ledger.APPLIES_NOT_CHECKED],
            s[scope_ledger.DOES_NOT_APPLY]) == (1, 1, 3)


def test_a_rerun_replaces_the_ledger_not_adds_to_it(review_run):
    run, ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    comparison.run_comparison(run, allowed_document_ids=scope, replace=True)
    assert len(scope_ledger.decisions_for(run)) == len(ids)


# ------------------------------------------------- AI applicability (#647): proposes, code confirms

class FakeModel:
    """Replies in order; stands in for the configured model (no weights)."""

    def __init__(self, *replies, model="test-model"):
        self.requested_model = model
        self.replies = [json.dumps(r) for r in replies]

    def reason(self, packet):
        from app.reasoning_provider import Response
        return Response(text=self.replies.pop(0), provider="ollama", model_tag=self.requested_model,
                        digest="d", finish_reason="stop", prompt_sha256=packet.sha256)


PSV = {"equipment_type": "Pressure Safety Valve"}
PUMP_CLAUSE = {"id": "a", "requirement_text": "Pump bearings shall be rated for 25000 hours."}
NOTE_CLAUSE = {"id": "b", "requirement_text": "NOTE Further guidance is given in Annex B."}
SHALL_CLAUSE = {"id": "c", "requirement_text": "The body shall be forged steel."}


def _ai(reqs, *replies, limit=None):
    from app import ai_applicability
    return ai_applicability.gate(reqs, classification=PSV, facts=[], provider=FakeModel(*replies),
                                 limit=limit)


def test_a_does_not_apply_that_code_confirms_leaves_the_check():
    out = _ai([PUMP_CLAUSE], {"applies": "no", "reason": "other_equipment",
                              "quote": "Pump bearings shall be rated"})
    assert out["kept"] == []
    [d] = out["decisions"]
    assert (d["state"], d["reason_code"], d["decided_by"]) == (
        scope_ledger.DOES_NOT_APPLY, "other_equipment", "ai:test-model+code")


def test_a_does_not_apply_code_cannot_confirm_stays_a_check_with_a_note():
    """The model says the forged-body clause is about other equipment; the
    vocabulary finds no equipment in it, so code cannot confirm: still a check."""
    out = _ai([SHALL_CLAUSE], {"applies": "no", "reason": "other_equipment",
                               "quote": "The body shall be forged steel."})
    assert [r["id"] for r in out["kept"]] == ["c"] and out["decisions"] == []
    assert "could not confirm" in out["notes"]["c"]


def test_unsure_stays_a_check_never_dropped():
    out = _ai([PUMP_CLAUSE], {"applies": "unsure", "reason": "none", "quote": None})
    assert [r["id"] for r in out["kept"]] == ["a"]
    assert out["notes"]["a"] == "the model was unsure whether it applies"


def test_a_quote_that_is_not_in_the_clause_confirms_nothing():
    out = _ai([PUMP_CLAUSE], {"applies": "no", "reason": "other_equipment",
                              "quote": "Compressor seals shall be dry gas seals"})
    assert [r["id"] for r in out["kept"]] == ["a"] and out["decisions"] == []


def test_an_informative_note_is_confirmed_only_without_a_mandatory_word():
    out = _ai([NOTE_CLAUSE, SHALL_CLAUSE],
              {"applies": "no", "reason": "informative_note",
               "quote": "NOTE Further guidance is given in Annex B."},
              {"applies": "no", "reason": "informative_note",
               "quote": "The body shall be forged steel."})
    assert [d["requirement_id"] for d in out["decisions"]] == ["b"]
    assert [r["id"] for r in out["kept"]] == ["c"]


def test_the_per_run_cap_asks_no_more_than_it_may():
    out = _ai([PUMP_CLAUSE, SHALL_CLAUSE],
              {"applies": "yes", "reason": "none", "quote": None}, limit=1)
    assert (out["asked"], out["not_asked"]) == (1, 1)
    assert [r["id"] for r in out["kept"]] == ["a", "c"]


def test_the_review_records_the_models_note_on_an_unchecked_requirement(review_run, monkeypatch):
    """Switched on, through the review: an unconfirmed suggestion travels to
    the requirement's stored reason; the model is named on a confirmed one."""
    from app import ai_applicability, ai_task_runner
    run, ids, scope = review_run
    # one more clause that reaches the comparison and finds no field
    leak = _req("spec", "sc", "The seat leakage shall not exceed 5 bubbles per minute.",
                requirement_type="numeric_limit", operator="<=", value=5.0, raw_value="5",
                field="seat leakage", subject="seat leakage")
    monkeypatch.setattr(settings, "ai_applicability_enabled", True)
    calls = {"n": 0}

    def fake_run_task(spec, text, provider=None, use_cache=True):
        calls["n"] += 1
        data = {"applies": "unsure", "reason": "none", "quote": None}
        return ai_task_runner.TaskResult(spec.name, ai_task_runner.STATE_OK, data, None, "test-model")

    monkeypatch.setattr(ai_applicability.ai_task_runner, "run_task", fake_run_task)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert calls["n"] == result["ai_applicability"]["asked"] >= 1
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    # the compared one stays checked and carries no note; the unchecked one does
    assert stored[ids["compared"]]["state"] == scope_ledger.CHECKED
    assert "unsure" not in stored[ids["compared"]]["reason"]
    assert stored[leak]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert stored[leak]["reason"].endswith("the model was unsure whether it applies")
    assert result["scope"]["in_scope"] == 6
