"""`claude_recheck`: the model's second opinion may record and may raise, and
may never change a status. Every test runs against a fake callable."""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest

from app import claude_recheck as cr
from app import comparison, db, submittal_review
from app.config import settings

# ------------------------------------------------------------------ fixtures

SENTENCE = "The noise level shall not exceed 90 dB(A)."


def _finding(status=comparison.COMPLIANT, **fields) -> dict:
    base = {
        "id": "f1",
        "compliance_status": status,
        "requirement": SENTENCE,
        "requirement_source_text": SENTENCE,
        "standard_clause": "5.3.3",
        "matched_phrase": "noise level",
        "contractor_evidence_text": "85 dB(A)",
        "value": "85",
        "unit": "dB(A)",
        "ai_rationale": "the submitted value 85 dB(A) is within the required <= 90 dB(A)",
        "unresolved_evidence": [],
        "confirmed_by": None,
    }
    base.update(fields)
    return base


def _model(agree: bool, quote="shall not exceed 90 dB(A)", reason="", **extra):
    body = {"agree": agree, "quote": quote, "reason": reason, **extra}
    return lambda prompt: json.dumps(body)


# ----------------------------------------------------- requirement_state

@pytest.mark.parametrize("status, state", [
    (comparison.COMPLIANT, cr.EVALUATED),
    (comparison.NON_COMPLIANT, cr.EVALUATED),
    (comparison.CONDITIONAL, cr.EVALUATED),
    (comparison.MISSING_INFORMATION, cr.MISSING_EVIDENCE),
    (comparison.NOT_APPLICABLE, cr.NOT_APPLICABLE),
    (comparison.NEEDS_ENGINEER_REVIEW, cr.ENGINEER_JUDGMENT),
    (None, cr.BLOCKED),
    ("SOMETHING_ELSE", cr.BLOCKED),
])
def test_state_mapping(status, state):
    assert cr.requirement_state(_finding(status, ai_rationale="")) == state
    assert state in cr.STATES


def test_states_are_exactly_five():
    assert len(cr.STATES) == 5 and len(set(cr.STATES)) == 5


def test_unresolved_citation_is_blocked_even_when_status_says_engineer():
    f = _finding(comparison.NEEDS_ENGINEER_REVIEW,
                 unresolved_evidence=["the standard citation does not resolve"])
    assert cr.requirement_state(f) == cr.BLOCKED
    # As stored: a JSON string, not a list.
    f["unresolved_evidence"] = json.dumps(["the contractor citation does not resolve"])
    assert cr.requirement_state(f) == cr.BLOCKED


@pytest.mark.parametrize("marker", [
    comparison.UNIT_MISMATCH, comparison.TABLE_ROW_REASON,
    comparison.RELATIVE_LIMIT_REASON])
def test_engine_refusals_are_blocked(marker):
    f = _finding(comparison.NEEDS_ENGINEER_REVIEW,
                 ai_rationale=f"{marker}: this requirement was not compared")
    assert cr.requirement_state(f) == cr.BLOCKED


def test_no_conversion_refusal_is_blocked():
    f = _finding(comparison.NEEDS_ENGINEER_REVIEW, ai_rationale=(
        "the submitted unit 'psi' and the required unit 'dB(A)' cannot be "
        "compared by this system; no conversion is guessed"))
    assert cr.requirement_state(f) == cr.BLOCKED


def test_ambiguous_match_is_engineer_judgment_not_blocked():
    f = _finding(comparison.NEEDS_ENGINEER_REVIEW,
                 ai_rationale="ambiguous_match: more than one submitted field")
    assert cr.requirement_state(f) == cr.ENGINEER_JUDGMENT


# ---------------------------------------------------------------- prompt

def test_prompt_carries_inputs_and_forbids_a_status():
    prompt = cr.build_prompt(_finding())
    for piece in (SENTENCE, "5.3.3", "noise level", "85", "dB(A)", "COMPLIANT"):
        assert piece in prompt
    assert "Do NOT include a status field" in prompt


# ------------------------------------------------------------ parse/accept

def test_parse_rejects_non_json_and_non_bool_agree():
    assert cr.parse_response("nope") == (None, "model_malformed")
    assert cr.parse_response(json.dumps({"agree": "yes"})) == (None, "model_malformed")
    assert cr.parse_response(json.dumps([1])) == (None, "model_malformed")


def test_agree_records_nothing_and_never_raises():
    out = cr.recheck_finding(_finding(comparison.COMPLIANT), _model(True))
    assert out["agree"] is True
    assert out["reason"] is None
    assert out["raise_to_engineer"] is False
    assert out["rejected"] == [] and out["counts"] == {}
    assert out["state"] == cr.EVALUATED


def test_disagree_on_compliant_raises():
    out = cr.recheck_finding(
        _finding(comparison.COMPLIANT),
        _model(False, reason="The limit is 90 dB(A) and 85 is a range end, not a value."))
    assert out["agree"] is False
    assert out["raise_to_engineer"] is True
    assert "90" in out["reason"]


