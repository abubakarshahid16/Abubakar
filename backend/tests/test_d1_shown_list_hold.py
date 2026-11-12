"""D1 PR 1 (owner, 12 Nov 2026, #1584): "the screen lists every document that will leave the Mac before the review starts".
Until a start route stores such a list, a SPECIFICATION that is not the paper under review is not sent, on every review route:
the AI reviewer and the three `claude_api` review routes. The paper, rule books and chat's per-request consent are unchanged.
Invented documents; no call is made (the gate is asked, nothing is sent)."""

from __future__ import annotations

import json

import pytest

from app import (
    classification,
    claude_approved,
    claude_spend,
    claude_spend_report,
    db,
    review_shown,
    submittal_review,
)
from app.config import settings

NOW = "2026-11-12T00:00:00Z"
SUBMITTAL, STANDARD, SPEC = "CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "SPECIFICATION"
SHA = {
    "doc_paper": "a1" * 32,
    "doc_spec": "b2" * 32,
    "doc_book": "c3" * 32,
    "doc_spec_paper": "d4" * 32,
}


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "d1.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    for doc_id, role in (
        ("doc_paper", SUBMITTAL),
        ("doc_spec", SPEC),
        ("doc_book", STANDARD),
        ("doc_spec_paper", SPEC),
    ):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", SHA[doc_id], f"{doc_id}.pdf", NOW),
            )
        classification.set_role(doc_id, role)
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {"sha256": s, "status": "approved", "label": "invented"}
                    for s in SHA.values()
                ]
            }
        ),
        encoding="utf-8",
    )
    yield
    db.reset_connection()


def _run(paper="doc_paper", cited=("doc_spec", "doc_book")) -> str:
    run_id = "run_d1"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?, 'running', ?, ?)",
            (run_id, paper, NOW, NOW),
        )
        for n, doc in enumerate(cited):
            conn.execute(
                "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, selection_reason,"
                " selection_method, included, created_at) VALUES (?,?,?,'x','referenced',1,?)",
                (f"s{n}", run_id, doc, NOW),
            )
    return run_id


def _show(run_id, ids):
    with db.connect() as conn, conn:
        review_shown.record_in(conn, run_id, ids, NOW)


def _gate_ai_reviewer(run_id, ids):
    """How `agent_review_jobs._ask` declares: carrying + for_run."""
    with claude_approved.carrying(sorted(ids)), claude_spend.for_run(run_id):
        return claude_approved.refusal()


def _gate_select_and_datasheet(run_id, ids):
    """How the select-standards and read-datasheet routes declare: carrying + for_route."""
    with claude_approved.carrying(ids), claude_spend_report.for_route(run_id):
        return claude_approved.refusal()


def _gate_recheck(run_id, ids):
    """The recheck route and the review steps: `for_review` declares the run's documents."""

    @claude_approved.for_review
    def step(review_run_id):
        return claude_approved.refusal()

    return step(run_id)


def _gate_comparison(run_id, ids):
    with (
        claude_approved.carrying(claude_approved.review_documents(run_id)),
        claude_approved.reviewing(run_id),
    ):
        return claude_approved.refusal()


ROUTES = [
    _gate_ai_reviewer,
    _gate_select_and_datasheet,
    _gate_recheck,
    _gate_comparison,
]


@pytest.mark.parametrize("gate", ROUTES)
def test_a_cited_specification_on_the_approved_list_is_refused_when_no_list_was_shown(
    gate,
):
    run_id = _run()
    found = gate(run_id, ["doc_paper", "doc_spec"])
    assert found is not None and found[0] == claude_approved.NOT_APPROVED
    assert "doc_spec" in found[1] and "shown before the start" in found[1]
    assert "doc_paper" not in found[1]


@pytest.mark.parametrize("gate", ROUTES)
def test_the_same_specification_goes_when_the_shown_list_names_it(gate):
    run_id = _run()
    _show(run_id, ["doc_paper", "doc_spec", "doc_book"])
    assert gate(run_id, ["doc_paper", "doc_spec", "doc_book"]) is None


def test_a_shown_list_that_leaves_the_specification_out_still_refuses_it():
    run_id = _run()
    _show(run_id, ["doc_paper", "doc_book"])
    assert _gate_ai_reviewer(run_id, ["doc_paper", "doc_spec"]) is not None


def test_a_specification_that_is_the_paper_under_review_is_unchanged():
    run_id = _run(paper="doc_spec_paper", cited=())
    for gate in ROUTES:
        assert gate(run_id, ["doc_spec_paper"]) is None


def test_a_rule_book_and_the_paper_are_unchanged_without_a_list():
    run_id = _run(cited=("doc_book",))
    for gate in ROUTES:
        assert gate(run_id, ["doc_paper", "doc_book"]) is None


def test_outside_a_review_run_nothing_changes():
    with claude_approved.carrying(["doc_spec"]):
        assert claude_approved.refusal() is None


def test_chats_per_request_consent_is_unchanged(monkeypatch):
    run_id = _run()
    with (
        claude_approved.per_request_consent(["doc_spec"]),
        claude_spend.for_run(run_id),
    ):
        assert claude_approved.refusal() is None


def test_a_library_that_cannot_be_read_holds_the_specification(monkeypatch):
    run_id = _run()

    def boom(*a, **k):
        raise review_shown.sqlite3.OperationalError("locked")

    monkeypatch.setattr(review_shown, "unshown_specifications", boom)
    assert _gate_ai_reviewer(run_id, ["doc_paper", "doc_spec"]) is not None


def test_local_instead_says_the_specification_was_not_on_the_list_shown():
    run_id = _run()
    with (
        claude_approved.carrying(["doc_paper", "doc_spec"]),
        claude_approved.reviewing(run_id),
    ):
        said = claude_approved.local_instead()
    assert said is not None and "not on the list shown before the start" in said
    assert "doc_spec" not in said  # counts, never an id or a title


def test_the_run_note_counts_the_cited_specifications_not_sent():
    run_id = _run()
    with db.connect() as conn:
        assert review_shown.cited_unshown(conn, run_id) == 1
    _show(run_id, ["doc_spec"])
    with db.connect() as conn:
        assert review_shown.cited_unshown(conn, run_id) == 0


def test_the_run_says_it_did_not_send_the_cited_specification_even_with_the_switch_off():
    from app import absence, claude_auto_approve

    run_id = _run()
    claude_auto_approve.record_on_run(run_id)
    with db.connect() as conn:
        outcome = json.loads(
            conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
            ).fetchone()[0]
            or "{}"
        )
    assert outcome[claude_auto_approve.SHOWN_KEY] == {"not_sent": 1}
    lines = [p["line"] for p in claude_auto_approve.run_lines(outcome)]
    assert any(
        line.startswith("Not sent: 1 specification(s)")
        and "shown before the start" in line
        for line in lines
    )
    _show(run_id, ["doc_spec"])
    claude_auto_approve.record_on_run(run_id)
    with db.connect() as conn:
        outcome = json.loads(
            conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
            ).fetchone()[0]
            or "{}"
        )
    assert claude_auto_approve.SHOWN_KEY not in outcome
