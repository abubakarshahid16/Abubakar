"""GitHub issue #164 - the four verification gates a finding must pass.

Part 8 (commit c7a8337) read `create_finding`, `_citation_resolves`,
`_reconcile`, and `quotes.py` in full and found most of the acceptance
criteria already enforced by code that predates the issue. This module is
the regression proof for each of the four, written AFTER reading the code
rather than assumed from the issue text:

  1. QUOTE NORMALISATION - only the closed list in `quotes.py` may ever touch
     a quote, and the LIVE comparison path does not even call it: `compare`
     and `create_finding` store structured `raw_value`/source text verbatim,
     never a free-text "quote". `quotes.py` itself is exhaustively tested in
     `test_quote_validation.py`; the test here is the missing half - proof
     that the live path does not do its OWN, unapproved normalisation.

  2. CITATION GATE - `create_finding` already downgrades to
     NEEDS_ENGINEER_REVIEW, never COMPLIANT/NON_COMPLIANT, when either side's
     citation fails to resolve (`test_comparison.py` covers each side
     separately). This module adds one composite regression tying the
     behaviour explicitly to issue #164's wording.

  3. DUPLICATE FINDINGS - THE GENUINE GAP. Nothing before this change stopped
     `create_finding` from writing a second, unconfirmed row for the same
     (review_run_id, requirement_id, fact_id) identity. `run_comparison`
     happens to avoid it structurally (one requirement per loop iteration),
     but `create_finding` is a public entry point callable directly, and
     nothing on the table or in the function enforced it. See the gate added
     in `comparison.create_finding` just after `submittal_review.ensure_schema()`.

  4. RATIONALE VS EVIDENCE - the only LIVE path that puts free (model-written)
     text into a finding's rationale is the model pairing tier's `reason`
     field, and `_ask_model_once` already checks it against the evidence it
     was given (the candidate field names) via MODEL_NAMED_OTHER
     (`test_model_matching.py`). Every OTHER word in `ai_rationale` is a
     deterministic f-string built from verified structured values - there is
     no live path where free model text makes an unsupported factual claim,
     because `model_opinions` (the one parameter that could inject one) is
     never passed by the only live caller, `main.py`'s review-run route. This
     module adds the regression proving that.
"""

from __future__ import annotations

import uuid

import pytest

from app import comparison, db, quotes, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "issue164.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, pages: int = 1) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename, pages))
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            " document_role) VALUES (?,?,?)", (doc_id, "test", role))
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


# ============================================================== criterion 1

def test_criterion_1_the_live_path_stores_evidence_text_verbatim():
    """The requirement source text and the contractor's evidence text reach
    `review_findings` UNCHANGED, curly quotes, en dash and all.

    If anything in `compare`/`create_finding` were doing its own, unapproved
    normalisation (the exact failure `quotes.py`'s docstring describes: a
    model silently editing text nothing checked), this text would come back
    altered. It does not, because the live path never touches it - it copies
    the structured columns straight through.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)

    # A curly quote, an en dash and a non-breaking space - every character
    # `quotes.normalise` would rewrite, deliberately placed in text that never
    # passes through it.
    tricky_source = "the valve’s rating – 90 dB(A) — applies"
    tricky_evidence = "95 dB(A) – per the vendor’s data"

    requirement = _requirement(std, sc, source_text=tricky_source)
    fact = _fact(sub, fc, field_value=tricky_evidence)
    verdict = comparison.compare(requirement, fact)

    finding = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=fact, verdict=verdict)

    assert finding["requirement_source_text"] == tricky_source
    assert finding["contractor_evidence_text"] == tricky_evidence


def test_criterion_1_quotes_module_matches_the_approved_closed_list_exactly():
    """`quotes.normalise` implements exactly the five approved rules and
    nothing else - digits, units and operators are untouched.

    `test_quote_validation.py` already covers this exhaustively; this is a
    short, load-bearing spot check tied explicitly to issue #164's wording so
    a future change to the closed list trips a test that names the issue.
    """
    assert quotes.normalise("1/16”") == '1/16"'          # curly -> straight
    assert quotes.normalise("A – B") == "A - B"           # en dash -> hyphen
    assert quotes.normalise("A B") == "A B"                # NBSP -> space
    assert quotes.normalise("A   B  ") == "A B"                 # collapse + trim
    # NEVER touched: digits, decimals, units, operators, words.
    assert quotes.normalise("1.6 mm") == "1.6 mm"
    assert quotes.normalise("at least 90") == "at least 90"
    assert quotes.normalise(">= 90") == ">= 90"
    ok, _ = quotes.validate("1.6", "the value is 1.5")
    assert ok is False, "a changed digit must never validate"


# ============================================================== criterion 2

def test_criterion_2_a_verdict_cannot_carry_compliant_or_non_compliant_when_either_citation_fails():
    """Composite regression for issue #164 criterion 2: whichever side's
    citation fails to resolve, the stored status is NEVER COMPLIANT or
    NON_COMPLIANT - it is downgraded to NEEDS_ENGINEER_REVIEW and the reason
    is recorded on the finding, every time.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std)
    run = _run(sub)

    # Standard citation does not resolve (no such chunk).
    req_bad_std = _requirement(std, "no-such-chunk")
    fact = _fact(sub, sc)
    finding_a = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=req_bad_std, fact=fact,
        verdict=comparison.compare(req_bad_std, fact))
    assert finding_a["compliance_status"] not in (
        comparison.COMPLIANT, comparison.NON_COMPLIANT)
    assert finding_a["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW

    # Contractor citation does not resolve (no such chunk).
    req_ok = _requirement(std, sc)
    fact_bad = _fact(sub, "no-such-chunk")
    finding_b = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=req_ok, fact=fact_bad,
        verdict=comparison.compare(req_ok, fact_bad))
    assert finding_b["compliance_status"] not in (
        comparison.COMPLIANT, comparison.NON_COMPLIANT)
    assert finding_b["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW


# ============================================================== criterion 3

def test_criterion_3_a_duplicate_finding_for_the_same_pair_in_the_same_run_is_blocked():
    """THE GENUINE GAP. The same (review_run_id, requirement_id, fact_id)
    identity may not produce two unconfirmed finding rows.

    Before this change nothing enforced it: `create_finding` would happily
    insert a second, byte-for-byte duplicate row.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    verdict = comparison.compare(requirement, fact)

    first = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=fact, verdict=verdict)
    assert first["compliance_status"] == comparison.NON_COMPLIANT

    with pytest.raises(comparison.ComparisonError):
        comparison.create_finding(
            review_run_id=run, submittal_document_id=sub,
            requirement=requirement, fact=fact, verdict=verdict)

    rows = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?"
        " AND requirement_id = ?", (run, requirement["id"])).fetchone()[0]
    assert rows == 1, "a blocked duplicate must not have been written"


def test_criterion_3_a_confirmed_finding_does_not_block_a_fresh_rerun_proposal():
    """THE GUARD ON THE GATE ABOVE. `run_comparison`'s re-run behaviour - an
    engineer's CONFIRMED finding survives, and a fresh unconfirmed proposal
    for the same requirement is written beside it on every re-run - must keep
    working. The duplicate gate only ever compares against OTHER unconfirmed
    rows, never a confirmed one.
    """
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    requirement = _requirement(std, sc)
    fact = _fact(sub, fc)
    verdict = comparison.compare(requirement, fact)

    first = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=fact, verdict=verdict)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('eng','e@x.test','eng','h','2026-09-19T00:00:00Z')")
        conn.execute(
            "UPDATE review_findings SET confirmed_by='eng',"
            " confirmed_at='2026-09-19T00:00:00Z' WHERE id=?", (first["id"],))

    # The same requirement/fact pair, proposed again - as `run_comparison`
    # does on every re-run - must not be refused by the duplicate gate.
    second = comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=requirement, fact=fact, verdict=verdict)
    assert second["id"] != first["id"]

    rows = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?"
        " AND requirement_id = ?", (run, requirement["id"])).fetchone()[0]
    assert rows == 2


def test_criterion_3_different_requirements_against_the_same_fact_are_not_duplicates():
    """A fact may legitimately satisfy more than one requirement - the gate
    is keyed on the PAIR, not on the fact alone."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    fact = _fact(sub, fc)

    req_a = _requirement(std, sc, clause="5.3.3")
    req_b = _requirement(std, sc, clause="5.3.4")
    comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=req_a, fact=fact, verdict=comparison.compare(req_a, fact))
    # Must not raise: a different requirement, same fact.
    comparison.create_finding(
        review_run_id=run, submittal_document_id=sub,
        requirement=req_b, fact=fact, verdict=comparison.compare(req_b, fact))

    rows = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?",
        (run,)).fetchone()[0]
    assert rows == 2


