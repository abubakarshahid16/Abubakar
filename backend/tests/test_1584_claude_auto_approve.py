"""#1584 (owner decision): every document uploaded for review joins the approved
list automatically unless blocked; the register file (CLAUDE.md rule 3) is always
blocked; the list stays the record of what was sent to Claude.

Behind `claude_auto_approve_reviews_enabled`, off by default. No Claude call:
the transports here are fakes, and every document and file is invented. The file
named like the register is a few invented bytes, never the real PDF (rule 3).
"""

from __future__ import annotations

import io
import json
import threading

import pytest

from app import (
    absence,
    applicability,
    classification,
    claude_approved,
    claude_auto_approve,
    claude_selection,
    claude_spend,
    db,
    review_jobs,
    submittal_review,
    upload,
)
from app.config import Settings, settings

NOW = "2026-11-02T00:00:00Z"
SUBMITTAL = "CONTRACTOR_SUBMITTAL"
STANDARD = "COMPANY_STANDARD"
SHA_A, SHA_B, SHA_C = "aa" * 32, "bb" * 32, "cc" * 32
OWNER_HASH = "ee" * 32  # the owner's real register hash stands here


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "auto.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    _write_block_file([OWNER_HASH])
    yield
    db.reset_connection()


def _write_block_file(hashes) -> None:
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": list(hashes)}), encoding="utf-8"
    )


def _doc(doc_id, sha, role=None, filename=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, filename or f"{doc_id}.pdf", sha, f"{doc_id}.pdf", NOW),
        )
    if role:
        classification.set_role(doc_id, role)
    return doc_id


def _pdf(marker: bytes = b"x") -> bytes:
    return b"%PDF-1.4\n" + marker * 5000 + b"\n%%EOF\n"


def _upload(name, marker=b"x"):
    row, _job, _dup = upload.ingest(io.BytesIO(_pdf(marker)), name)
    return row


def _rows():
    path = claude_approved.list_path()
    return (
        json.loads(path.read_text(encoding="utf-8"))["documents"]
        if path.is_file()
        else []
    )


def _rows_for(sha):
    return [r for r in _rows() if r["sha256"] == sha]


def _set_list(*entries):
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {"sha256": sha, "status": status, "approved_by": "owner"}
                    for sha, status in entries
                ]
            }
        ),
        encoding="utf-8",
    )


def _start_review(doc_id):
    run_id, _job = review_jobs.enqueue(
        doc_id, allowed_document_ids=frozenset({doc_id}), requested_by=None
    )
    return run_id


def _cite(
    run_id, standard_id, *, included=True, method=applicability.METHOD_REFERENCED
):
    return applicability.record_selection(
        review_run_id=run_id,
        standard_document_id=standard_id,
        reason="invented reason",
        method=method,
        included=included,
        exclusion_reason=None if included else "invented exclusion",
    )


def _reserve(step="auto-test"):
    return claude_spend.reserve(step, 0.01, model="claude-sonnet-5")


def _refused_code(ids):
    with claude_approved.carrying(ids):
        with pytest.raises(claude_spend.DocumentNotApproved) as caught:
            _reserve()
    return caught.value.code


def _ledger():
    path = settings.claude_spend_log
    return (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )


def _outcome(run_id):
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["outcome_json"]) if row["outcome_json"] else None


def _store_outcome(run_id, outcome):
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run_id),
        )


def _audit(action):
    return (
        db.connect()
        .execute("SELECT * FROM audit_events WHERE action = ? ORDER BY id", (action,))
        .fetchall()
    )


# ---------------------------------------------------------------- the switch


def test_the_switch_ships_off():
    assert Settings.model_fields["claude_auto_approve_reviews_enabled"].default is False


def test_switch_off_nothing_is_listed_written_or_recorded(monkeypatch):
    # The block file stays valid here: without the switch's own guard the hooks
    # would write, so this fails when the guard is removed.
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    row = _upload("invented submittal.pdf")
    classification.set_role(row["id"], SUBMITTAL)
    run_id = _start_review(row["id"])
    standard = _doc("doc_std", SHA_B, STANDARD)
    _cite(run_id, standard)
    other = _doc("doc_eq", SHA_C, STANDARD)
    _cite(run_id, other, method=applicability.METHOD_EQUIPMENT)
    _store_outcome(run_id, {})
    _upload("Engineering Deliverables.pdf", marker=b"y")
    claude_auto_approve.record_on_run(run_id)
    assert not claude_approved.list_path().exists()
    assert _audit(claude_auto_approve.AUDIT_ADDED) == []
    assert _audit(claude_approved.AUDIT_ACTION) == []
    assert "claude_unlisted_standards" not in (_outcome(run_id) or {})
    # A hand-approved row passes as today, with no ledger field; chat consent waives the list.
    _set_list((row["sha256"], "approved"))
    with claude_approved.carrying([row["id"]]):
        _reserve()
    assert not [e for e in _ledger() if "sent_documents" in e]
    _set_list()
    with claude_approved.per_request_consent([row["id"]]):
        _reserve()


