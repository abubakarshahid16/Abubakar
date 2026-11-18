# ruff: noqa: F811
"""Reference papers on the plan (order 14): a contract's cited Schedule that one held paper is, is LISTED before the start with why
"cited by the paper; same package", through the same gate as any contract; nothing is added for a paper that is not a contract; a part the
viewer may not read is counted, never named. Invented documents only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import db
from app.aim_review import references as R
from app.main import app
from tests.test_g2_review_list import papers, real_roles  # noqa: F401 - fixtures
from tests.test_p3_review_jobs import _doc, _user, temp_storage  # noqa: F401 - fixtures

AGREEMENT_TEXT = "FORM OF AGREEMENT\nThe milestones are set out in Schedule C.\n"


def _pages(doc_id: str, text: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, 1, ?, ?, 0)",
            (doc_id, text, len(text)),
        )


def _world(ids):
    _pages(ids["contract"], AGREEMENT_TEXT)
    ids["sched"] = _doc("doc_r_sched_c", "CONTRACT_DOCUMENT", "Invented schedule.")
    with (
        db.connect() as conn
    ):  # the administrator's role is granted each document one by one in these worlds
        conn.execute(
            "INSERT INTO document_role_access (document_id, role_id, granted_at) VALUES (?, 'r-adm', '2026-11-18T10:00:00Z')",
            (ids["sched"],),
        )
    _pages(
        ids["sched"],
        "SCHEDULE C\nMILESTONES\nThe contractor shall complete milestone one in ninety days.\n",
    )
    with db.connect() as conn:  # the parts of one package carry one RECORDED project
        conn.execute(
            "UPDATE document_classification SET project = 'Invented Project One' WHERE document_id IN (?, ?)",
            (ids["contract"], ids["sched"]),
        )
    return ids


def _docs(ids, doc, engine, headers=None):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": ids[doc], "engine": engine},
        headers=headers or ids["admin"],
    )
    assert r.status_code == 200, r.text
    return r.json()["documents"]


def test_the_explicit_choice_of_claude_lists_the_schedule_as_a_reference_paper(
    real_roles,
):
    ids = _world(real_roles)
    docs = _docs(ids, "contract", "claude")
    ref = [d for d in docs["leaving"] if d["id"] == ids["sched"]]
    assert len(ref) == 1
    assert ref[0]["kind"] == R.KIND_WORDS == "reference paper"
    assert (
        ref[0]["why"] == "cited by the paper; same package"
        and ref[0]["contract"] is True
    )
    assert ref[0]["part"] == "Schedule C"


def test_automatic_sends_nothing_of_a_contract_and_the_gate_refuses_the_reference_without_the_explicit_choice(
    real_roles,
):
    from types import SimpleNamespace

    from app import review_leaving

    ids = _world(real_roles)
    assert ids["sched"] not in {
        d["id"] for d in _docs(ids, "contract", "automatic")["leaving"]
    }
    row = {
        "id": ids["sched"],
        "sha256": "x",
        "filename": "invented.pdf",
        "role": "CONTRACT_DOCUMENT",
    }
    facts = SimpleNamespace(paper_approved=True, is_contract=True)
    assert (
        review_leaving._Gate(facts, explicit=False).why_not(row, R.KIND_WORDS)
        == review_leaving.CONTRACT_WORDS
    )
    assert (
        review_leaving._Gate(facts, explicit=True).why_not(row, R.KIND_WORDS) is None
    )  # the explicit choice, as for any contract


def test_a_paper_that_is_not_a_contract_lists_no_reference_paper(
    real_roles, monkeypatch
):
    from app import claude_auto_approve

    ids = _world(real_roles)
    monkeypatch.setattr(
        claude_auto_approve, "is_contract_paper", lambda doc: doc == ids["contract"]
    )
    _pages(
        ids["submittal"], AGREEMENT_TEXT
    )  # it names Schedule C too, but it is not a contract
    docs = _docs(ids, "submittal", "claude")
    assert ids["sched"] not in {
        d["id"] for d in docs["leaving"] + docs["not_sent"] if "id" in d
    }


def test_a_part_the_viewer_may_not_read_is_counted_never_named(real_roles):
    ids = _world(real_roles)
    reader = _user(
        "rf_rdr", [ids["contract"]]
    )  # may read the agreement, not the schedule
    docs = _docs(ids, "contract", "claude", headers=reader)
    assert ids["sched"] not in str(docs) and "doc_r_sched_c" not in str(docs)
    assert docs["not_readable"] >= 1
