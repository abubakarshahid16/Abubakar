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

from app import applicability, comparison, datasheets, db, review, standards, submittal_review
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


def _user(user_id: str = "eng") -> str:
    """A REAL ENGINEER, because `decided_by` references `users(id)`.

    `reviewer` is written to that column, so a fixture passing an email or a
    bare initial made the schema refuse the write - the same FK `confirmed_by`
    has always had. The fixture is what was wrong, not the constraint.
    """
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "created_at) VALUES (?,?,?,'h','2026-09-18T00:00:00Z')",
            (user_id, f"{user_id}@example.test", user_id))
    return user_id


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


def test_a_machine_finding_starts_its_history_pending_and_unsigned():
    """B10: the audit trail says the REVIEW wrote the finding - no person, and
    pending. It used to start at the first human edit."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=fact, verdict=comparison.compare(requirement, fact))
    events = review.history(finding["id"])
    assert [e["event_type"] for e in events] == ["created_by_review"]
    assert events[0]["actor_user_id"] is None
    assert events[0]["changes"]["approval_status"] == "pending"
    assert events[0]["changes"]["review_run_id"] == run


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


# ------------------------------------------ B9: NOT_IN_DOCUMENT_SCOPE, rule R1

_STATEMENT = {
    "requirement_type": "statement", "operator": None, "raw_value": None,
    "raw_unit": None, "field": None,
    "requirement_text": "Welding procedures shall be qualified before production welding.",
    "source_text": "Welding procedures shall be qualified before production welding.",
}


def test_an_unmatched_statement_is_not_in_document_scope_not_missing():
    """B9, R1. A statement names no field or value a datasheet could fill in,
    so a datasheet that does not state it has omitted nothing."""
    verdict = comparison.compare(_requirement("std", "c1", **_STATEMENT), None)
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE
    assert verdict["status"] != comparison.MISSING_INFORMATION


def test_an_unmatched_limit_is_still_missing_information():
    """Control: R1 moves statements ONLY. A limit the sheet should state and
    does not is still the contractor's omission."""
    verdict = comparison.compare(_requirement("std", "c1"), None)
    assert verdict["status"] == comparison.MISSING_INFORMATION


def test_a_statement_that_met_a_blank_field_is_still_the_contractors_to_fill(tmp_path):
    """R1 applies only when NOTHING matched. A statement paired with a field
    the sheet leaves "By Contractor" is a real omission."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    blank = _fact(sub, _chunk("fc", sub), raw_value=None, field_value="By Contractor",
                  is_blank=1, blank_marker="By Contractor")
    verdict = comparison.compare(_requirement("std", "c1", **_STATEMENT), blank)
    assert verdict["status"] == comparison.MISSING_INFORMATION


def test_required_evidence_type_of_a_certificate_is_not_in_document_scope():
    """Issue #163, criterion 4. A numeric_limit clause that ALSO names its own
    evidence ("... confirmed by a calibration certificate to within 0.5%")
    must not be answered from the datasheet just because a field happens to
    carry a matching name and a passing value - the certificate is a
    different document than the one under review."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    requirement = _requirement(std, sc, required_evidence_type="certificate")
    # A VALUE THAT WOULD OTHERWISE READ COMPLIANT. Proves the gate fires
    # before the arithmetic, not merely on an absent fact.
    fact = _fact(sub, fc, raw_value="85")

    verdict = comparison.compare(requirement, fact)

    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE
    assert verdict["status"] not in (comparison.COMPLIANT, comparison.NON_COMPLIANT)
    assert comparison.REQUIRES_OTHER_DOCUMENT in verdict["rationale"]


def test_required_evidence_type_of_a_certificate_with_no_fact_is_not_missing_information():
    """The other half of criterion 4: 'never contractor-missing information'.
    Before this a requirement demanding a certificate, with no field to pair
    it against at all, fell through to MISSING_INFORMATION - the wrong-
    document case must read the same whether or not a field name happened to
    match."""
    verdict = comparison.compare(
        _requirement("std", "c1", required_evidence_type="certificate"), None)
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE
    assert verdict["status"] != comparison.MISSING_INFORMATION


