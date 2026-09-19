"""Phase 5B: the compliance comparison engine.

THE TWO TESTS THAT MATTER MOST are the PSV exception case and the
missing-information case. The first prevents a false breach against a
compliant valve; the second prevents a finding against a vendor who was never
asked. Everything else is scaffolding around those two.

All four species lessons applied: through the pipeline not the helper, a
positive assertion before any absence, and where a guard is targeted the test
checks that guard is the only thing holding the behaviour.

Mutations: M64-M72, `python scripts/mutation_check.py --phase 7`.
"""

from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, standards, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "cmp.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, pages: int = 1, **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename, pages))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
    return doc_id


def _chunk(chunk_id: str, doc_id: str, page: int = 1, text: str = "x") -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,?,?,NULL,'prose',?,1,?,1)""",
            (chunk_id, doc_id, "f.pdf", page, page, text, f"h-{chunk_id}"))
    return chunk_id


def _run(submittal_id: str) -> str:
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run_id, submittal_id))
    return run_id


def _requirement(standard_id: str, chunk_id: str, **fields) -> dict:
    """A requirement as `standards.list_requirements` returns one."""
    base = {
        "id": str(uuid.uuid4()),
        "standard_document_id": standard_id,
        "chunk_id": chunk_id,
        "clause": "5.3.3",
        "page": 1,
        "requirement_text": "The noise level shall not exceed 90 dB(A).",
        "source_text": "The noise level shall not exceed 90 dB(A).",
        "operator": "<=",
        "raw_value": "90",
        "raw_unit": "dB(A)",
        "field": "noise level",
        "exceptions": [],
    }
    base.update(fields)
    return base


def _fact(submittal_id: str, chunk_id: str, **fields) -> dict:
    """A fact as `datasheets.list_facts` returns one."""
    base = {
        "id": str(uuid.uuid4()),
        "submittal_document_id": submittal_id,
        "chunk_id": chunk_id,
        "field_name": "noise level",
        "field_label": "Noise level",
        "field_value": "95 dB(A)",
        "raw_value": "95",
        "raw_unit": "dB(A)",
        "page": 1,
        "section": None,
        "is_blank": 0,
        "blank_marker": None,
    }
    base.update(fields)
    return base


def _scope(*ids): return frozenset(ids)


# ============================================== deterministic numeric verdict

def test_a_numeric_breach_is_caught_with_both_citations():
    """THE MUTATION TARGET (M64). 95 dB(A) against a <= 90 dB(A) limit."""
    std = _doc("std", "SAES-A-105.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)

    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    verdict = comparison.compare(requirement, fact)
    assert verdict["status"] == comparison.NON_COMPLIANT

    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=fact, verdict=verdict)

    assert finding["compliance_status"] == comparison.NON_COMPLIANT
    # BOTH CITATIONS, and both resolve.
    assert finding["standard_clause"] == "5.3.3"
    assert finding["standard_page"] == 1
    assert finding["standard_document_id"] == std
    assert finding["contractor_page"] == 1
    assert finding["contractor_evidence_text"] == "95 dB(A)"
    assert finding["citation_resolves"] is True
    # The rationale is stored SEPARATELY from the comment.
    assert finding["ai_rationale"]
    assert "90" in finding["ai_rationale"] and "95" in finding["ai_rationale"]


def test_a_value_within_the_limit_is_compliant():
    """The control: the same machinery must also clear a passing value."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    verdict = comparison.compare(
        _requirement(std, sc), _fact(sub, fc, raw_value="85"))
    assert verdict["status"] == comparison.COMPLIANT


# ==================================================== THE PSV EXCEPTION CASE

