"""#892 items 10 and 11: a comment an engineer ACCEPTED names that engineer, not "AI Review", and an
AI or web check item they accepted is confirmed like any other row.

The plain accept button writes `approval_status = 'accepted'` and `approved_by`, not
`confirmed_by`. `_confirmed` already counted such a row as the engineer's (the issue copy prints it),
but its byline stayed "AI Review", and an AI or web item ignored `accepted` altogether. Invented
findings only."""

from __future__ import annotations

from app import crs_mapping
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401 - fixture

NC = {
    "id": "nc1",
    "compliance_status": "NON_COMPLIANT",
    "standard_name": "SPEC-X.pdf",
    "standard_clause": "5.1",
    "standard_page": 7,
    "requirement_source_text": "The set pressure shall not exceed 10 barg.",
    "crs_field_label": "SET PRESSURE",
    "severity": "major",
    "fact_id": "f1",
    "equipment_tag": "PSV-1",
    "contractor_evidence_text": "12 barg",
    "contractor_page": 2,
}

AI = {
    "id": "ai1",
    "origin": "ai_engineering_check",
    "compliance_status": "NEEDS_ENGINEER_REVIEW",
    "finding": "Please check that an invented coupling guard is fitted.",
    "contractor_page": 1,
    "approval_status": "pending",
}


def _row(finding, **over):
    rows = crs_mapping.build_crs_rows([{**finding, **over}], [], "s.pdf")
    [row] = rows
    return row


def test_a_machine_row_an_engineer_accepted_names_them():
    row = _row(
        NC, approval_status="accepted", approved_by="u-7", confirmed_by_name="Ali"
    )
    assert row["engineer_confirmed"] is True
    assert row["comment_by"] == "AI Review, confirmed by Ali"


def test_the_id_is_the_fallback_when_no_name_is_on_record():
    row = _row(NC, approval_status="accepted", approved_by="u-7")
    assert row["comment_by"] == "AI Review, confirmed by u-7"


def test_a_row_nobody_decided_stays_ai_review():
    row = _row(NC, approval_status="pending")
    assert row["comment_by"] == "AI Review" and row["engineer_confirmed"] is False


def test_an_approver_on_a_pending_row_does_not_confirm_it():
    """`approved_by` counts only together with `accepted`: a rejected or pending row never reads as confirmed."""
    row = _row(NC, approval_status="pending", approved_by="u-7")
    assert row["comment_by"] == "AI Review" and row["engineer_confirmed"] is False


def test_confirmed_by_still_wins_over_the_approver():
    row = _row(
        NC,
        confirmed_by="u-1",
        approved_by="u-7",
        approval_status="accepted",
        confirmed_by_name="Sam",
    )
    assert row["comment_by"] == "AI Review, confirmed by Sam"


def test_an_ai_item_the_engineer_accepted_is_confirmed_and_names_them():
    row = _row(
        AI, approval_status="accepted", approved_by="u-7", confirmed_by_name="Ali"
    )
    assert row["engineer_confirmed"] is True
    assert row["comment"] == AI["finding"]
    assert "Ali" in row["comment_by"]
    assert row["ai_review_comment"] == ""


def test_an_ai_item_nobody_decided_stays_an_unconfirmed_draft():
    row = _row(AI)
    assert row["engineer_confirmed"] is False
    assert row["comment"] != AI["finding"] and row["ai_review_comment"] == AI["finding"]


# ------------------------------------------- the real path: names come from the users table


def test_the_real_crs_content_resolves_the_accepters_display_name(world):  # noqa: F811
    from app import db, main
    from app.access import AccessScope

    _sub, run, scope = world
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES ('u-acc','acc@example.test','Amina Accepter','x',1,'2026-01-01')"
        )
        conn.execute(
            "UPDATE review_findings SET approval_status='accepted', approved_by='u-acc',"
            " confirmed_by=NULL WHERE id = (SELECT id FROM review_findings"
            " WHERE review_run_id = ? LIMIT 1)",
            (run,),
        )
    rows, *_ = main._crs_content(
        run, AccessScope(user_id="u-acc", allowed_document_ids=scope)
    )
    assert any("Amina Accepter" in (r.get("comment_by") or "") for r in rows), [
        r.get("comment_by") for r in rows
    ]