def test_switch_off_no_block_file_is_asked_for(monkeypatch):
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    claude_approved.block_file_path().unlink()
    doc = _doc("doc_h", SHA_A)
    _set_list((SHA_A, "approved"))
    with claude_approved.carrying([doc]):
        _reserve()


def test_switch_off_is_a_rollback_an_auto_row_does_not_count(monkeypatch):
    doc = _doc("doc_a", SHA_A)
    cited = _doc("doc_b", SHA_B)
    classification.set_role(doc, SUBMITTAL)
    run_id = _start_review(doc)
    _cite(run_id, cited)
    assert {r["status"] for r in _rows()} == {"approved"} and len(_rows()) == 2
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    assert claude_approved.approved_hashes() == frozenset()
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    assert _refused_code([cited]) == claude_approved.NOT_APPROVED


@pytest.mark.parametrize("on", [True, False])
def test_blocks_apply_whatever_the_switch_says(monkeypatch, on):
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", on)
    beside = _doc("doc_x", SHA_A)
    named = _doc("doc_r", SHA_B, filename="Engineering Deliverables.pdf")
    filed = _doc("doc_f", SHA_C)
    _write_block_file([SHA_C])
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {"sha256": SHA_A, "status": "approved"},
                    {"sha256": SHA_A, "status": "blocked"},
                    {"sha256": SHA_B, "status": "approved"},
                    {"sha256": SHA_C, "status": "approved"},
                ]
            }
        ),
        encoding="utf-8",
    )
    for doc in (beside, named, filed):
        assert _refused_code([doc]) == claude_approved.NOT_APPROVED
        with claude_approved.per_request_consent([doc]):
            with pytest.raises(claude_spend.DocumentNotApproved):
                _reserve()


@pytest.mark.parametrize("on", [True, False])
def test_blocks_apply_with_the_list_guard_off(monkeypatch, on):
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", on)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    blocked = _doc("doc_x", SHA_A)
    named = _doc("doc_r", SHA_B, filename="engineering_deliverables.pdf")
    free = _doc("doc_f", SHA_C)
    _set_list((SHA_A, "blocked"))
    assert _refused_code([blocked]) == claude_approved.NOT_APPROVED
    assert _refused_code([named]) == claude_approved.NOT_APPROVED
    with claude_approved.carrying([free]):
        _reserve()


# ---------------------------------------------------------------- what is listed


def test_an_upload_with_a_review_role_is_listed_with_every_field():
    row = _upload("invented submittal.pdf")
    assert _rows() == []  # no role yet: the role says what it is for
    classification.set_role(row["id"], SUBMITTAL)
    entry = _rows_for(row["sha256"])[0]
    assert entry["document_id"] == row["id"]
    assert entry["label"] == "invented submittal.pdf"
    assert entry["status"] == "approved"
    assert entry["approved_by"] == "auto: owner decision #1584"
    assert len(entry["approved_on"]) == 10 and entry["approved_on"][4] == "-"
    assert entry["source"] == "auto"
    with claude_approved.carrying([row["id"]]):
        assert _reserve().step == "auto-test"


def test_the_upload_hook_itself_lists_a_document_that_already_has_a_review_role():
    row = _upload("invented submittal.pdf")
    with db.connect() as conn:  # a role written with no hook behind it
        conn.execute(
            "INSERT OR REPLACE INTO document_classification (document_id, document_role, suggested_by)"
            " VALUES (?, ?, 'test')",
            (row["id"], SUBMITTAL),
        )
    assert _rows() == []
    _upload("the same bytes again.pdf")
    assert _rows_for(row["sha256"])[0]["status"] == "approved"