def test_required_evidence_type_of_a_data_sheet_is_unaffected():
    """CONTROL. `data_sheet` is the one evidence type this engine actually
    reads, so a requirement naming it must still be compared normally rather
    than being swept into NOT_IN_DOCUMENT_SCOPE by the new gate."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    requirement = _requirement(std, sc, required_evidence_type="data_sheet")
    fact = _fact(sub, fc, raw_value="85")

    verdict = comparison.compare(requirement, fact)

    assert verdict["status"] == comparison.COMPLIANT


def test_a_requirement_naming_other_evidence_never_reaches_compliant_end_to_end():
    """The full pipeline: containment pairs the field by name, and the
    evidence-type gate must still keep the run from emitting a verdict this
    submittal has no standing to answer."""
    std = _doc("std", "SAES-X.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,
             created_at) VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run, std, "2026-09-18T00:00:00Z"))
    standards.create_requirement(
        standard_document_id=std, chunk_id=sc, clause="7.1", page=1,
        requirement_text=(
            "The vendor shall submit a calibration certificate confirming "
            "accuracy within 0.5 pct."),
        source_text=(
            "The vendor shall submit a calibration certificate confirming "
            "accuracy within 0.5 pct."),
        structured={
            "requirement_type": "numeric_limit", "operator": "<=",
            "value": 0.5, "unit": "pct", "raw_value": "0.5", "raw_unit": "pct",
            "field": "accuracy", "subject": "accuracy",
            "required_evidence_type": "certificate",
        })
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id=fc, field_label="Accuracy",
        raw_value="0.3 pct", page=1)

    result = comparison.run_comparison(run, allowed_document_ids=_scope(std, sub))

    assert result["by_status"][comparison.COMPLIANT] == 0
    assert result["by_status"][comparison.NON_COMPLIANT] == 0
    assert result["by_status"][comparison.NOT_IN_DOCUMENT_SCOPE] == 1
    finding = result["findings"][0]
    assert finding["compliance_status"] == comparison.NOT_IN_DOCUMENT_SCOPE
    assert comparison.REQUIRES_OTHER_DOCUMENT in finding["ai_rationale"]


def test_an_excluded_standards_requirements_produce_no_findings_at_all():
    """Issue #163, criterion 2's applicability leg. `run_comparison` reads its
    requirement list only from standards `list_applicable_standards` returns
    with `include_excluded=False` (applicability.py's own decision, not
    re-decided here) - a requirement from a standard ruled OUT does not reach
    `compare` at all, so it can never be quoted as COMPLIANT/NON_COMPLIANT
    against a submittal the standard does not even govern."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,
             confidence,included,exclusion_reason,created_at)
            VALUES (?,?,?,'rule',0.4,0,'different service class',?)""",
            (str(uuid.uuid4()), run, std, "2026-09-18T00:00:00Z"))
    standards.create_requirement(
        standard_document_id=std, chunk_id=sc, clause="5.3.3", page=1,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).",
        structured={
            "requirement_type": "numeric_limit", "operator": "<=",
            "value": 90, "unit": "dB(A)", "raw_value": "90",
            "raw_unit": "dB(A)", "field": "noise level",
            "subject": "the noise level"})
    # A VALUE THAT WOULD OTHERWISE BREACH THE LIMIT, so the test stands where
    # skipping the standard can fail: silence here could mean "nothing to
    # find" rather than "correctly excluded".
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id=fc, field_label="Noise level",
        raw_value="95 dB(A)", page=1)

    result = comparison.run_comparison(run, allowed_document_ids=_scope(std, sub))

    assert result["requirements_evaluated"] == 0
    assert result["findings"] == []


def test_out_of_scope_findings_never_approve_a_submittal():
    """NORTH-STAR 2.2. Moved out of the missing count, an out-of-scope-only
    run used to fall through to "every evaluated requirement is met"."""
    findings = [{"compliance_status": comparison.NOT_IN_DOCUMENT_SCOPE}] * 3
    complete = {"sufficient": True, "fields_read": 100, "fields_estimated": 100}
    result = comparison.recommend_code(findings, complete)
    assert result["code"] == comparison.CODE_MANUAL
    assert result["code"] != comparison.CODE_APPROVED
    assert result["not_in_document_scope"] == 3
    # A SPECIFIC reason, the owner's wording - not a generic manual flag.
    assert result["reason"] == "Manual review: 3 requirements require other documents"
    one = comparison.recommend_code(
        [{"compliance_status": comparison.NOT_IN_DOCUMENT_SCOPE}], complete)
    assert one["reason"] == "Manual review: 1 requirement requires other documents"


def test_out_of_scope_is_never_counted_as_the_contractors_omission():
    """The owner's rule: not a contractor omission. It is counted APART, and
    the "left for the contractor to provide" wording counts only the real
    missing field."""
    findings = [{"compliance_status": comparison.NOT_IN_DOCUMENT_SCOPE}] * 5 + [
        {"compliance_status": comparison.MISSING_INFORMATION}]
    complete = {"sufficient": True, "fields_read": 100, "fields_estimated": 100}
    result = comparison.recommend_code(findings, complete)
    assert result["code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert result["missing_information"] == 1
    assert result["not_in_document_scope"] == 5
    assert result["reason"].startswith("1 field(s)")


# ------------------------------------------------ B18: an unmeasured factor

def test_an_unmeasured_extraction_does_not_let_references_alone_score_the_run():
    """B18. With the page count unknown, how much of the sheet was examined
    was never measured - and completeness used to be the min of what was
    left: every cited standard held made the run 1.0 and SUFFICIENT, so
    recommend_code could approve a sheet nobody had measured reading."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=0)
    result = comparison.completeness_for_run(
        sub, allowed_document_ids=_scope(sub), reference_coverage=1.0)
    assert result["extraction_coverage"] is None
    assert result["completeness"] is None
    assert result["sufficient"] is False