def test_a_psv_at_108_db_is_compliant_because_the_exception_applied():
    """THE MUTATION TARGET (M65), AND THE CASE THE PLAN IS WRITTEN AROUND.

    SAES-A-105 caps equipment at 90 dB(A) with an exception allowing pressure
    relief valves 115 dB(A). A PSV at 108 is COMPLIANT. An engine that drops
    the exception reports a false breach against a compliant valve.
    """
    std = _doc("std", "SAES-A-105.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)

    requirement = _requirement(std, sc, exceptions=[{
        "applies_to": "pressure relief valves",
        "operator": "<=", "raw_value": "115", "raw_unit": "dB(A)",
    }])
    fact = _fact(sub, fc, raw_value="108", field_value="108 dB(A)")

    # POSITIVE FIRST: without the exception this same value IS a breach, so
    # the test is standing where the exception can fail it. Without this the
    # test would pass on an engine that called everything compliant.
    general = comparison.compare(_requirement(std, sc), fact, subject="pressure relief valve")
    assert general["status"] == comparison.NON_COMPLIANT

    verdict = comparison.compare(requirement, fact, subject="pressure relief valve")
    assert verdict["status"] == comparison.COMPLIANT, \
        "the exception was dropped and a compliant valve was reported as a breach"
    assert verdict["exception_applied"] is not None
    assert "pressure relief valve" in verdict["rationale"]


def test_the_exception_does_not_excuse_equipment_it_does_not_cover():
    """An exception applied too eagerly EXCUSES a real breach - the more
    dangerous direction."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    requirement = _requirement(std, sc, exceptions=[{
        "applies_to": "pressure relief valves",
        "operator": "<=", "raw_value": "115", "raw_unit": "dB(A)",
    }])
    # A PUMP at 108 is still a breach: the exception is not about pumps.
    verdict = comparison.compare(
        requirement, _fact(sub, fc, raw_value="108"), subject="centrifugal pump")
    assert verdict["status"] == comparison.NON_COMPLIANT
    assert verdict["exception_applied"] is None


def test_an_unknown_subject_gets_the_general_limit():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    requirement = _requirement(std, sc, exceptions=[{
        "applies_to": "pressure relief valves",
        "operator": "<=", "raw_value": "115", "raw_unit": "dB(A)"}])
    verdict = comparison.compare(
        requirement, _fact(sub, fc, raw_value="108"), subject=None)
    assert verdict["status"] == comparison.NON_COMPLIANT


# ============================================= MISSING INFORMATION, NOT FAILURE

def test_a_blank_by_contractor_field_is_missing_information_never_non_compliant():
    """THE MUTATION TARGET (M66).

    Manufacturing a finding against a vendor who was never asked is the worst
    output this system could produce.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)

    blank = _fact(sub, fc, raw_value=None, raw_unit=None, is_blank=1,
                  blank_marker="By Contractor", field_value="By Contractor / Vendor")
    requirement = _requirement(std, sc)

    verdict = comparison.compare(requirement, blank)
    assert verdict["status"] == comparison.MISSING_INFORMATION, \
        "a blank field was turned into a failure"
    assert verdict["status"] != comparison.NON_COMPLIANT

    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=blank, verdict=verdict)
    assert finding["compliance_status"] == comparison.MISSING_INFORMATION
    assert "provide" in finding["required_action"].lower()
    # The sheet's own words survive so a reader can see what it said.
    assert "Contractor" in finding["contractor_evidence_text"]


def test_a_requirement_with_no_matching_field_is_missing_information():
    """"This system could not find the field" is not "the contractor got it
    wrong"."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std)
    verdict = comparison.compare(_requirement(std, sc), None)
    assert verdict["status"] == comparison.MISSING_INFORMATION


def test_missing_information_does_not_block_approval():
    """It is not a failure, so it does not reject - and not nothing, so it
    does not approve silently."""
    findings = [{"compliance_status": comparison.MISSING_INFORMATION}]
    complete = {"sufficient": True, "fields_read": 100, "fields_estimated": 100}
    result = comparison.recommend_code(findings, complete)
    assert result["code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert result["code"] != comparison.CODE_REJECTED


# ================================================= citations must both resolve

def test_a_finding_whose_standard_citation_does_not_resolve_is_refused():
    """THE MUTATION TARGET (M67). Downgraded, never stored as a verdict."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    fc = _chunk("fc", sub)
    run = _run(sub)

    # POSITIVE FIRST: with a real standard chunk this same finding is a breach.
    sc = _chunk("sc", std)
    good = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=_requirement(std, sc), fact=_fact(sub, fc),
        verdict=comparison.compare(_requirement(std, sc), _fact(sub, fc)))
    assert good["compliance_status"] == comparison.NON_COMPLIANT

    # Now with a standard chunk that does not exist.
    bad = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=_requirement(std, "no-such-chunk"), fact=_fact(sub, fc),
        verdict=comparison.compare(_requirement(std, "no-such-chunk"), _fact(sub, fc)))
    assert bad["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert bad["citation_resolves"] is False
    assert any("standard citation" in u for u in bad["unresolved_evidence"])


def test_a_finding_whose_contractor_citation_does_not_resolve_is_refused():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std)
    run = _run(sub)
    fact = _fact(sub, "no-such-chunk")
    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=_requirement(std, sc), fact=fact,
        verdict=comparison.compare(_requirement(std, sc), fact))
    assert finding["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert any("contractor citation" in u for u in finding["unresolved_evidence"])


def test_a_citation_pointing_at_another_document_is_refused():
    """A citation that opens the WRONG document is worse than one that opens
    nothing: a reader who follows it sees something real and believes it."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    other = _doc("other", "o.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); oc = _chunk("oc", other)
    run = _run(sub)
    fact = _fact(sub, oc)          # a chunk belonging to `other`
    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=_requirement(std, sc), fact=fact,
        verdict=comparison.compare(_requirement(std, sc), fact))
    assert finding["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW


# ======================================================== units and unknowns

def test_an_unknown_unit_yields_no_comparison_rather_than_a_guess():
    """THE MUTATION TARGET (M68). pcf against dB(A) cannot be compared."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    verdict = comparison.compare(
        _requirement(std, sc), _fact(sub, fc, raw_value="12", raw_unit="pcf"))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "cannot be compared" in verdict["rationale"]
    # NOT a pass and NOT a failure: no comparison was made.
    assert verdict["status"] not in (comparison.COMPLIANT, comparison.NON_COMPLIANT)