def test_an_upload_as_a_standard_or_reference_is_not_listed():
    for name, role in (("a.pdf", STANDARD), ("b.pdf", "SUPPORTING_DOCUMENT")):
        row = _upload(name, marker=name[0].encode())
        classification.set_role(row["id"], role)
    assert _rows() == []


def test_a_document_uploaded_earlier_is_listed_when_its_review_starts():
    doc = _doc("doc_old", SHA_A)
    assert _rows() == []
    _start_review(doc)
    assert _rows_for(SHA_A)[0]["source"] == "auto"


def test_the_other_review_start_lists_too():
    doc = _doc("doc_old", SHA_A)
    submittal_review.create_review_run(
        submittal_document_id=doc, allowed_document_ids=frozenset({doc})
    )
    assert _rows_for(SHA_A)[0]["status"] == "approved"


@pytest.mark.parametrize(
    "role", [STANDARD, "CONTRACT_DOCUMENT", "SUPPORTING_DOCUMENT", "CRS_TEMPLATE"]
)
def test_a_review_start_does_not_list_a_subject_whose_role_says_otherwise(role):
    doc = _doc("doc_s", SHA_A, role)
    _start_review(doc)
    assert _rows() == []


def test_a_cited_standard_is_listed_an_uncited_one_is_not():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    cited = _doc("doc_cited", SHA_B, STANDARD)
    excluded = _doc("doc_excluded", SHA_C, STANDARD)
    _doc("doc_library", "dd" * 32, STANDARD)  # in the library, untouched by this review
    run_id = _start_review(doc)
    _cite(run_id, cited)
    _cite(run_id, excluded, included=False)
    assert _rows_for(SHA_B)[0]["source"] == f"auto: cited by {doc}"
    assert _rows_for(SHA_C) == []
    assert _rows_for("dd" * 32) == []
    assert {r["sha256"] for r in _rows()} == {SHA_A, SHA_B}


def test_a_governing_standard_is_listed_and_labelled_as_such():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    governing = _doc("doc_gov", SHA_B, STANDARD)
    _cite(_start_review(doc), governing, method=applicability.METHOD_GOVERNING)
    assert _rows_for(SHA_B)[0]["source"] == f"auto: governing standard for {doc}"


def test_the_listed_methods_are_the_ones_the_review_writes():
    assert set(claude_auto_approve.LISTED_METHODS) == {
        applicability.METHOD_REFERENCED,
        applicability.METHOD_GOVERNING,
    }


@pytest.mark.parametrize(
    "method",
    [
        applicability.METHOD_EQUIPMENT,
        applicability.METHOD_SERVICE,
        applicability.METHOD_PROJECT,
        applicability.METHOD_SCOPE,
        applicability.METHOD_MANUAL,
    ],
)
def test_a_standard_applied_without_a_citation_is_not_listed_and_the_review_says_so(
    method,
):
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    standard = _doc("doc_std", SHA_B, STANDARD)
    cited = _doc("doc_cited", SHA_C, STANDARD)
    run_id = _start_review(doc)
    _cite(run_id, standard, method=method)
    _cite(run_id, cited)
    assert _rows_for(SHA_B) == []
    claude_auto_approve.on_review_start(run_id)  # nor at the start of a later look
    assert _rows_for(SHA_B) == []
    _store_outcome(run_id, {})
    claude_auto_approve.record_on_run(run_id)
    outcome = _outcome(run_id)
    assert outcome["claude_unlisted_standards"] == {"not_listed": 1, "of": 2}
    parts = absence.unchecked_parts(run_status="completed", outcome=outcome)
    line = next(p["line"] for p in parts if p["part"] == "claude_unlisted_standards")
    assert "1 of 2 standard(s)" in line and "doc_std" not in line
    note = next(p["note"] for p in parts if p["part"] == "claude_unlisted_standards")
    assert note == "Not read by the cloud model"  # the local check did read them
    assert (
        absence.notice_for(parts) == ""
    )  # the local check ran: the sheet is not called incomplete


def test_a_review_with_every_standard_cited_says_nothing():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    cited = _doc("doc_cited", SHA_C, STANDARD)
    run_id = _start_review(doc)
    _cite(run_id, cited)
    _store_outcome(run_id, {})
    claude_auto_approve.record_on_run(run_id)
    assert "claude_unlisted_standards" not in _outcome(run_id)


