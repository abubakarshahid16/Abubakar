"""#450 / #451: not found is never a positive outcome, and a side that could
not be checked is not a side that was empty. Synthetic data only.
Mutations M3301-M3320."""
from __future__ import annotations

import itertools

import pytest

from app import absence, chat_comparison, comparison, db
from app.config import settings

ALL = frozenset({"doc-a", "doc-b", "doc-c"})
GOOD = {"answer_type": "generated", "answer": "Alpha [S1].",
        "passages": [{"chunk_id": "c1", "document_id": "doc-a"}]}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w450.sqlite")
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


def _compare(monkeypatch, per_side):
    """Run chat_comparison.compare with each side's answer scripted. A scripted
    value that is an Exception is raised."""
    answers = iter(per_side)

    def fake(question, ids, **kwargs):
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(chat_comparison, "_side_answer", fake)
    sides = [(f"STD-{i}", frozenset({d})) for i, d in zip("ABC", ("doc-a", "doc-b", "doc-c"))][:len(per_side)]
    return chat_comparison.compare(
        "compare them on welding", sides, tier="generate", allowed_document_ids=ALL,
        progress_id=None, model=None, history="", topic="welding")


# ------------------------------------------------- #451 a failed side

def test_a_side_that_raised_says_it_could_not_be_checked_and_the_others_keep_their_answers(monkeypatch):
    result = _compare(monkeypatch, [GOOD, RuntimeError("boom with secret text")])
    a, b = result["comparison"]["sides"]
    assert a["answer_type"] == "generated" and "Alpha" in a["text"]      # positive first
    assert b["answer_type"] == "could_not_be_checked"
    assert "RuntimeError" in b["reason"] and "secret text" not in str(result)
    assert "STD-B: could not be checked" in result["answer"]
    assert "not found in the pages read" not in b["text"]
    assert result["comparison"]["incomplete"] is True
    assert result["comparison"]["could_not_be_checked"] == ["STD-B"]
    assert "1 of 2 sides could not be checked" in result["reason"]


def test_a_stopped_side_and_every_side_after_it_are_not_reported_as_empty_searches(monkeypatch):
    ran = []

    def fake(question, ids, **kwargs):
        ran.append(question)
        return {"answer_type": "cancelled", "reason": "stopped by the reader", "cancelled": True}

    monkeypatch.setattr(chat_comparison, "_side_answer", fake)
    result = chat_comparison.compare(
        "compare them on welding",
        [("STD-A", frozenset({"doc-a"})), ("STD-B", frozenset({"doc-b"}))],
        tier="generate", allowed_document_ids=ALL, progress_id=None, model=None,
        history="", topic="welding")
    sides = result["comparison"]["sides"]
    assert len(ran) == 1                                  # nothing after Stop is searched
    assert [s["answer_type"] for s in sides] == ["could_not_be_checked"] * 2
    assert all("not found" not in s["text"] for s in sides)
    assert sides[1]["reason"] == absence.STOPPED_REASON


def test_a_refusal_that_is_not_an_absence_is_not_worded_as_one(monkeypatch):
    unsupported = {"answer_type": "insufficient_evidence", "passages": [],
                   "reason": "none of the answer's points could be found on the page they cited"}
    searched_nothing = {"answer_type": "insufficient_evidence", "passages": [],
                        "absence_kind": "not_found", "reason": "none of the indexed documents mention this topic"}
    result = _compare(monkeypatch, [unsupported, searched_nothing])
    a, b = result["comparison"]["sides"]
    assert a["answer_type"] == "could_not_be_checked"
    assert "could be found on the page they cited" in a["reason"]
    assert b["answer_type"] == "insufficient_evidence"      # a real absence stays one
    assert b["text"] == "STD-B: not found in the pages read."


def test_a_model_that_returned_no_text_is_not_the_model_reporting_an_absence():
    side = {"answer_type": "insufficient_evidence", "absence_kind": None,
            "reason": "the answer model returned no text"}
    assert absence.side_state(side, [])[0] == absence.COULD_NOT_BE_CHECKED


# ------------------------------------------- the review code never improves