def test_same_unit_db_values_do_compare():
    """The phase 4 claims.py fix, exercised through this engine."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    assert comparison.compare(
        _requirement(std, sc), _fact(sub, fc, raw_value="95")
    )["status"] == comparison.NON_COMPLIANT


def test_a_requirement_with_no_numeric_limit_is_not_a_failure():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    verdict = comparison.compare(
        _requirement(std, sc, raw_value=None, raw_unit=None), _fact(sub, fc))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert verdict["status"] != comparison.NON_COMPLIANT


# ================================== the model describes, python decides

def test_the_model_disagreeing_does_not_change_the_verdict():
    """THE MUTATION TARGET (M69). Section 14's hard line.

    The model may be better at reading a clause. It is not better at deciding
    whether 95 is under 90.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)                       # 95 against <= 90: a breach
    verdict = comparison.compare(requirement, fact)
    assert verdict["status"] == comparison.NON_COMPLIANT

    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=fact, verdict=verdict,
        model_opinion=comparison.COMPLIANT)     # the model says it passes

    assert finding["compliance_status"] == comparison.NON_COMPLIANT, \
        "the model overruled the arithmetic"
    # AND THE DISAGREEMENT IS RECORDED rather than discarded.
    assert "deterministic result stands" in finding["ai_rationale"]
    assert comparison.COMPLIANT in finding["ai_rationale"]


def test_an_agreeing_model_records_no_disagreement():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=fact, verdict=comparison.compare(requirement, fact),
        model_opinion=comparison.NON_COMPLIANT)
    assert "deterministic result stands" not in finding["ai_rationale"]


def test_confidence_is_never_high():
    """CLAUDE.md rule 4."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=fact, verdict=comparison.compare(requirement, fact))
    assert finding["confidence"] in ("low", "medium")
    assert finding["confidence"] != "high"


# ================================================ completeness gates the code

def test_low_completeness_forces_manual_review_even_with_zero_breaches():
    """THE MUTATION TARGET (M70), AND THE MOST DANGEROUS OUTPUT PREVENTED.

    A review that examined nine fields and returns "Approved with Comments" is
    making a claim about the 240 nobody looked at.
    """
    findings = [{"compliance_status": comparison.COMPLIANT}]
    poor = {"sufficient": False, "fields_read": 9, "fields_estimated": 250}

    # POSITIVE FIRST: with the SAME findings and sufficient completeness this
    # is an approval, so the gate is the only thing changing the answer.
    good = {"sufficient": True, "fields_read": 240, "fields_estimated": 250}
    assert comparison.recommend_code(findings, good)["code"] == comparison.CODE_APPROVED

    result = comparison.recommend_code(findings, poor)
    assert result["code"] == comparison.CODE_MANUAL
    assert result["code"] not in (comparison.CODE_APPROVED,
                                  comparison.CODE_APPROVED_WITH_COMMENTS)
    # REPORTED WITH ITS DENOMINATOR.
    assert "9" in result["reason"] and "250" in result["reason"]


def test_completeness_is_the_weakest_link_not_the_average():
    """A review with every standard present but a tenth of the sheet read is a
    tenth of a review."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=2)
    scope = _scope(sub)
    result = comparison.completeness_for_run(
        sub, allowed_document_ids=scope, reference_coverage=1.0)
    # No facts extracted at all, so extraction is 0 and completeness follows
    # it rather than averaging up to 0.5.
    assert result["extraction_coverage"] == 0.0
    assert result["completeness"] == 0.0
    assert result["sufficient"] is False