def test_a_measured_zero_stays_zero_whatever_is_unknown():
    """0 of the cited standards held is 0 however the unmeasured half would
    have come out - so it is reported, not hidden behind None."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=0)
    result = comparison.completeness_for_run(
        sub, allowed_document_ids=_scope(sub), reference_coverage=0.0)
    assert result["completeness"] == 0.0


def test_applicability_completeness_is_none_when_extraction_was_never_measured():
    """The same defect in the other home (CLAUDE.md rule 8): the product of
    the factors that exist, with the unmeasured one silently dropped.

    B10: "never measured" is an UNKNOWN PAGE COUNT, as in the gate's formula,
    which applicability now delegates to. (No facts on known pages is a
    measured 0, below.)"""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=0)
    held = {"std": {"method": applicability.METHOD_REFERENCED}}
    result = applicability.completeness(
        held, [], sub, allowed_document_ids=_scope(sub))
    assert result["reference_coverage"] == 1.0
    assert result["extraction_coverage"] is None
    assert result["completeness"] is None


def test_applicability_and_the_gate_report_one_completeness(monkeypatch):
    """B10: ONE FORMULA. The selection's completeness and the gate's were two
    different calculations (pages-with-a-fact x references, against
    fields-read / nominal fields, weakest link) and printed different numbers
    for one review. Now the selection delegates; the numbers are identical."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=2)
    facts = [{"page": 1, "id": f"f{i}"} for i in range(7)]
    monkeypatch.setattr(comparison.datasheets, "list_facts", lambda *a, **k: facts)
    held = {"std": {"method": applicability.METHOD_REFERENCED}}
    selection = applicability.completeness(
        held, ["MISSING-1"], sub, allowed_document_ids=_scope(sub))
    gate = comparison.completeness_for_run(
        sub, allowed_document_ids=_scope(sub),
        reference_coverage=selection["reference_coverage"])
    assert selection["reference_coverage"] == 0.5
    assert selection["extraction_coverage"] == gate["extraction_coverage"] == 0.1
    assert selection["completeness"] == gate["completeness"] == 0.1


def test_an_unknown_page_count_is_not_full_extraction(monkeypatch):
    """The old selection formula divided pages-with-a-fact by itself when the
    page count was unknown - 1.0, for any sheet with one fact."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=0)
    monkeypatch.setattr(comparison.datasheets, "list_facts",
                        lambda *a, **k: [{"page": 1, "id": "f1"}])
    result = applicability.completeness(
        {"std": {"method": applicability.METHOD_REFERENCED}}, [], sub,
        allowed_document_ids=_scope(sub))
    assert result["extraction_coverage"] is None
    assert result["completeness"] is None


def test_applicability_completeness_keeps_m03s_determinate_zero():
    """M-03: 0 of 15 cited standards held locally, no facts. Its 0.0 was
    CORRECT - the register's framing of B18 was wrong about that - and must
    survive the fix."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=3)
    missing = [f"STD-{i}" for i in range(15)]
    result = applicability.completeness(
        {}, missing, sub, allowed_document_ids=_scope(sub))
    assert result["reference_coverage"] == 0.0
    # B10: three known pages, no facts - a measured 0, the gate's own reading.
    assert result["extraction_coverage"] == 0.0
    assert result["completeness"] == 0.0
    # and with the page count unknown, the determinate 0 still survives
    unknown = _doc("sub2", "e.pdf", "CONTRACTOR_SUBMITTAL", pages=0)
    result = applicability.completeness(
        {}, missing, unknown, allowed_document_ids=_scope(unknown))
    assert result["extraction_coverage"] is None
    assert result["completeness"] == 0.0