def test_disagree_on_non_compliant_raises():
    out = cr.recheck_finding(
        _finding(comparison.NON_COMPLIANT),
        _model(False, reason="85 does not exceed 90."))
    assert out["raise_to_engineer"] is True


@pytest.mark.parametrize("status", [
    comparison.MISSING_INFORMATION, comparison.NOT_APPLICABLE,
    comparison.CONDITIONAL, comparison.NEEDS_ENGINEER_REVIEW])
def test_disagree_with_nothing_to_overturn_does_not_raise(status):
    out = cr.recheck_finding(
        _finding(status), _model(False, reason="The sheet does state a value."))
    assert out["agree"] is False
    assert out["raise_to_engineer"] is False


def test_number_not_in_inputs_is_rejected():
    out = cr.recheck_finding(
        _finding(), _model(False, reason="The real limit is 65 dB(A)."))
    assert out["agree"] is None
    assert out["counts"] == {"number_not_in_inputs": 1}
    assert out["raise_to_engineer"] is False
    assert out["rejected"][0]["model_reason"] == "The real limit is 65 dB(A)."


def test_numbers_from_clause_value_and_unit_are_allowed():
    out = cr.recheck_finding(
        _finding(), _model(False, reason="Clause 5.3.3 caps at 90; 85 is under it."))
    assert out["agree"] is False


def test_thousands_separators_are_the_same_number():
    f = _finding(requirement_source_text="The bearing stress shall be 8,300 kPa.",
                 requirement="The bearing stress shall be 8,300 kPa.",
                 value="8300", unit="kPa")
    out = cr.recheck_finding(
        f, _model(False, quote="shall be 8,300 kPa", reason="8300 equals the stated value."))
    assert out["agree"] is False


def test_status_change_attempted_is_rejected():
    out = cr.recheck_finding(
        _finding(comparison.NON_COMPLIANT),
        _model(True, status="COMPLIANT"))
    assert out["agree"] is None
    assert out["counts"] == {"status_change_attempted": 1}


def test_compliance_status_key_is_also_a_status_change():
    proposal, _ = cr.parse_response(json.dumps(
        {"agree": False, "quote": "shall not exceed", "reason": "x",
         "compliance_status": "COMPLIANT"}))
    gate = cr.accept(proposal, _finding())
    assert gate["accepted"] is None
    assert gate["rejected"][0]["reason"] == cr.Reason.STATUS_CHANGE_ATTEMPTED.value


def test_two_runs_disagreeing_is_unstable_and_does_not_raise():
    out = cr.recheck_finding(
        _finding(comparison.COMPLIANT),
        _model(False, reason="85 is a range end."),
        second_call=_model(True))
    assert out["agree"] is None
    assert out["counts"] == {"model_unstable": 1}
    assert out["raise_to_engineer"] is False


def test_second_run_malformed_is_an_error_not_a_verdict():
    out = cr.recheck_finding(_finding(), _model(False, reason="x"),
                             second_call=lambda p: "garbage")
    assert out["agree"] is None and out["error"] == "model_malformed"


def test_quote_not_in_sentence_is_rejected():
    out = cr.recheck_finding(
        _finding(), _model(False, quote="shall not exceed 115 dB(A)", reason="x"))
    assert out["counts"] == {"quote_not_in_sentence": 1}


def test_quote_is_whole_word_and_fold_tolerant():
    f = _finding(requirement_source_text="The  noise\nlevel shall NOT exceed 90 dB(A).")
    out = cr.recheck_finding(f, _model(True, quote="noise level shall not exceed"))
    assert out["agree"] is True
    out = cr.recheck_finding(f, _model(True, quote="oise level"))
    assert out["counts"] == {"quote_not_in_sentence": 1}


def test_disagreement_without_reason_is_rejected():
    out = cr.recheck_finding(_finding(), _model(False, reason=""))
    assert out["counts"] == {"reason_missing": 1}


def test_recheck_never_alters_the_finding_it_was_given():
    f = _finding(comparison.COMPLIANT)
    before = dict(f)
    cr.recheck_finding(f, _model(False, reason="85 is a range end."))
    assert f == before


# ------------------------------------------------------------ recheck_run