RANK = {comparison.CODE_APPROVED: 0, comparison.CODE_APPROVED_WITH_COMMENTS: 1,
        comparison.CODE_MANUAL: 2, comparison.CODE_REJECTED: 3}
SUFFICIENT = {"sufficient": True, "fields_read": 100, "fields_estimated": 100,
              "extraction_coverage": 1.0}
ABSENCES = (comparison.MISSING_INFORMATION, comparison.NEEDS_ENGINEER_REVIEW,
            comparison.NOT_IN_DOCUMENT_SCOPE, None, "SOMETHING_NEW")


def _code(statuses, **kwargs):
    return comparison.recommend_code(
        [{"compliance_status": s} for s in statuses], SUFFICIENT, **kwargs)["code"]


def _rank(code):
    # Manual review is worse than approval but is not a rejection of the sheet.
    order = {comparison.CODE_APPROVED: 0, comparison.CODE_APPROVED_WITH_COMMENTS: 1,
             comparison.CODE_MANUAL: 2, comparison.CODE_REJECTED: 3}
    return order[code]


def test_adding_a_missing_or_unknown_finding_never_improves_the_review_code():
    """The property, over every small combination of statuses."""
    pool = (comparison.COMPLIANT, comparison.NOT_APPLICABLE, comparison.NON_COMPLIANT,
            *ABSENCES)
    checked = 0
    for size in range(0, 4):
        for base in itertools.combinations_with_replacement(pool, size):
            before = _rank(_code(list(base)))
            for extra in ABSENCES:
                after = _rank(_code([*base, extra]))
                assert after >= before, (base, extra, before, after)
                checked += 1
    assert checked > 200


def test_a_status_the_policy_does_not_know_can_never_approve():
    assert _code([comparison.COMPLIANT, None]) == comparison.CODE_MANUAL
    assert _code([comparison.COMPLIANT, "SOMETHING_NEW"]) == comparison.CODE_MANUAL
    assert _code([comparison.COMPLIANT, comparison.CONDITIONAL]) == comparison.CODE_MANUAL
    assert _code([comparison.COMPLIANT, comparison.COMPLIANT]) == comparison.CODE_APPROVED  # control


def test_requirements_nobody_could_check_outrank_the_contractors_blanks():
    """Same run without the blank is Manual; with it, it must not be better."""
    base = [comparison.COMPLIANT, comparison.NOT_IN_DOCUMENT_SCOPE]
    assert _code(base) == comparison.CODE_MANUAL
    assert _code([*base, comparison.MISSING_INFORMATION]) == comparison.CODE_MANUAL


def test_a_standard_in_scope_with_nothing_to_check_is_not_approved_over():
    assert _code([comparison.COMPLIANT]) == comparison.CODE_APPROVED            # control
    result = comparison.recommend_code(
        [{"compliance_status": comparison.COMPLIANT}], SUFFICIENT,
        unchecked_standards=["SAES-X-001.pdf"])
    assert result["code"] == comparison.CODE_MANUAL
    assert "SAES-X-001.pdf" in result["reason"] and "not checked" in result["reason"]


def test_an_unread_page_range_is_stated_and_never_leaves_a_missing_value_as_the_contractors_omission():
    verdict = {"status": comparison.MISSING_INFORMATION, "rationale": "no field answers this"}
    coverage = {"pages_total": 10, "fact_pages": [1, 2, 3],
                "pages_not_read_into_fields": [4, 5, 6, 7, 8, 9, 10],
                "pages_read_only_by_page_reader": []}
    out = comparison.qualify_by_pages(verdict, coverage)
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "4-10" in out["rationale"] and "3 of 10" in out["rationale"]


# ------------------------------------------- a pairing step that did not complete

def test_a_pairing_step_that_failed_or_was_refused_is_not_a_missing_value():
    for model_reason in ("model_unavailable", "model_malformed", "model_budget",
                         "model_unstable", "model_out_of_range"):
        assert absence.pairing_not_checked(None, model_reason, None)
    assert absence.pairing_not_checked("refused_by_rule", None, None)
    assert absence.pairing_not_checked(None, None, "the table could not be read")
    # Real absences stay absences: the model looked and declined, or is off.
    assert absence.pairing_not_checked(None, "model_declined", None) is None
    assert absence.pairing_not_checked(None, "model_disabled", None) is None
    assert absence.pairing_not_checked(None, None, None) is None