def test_a_hand_approved_standard_is_not_counted_as_unlisted():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    standard = _doc("doc_std", SHA_B, STANDARD)
    run_id = _start_review(doc)
    _cite(run_id, standard, method=applicability.METHOD_EQUIPMENT)
    rows = [*_rows(), {"sha256": SHA_B, "status": "approved", "approved_by": "owner"}]
    claude_approved.list_path().write_text(
        json.dumps({"documents": rows}), encoding="utf-8"
    )
    _store_outcome(run_id, {})
    claude_auto_approve.record_on_run(run_id)
    assert "claude_unlisted_standards" not in _outcome(run_id)


def test_a_standard_the_model_selected_is_not_listed():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    cited = _doc("doc_cited", SHA_B, STANDARD)
    run_id = _start_review(doc)
    claude_selection.store_selection(
        run_id,
        [
            {
                "document_id": cited,
                "basis": sorted(claude_selection.BASES)[0],
                "reason": "invented",
            }
        ],
        [{"document_id": cited}],
        allowed_document_ids=frozenset({doc, cited}),
    )
    assert _rows_for(SHA_B) == []


@pytest.mark.parametrize(
    ("method", "label"),
    [
        ("referenced", "auto: cited by"),
        ("governing_standard", "auto: governing standard for"),
    ],
)
def test_a_standard_already_on_the_run_is_listed_when_a_review_starts(method, label):
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    cited = _doc("doc_cited", SHA_B, STANDARD)
    run_id = _start_review(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id,"
            " selection_reason, selection_method, included, created_at)"
            " VALUES ('r1', ?, ?, 'x', ?, 1, ?)",
            (run_id, cited, method, NOW),
        )
    assert _rows_for(SHA_B) == []
    claude_auto_approve.on_review_start(run_id)
    assert _rows_for(SHA_B)[0]["source"] == f"{label} {doc}"


# ---------------------------------------------------------------- withdrawn


@pytest.mark.parametrize("role", [STANDARD, "SUPPORTING_DOCUMENT"])
def test_a_role_that_stops_qualifying_withdraws_the_auto_row_and_keeps_the_record(role):
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    assert _rows_for(SHA_A)[0]["status"] == "approved"
    classification.set_role(doc, role)
    entry = _rows_for(SHA_A)[0]
    assert len(_rows_for(SHA_A)) == 1
    assert entry["status"] == "withdrawn"
    assert entry["approved_by"] == "auto: owner decision #1584"  # the record stays
    assert entry["withdrawn_on"]
    rows = _audit(claude_auto_approve.AUDIT_WITHDRAWN)
    assert [r["resource_id"] for r in rows] == [SHA_A]
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


def test_the_details_form_withdraws_too():
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    classification.confirm(
        doc,
        doc_type=None,
        discipline=None,
        doc_class=None,
        subject_ids=(),
        confirmed_by=None,
        metadata={"document_role": "SUPPORTING_DOCUMENT"},
    )
    assert _rows_for(SHA_A)[0]["status"] == "withdrawn"


def test_a_review_of_a_subject_whose_role_stopped_qualifying_withdraws():
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    with db.connect() as conn:  # a role written with no hook behind it
        conn.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            (STANDARD, doc),
        )
    _start_review(doc)
    assert _rows_for(SHA_A)[0]["status"] == "withdrawn"


def _lapsed_row(doc, role=STANDARD):
    """An approved automatic row whose document lost its role with no hook behind it."""
    classification.set_role(doc, SUBMITTAL)
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            (role, doc),
        )
    assert _rows_for(SHA_A)[0]["status"] == "approved"


def test_the_gate_refuses_an_auto_row_whose_role_stopped_qualifying():
    doc = _doc("doc_a", SHA_A)
    _lapsed_row(doc)
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


def test_a_role_change_while_the_switch_was_off_is_refused_when_it_comes_back(
    monkeypatch,
):
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    classification.set_role(doc, STANDARD)  # the hook is off: the row stays approved
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    assert _rows_for(SHA_A)[0]["status"] == "approved"
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


def test_a_role_change_while_the_list_was_unreadable_is_refused_when_it_is_repaired():
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    good = claude_approved.list_path().read_text(encoding="utf-8")
    claude_approved.list_path().write_text("{not json", encoding="utf-8")
    classification.set_role(doc, STANDARD)
    claude_approved.list_path().write_text(good, encoding="utf-8")
    assert _rows_for(SHA_A)[0]["status"] == "approved"
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