def test_recheck_run_aggregates_counts_and_states():
    findings = [
        _finding(comparison.COMPLIANT, id="a"),
        _finding(comparison.NON_COMPLIANT, id="b"),
        _finding(comparison.MISSING_INFORMATION, id="c"),
        _finding(comparison.NEEDS_ENGINEER_REVIEW, id="d",
                 ai_rationale="table_row: not compared"),
    ]
    answers = {
        "COMPLIANT": {"agree": True, "quote": "shall not exceed"},
        "NON_COMPLIANT": {"agree": False, "quote": "shall not exceed",
                          "reason": "85 is under 90."},
        "MISSING_INFORMATION": {"agree": False, "quote": "shall not exceed",
                                "reason": "the sheet states 85."},
        "NEEDS_ENGINEER_REVIEW": {"agree": True, "quote": "shall not exceed",
                                  "status": "COMPLIANT"},
    }

    def model(prompt):
        verdict = prompt.split("ENGINE VERDICT: ")[1].splitlines()[0].strip()
        return json.dumps(answers[verdict])

    out = cr.recheck_run("run", model, allowed_document_ids=frozenset(),
                         findings=findings)
    assert out["total"] == 4
    assert out["agreed"] == 1 and out["disagreed"] == 2 and out["raised"] == 1
    assert out["rejected"] == {"status_change_attempted": 1}
    assert out["states"] == {cr.EVALUATED: 2, cr.MISSING_EVIDENCE: 1,
                             cr.NOT_APPLICABLE: 0, cr.ENGINEER_JUDGMENT: 0,
                             cr.BLOCKED: 1}
    assert out["findings"]["b"]["raise_to_engineer"] is True
    assert out["findings"]["c"]["raise_to_engineer"] is False


# ------------------------------------------------------------------ store

@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "recheck.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _stored_finding(status, **fields) -> str:
    fid = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('d1','s.pdf','sha-d1',1,'s.pdf','ready',1,'2026-09-18T00:00:00Z')
            ON CONFLICT(id) DO NOTHING""")
        columns = {"id": fid, "document_id": "d1", "category": "requirement_deviation",
                   "severity": "major", "requirement": SENTENCE,
                   "finding": "x", "required_action": comparison._required_action(status),
                   "created_at": "2026-09-18T00:00:00Z", "updated_at": "2026-09-18T00:00:00Z",
                   "review_run_id": "run", "compliance_status": status,
                   "ai_rationale": "engine said so", **fields}
        conn.execute(
            f"INSERT INTO review_findings ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(columns))})", list(columns.values()))
    return fid


def _row(fid):
    return dict(db.connect().execute(
        "SELECT * FROM review_findings WHERE id = ?", (fid,)).fetchone())


def test_store_disagreement_raises_compliant_with_prefixed_note(temp_storage):
    fid = _stored_finding(comparison.COMPLIANT)
    result = cr.recheck_finding(_finding(comparison.COMPLIANT),
                                _model(False, reason="85 is a range end."))
    out = cr.store_recheck(fid, result)
    assert out == {"stored": True, "raised": True, "why": "disagreed"}
    row = _row(fid)
    assert row["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert cr.NOTE_PREFIX in row["ai_rationale"]
    assert row["ai_rationale"].startswith("engine said so")
    assert row["required_action"] == comparison._required_action(
        comparison.NEEDS_ENGINEER_REVIEW)


def test_store_agreement_records_only_the_agreement(temp_storage):
    fid = _stored_finding(comparison.NON_COMPLIANT)
    out = cr.store_recheck(fid, cr.recheck_finding(
        _finding(comparison.NON_COMPLIANT), _model(True)))
    assert out["stored"] is True and out["raised"] is False
    row = _row(fid)
    assert row["compliance_status"] == comparison.NON_COMPLIANT
    assert row["ai_rationale"].endswith(
        cr.NOTE_PREFIX + "Model agrees with the engine's verdict.")


def test_store_never_touches_an_engineer_decided_finding(temp_storage):
    fid = _stored_finding(comparison.COMPLIANT, confirmed_by="u1")
    result = cr.recheck_finding(_finding(comparison.COMPLIANT),
                                _model(False, reason="85 is a range end."))
    assert cr.store_recheck(fid, result)["why"] == "engineer_decided"
    row = _row(fid)
    assert row["compliance_status"] == comparison.COMPLIANT
    assert cr.NOTE_PREFIX not in row["ai_rationale"]


def test_store_rejected_result_writes_nothing(temp_storage):
    fid = _stored_finding(comparison.COMPLIANT)
    result = cr.recheck_finding(_finding(comparison.COMPLIANT),
                                _model(False, reason="the true limit is 65."))
    assert cr.store_recheck(fid, result)["why"] == "rejected"
    assert _row(fid)["ai_rationale"] == "engine said so"
    assert cr.store_recheck("no-such-id", result) is None


def test_store_cannot_raise_past_the_stored_status(temp_storage):
    """A result claiming `raise_to_engineer` against a MISSING_INFORMATION row
    is not obeyed: the stored status governs, not the caller's dict."""
    fid = _stored_finding(comparison.MISSING_INFORMATION)
    forged = {"agree": False, "reason": "x", "quote": "q", "raise_to_engineer": True}
    out = cr.store_recheck(fid, forged)
    assert out["raised"] is False
    assert _row(fid)["compliance_status"] == comparison.MISSING_INFORMATION


# ------------------------------------------------------------ containment

def test_module_imports_no_http_library():
    source = Path(cr.__file__).read_text(encoding="utf-8")
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"httpx", "requests", "urllib", "urllib3", "aiohttp",
                        "socket", "http", "websockets"}