# ------------------------------------------- the engineer's code, the drafted comment

def test_a_run_with_no_recommendation_cannot_be_approved_without_a_reason():
    from app import submittal_review
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('sub','s.pdf','sha-sub',1,'s.pdf','ready',1,'2026-09-18T00:00:00Z')""")
        conn.execute("""INSERT INTO document_classification (document_id,suggested_by,document_role)
            VALUES ('sub','test','CONTRACTOR_SUBMITTAL')""")
        conn.execute("""INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)
            VALUES ('run','sub','failed','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""")
    scope = frozenset({"sub"})
    with pytest.raises(comparison.ComparisonError, match="no recommended code"):
        comparison.record_engineer_code(
            "run", code=comparison.CODE_APPROVED, reviewer=None,
            allowed_document_ids=scope)
    # A stated reason, or any non-approving code, is still allowed.
    comparison.record_engineer_code(
        "run", code=comparison.CODE_MANUAL, reviewer=None, allowed_document_ids=scope)


# ------------------------------------------- applicability: no data is not "not applicable"

def _std_and_sub(std_fields, sub_fields):
    from app import keyword, submittal_review
    submittal_review.ensure_schema(); keyword.ensure_schema()
    for doc_id, role, fields in (("std", "COMPANY_STANDARD", std_fields),
                                 ("sub", "CONTRACTOR_SUBMITTAL", sub_fields)):
        with db.connect() as conn:
            conn.execute("""INSERT INTO documents
                (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
                VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf"))
            columns = ["document_id", "suggested_by", "document_role", *fields]
            values = [doc_id, "test", role, *fields.values()]
            conn.execute(f"INSERT INTO document_classification ({','.join(columns)})"
                         f" VALUES ({','.join('?' * len(values))})", values)
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c", doc_id, f"{doc_id}.pdf",
                 "zinc coating thickness for galvanised pipe racks" if doc_id == "std"
                 else "centrifugal pump bearing housing vibration limits", f"h-{doc_id}"))
        keyword.index_document(doc_id)
    return frozenset({"std", "sub"})


def test_two_profiles_that_share_no_filled_field_are_unknown_not_not_applicable():
    from app import applicability
    scope = _std_and_sub({"document_number": "STD-1", "service": "water"},
                         {"equipment_type": "pump"})
    [row] = [r for r in applicability.applicability_with_reasons(
        "sub", allowed_document_ids=scope) if r["standard_document_id"] == "std"]
    assert row["status"] == applicability.STATUS_UNKNOWN
    assert "cannot be determined" in row["reason"]


def test_a_stated_mismatch_is_still_not_applicable():          # control
    from app import applicability
    scope = _std_and_sub({"document_number": "STD-1", "equipment_type": "transformer"},
                         {"equipment_type": "pump"})
    [row] = [r for r in applicability.applicability_with_reasons(
        "sub", allowed_document_ids=scope) if r["standard_document_id"] == "std"]
    assert row["status"] == applicability.STATUS_NOT_APPLICABLE


def test_a_scope_reasoning_that_failed_is_unknown_with_a_reason_not_silence(monkeypatch):
    from app import applicability, applicability_v2

    monkeypatch.setattr(applicability, "scope_record", lambda sid: ({"covered": []}, False))

    def boom(*args, **kwargs):
        raise RuntimeError("model host down")

    monkeypatch.setattr(applicability, "_cached_scope_decision", boom)
    decisions, not_run = applicability.scope_decisions_by_reasoning(
        [{"id": "std"}], {"equipment_type": "pump"}, provider=object())
    assert not_run is None
    assert decisions["std"]["decision"] == applicability_v2.UNKNOWN
    assert "could not be checked" in decisions["std"]["basis"]
    assert "RuntimeError" in decisions["std"]["basis"]