def test_a_lapsed_row_says_so_when_the_step_runs_local():
    doc = _doc("doc_a", SHA_A)
    _lapsed_row(doc)
    with claude_approved.carrying([doc]):
        assert claude_approved.local_instead() == claude_approved.LOCAL_INSTEAD.format(
            n=1, of=1
        )


@pytest.mark.parametrize(
    "beside",
    [
        {"status": "approved", "approved_by": "owner"},
        {"status": "approved", "source": "auto: cited by doc_x"},
    ],
)
def test_a_human_or_citation_row_beside_it_still_passes(beside):
    doc = _doc("doc_a", SHA_A)
    _lapsed_row(doc)
    rows = [*_rows(), {"sha256": SHA_A, **beside}]
    claude_approved.list_path().write_text(
        json.dumps({"documents": rows}), encoding="utf-8"
    )
    with claude_approved.carrying([doc]):
        _reserve()


def test_an_auto_row_with_no_role_or_a_review_role_passes():
    no_role = _doc("doc_a", SHA_A)
    with db.connect() as conn:  # a classification row that records no role
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by) VALUES (?, 'test')",
            (no_role,),
        )
    _start_review(no_role)
    with claude_approved.carrying([no_role]):
        _reserve()
    submittal = _doc("doc_b", SHA_B, SUBMITTAL)
    with claude_approved.carrying([submittal]):
        _reserve()


def test_a_human_approved_row_is_not_withdrawn():
    doc = _doc("doc_a", SHA_A)
    _set_list((SHA_A, "approved"))
    before = claude_approved.list_path().read_bytes()
    classification.set_role(doc, SUBMITTAL)
    classification.set_role(doc, STANDARD)
    assert claude_approved.list_path().read_bytes() == before


def test_a_cited_row_is_not_withdrawn_by_a_role_change():
    doc = _doc("doc_a", SHA_A, SUBMITTAL)
    cited = _doc("doc_c", SHA_B, STANDARD)
    _cite(_start_review(doc), cited)
    classification.set_role(cited, "SUPPORTING_DOCUMENT")
    assert _rows_for(SHA_B)[0]["status"] == "approved"


