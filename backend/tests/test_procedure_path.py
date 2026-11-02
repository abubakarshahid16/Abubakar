"""#1476: the procedure path. The document is the evidence.

Invented procedure text only. Mutations: M<PR>-NN in scripts/mutations/c1_1476_procedure_path.py.
"""

from __future__ import annotations

import pytest

from app import comparison, db, procedure_text, submittal_review
from app.config import settings

PAGES = [
    (
        1,
        "Scope of the work. This procedure covers hydrostatic testing of the pipe spools.",
    ),
    (
        2,
        "Welders shall be qualified before production welding begins.\nRecords are kept on site.",
    ),
]

STATEMENT = {
    "requirement_type": "statement",
    "operator": None,
    "raw_value": None,
    "raw_unit": None,
    "field": None,
    "requirement_text": "Welding procedures shall be qualified before production welding.",
    "source_text": "Welding procedures shall be qualified before production welding.",
}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "pp.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def test_a_found_requirement_is_an_engineer_row_with_a_verified_quote_and_page():
    with procedure_text.using(PAGES):
        verdict = comparison.compare(STATEMENT, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "found on page 2" in verdict["rationale"]
    assert "qualified before production welding" in verdict["rationale"]
    assert "engineer to confirm" in verdict["rationale"]
    quote = procedure_text.find_passage(STATEMENT["source_text"], PAGES)["quote"]
    assert quote in dict(PAGES)[2]


def test_nothing_found_is_missing_information_for_the_contractor():
    other = {
        **STATEMENT,
        "requirement_text": "Crane lifting plans must name the rigging inspector.",
        "source_text": "Crane lifting plans must name the rigging inspector.",
    }
    with procedure_text.using(PAGES):
        verdict = comparison.compare(other, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "keyword search" in verdict["rationale"]
    assert "engineer to check" in verdict["rationale"]


def test_a_text_match_is_never_compliant():
    for req in (STATEMENT, {**STATEMENT, "required_evidence_type": "procedure"}):
        with procedure_text.using(PAGES):
            verdict = comparison.compare(req, None)
        assert verdict["status"] not in (comparison.COMPLIANT, comparison.NON_COMPLIANT)


def test_a_procedure_evidence_demand_is_checked_against_the_text():
    req = {
        **STATEMENT,
        "requirement_type": "numeric_limit",
        "required_evidence_type": "procedure",
    }
    with procedure_text.using(PAGES):
        verdict = comparison.compare(req, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "found on page 2" in verdict["rationale"]


@pytest.mark.parametrize(
    "evidence", ["certificate", "drawing", "report", "calculation", "record"]
)
def test_a_certificate_or_drawing_demand_still_goes_to_another_document(evidence):
    req = {**STATEMENT, "required_evidence_type": evidence}
    with procedure_text.using(PAGES):
        verdict = comparison.compare(req, None)
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_a_datasheet_submittal_is_unchanged():
    """No pages given (not a procedure): both branches behave as before."""
    assert (
        comparison.compare(STATEMENT, None)["status"]
        == comparison.NOT_IN_DOCUMENT_SCOPE
    )
    cert = {**STATEMENT, "required_evidence_type": "procedure"}
    assert comparison.compare(cert, None)["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def _kind(doc_id, kind, state="suggested"):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-11-01')",
            (doc_id, doc_id + ".pdf", "sha-" + doc_id, doc_id + ".pdf"),
        )
        conn.execute(
            "INSERT INTO document_kinds (document_id,kind,state,routed_at)"
            " VALUES (?,?,?,'2026-11-01')",
            (doc_id, kind, state),
        )


def test_the_router_kind_decides(monkeypatch):
    monkeypatch.setattr(settings, "procedure_path_enabled", False)
    _kind("d1", "procedure")
    _kind("d2", "datasheet")
    _kind("d3", "procedure", "needs_engineer")
    _kind("d4", "specification", "confirmed")
    assert procedure_text.is_procedure_submittal("d1") is False  # switch off
    monkeypatch.setattr(settings, "procedure_path_enabled", True)
    assert procedure_text.is_procedure_submittal("d1") is True
    assert procedure_text.is_procedure_submittal("d4") is True
    assert procedure_text.is_procedure_submittal("d2") is False
    assert procedure_text.is_procedure_submittal("d3") is False
    assert procedure_text.is_procedure_submittal("no-row") is False


def test_a_clause_that_only_asks_to_be_stated_on_the_datasheet_is_not_looked_up_in_the_text():
    text = "The relief valve set pressure shall be stated on the datasheet."
    req = {**STATEMENT, "requirement_text": text, "source_text": text}
    pages = [
        (1, "The relief valve set pressure is tested before the valve is installed.")
    ]
    with procedure_text.using(pages):
        verdict = comparison.compare(req, None)
    assert verdict["status"] == comparison.MISSING_INFORMATION
    assert "found on page" not in verdict["rationale"]
    assert "procedure_text" not in verdict["rationale"]


def _procedure_run(doc_id: str = "docP") -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',2,'2026-11-01T00:00:00Z')",
            (doc_id, "p.pdf", "sha-" + doc_id, "p.pdf"),
        )
        for page_no, text in PAGES:
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no)"
                " VALUES (?,?,?,?,0)",
                (doc_id, page_no, text, len(text)),
            )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES ('run1',?,'pending','2026-11-01','2026-11-01')",
            (doc_id,),
        )
    return "run1"