def test_completeness_reports_its_denominator():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=7)
    result = comparison.completeness_for_run(sub, allowed_document_ids=_scope(sub))
    assert result["fields_estimated"] == 7 * 35
    assert result["pages"] == 7
    assert "fields_read" in result


def test_an_unevaluable_requirement_forces_manual_review():
    findings = [{"compliance_status": comparison.NEEDS_ENGINEER_REVIEW}]
    complete = {"sufficient": True, "fields_read": 100, "fields_estimated": 100}
    assert comparison.recommend_code(
        findings, complete)["code"] == comparison.CODE_MANUAL


def test_a_breach_rejects():
    findings = [{"compliance_status": comparison.NON_COMPLIANT}]
    complete = {"sufficient": True, "fields_read": 100, "fields_estimated": 100}
    assert comparison.recommend_code(
        findings, complete)["code"] == comparison.CODE_REJECTED


def test_review_codes_are_configurable():
    """Section 15: the client may use different names or numbers."""
    findings = [{"compliance_status": comparison.NON_COMPLIANT}]
    complete = {"sufficient": True, "fields_read": 10, "fields_estimated": 10}
    custom = ("Code 1", "Code 2", "Code 3", "Code 4")
    assert comparison.recommend_code(
        findings, complete, codes=custom)["code"] == "Code 3"


# ============================================ the engineer decides, not the AI

def test_the_engineer_can_override_the_recommendation_with_a_reason():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=1)
    run = _run(sub)
    scope = _scope(sub)
    comparison._store_run_outcome(
        run, {"code": comparison.CODE_MANUAL, "reason": "low completeness"},
        {"completeness": 0.1})

    outcome = comparison.record_engineer_code(
        run, code=comparison.CODE_APPROVED, reviewer="eng@example.test",
        override_reason="checked the remaining fields by hand",
        allowed_document_ids=scope, actor={"id": None, "email": "eng@example.test"})

    assert outcome["final_code"] == comparison.CODE_APPROVED
    assert outcome["recommended_code"] == comparison.CODE_MANUAL
    assert outcome["override_reason"]
    assert outcome["reviewer"] == "eng@example.test"
    audit = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'review.code_recorded'").fetchone()
    assert audit is not None, "the engineer's decision wrote no audit row"