def test_qualifying_again_adds_a_new_row_and_keeps_the_withdrawn_one():
    doc = _doc("doc_a", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    classification.set_role(doc, STANDARD)
    classification.set_role(doc, SUBMITTAL)
    assert [r["status"] for r in _rows_for(SHA_A)] == ["withdrawn", "approved"]
    with claude_approved.carrying([doc]):
        _reserve()


def test_adding_twice_is_one_entry_and_an_owners_entry_is_left_as_written():
    doc = _doc("doc_sub", SHA_A)
    pending = _doc("doc_pending", SHA_B)
    _set_list((SHA_B, "pending_owner"))
    classification.set_role(doc, SUBMITTAL)
    claude_auto_approve.on_upload(doc)
    classification.set_role(pending, SUBMITTAL)
    assert len(_rows_for(SHA_A)) == 1
    assert _rows_for(SHA_B) == [
        {"sha256": SHA_B, "status": "pending_owner", "approved_by": "owner"}
    ]


# ---------------------------------------------------------------- the register


@pytest.mark.parametrize(
    "name",
    [
        "Engineering Deliverables.pdf",
        "engineering deliverables.pdf",
        "ENGINEERING DELIVERABLES.PDF",
        "Engineering_Deliverables.pdf",
        "engineering-deliverables.pdf",
        "EngineeringDeliverables.pdf",
        "  Engineering   Deliverables .pdf",
        "Engineering Deliverables (1).pdf",
        "Copy of Engineering Deliverables v2.pdf",
    ],
)
def test_a_register_named_file_is_blocked_in_every_spelling(name):
    row = _upload(name)
    entry = _rows_for(row["sha256"])[0]
    assert entry["status"] == "blocked"
    assert entry["source"] == "auto"
    assert entry.get("approved_by") is None
    # A role does not lift it, nor a review.
    classification.set_role(row["id"], SUBMITTAL)
    _start_review(row["id"])
    assert {r["status"] for r in _rows_for(row["sha256"])} == {"blocked"}
    assert _refused_code([row["id"]]) == claude_approved.NOT_APPROVED


@pytest.mark.parametrize(
    "name",
    [
        "Deliverables Engineering.pdf",
        "engineering deliverable list.pdf",
        "invented submittal.pdf",
        "",
        None,
    ],
)
def test_other_names_are_not_the_register(name):
    assert not claude_approved.is_register_name(name)


def test_a_cited_register_file_is_blocked_not_listed():
    doc = _doc("doc_sub", SHA_A, SUBMITTAL)
    register = _doc("doc_r", SHA_B, STANDARD, filename="Engineering Deliverables.pdf")
    _cite(_start_review(doc), register)
    assert {r["status"] for r in _rows_for(SHA_B)} == {"blocked"}


def test_two_uploads_at_once_the_loser_under_the_register_name_still_blocks(
    monkeypatch,
):
    row = _upload("invented submittal.pdf")
    real, calls = upload.find_by_hash, []

    def lost_the_race(sha):  # the first look finds nothing; the insert then loses
        calls.append(sha)
        return None if len(calls) == 1 else real(sha)

    monkeypatch.setattr(upload, "find_by_hash", lost_the_race)
    again = _upload("Engineering Deliverables.pdf")
    assert again["id"] == row["id"]
    assert [r["status"] for r in _rows_for(row["sha256"])] == ["blocked"]


def test_a_register_named_row_is_refused_even_when_hand_approved_and_with_chat_consent():
    doc = _doc("doc_r", SHA_A, filename="ENGINEERING deliverables.pdf")
    _set_list((SHA_A, "approved"))
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    with claude_approved.per_request_consent([doc]):
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


def test_the_same_bytes_uploaded_under_the_register_name_block_an_earlier_approval():
    row = _upload("invented submittal.pdf")
    classification.set_role(row["id"], SUBMITTAL)
    assert _rows_for(row["sha256"])[0]["status"] == "approved"
    again = _upload("Engineering Deliverables.pdf")
    assert again["id"] == row["id"]  # a duplicate: the same stored document
    assert "blocked" in {r["status"] for r in _rows_for(row["sha256"])}
    assert _refused_code([row["id"]]) == claude_approved.NOT_APPROVED


# ---------------------------------------------------------------- blocks win


def test_an_owner_block_is_never_overwritten():
    doc = _doc("doc_b", SHA_A)
    _set_list((SHA_A, "blocked"))
    before = claude_approved.list_path().read_bytes()
    classification.set_role(doc, SUBMITTAL)
    _start_review(doc)
    assert claude_approved.list_path().read_bytes() == before
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    with claude_approved.per_request_consent(
        [doc]
    ):  # chat consent does not lift a block
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


def test_a_re_upload_of_a_blocked_hash_under_another_name_stays_blocked():
    row = _upload("first name.pdf")
    _set_list((row["sha256"], "blocked"))
    again = _upload("a quite different name.pdf")
    classification.set_role(again["id"], SUBMITTAL)
    assert [r["status"] for r in _rows_for(row["sha256"])] == ["blocked"]
    assert _refused_code([again["id"]]) == claude_approved.NOT_APPROVED


def test_a_hash_in_the_block_file_is_not_added_and_is_refused_even_if_hand_approved():
    doc = _doc("doc_h", SHA_A)
    _write_block_file([SHA_A.upper()])
    classification.set_role(doc, SUBMITTAL)
    assert _rows() == []
    _set_list((SHA_A, "approved"))
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


def test_a_blocked_row_beside_an_approved_one_wins():
    doc = _doc("doc_b", SHA_A)
    _set_list((SHA_A, "approved"), (SHA_A, "blocked"))
    assert SHA_A not in claude_approved.approved_hashes()
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED


# ---------------------------------------------------------------- fail closed


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{not json",
        "[]",
        '{"blocked_sha256": "aa"}',
        '{"blocked_sha256": ["not-a-hash"]}',
        '{"blocked_sha256": []}',
    ],
)
def test_an_unreadable_block_file_adds_nothing_and_sends_nothing(content):
    if content is None:
        claude_approved.block_file_path().unlink()
    else:
        claude_approved.block_file_path().write_text(content, encoding="utf-8")
    doc = _doc("doc_u", SHA_A)
    classification.set_role(doc, SUBMITTAL)
    assert not claude_approved.list_path().exists()
    _set_list((SHA_A, "approved"))
    assert claude_approved.approved_hashes() == frozenset()
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    with claude_approved.per_request_consent([doc]):
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"documents": "x"}',
        '{"documents": ["x"]}',
        '{"documents": [{"status": "blocked"}]}',
    ],
)
def test_an_unreadable_list_is_not_overwritten_and_sends_nothing(content):
    doc = _doc("doc_u", SHA_A)
    claude_approved.list_path().write_text(content, encoding="utf-8")
    classification.set_role(doc, SUBMITTAL)
    assert claude_approved.list_path().read_text(encoding="utf-8") == content
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    with claude_approved.per_request_consent([doc]):
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