def test_the_run_reads_the_procedure_pages_only_when_on_and_listed_then_lets_go(
    monkeypatch,
):
    run = _procedure_run()
    with procedure_text.reading(run):
        assert procedure_text._PAGES.get() is None  # switch off
    monkeypatch.setattr(settings, "procedure_path_enabled", True)
    with procedure_text.reading(run):
        assert procedure_text._PAGES.get() is None  # no router kind
    _kind("docP", "procedure")
    with procedure_text.reading(run):
        assert procedure_text._PAGES.get() == PAGES
        verdict = comparison.compare(STATEMENT, None)
        assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert procedure_text._PAGES.get() is None  # no leak to the next caller
    assert (
        comparison.compare(STATEMENT, None)["status"]
        == comparison.NOT_IN_DOCUMENT_SCOPE
    )


def test_run_comparison_reads_the_procedure_pages_for_the_run(monkeypatch):
    run = _procedure_run()
    monkeypatch.setattr(settings, "procedure_path_enabled", True)
    _kind("docP", "procedure")
    seen = []
    monkeypatch.setattr(
        comparison,
        "_run_comparison",
        lambda *a, **k: seen.append(procedure_text._PAGES.get()),
    )
    comparison.run_comparison(run, allowed_document_ids=frozenset({"docP"}))
    assert seen == [PAGES]
    assert procedure_text._PAGES.get() is None


