"""`claude_selection`: the model proposes which standards apply; Python decides.

Every test runs against a FAKE model callable. No transport, no key, no
socket: the module takes `model_call(prompt) -> str` and nothing else, so a
fake that returns a string is the whole seam.

THE TESTS THAT MATTER MOST:
  * `test_contractual_without_a_citation_is_rejected_but_demonstration_is_kept`
    - the same standard refused on one basis and accepted on the other in a
    single answer, which is the gate doing the one thing it exists for.
  * `test_the_prompt_numbers_candidates_and_never_asks_for_a_name` - the
    one-sentence rule from `comparison.match_by_model`.
  * `test_two_runs_disagreeing_is_reported_as_unstable_not_dropped`.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app import claude_selection as cs
from app import applicability, db, submittal_review
from app.config import settings

# ------------------------------------------------------------- fixtures

CANDIDATES = [
    {"document_id": "doc-d001", "code": "SAES-D-001",
     "title": "Design Criteria for Pressure Vessels",
     "scope": "This standard covers the design of pressure vessels."},
    {"document_id": "doc-g005", "code": "SAES-G-005",
     "title": "Centrifugal Pumps",
     "scope": "Minimum requirements for centrifugal pumps in process service."},
    {"document_id": "doc-api610", "code": "API 610",
     "title": "Centrifugal Pumps for Petroleum Industries",
     "scope": "Specifies requirements for centrifugal pumps."},
]

SUMMARY = {
    "equipment_type": "pump", "discipline": "Mechanical", "service": "crude",
    "field_names": ["Design pressure", "Rated flow", "Noise level dB(A)"],
    "referenced_standards": ["API 610"],
    "text": "Pump shall comply with API 610.",
}


def answer(applicable=(), not_applicable=()) -> str:
    return json.dumps({"applicable": list(applicable),
                       "not_applicable": list(not_applicable)})


def fake(raw: str):
    """A model that always says `raw`. Records what it was asked."""
    def model_call(prompt: str) -> str:
        model_call.prompts.append(prompt)
        return raw
    model_call.prompts = []
    return model_call


def prop(index, basis="DEMONSTRATION", reason="Scope covers pumps.") -> dict:
    return {"index": index, "basis": basis, "reason": reason}


# --------------------------------------------------------------- prompt

def test_the_prompt_numbers_candidates_and_never_asks_for_a_name():
    prompt = cs.build_prompt(SUMMARY, CANDIDATES)
    for number, cand in enumerate(CANDIDATES, start=1):
        assert f"{number}. {cand['title']}" in prompt
    assert "answer by number" in prompt.lower()
    assert '"index": <n>' in prompt
    # The model is told NOT to name a standard, and no field asks for one.
    folded = " ".join(prompt.split())
    assert "Refer to a standard by its number ONLY" in folded
    assert "do not propose a standard that is not in the list" in folded
    assert '"name"' not in prompt and '"code"' not in prompt


def test_the_prompt_carries_the_summary_and_caps_the_scope_excerpt():
    long_scope = "x" * 1000
    prompt = cs.build_prompt(SUMMARY, [{**CANDIDATES[0], "scope": long_scope}])
    assert "equipment_type: pump" in prompt
    assert "discipline: Mechanical" in prompt
    assert "Noise level dB(A)" in prompt
    assert "API 610" in prompt
    assert "x" * cs.MAX_SCOPE_CHARS in prompt
    assert "x" * (cs.MAX_SCOPE_CHARS + 1) not in prompt


def test_the_prompt_explains_both_bases():
    prompt = cs.build_prompt(SUMMARY, CANDIDATES)
    assert "CONTRACTUAL" in prompt and "DEMONSTRATION" in prompt
    assert "names this standard" in prompt
    assert "not because" in prompt and "contract cites it" in prompt


def test_field_names_are_capped_at_forty():
    summary = {**SUMMARY, "field_names": [f"field {i}" for i in range(80)]}
    prompt = cs.build_prompt(summary, CANDIDATES)
    assert "field 39" in prompt
    assert "field 40" not in prompt


# ---------------------------------------------------------------- parse

def test_malformed_json_is_a_named_error_not_a_guess():
    proposals, err = cs.parse_response("I think standards 1 and 2 apply")
    assert proposals == []
    assert err == cs.Reason.MODEL_MALFORMED.value


@pytest.mark.parametrize("raw", ["[]", '{"applicable": "1"}', "null",
                                 '{"applicable": [1, 2]}'])
def test_wrong_shapes_are_malformed(raw):
    proposals, err = cs.parse_response(raw)
    assert proposals == [] and err == cs.Reason.MODEL_MALFORMED.value


def test_parse_keeps_verdict_index_basis_and_reason():
    proposals, err = cs.parse_response(answer(
        [{"index": "2", "basis": "contractual", "reason": "  cited  in note 8 "}],
        [{"index": 1, "reason": "vessel, not pump"}]))
    assert err is None
    assert proposals[0] == {"verdict": "applicable", "index": 2,
                            "basis": "CONTRACTUAL", "reason": "cited in note 8"}
    assert proposals[1]["verdict"] == "not_applicable"
    assert proposals[1]["basis"] is None


# ------------------------------------------------------------------ gate

def test_a_demonstration_proposal_with_a_reason_is_accepted_with_code_and_id():
    out = cs.accept([prop(2)], CANDIDATES, SUMMARY)
    assert len(out["accepted"]) == 1
    kept = out["accepted"][0]
    assert kept["code"] == "SAES-G-005"
    assert kept["document_id"] == "doc-g005"
    assert kept["confidence"] == 0.5
    assert out["rejected"] == [] and out["counts"] == {}


def test_an_out_of_range_index_is_rejected():
    out = cs.accept([prop(0), prop(4), {**prop(1), "index": None}],
                    CANDIDATES, SUMMARY)
    assert out["accepted"] == []
    assert [r["reason"] for r in out["rejected"]] == [
        cs.Reason.INDEX_OUT_OF_RANGE.value] * 3
    assert out["counts"] == {cs.Reason.INDEX_OUT_OF_RANGE.value: 3}


def test_a_word_where_an_index_should_be_is_out_of_range():
    """The model NAMED a standard instead of choosing one. Refused."""
    proposals, _ = cs.parse_response(answer(
        [{"index": "SAES-D-001", "basis": "DEMONSTRATION", "reason": "r"}]))
    out = cs.accept(proposals, CANDIDATES, SUMMARY)
    assert out["rejected"][0]["reason"] == cs.Reason.INDEX_OUT_OF_RANGE.value


def test_contractual_without_a_citation_is_rejected_but_demonstration_is_kept():
    """THE POINT OF THE GATE. SAES-D-001 is not cited by the datasheet."""
    proposals = [prop(1, "CONTRACTUAL", "The contract requires it.")]
    out = cs.accept(proposals, CANDIDATES, SUMMARY)
    assert out["accepted"] == []
    rej = out["rejected"][0]
    assert rej["reason"] == cs.Reason.CONTRACTUAL_NOT_REFERENCED.value
    assert rej["code"] == "SAES-D-001" and rej["document_id"] == "doc-d001"
    assert rej["model_reason"] == "The contract requires it."

    # The SAME standard as DEMONSTRATION is accepted.
    out2 = cs.accept([prop(1, "DEMONSTRATION")], CANDIDATES, SUMMARY)
    assert [a["code"] for a in out2["accepted"]] == ["SAES-D-001"]
    assert out2["accepted"][0]["confidence"] == 0.5


def test_contractual_with_a_citation_is_accepted_at_higher_confidence():
    out = cs.accept([prop(3, "CONTRACTUAL", "Datasheet cites API 610.")],
                    CANDIDATES, SUMMARY)
    assert out["accepted"][0]["code"] == "API 610"
    assert out["accepted"][0]["confidence"] == 0.8


def test_a_citation_found_only_in_the_datasheet_text_counts():
    """`referenced_standards` empty, but the text names SAES-D-001."""
    summary = {**SUMMARY, "referenced_standards": [],
               "text": "Vessel per SAES-D-001 latest edition."}
    out = cs.accept([prop(1, "CONTRACTUAL", "cited")], CANDIDATES, summary)
    assert [a["code"] for a in out["accepted"]] == ["SAES-D-001"]


def test_citation_and_code_meet_across_zero_padding_and_spacing():
    """SAES-B-14 in a filename-derived code, SAES-B-014 in the citation."""
    cand = [{"document_id": "b14", "code": "SAES-B-14", "title": "t", "scope": ""}]
    summary = {"referenced_standards": ["SAES-B-014"]}
    assert cs.is_referenced("SAES-B-14", summary)
    out = cs.accept([prop(1, "CONTRACTUAL", "cited")], cand, summary)
    assert len(out["accepted"]) == 1
    assert cs.is_referenced("API-610", {"referenced_standards": ["API 610"]})
    assert not cs.is_referenced("API 611", {"referenced_standards": ["API 610"]})
    assert not cs.is_referenced(None, SUMMARY)


def test_an_unknown_basis_is_rejected():
    out = cs.accept([prop(2, "MAYBE"), {**prop(2), "basis": None}],
                    CANDIDATES, SUMMARY)
    assert out["accepted"] == []
    # The first is basis_unknown; the second is the same index again and is
    # reported as duplicate BEFORE its basis is looked at.
    assert [r["reason"] for r in out["rejected"]] == [
        cs.Reason.BASIS_UNKNOWN.value, cs.Reason.DUPLICATE_INDEX.value]


def test_a_missing_reason_is_rejected():
    out = cs.accept([prop(2, reason=""), prop(3, reason="   ")], CANDIDATES, SUMMARY)
    assert out["accepted"] == []
    assert out["counts"] == {cs.Reason.REASON_MISSING.value: 2}


def test_a_duplicate_index_keeps_the_first_and_names_the_second():
    out = cs.accept([prop(2, "DEMONSTRATION"), prop(2, "CONTRACTUAL", "again")],
                    CANDIDATES, SUMMARY)
    assert [a["basis"] for a in out["accepted"]] == ["DEMONSTRATION"]
    rej = out["rejected"][0]
    assert rej["reason"] == cs.Reason.DUPLICATE_INDEX.value
    assert rej["code"] == "SAES-G-005"


def test_not_applicable_entries_are_kept_as_declined_never_stored():
    proposals, _ = cs.parse_response(answer(
        [prop(2)], [{"index": 1, "reason": "vessel, not pump"}]))
    out = cs.accept(proposals, CANDIDATES, SUMMARY)
    assert [a["code"] for a in out["accepted"]] == ["SAES-G-005"]
    assert [d["code"] for d in out["declined"]] == ["SAES-D-001"]
    assert out["rejected"] == []


def test_rejection_counts_totals():
    rejected = [{"reason": "a"}, {"reason": "b"}, {"reason": "a"}]
    assert cs.rejection_counts(rejected) == {"a": 2, "b": 1}
    assert cs.rejection_counts([]) == {}
    out = cs.accept([prop(0), prop(9), prop(1, "CONTRACTUAL"), prop(2, "X")],
                    CANDIDATES, SUMMARY)
    assert sum(out["counts"].values()) == len(out["rejected"]) == 4


# ------------------------------------------------------------- two runs

def test_two_runs_agreeing_pass_the_gate():
    model = fake(answer([prop(2), prop(3, "CONTRACTUAL", "cited")]))
    out = cs.select_standards(SUMMARY, CANDIDATES, model)
    assert out["error"] is None
    assert sorted(a["code"] for a in out["accepted"]) == ["API 610", "SAES-G-005"]
    assert out["rejected"] == []
    # Asked twice, and the same prompt both times.
    assert len(model.prompts) == 2 and model.prompts[0] == model.prompts[1]
    assert out["prompt"] == model.prompts[0]


def test_two_runs_disagreeing_is_reported_as_unstable_not_dropped():
    first = fake(answer([prop(2, "DEMONSTRATION"), prop(3, "CONTRACTUAL", "c")]))
    second = fake(answer([prop(2, "CONTRACTUAL"), prop(3, "CONTRACTUAL", "c")]))
    out = cs.select_standards(SUMMARY, CANDIDATES, first, second_call=second)
    assert [a["code"] for a in out["accepted"]] == ["API 610"]
    unstable = [r for r in out["rejected"]
                if r["reason"] == cs.Reason.MODEL_UNSTABLE.value]
    assert len(unstable) == 1
    assert unstable[0]["code"] == "SAES-G-005"
    assert unstable[0]["document_id"] == "doc-g005"
    assert out["counts"] == {cs.Reason.MODEL_UNSTABLE.value: 1}


def test_a_malformed_second_run_accepts_nothing():
    first = fake(answer([prop(2)]))
    second = fake("not json")
    out = cs.select_standards(SUMMARY, CANDIDATES, first, second_call=second)
    assert out["error"] == cs.Reason.MODEL_MALFORMED.value
    assert out["accepted"] == []


def test_the_gate_still_runs_on_stable_proposals():
    """Both runs agree on an uncited CONTRACTUAL claim: still rejected."""
    model = fake(answer([prop(1, "CONTRACTUAL", "contract")]))
    out = cs.select_standards(SUMMARY, CANDIDATES, model)
    assert out["accepted"] == []
    assert out["counts"] == {cs.Reason.CONTRACTUAL_NOT_REFERENCED.value: 1}


# ------------------------------------------------------------ the reason

def test_selection_reason_starts_with_the_exact_prefix():
    text = cs.selection_reason("DEMONSTRATION", "Scope covers pumps.")
    assert text.startswith("Proposed by model; engineer must confirm. Basis: DEMONSTRATION. ")
    assert text.endswith("Scope covers pumps.")


# --------------------------------------------------------------- storage

@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename, f"h-{doc_id}"))
    return doc_id


def _run(submittal_id: str) -> str:
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run_id, submittal_id))
    return run_id


def _rows(run_id: str) -> dict:
    rows = db.connect().execute(
        "SELECT * FROM review_applicable_standards WHERE review_run_id = ?",
        (run_id,)).fetchall()
    return {r["standard_document_id"]: dict(r) for r in rows}


def test_candidates_from_corpus_carry_code_title_and_scope(temp_storage):
    _doc("std_d001", "SAES-D-1 Rev 3.pdf", "COMPANY_STANDARD",
         text="Scope. This standard covers pressure vessels. " + "y" * 600,
         title="Design Criteria for Pressure Vessels")
    _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
         document_number="API 610", text="Centrifugal pumps.")
    _doc("std_old", "SAES-D-1 Rev 2.pdf", "COMPANY_STANDARD",
         superseded_by="std_d001")
    _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text="a datasheet")
    cands = cs.candidates_from_corpus(
        allowed_document_ids=frozenset({"std_d001", "std_610", "std_old", "sub"}))
    by_id = {c["document_id"]: c for c in cands}
    # Only selectable standards: no submittal, no superseded revision.
    assert set(by_id) == {"std_d001", "std_610"}
    assert by_id["std_d001"]["code"] == "SAES-D-001"        # padded from the filename
    assert by_id["std_d001"]["title"] == "Design Criteria for Pressure Vessels"
    assert by_id["std_d001"]["scope"].startswith("Scope. This standard covers")
    assert len(by_id["std_d001"]["scope"]) <= cs.MAX_SCOPE_CHARS
    assert by_id["std_610"]["code"] == "API 610"           # the recorded number


def test_candidates_from_corpus_respects_scope(temp_storage):
    _doc("std_a", "SAES-A-001.pdf", "COMPANY_STANDARD")
    _doc("std_b", "SAES-B-001.pdf", "COMPANY_STANDARD")
    cands = cs.candidates_from_corpus(allowed_document_ids=frozenset({"std_a"}))
    assert [c["document_id"] for c in cands] == ["std_a"]
    assert cs.candidates_from_corpus(allowed_document_ids=frozenset()) == []


def test_code_of_reads_number_then_filename_then_title():
    assert cs.code_of({"document_number": "API 610"}) == "API 610"
    assert cs.code_of({"filename": "SAES-B-14 -Final Draft.pdf"}) == "SAES-B-014"
    assert cs.code_of({"title": "Piping per ASME B31.3 requirements",
                       "filename": "piping.pdf"}) == "ASME B31.3"
    assert cs.code_of({"filename": "notes.pdf", "title": "Notes"}) is None


def test_store_selection_writes_model_rows_with_prefix_and_confidence(temp_storage):
    std1 = _doc("std_d001", "SAES-D-001.pdf", "COMPANY_STANDARD")
    std2 = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text="per API 610")
    run = _run(sub)
    scope = frozenset({std1, std2, sub})
    cands = cs.candidates_from_corpus(allowed_document_ids=scope)
    by_code = {c["code"]: c for c in cands}
    index = lambda code: cands.index(by_code[code]) + 1
    model = fake(answer([
        prop(index("SAES-D-001"), "DEMONSTRATION", "Scope covers vessels."),
        prop(index("API 610"), "CONTRACTUAL", "Datasheet cites it."),
    ]))
    out = cs.select_standards(SUMMARY, cands, model)
    assert len(out["accepted"]) == 2
    result = cs.store_selection(run, out["accepted"], cands, allowed_document_ids=scope)
    assert len(result["written"]) == 2
    rows = _rows(run)
    assert rows[std1]["selection_method"] == "model"
    assert rows[std1]["selection_reason"] == (
        "Proposed by model; engineer must confirm. Basis: DEMONSTRATION. "
        "Scope covers vessels.")
    assert rows[std1]["confidence"] == 0.5 and rows[std1]["included"] == 1
    assert rows[std2]["selection_reason"].startswith(
        "Proposed by model; engineer must confirm. Basis: CONTRACTUAL. ")
    assert rows[std2]["confidence"] == 0.8
    # Readable through the existing scoped listing.
    listed = submittal_review.list_applicable_standards(run, allowed_document_ids=scope)
    assert {r["standard_document_id"] for r in listed} == {std1, std2}


def test_store_selection_never_overwrites_an_engineers_row(temp_storage):
    std = _doc("std_d001", "SAES-D-001.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    scope = frozenset({std, sub})
    applicability.record_selection(
        review_run_id=run, standard_document_id=std,
        method=applicability.METHOD_MANUAL, reason="engineer excluded it",
        included=False, exclusion_reason="not this project")
    cands = cs.candidates_from_corpus(allowed_document_ids=scope)
    accepted = cs.accept([prop(1, "DEMONSTRATION")], cands, SUMMARY)["accepted"]
    result = cs.store_selection(run, accepted, cands, allowed_document_ids=scope)
    assert result["written"] == []
    assert [k["existing_method"] for k in result["kept_existing"]] == ["manual"]
    row = _rows(run)[std]
    assert row["selection_method"] == "manual"
    assert row["included"] == 0 and row["selection_reason"] == "engineer excluded it"


def test_store_selection_replaces_only_its_own_earlier_row(temp_storage):
    std = _doc("std_d001", "SAES-D-001.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    scope = frozenset({std, sub})
    cands = cs.candidates_from_corpus(allowed_document_ids=scope)
    first = cs.accept([prop(1, "DEMONSTRATION", "first")], cands, SUMMARY)["accepted"]
    cs.store_selection(run, first, cands, allowed_document_ids=scope)
    second = cs.accept([prop(1, "DEMONSTRATION", "second")], cands, SUMMARY)["accepted"]
    result = cs.store_selection(run, second, cands, allowed_document_ids=scope)
    assert len(result["written"]) == 1
    rows = _rows(run)
    assert len(rows) == 1 and rows[std]["selection_reason"].endswith("second")


def test_store_selection_skips_a_standard_outside_scope(temp_storage):
    std = _doc("std_d001", "SAES-D-001.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    cands = cs.candidates_from_corpus(allowed_document_ids=frozenset({std, sub}))
    accepted = cs.accept([prop(1)], cands, SUMMARY)["accepted"]
    result = cs.store_selection(run, accepted, cands,
                                allowed_document_ids=frozenset({sub}))
    assert result["written"] == []
    assert result["skipped"][0]["why"] == "standard not in scope"
    assert _rows(run) == {}


def test_the_module_opens_no_socket():
    import inspect
    source = inspect.getsource(cs)
    for name in ("httpx", "requests", "urllib", "socket", "aiohttp"):
        assert f"import {name}" not in source