def test_a_submittal_citing_nothing_is_judged_on_extraction_alone():
    """The OTHER None - no standard cited, nothing to cover - is still simply
    left out, so the fix does not blank every such run."""
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", pages=2)
    result = comparison.completeness_for_run(
        sub, allowed_document_ids=_scope(sub), reference_coverage=None)
    assert result["extraction_coverage"] == 0.0
    assert result["completeness"] == 0.0


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

    engineer = _user()

    outcome = comparison.record_engineer_code(
        run, code=comparison.CODE_APPROVED, reviewer=engineer,
        override_reason="checked the remaining fields by hand",
        allowed_document_ids=scope,
        actor={"id": engineer, "email": "eng@example.test"})

    assert outcome["final_code"] == comparison.CODE_APPROVED
    assert outcome["recommended_code"] == comparison.CODE_MANUAL
    assert outcome["override_reason"]
    assert outcome["reviewer"] == engineer
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
        run, code=comparison.CODE_MANUAL, reviewer=_user(),
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


def test_a_confirmed_finding_survives_run_comparison_replace():
    """THROUGH `run_comparison`, WHICH IS WHERE `replace` ACTUALLY DELETES.

    Re-running a comparison is how every fix to this engine reaches the
    corpus, so an engineer's confirmation must outlive it. A test that issued
    the DELETE itself would pass while `run_comparison` still destroyed the
    row - the pattern this file's own notes call species four.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    standards.create_requirement(
        standard_document_id=std, chunk_id=sc,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).",
        clause="5.3.3", page=1,
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
    first = comparison.run_comparison(run, allowed_document_ids=scope)
    assert first["by_status"][comparison.NON_COMPLIANT] == 1
    kept_id = first["findings"][0]["id"]
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES ('boss','b@e.test','boss','h',?)",
                     ("2026-09-19T00:00:00Z",))
        conn.execute("UPDATE review_findings SET confirmed_by='boss',"
                     " confirmed_at=? WHERE id=?",
                     ("2026-09-19T00:00:00Z", kept_id))

    comparison.run_comparison(run, allowed_document_ids=scope, replace=True)

    rows = db.connect().execute(
        "SELECT id, confirmed_by FROM review_findings WHERE review_run_id=?",
        (run,)).fetchall()
    kept = [r for r in rows if r["id"] == kept_id]
    assert kept, "re-running the comparison destroyed a CONFIRMED finding"
    assert kept[0]["confirmed_by"] == "boss"


def test_a_rejected_pair_survives_re_extraction_of_the_standard():
    """THE TEST THE KEYING EXISTS FOR.

    `standard_requirements.id` and `submittal_facts.id` are uuid4, regenerated
    by every `replace=True` extraction - and re-extraction is how every fix to
    the extractors reaches the corpus. A rejection keyed on those ids matches
    nothing afterwards: it stops applying SILENTLY, the same wrong pairing is
    proposed again, and the engineer cannot tell their correction was
    forgotten rather than ignored.

    So this rejects a pair, re-extracts the standard, and asserts the pairing
    is still refused - against requirement rows that now have different ids.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    # BOTH SIDES THROUGH THE REAL EXTRACTOR. Building the first requirement by
    # hand and the second by extraction compares two different code paths, and
    # any difference between them - a clause the parser derives differently -
    # looks exactly like the defect under test.
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES ('sc',?,'f.pdf',0,1,1,'5.3.3 Noise','prose',?,1,'h-sc',1)""",
            (std, "The noise level shall not exceed 90 dB(A)."))
    sc = "sc"
    fc = _chunk("fc", sub)
    standards.extract_requirements(
        std, allowed_document_ids=_scope(std, sub), replace=True)
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id=fc, field_label="Noise level",
        raw_value="95 dB(A)", page=1)

    scope = _scope(std, sub)
    requirement = standards.list_requirements(std, allowed_document_ids=scope)[0]
    fact = datasheets.list_facts(sub, allowed_document_ids=scope)[0]
    first_requirement_id, first_fact_id = requirement["id"], fact["id"]

    # It matches before the rejection, so the test stands where it can fail.
    assert comparison.match_by_containment(
        requirement, [fact])["fact"]["id"] == first_fact_id

    comparison.reject_pair(requirement, fact, rejected_by=None,
                           reason="a different piece of equipment")
    assert comparison.match_by_containment(requirement, [fact])["fact"] is None

    # RE-EXTRACT. Every requirement row is replaced and re-issued a new id.
    standards.extract_requirements(std, allowed_document_ids=scope, replace=True)
    again = standards.list_requirements(std, allowed_document_ids=scope)[0]
    assert again["id"] != first_requirement_id, (
        "the fixture did not actually re-issue the row id, so this test would "
        "prove nothing")

    assert comparison.match_by_containment(again, [fact])["fact"] is None, (
        "the rejection stopped applying after re-extraction - it was keyed on "
        "a row id that no longer exists")