def test_overriding_without_a_reason_is_refused():
    """THE MUTATION TARGET (M71). An override with no reason is
    indistinguishable from a mistake six months later."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    comparison._store_run_outcome(
        run, {"code": comparison.CODE_MANUAL, "reason": "x"}, {})
    with pytest.raises(comparison.ComparisonError):
        comparison.record_engineer_code(
            run, code=comparison.CODE_APPROVED, reviewer="e",
            override_reason="   ", allowed_document_ids=_scope(sub))


def test_agreeing_with_the_recommendation_needs_no_reason():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    comparison._store_run_outcome(
        run, {"code": comparison.CODE_MANUAL, "reason": "x"}, {})
    outcome = comparison.record_engineer_code(
        run, code=comparison.CODE_MANUAL, reviewer="e",
        allowed_document_ids=_scope(sub))
    assert outcome["final_code"] == comparison.CODE_MANUAL
    assert outcome["override_reason"] is None


# ================================================================ permissions

def test_an_unauthorised_caller_sees_no_findings_for_a_run():
    """THE MUTATION TARGET (M72)."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    mine = _doc("sub_mine", "m.pdf", "CONTRACTOR_SUBMITTAL")
    theirs = _doc("sub_theirs", "t.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); tc = _chunk("tc", theirs)
    their_run = _run(theirs)
    requirement = _requirement(std, sc)
    fact = _fact(theirs, tc)
    comparison.create_finding(
        review_run_id=their_run, submittal_document_id=theirs,
        requirement=requirement, fact=fact,
        verdict=comparison.compare(requirement, fact))

    # POSITIVE FIRST: the owner can read it.
    assert comparison.list_findings(
        their_run, allowed_document_ids=_scope(std, theirs))
    # And a caller granted only their own submittal cannot.
    assert comparison.list_findings(
        their_run, allowed_document_ids=_scope(mine)) == []
    assert comparison.run_outcome(
        their_run, allowed_document_ids=_scope(mine)) is None


def test_an_empty_grant_set_sees_nothing():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    assert comparison.list_findings(run, allowed_document_ids=frozenset()) == []
    assert comparison.run_outcome(run, allowed_document_ids=frozenset()) is None


def test_running_a_comparison_for_an_unreadable_run_is_refused():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    other = _doc("other", "o.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    with pytest.raises(comparison.ComparisonError):
        comparison.run_comparison(run, allowed_document_ids=_scope(other))


@pytest.mark.parametrize("call", [
    lambda: comparison.run_comparison("r"),
    lambda: comparison.list_findings("r"),
    lambda: comparison.run_outcome("r"),
    lambda: comparison.completeness_for_run("d"),
    lambda: comparison.record_engineer_code("r", code="x", reviewer=None),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    with pytest.raises(TypeError):
        call()


# =========================================================== end to end

def test_a_full_run_writes_findings_into_the_phase_1_columns():
    """The phase 1 columns, filled at last - not a second table."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=1,
               discipline="Mechanical")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)

    standards.create_requirement(
        standard_document_id=std, chunk_id=sc,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).",
        clause="5.3.3", page=1,
        # `subject`, not `field`: the pipeline pairs a requirement to a fact by
        # CONTAINMENT of the field name inside the subject. `field` stays NULL
        # everywhere in production - the measured exact-match rate against it
        # was 0 of 77 - so a fixture relying on it tested a join the pipeline
        # no longer performs.
        structured={"subject": "noise level", "operator": "<=",
                    "raw_value": "90", "raw_unit": "dB(A)",
                    "requirement_type": "numeric_limit"})
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id=fc, field_label="Noise level",
        raw_value="95 dB(A)", page=1)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,?,'cited','referenced',1,'2026-09-18T00:00:00Z')""",
            (str(uuid.uuid4()), run, std))

    scope = _scope(std, sub)
    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert result["requirements_evaluated"] == 1
    assert result["by_status"][comparison.NON_COMPLIANT] == 1
    row = db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ?", (run,)).fetchone()
    assert row is not None, "the phase 1 columns are still empty"
    assert row["compliance_status"] == comparison.NON_COMPLIANT
    assert row["standard_clause"] == "5.3.3"
    assert row["contractor_page"] == 1
    assert row["ai_rationale"]
    # One page of facts against a 35-slot estimate gates the code.
    assert result["recommended_code"]["code"] == comparison.CODE_MANUAL


def test_re_running_a_comparison_does_not_double_the_findings():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=1)
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    standards.create_requirement(
        standard_document_id=std, chunk_id=sc, requirement_text="r",
        source_text="r", clause="1.1", page=1,
        structured={"field": "noise level", "operator": "<=",
                    "raw_value": "90", "raw_unit": "dB(A)"})
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id=fc, field_label="Noise level",
        raw_value="95 dB(A)", page=1)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,?,'cited','referenced',1,'2026-09-18T00:00:00Z')""",
            (str(uuid.uuid4()), run, std))
    scope = _scope(std, sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    comparison.run_comparison(run, allowed_document_ids=scope)
    count = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?",
        (run,)).fetchone()[0]
    assert count == 1


def test_the_completeness_denominator_says_it_is_nominal():
    """"42 of approximately 385 fields" reads like somebody counted the sheet.

    Nobody did. 385 is the page count times a nominal 35 slots per page, a
    figure taken from OTHER datasheets - an estimate of an estimate. A reader
    who believes it was measured here also believes 42/385 means something
    about this document's coverage.
    """
    reason = comparison._insufficient_reason(
        {"fields_read": 42, "fields_estimated": 385, "pages": 11})

    assert "NOMINAL ESTIMATE" in reason
    assert "not a count of this document" in reason
    assert "42" in reason and "385" in reason, "the counts must still be shown"