# ============================================================== criterion 4

def test_criterion_4_no_live_caller_passes_a_model_opinion_into_the_review_run_route():
    """The only parameter that could inject free model text as a rationale
    claim is `model_opinions`, and the only live caller of `run_comparison`
    (`main.py`'s `POST /api/reviews/run`) never supplies one.

    This is a static regression on the source, matching how Part 8 verified
    `quotes.py`'s reachability: read the one call site rather than assume.
    """
    import inspect
    from app import main as main_mod

    source = inspect.getsource(main_mod)
    # The single call site, isolated so a second one added elsewhere would
    # still need its own check rather than silently reusing this pass.
    start = source.index("comparison_mod.run_comparison(")
    call_site = source[start:start + 200]
    assert "model_opinions" not in call_site, (
        "a live caller now passes model_opinions into run_comparison; "
        "criterion 4 needs re-verification because free model text can "
        "reach a finding's rationale on the live path")


def test_criterion_4_a_model_reason_naming_an_unchosen_candidate_is_rejected(monkeypatch):
    """The one live path that DOES carry free (model-written) text into a
    finding - the pairing tier's `reason` - is checked against the evidence
    it was given. Already covered in depth by `test_model_matching.py`; this
    is the issue-164-scoped regression."""
    import json as json_mod
    from app import model_transport

    def fake_post_json(path, body, timeout=None):
        return {"response": json_mod.dumps(
            {"choice": 0, "reason": "the hydrotest pressure field matches"})}

    monkeypatch.setattr(model_transport, "post_json", fake_post_json)

    requirement = {
        "id": "r1", "standard_document_id": "std", "clause": "5.1",
        "requirement_text": "shell design pressure shall not exceed 30 barg",
        "subject": "shell design pressure shall not exceed",
        "requirement_type": "numeric_limit", "raw_value": "30", "raw_unit": "barg",
    }
    candidates = [
        {"id": "f0", "field_name": "shell design pressure", "raw_value": "25",
         "raw_unit": "barg", "is_blank": 0},
        {"id": "f1", "field_name": "hydrotest pressure", "raw_value": "45",
         "raw_unit": "barg", "is_blank": 0},
    ]
    result = comparison.match_by_model(requirement, candidates)
    assert result["fact"] is None, (
        "the model chose candidate 0 but its stated reason names candidate 1 "
        "- an unsupported claim against the evidence it was shown, and it "
        "must be rejected rather than trusted"
    )
    assert result["reason"] == comparison.MODEL_NAMED_OTHER
