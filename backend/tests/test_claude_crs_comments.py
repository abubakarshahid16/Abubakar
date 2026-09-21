"""The CRS comment gate, against a FAKE model and no transport.

Every test hands `claude_crs_comments` a callable that returns a string; no
key, no socket, no database. The tests that matter most:

  * `test_invented_number_is_rejected` - the fabrication catch, and
    `test_number_that_is_in_the_inputs_is_accepted` beside it so the gate is
    shown to pass a true draft and not merely to reject everything.
  * `test_non_compliant_comment_saying_complies_is_rejected` - the defect
    that reverses a verdict in the client's hands.
  * `test_one_of_two_runs_failing_is_model_unstable` - two runs, gate on
    both, no equality demanded.
  * `test_apply_drafts_prefixes_and_keeps_machine_comment` - the sheet marks
    what a model wrote and keeps what the engine wrote.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app import claude_crs_comments as cc
from app.claude_crs_comments import (
    MODEL_DRAFT_PREFIX,
    Reason,
    accept,
    apply_drafts,
    build_prompt,
    clause_citation,
    draft_comment,
    draft_run,
    parse_response,
    standard_code,
)
from app.crs_export import build_crs_view
from app.crs_mapping import build_crs_rows

# ------------------------------------------------------------- fixtures

NC = {
    "id": "f-nc-1",
    "compliance_status": "NON_COMPLIANT",
    "standard_name": "SAES-D-001.pdf",
    "standard_document_id": "doc-d001",
    "standard_clause": "6.2.3",
    "standard_page": 14,
    "contractor_page": 4,
    "requirement_source_text": "The chloride content shall not exceed 5 g/L.",
    "contractor_evidence_text": "8 g/L",
    "required_value": "5",
    "required_unit": "g/L",
    "comparator": "<=",
    "matched_phrase": "chloride content",
    "ai_rationale": "8 exceeds 5.",
    "equipment_tag": "V-001",
}
OK = {
    "id": "f-ok-1",
    "compliance_status": "COMPLIANT",
    "standard_name": "SAES-D-001.pdf",
    "standard_clause": "6.2.3",
    "requirement_source_text": "The chloride content shall not exceed 5 g/L.",
    "contractor_evidence_text": "3 g/L",
    "required_value": "5",
    "required_unit": "g/L",
    "comparator": "<=",
}
NER = {
    "id": "f-ner-1",
    "compliance_status": "NEEDS_ENGINEER_REVIEW",
    "standard_name": "SAES-D-001.pdf",
    "standard_clause": "7.1",
    "standard_page": 20,
    "requirement_source_text": "Vessel wall thickness per the following table.",
    "ai_rationale": "table_row: no comparison made.",
}

GOOD_NC = ("The submitted chloride content of 8 g/L for V-001 exceeds the "
           "5 g/L limit stated in SAES-D-001 Para. 6.2.3. The submittal does "
           "not comply with the referenced requirement.")
GOOD_NC_ACTION = ("Contractor shall revise the chloride content to not exceed "
                  "5 g/L per SAES-D-001 Para. 6.2.3.")
GOOD_OK = ("The submitted chloride content of 3 g/L is within the 5 g/L limit "
           "of SAES-D-001 Para. 6.2.3. No deviation is noted.")


def row_for(finding: dict) -> dict:
    """The CRS row the export route would build for this finding."""
    rows = build_crs_rows([finding], [], "sheet.pdf")
    return rows[0] if rows else {"page_section": "", "finding_id": finding["id"]}


def answer(comment: str, action=None) -> str:
    return json.dumps({"comment": comment, "action": action})


def fake(*answers: str):
    """A model that returns the given answers in order, then the last one."""
    calls = {"n": 0, "prompts": []}

    def model_call(prompt: str) -> str:
        calls["prompts"].append(prompt)
        i = min(calls["n"], len(answers) - 1)
        calls["n"] += 1
        return answers[i]
    model_call.calls = calls
    return model_call


# ---------------------------------------------------------------- inputs

def test_standard_code_strips_the_filename_extension():
    assert standard_code(NC) == "SAES-D-001"
    assert standard_code({"standard_document_id": "doc-1"}) == "doc-1"
    assert standard_code({}) == ""


def test_clause_citation_is_the_form_the_client_expects():
    assert clause_citation(NC) == "SAES-D-001 Para. 6.2.3"
    assert clause_citation({"standard_name": "X.pdf"}) == "X"


def test_prompt_carries_every_input_and_asks_for_json_only():
    prompt = build_prompt(NC, row_for(NC))
    for piece in ("SAES-D-001 Para. 6.2.3", "8 g/L", "Required value: 5",
                  "Required unit: g/L", "Comparator: <=", "NON_COMPLIANT",
                  "chloride content", "V-001", "clause 6.2.3 p14",
                  "Contractor shall revise"):
        assert piece in prompt, piece
    assert '"comment"' in prompt and '"action"' in prompt
    assert prompt.rstrip().endswith("Answer with JSON and nothing else.")


def test_prompt_marks_absent_inputs_rather_than_inventing_them():
    prompt = build_prompt(NER, row_for(NER))
    assert "Required value: (not given)" in prompt
    assert "Submitted value: (not given)" in prompt


# ----------------------------------------------------------------- parse

def test_malformed_json_is_named_not_repaired():
    proposal, err = parse_response("The comment is: 8 g/L exceeds 5 g/L")
    assert proposal is None and err == Reason.MODEL_MALFORMED.value
    proposal, err = parse_response(json.dumps(["not", "an", "object"]))
    assert proposal is None and err == Reason.MODEL_MALFORMED.value
    proposal, err = parse_response(json.dumps({"action": "x"}))
    assert err == Reason.MODEL_MALFORMED.value


def test_parse_strips_a_code_fence_and_normalises_null_action():
    proposal, err = parse_response("```json\n" + answer(GOOD_OK) + "\n```")
    assert err is None
    assert proposal == {"comment": GOOD_OK, "action": None}
    proposal, _ = parse_response(answer(GOOD_OK, "null"))
    assert proposal["action"] is None


def test_malformed_response_ends_the_draft_with_model_malformed():
    out = draft_comment(NC, row_for(NC), fake("not json"))
    assert out["accepted"] is False
    assert out["reason"] == Reason.MODEL_MALFORMED.value
    assert out["comment"] is None


# ------------------------------------------------------------------ gate

def test_good_draft_is_accepted():
    gate = accept({"comment": GOOD_NC, "action": GOOD_NC_ACTION}, NC, row_for(NC))
    assert gate["accepted"] is True and gate["reason"] is None


def test_empty_comment_is_comment_missing():
    gate = accept({"comment": "  ", "action": GOOD_NC_ACTION}, NC, row_for(NC))
    assert gate["reason"] == Reason.COMMENT_MISSING.value


def test_clause_missing_is_rejected():
    comment = ("The submitted chloride content of 8 g/L exceeds the 5 g/L "
               "limit in SAES-D-001. The submittal does not comply.")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.CLAUSE_NOT_CITED.value


def test_wrong_clause_is_rejected():
    comment = GOOD_NC.replace("6.2.3", "6.2.4")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.CLAUSE_NOT_CITED.value


def test_standard_missing_is_rejected():
    comment = ("The submitted chloride content of 8 g/L exceeds the 5 g/L "
               "limit in Para. 6.2.3. The submittal does not comply.")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.STANDARD_NOT_CITED.value


def test_finding_with_no_standard_cannot_be_drafted():
    bare = {**NC, "standard_name": None, "standard_document_id": None,
            "standard_clause": None}
    gate = accept({"comment": GOOD_NC, "action": None}, bare, row_for(bare))
    assert gate["accepted"] is False


def test_invented_number_is_rejected():
    comment = GOOD_NC + " Typical values are around 6 g/L."
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.NUMBER_NOT_IN_INPUTS.value


def test_invented_number_in_the_action_is_rejected():
    # 4 would pass - it is the contractor page. 2 is nowhere in the inputs.
    action = "Contractor shall revise the design to 2 g/L."
    gate = accept({"comment": GOOD_NC, "action": action}, NC, row_for(NC))
    assert gate["reason"] == Reason.NUMBER_NOT_IN_INPUTS.value


def test_number_that_is_in_the_inputs_is_accepted():
    # 8 (submitted), 5 (required), 14 and 4 (page/section), 6.2.3 and 001
    # (citation) are all inputs; a comment repeating them is honest.
    comment = ("At submittal p4 the chloride content is stated as 8 g/L; "
               "SAES-D-001 Para. 6.2.3 (p14) limits it to 5 g/L. The "
               "submittal does not comply.")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["accepted"] is True, gate


def test_thousands_separator_is_the_same_number():
    finding = {**NC, "contractor_evidence_text": "8300 kPa",
               "required_value": "8,300", "required_unit": "kPa",
               "requirement_source_text": "The bearing stress shall be 8,300 kPa."}
    comment = ("The submitted bearing stress of 8,300 kPa matches the 8300 kPa "
               "stated in SAES-D-001 Para. 6.2.3. The submittal does not comply.")
    gate = accept({"comment": comment, "action": None}, finding, row_for(finding))
    assert gate["accepted"] is True, gate


def test_too_long_is_rejected():
    padding = " The submittal does not comply." * 30
    gate = accept({"comment": GOOD_NC + padding, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.TOO_LONG.value


def test_non_compliant_comment_saying_complies_is_rejected():
    comment = ("The submitted chloride content of 8 g/L against the 5 g/L "
               "limit of SAES-D-001 Para. 6.2.3 complies with the standard.")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["reason"] == Reason.STATUS_CONTRADICTED.value


def test_non_compliant_comment_saying_not_acceptable_is_still_rejection():
    comment = ("The submitted chloride content of 8 g/L is not acceptable "
               "against the 5 g/L limit of SAES-D-001 Para. 6.2.3.")
    gate = accept({"comment": comment, "action": None}, NC, row_for(NC))
    assert gate["accepted"] is True, gate


def test_compliant_comment_saying_shall_revise_is_rejected():
    gate = accept({"comment": GOOD_OK, "action": "Contractor shall revise it."},
                  OK, row_for(OK))
    assert gate["reason"] == Reason.STATUS_CONTRADICTED.value
    gate = accept({"comment": GOOD_OK + " It does not comply.", "action": None},
                  OK, row_for(OK))
    assert gate["reason"] == Reason.STATUS_CONTRADICTED.value


def test_compliant_draft_with_null_action_is_accepted():
    gate = accept({"comment": GOOD_OK, "action": None}, OK, row_for(OK))
    assert gate["accepted"] is True


def test_reason_values_are_the_stored_strings():
    assert Reason.MODEL_UNSTABLE.value == "model_unstable"
    assert Reason.NUMBER_NOT_IN_INPUTS.value == "number_not_in_inputs"
    assert {r.value for r in Reason} == {
        "model_malformed", "comment_missing", "clause_not_cited",
        "standard_not_cited", "number_not_in_inputs", "too_long",
        "status_contradicted", "model_unstable"}


# --------------------------------------------------------------- two runs

def test_two_passing_runs_keep_the_first_wording():
    second = GOOD_NC.replace("exceeds", "is above")
    model = fake(answer(GOOD_NC, GOOD_NC_ACTION), answer(second, GOOD_NC_ACTION))
    out = draft_comment(NC, row_for(NC), model)
    assert out["accepted"] is True
    assert out["comment"] == GOOD_NC
    assert out["action"] == GOOD_NC_ACTION
    assert out["finding_id"] == "f-nc-1"
    assert model.calls["n"] == 2


def test_one_of_two_runs_failing_is_model_unstable():
    bad = GOOD_NC + " Typical values are around 6 g/L."
    out = draft_comment(NC, row_for(NC), fake(answer(GOOD_NC)), fake(answer(bad)))
    assert out["accepted"] is False
    assert out["reason"] == Reason.MODEL_UNSTABLE.value
    # The lucky run is not shipped either way round.
    out = draft_comment(NC, row_for(NC), fake(answer(bad)), fake(answer(GOOD_NC)))
    assert out["reason"] == Reason.MODEL_UNSTABLE.value


def test_both_runs_failing_reports_the_first_reason():
    no_clause = "SAES-D-001 says 8 g/L exceeds 5 g/L. Does not comply."
    out = draft_comment(NC, row_for(NC), fake(answer(no_clause)))
    assert out["reason"] == Reason.CLAUSE_NOT_CITED.value


# --------------------------------------------------------------- draft_run

def test_draft_run_drafts_only_rows_that_enter_the_crs_and_counts_reasons():
    findings = [NC, OK, NER]
    bad_ner = "Para. 7.1 could not be verified."  # no standard code
    model = fake(answer(GOOD_NC, GOOD_NC_ACTION), answer(GOOD_NC, GOOD_NC_ACTION),
                 answer(bad_ner), answer(bad_ner))
    out = draft_run("run-1", model, allowed_document_ids=frozenset({"sub"}),
                    findings=findings, submittal_name="sheet.pdf")
    assert set(out["drafts"]) == {"f-nc-1", "f-ner-1"}
    assert out["skipped"] == 1  # the COMPLIANT finding has no CRS row
    assert out["drafted"] == 1 and out["rejected"] == 1
    assert out["counts"] == {Reason.STANDARD_NOT_CITED.value: 1}
    assert out["drafts"]["f-nc-1"]["row_ref"].startswith("RF-")
    assert model.calls["n"] == 4


def test_draft_run_accepts_injected_rows():
    rows = [{"finding_id": "f-nc-1", "document_name": "s.pdf",
             "page_section": "SAES-D-001 clause 6.2.3 p14", "comment": "m",
             "comment_by": "AI Review"}]
    out = draft_run("run-1", fake(answer(GOOD_NC)), rows=rows, findings=[NC],
                    allowed_document_ids=frozenset())
    assert out["drafted"] == 1


# ------------------------------------------------------------ apply_drafts

def test_apply_drafts_prefixes_and_keeps_machine_comment():
    rows = build_crs_rows([NC, NER], [], "sheet.pdf")
    view = build_crs_view(rows, {"review_run_id": "run-1"})
    run = draft_run("run-1", fake(answer(GOOD_NC, GOOD_NC_ACTION)),
                    allowed_document_ids=frozenset(), findings=[NC], rows=rows)
    before = json.dumps(view, sort_keys=True)

    out = apply_drafts(view, run)

    assert json.dumps(view, sort_keys=True) == before, "input was mutated"
    drafted, untouched = out["rows"]
    lines = drafted["comment"].split("\n")
    assert lines[0] == view["rows"][0]["comment"].split("\n")[0]  # Ref: kept
    assert lines[1] == MODEL_DRAFT_PREFIX + GOOD_NC
    assert lines[2] == "Action: " + GOOD_NC_ACTION
    assert drafted["machine_comment"] == view["rows"][0]["comment"]
    assert "8 exceeds 5." in drafted["machine_comment"]
    assert drafted["model_drafted"] is True
    assert untouched == view["rows"][1]
    assert "machine_comment" not in untouched
    # Everything else about the sheet is as it was.
    for key in ("title", "header", "columns", "recommended_code"):
        assert out[key] == view[key]


def test_apply_drafts_ignores_rejected_drafts():
    rows = build_crs_rows([NC], [], "sheet.pdf")
    view = build_crs_view(rows, {"review_run_id": "run-1"})
    drafts = {"f-nc-1": {"accepted": False, "reason": "model_unstable",
                         "row_ref": view["rows"][0]["row_ref"]}}
    out = apply_drafts(view, drafts)
    assert out["rows"] == view["rows"]


def test_apply_drafts_matches_by_finding_id_when_the_row_carries_one():
    view = {"rows": [{"finding_id": "f-nc-1", "comment": "machine text"}]}
    out = apply_drafts(view, {"f-nc-1": {"accepted": True, "comment": GOOD_NC,
                                         "action": None}})
    assert out["rows"][0]["comment"] == MODEL_DRAFT_PREFIX + GOOD_NC
    assert out["rows"][0]["machine_comment"] == "machine text"


def test_prefix_is_the_exact_agreed_string():
    assert MODEL_DRAFT_PREFIX == "[Draft by model - engineer to confirm] "


# ----------------------------------------------------------- containment

def test_module_imports_no_http_library():
    tree = ast.parse(Path(cc.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"httpx", "requests", "urllib", "urllib3",
                           "aiohttp", "socket", "http"}, imported