@pytest.mark.parametrize("content", [None, "{not json", '{"blocked_sha256": []}'])
def test_a_register_named_upload_keeps_its_block_when_the_block_file_cannot_be_read(
    content,
):
    if content is None:
        claude_approved.block_file_path().unlink()
    else:
        claude_approved.block_file_path().write_text(content, encoding="utf-8")
    row = _upload("Engineering Deliverables.pdf")
    assert [r["status"] for r in _rows_for(row["sha256"])] == ["blocked"]
    # The owner repairs the file: the same bytes stay blocked under another name.
    _write_block_file([OWNER_HASH])
    again = _upload("a quite different name.pdf")
    classification.set_role(again["id"], SUBMITTAL)
    assert [r["status"] for r in _rows_for(row["sha256"])] == ["blocked"]


def test_a_step_with_a_blocked_document_runs_local_and_says_how_many():
    doc = _doc("doc_b", SHA_A, filename="Engineering Deliverables.pdf")
    other = _doc("doc_ok", SHA_B)
    _set_list((SHA_A, "approved"), (SHA_B, "approved"))
    with claude_approved.carrying([doc, other]):
        assert claude_approved.local_instead() == claude_approved.LOCAL_INSTEAD.format(
            n=1, of=2
        )


# ---------------------------------------------------------------- the gate


def _fake_send(url, *, headers, body, timeout):
    return {
        "model": "claude-sonnet-5",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "stop_reason": "end_turn",
    }


_BODY = {
    "model": "claude-sonnet-5",
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "hi"}],
}


def test_the_gate_refuses_unlisted_and_blocked_and_the_transport_is_never_called():
    unlisted = _doc("doc_x", SHA_A)
    blocked = _doc("doc_y", SHA_B)
    _set_list((SHA_B, "blocked"))
    calls = []

    def send(url, *, headers, body, timeout):
        calls.append(body)
        return _fake_send(url, headers=headers, body=body, timeout=timeout)

    metered = claude_spend.metered(send, "auto-test")
    for doc in (unlisted, blocked):
        with claude_approved.carrying([doc]):
            with pytest.raises(claude_spend.DocumentNotApproved):
                metered("https://invalid.invalid", headers={}, body=_BODY, timeout=1)
    assert calls == []
    assert not [e for e in claude_spend.entries() if e.get("reserved")]


# ---------------------------------------------------------------- the audit


def test_every_auto_add_is_recorded_with_hash_and_id_never_the_name():
    row = _upload("Invented Secret Title.pdf")
    classification.set_role(row["id"], SUBMITTAL)
    rows = _audit(claude_auto_approve.AUDIT_ADDED)
    assert [r["resource_id"] for r in rows] == [row["sha256"]]
    assert json.loads(rows[0]["detail"]) == {"document_id": row["id"], "source": "auto"}
    assert rows[0]["actor_username"] == "auto: owner decision #1584"
    changed = _audit(claude_approved.AUDIT_ACTION)
    assert changed and changed[-1]["actor_username"] == "auto: owner decision #1584"
    assert "Invented Secret Title" not in json.dumps([dict(r) for r in rows + changed])


def test_a_register_block_is_recorded_without_the_name():
    row = _upload("Engineering Deliverables.pdf")
    rows = _audit(claude_auto_approve.AUDIT_BLOCKED)
    assert [r["resource_id"] for r in rows] == [row["sha256"]]
    assert "Deliverables" not in json.dumps([dict(r) for r in rows])


def test_an_owner_edit_is_recorded_when_a_review_starts():
    doc = _doc("doc_sub", SHA_A)
    _set_list((SHA_B, "blocked"))
    assert _audit(claude_approved.AUDIT_ACTION) == []
    _start_review(doc)
    assert _audit(claude_approved.AUDIT_ACTION)