def test_a_requirement_with_too_few_words_goes_to_the_engineer_not_to_a_guess():
    short = {**STATEMENT, "requirement_text": "Maximum C.A. shall be 3.2 mm."}
    short["source_text"] = short["requirement_text"]
    pages = [(1, "Maximum operating pressure : 10 bar")]
    with procedure_text.using(pages):
        verdict = comparison.compare(short, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "too few distinguishing words" in verdict["rationale"]


def test_one_shared_word_is_not_a_passage():
    text = "Rewelding shall be done only with the prior approval of the inspector."
    req = {**STATEMENT, "requirement_text": text, "source_text": text}
    pages = [(1, "Prior to start the inspector signs the log. Approval number 7.")]
    with procedure_text.using(pages):
        verdict = comparison.compare(req, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "keyword search" in verdict["rationale"]


def test_two_of_three_words_is_not_enough_for_one_shared_word_rule():
    text = "Rewelding inspector approval."
    req = {**STATEMENT, "requirement_text": text, "source_text": text}
    pages = [(1, "The inspector gave approval yesterday.")]
    with procedure_text.using(pages):
        verdict = comparison.compare(req, None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "keyword search" in verdict["rationale"]


def _crs_finding(requirement: dict, status: str, rationale: str) -> dict:
    return {
        "id": "pf1",
        "compliance_status": status,
        "origin": None,
        "requirement_id": "r1",
        "requirement_source_text": requirement["source_text"],
        "requirement_limit": None,
        "standard_document_id": "std-1",
        "standard_name": "STD-100.pdf",
        "standard_clause": "5.3",
        "standard_page": 4,
        "contractor_page": None,
        "contractor_section": None,
        "contractor_evidence_text": "",
        "fact_id": None,
        "crs_field_label": None,
        "crs_is_blank": False,
        "matched_phrase": None,
        "equipment_tag": None,
        "engineer_comment": None,
        "confirmed_by": None,
        "approval_status": "pending",
        "ai_rationale": rationale,
        "reason_code": comparison.reason_code_of(rationale),
        "finding": rationale,
        "required_action": "",
        "severity": "minor",
    }


def test_a_found_row_is_a_crs_line_with_its_page_and_the_rest_are_one_counted_note():
    """From compare() through the CRS builder and the review notes."""
    from app import crs_mapping

    def other(n):
        text = f"Crane lifting plan {n} must name the rigging inspector."
        return {**STATEMENT, "requirement_text": text, "source_text": text}

    findings = []
    for i, req in enumerate((STATEMENT, other(1), other(2), other(3))):
        with procedure_text.using(PAGES):
            v = comparison.compare(req, None)
        f = _crs_finding(req, v["status"], v["rationale"])
        f["contractor_page"] = procedure_text.page_of(None, v["rationale"])
        findings.append({**f, "id": f"pf{i}"})
    assert [f["reason_code"] for f in findings] == (
        ["procedure_text_found"] + ["procedure_text_not_found"] * 3
    )
    assert findings[0]["contractor_page"] == 2
    assert all(f["compliance_status"] != comparison.COMPLIANT for f in findings)
    rows = crs_mapping.build_crs_rows(findings, [], "proc.pdf")
    assert len(rows) == 1  # the found row only
    text = str(rows[0].get("comment"))
    assert "found on page 2" in text and "qualified before production welding" in text
    assert "2" in str(rows[0].get("page_section"))
    notes = [
        n
        for n in crs_mapping.build_review_notes(findings, [])
        if "Procedure check" in n["note"]
    ]
    assert len(notes) == 1
    assert (
        notes[0]["count"]
        == 3
        == sum(f["reason_code"] == "procedure_text_not_found" for f in findings)
    )
    assert "keyword search" in notes[0]["detail"]
    assert crs_mapping.build_review_notes(findings[:1], []) == []


def test_a_procedure_records_demand_is_another_document():
    req = {
        **STATEMENT,
        "required_evidence_type": "procedure",
        "requirement_text": "Welding procedure records shall be submitted.",
        "source_text": "Welding procedure records shall be submitted.",
    }
    with procedure_text.using(PAGES):
        assert (
            comparison.compare(req, None)["status"] == comparison.NOT_IN_DOCUMENT_SCOPE
        )


def test_a_quote_not_in_the_stored_page_is_never_shown(monkeypatch):
    monkeypatch.setattr(
        procedure_text,
        "find_passage",
        lambda text, pages: {"page": 2, "quote": "words that are not on the page"},
    )
    with procedure_text.using(PAGES):
        verdict = comparison.compare(STATEMENT, None)
    assert "not on the page" not in verdict["rationale"]
    assert "keyword search" in verdict["rationale"]


def test_a_found_row_stored_without_a_page_is_still_a_crs_line():
    from app import crs_mapping

    with procedure_text.using(PAGES):
        v = comparison.compare(STATEMENT, None)
    f = _crs_finding(STATEMENT, v["status"], v["rationale"])
    assert f["contractor_page"] is None
    assert len(crs_mapping.build_crs_rows([f], [], "proc.pdf")) == 1


def test_a_found_row_carries_the_page_of_its_quote_not_its_facts_page():
    pages = [
        (3, "Welders shall be qualified before production welding begins."),
        (9, "Unrelated text about crane plans."),
    ]
    req = {**STATEMENT, "required_evidence_type": "procedure"}
    with procedure_text.using(pages):
        v = comparison.compare(req, {"page": 9, "is_blank": 0})
    assert "found on page 3" in v["rationale"]
    assert procedure_text.page_of({"page": 9}, v["rationale"]) == 3
    assert procedure_text.page_of({"page": 9}, "other") == 9