def test_every_send_is_recorded_with_document_step_model_and_time_and_no_name():
    doc = _doc("doc_a", SHA_A, filename="Invented Secret Title.pdf")
    other = _doc("doc_b", SHA_B)
    _set_list((SHA_A, "approved"), (SHA_B, "approved"))
    with claude_approved.carrying([doc, other]):
        claude_spend.metered(_fake_send, "auto-step")(
            "https://invalid.invalid", headers={}, body=_BODY, timeout=1
        )
    sent = [e for e in _ledger() if e.get("sent_documents")]
    assert len(sent) == 1
    line = sent[0]
    assert (
        line["step"] == "auto-step"
        and line["model"] == "claude-sonnet-5"
        and line["at"]
    )
    assert line["sent_documents"] == [
        {"document_id": doc, "sha256": SHA_A},
        {"document_id": other, "sha256": SHA_B},
    ]
    assert "Invented Secret Title" not in settings.claude_spend_log.read_text(
        encoding="utf-8"
    )


def test_every_request_of_a_batch_is_recorded():
    doc = _doc("doc_a", SHA_A)
    _set_list((SHA_A, "approved"))
    with claude_approved.carrying([doc]):
        claude_spend.reserve_all([("s1", 0.01), ("s2", 0.01)], model="claude-sonnet-5")
    assert [e["step"] for e in _ledger() if e.get("sent_documents")] == ["s1", "s2"]


def test_a_chat_consent_send_is_recorded():
    doc = _doc("doc_a", SHA_A)  # on no list: the user selected it for this request
    with claude_approved.per_request_consent([doc]):
        _reserve("chat-step")
    assert [e["sent_documents"] for e in _ledger() if e.get("step") == "chat-step"] == [
        [{"document_id": doc, "sha256": SHA_A}]
    ]


def test_a_prompt_with_no_document_content_records_no_document():
    with claude_approved.carrying(()):
        _reserve("no-docs")
    assert not [e for e in _ledger() if "sent_documents" in e]


def test_a_refused_call_records_no_send():
    doc = _doc("doc_x", SHA_A)
    _refused_code([doc])
    assert not [e for e in _ledger() if "sent_documents" in e]


# ---------------------------------------------------------------- safe writes


def test_concurrent_uploads_lose_no_entry():
    docs = [_doc(f"doc_{i}", f"{i:02x}" * 32, None) for i in range(24)]
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO document_classification (document_id, document_role, suggested_by)"
            " VALUES (?, ?, 'test')",
            [(d, SUBMITTAL) for d in docs],
        )
    start, faults = threading.Barrier(len(docs)), []

    def add(doc):
        try:
            start.wait()
            claude_auto_approve.on_upload(doc)
        except Exception as exc:  # noqa: BLE001 - reported by the assert below
            faults.append(exc)
        finally:
            db.reset_connection()

    threads = [threading.Thread(target=add, args=(d,)) for d in docs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert faults == []
    assert sorted(r["document_id"] for r in _rows()) == sorted(docs)


def test_a_write_waits_for_another_process_holding_the_file_lock():
    doc = _doc("doc_1", SHA_A, None)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, suggested_by)"
            " VALUES (?, ?, 'test')",
            (doc, SUBMITTAL),
        )
    path = claude_approved.list_path()
    done = threading.Event()

    def add():
        claude_auto_approve.on_upload(doc)
        db.reset_connection()
        done.set()

    with path.with_name(path.name + ".lock").open("a+b") as fh:
        claude_spend._os_lock(fh)  # what another process holds: not the thread lock
        thread = threading.Thread(target=add)
        thread.start()
        assert not done.wait(0.4)
        assert _rows() == []
        claude_spend._os_unlock(fh)
    thread.join()
    assert _rows_for(SHA_A)[0]["status"] == "approved"


def test_a_failed_write_leaves_the_old_list_whole(monkeypatch):
    first = _doc("doc_1", SHA_A)
    second = _doc("doc_2", SHA_B)
    classification.set_role(first, SUBMITTAL)
    before = claude_approved.list_path().read_bytes()

    def broken(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(claude_auto_approve.Path, "replace", broken)
    classification.set_role(second, SUBMITTAL)  # never raises into the role write
    assert claude_approved.list_path().read_bytes() == before
    assert [
        p.name
        for p in settings.data_dir.iterdir()
        if p.name.startswith(".claude_approved")
    ] == []


def test_a_hook_never_raises_into_the_upload(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("invented fault")

    monkeypatch.setattr(claude_auto_approve, "_apply", broken)
    row = _upload("invented submittal.pdf")
    assert row["id"]
    claude_auto_approve.on_upload(row["id"])


def test_the_list_write_is_outside_git():
    assert claude_approved.list_path().parent == settings.data_dir
    assert claude_approved.block_file_path().parent == settings.data_dir
