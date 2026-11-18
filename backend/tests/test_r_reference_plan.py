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


def _docs(ids, doc, engine, headers=None, project=()):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={
            "submittal_document_id": ids[doc],
            "engine": engine,
            "project_document_ids": list(project),
        },
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


def _unlink(ids):
    """The Schedule belongs to ANOTHER recorded project: no recorded link ties it to the agreement."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET project = 'Invented Project Two' WHERE document_id = ?",
            (ids["sched"],),
        )


def test_a_held_schedule_no_record_ties_is_offered_unticked_and_not_listed_as_leaving(
    real_roles,
):
    ids = _world(real_roles)
    _unlink(ids)
    docs = _docs(ids, "contract", "claude")
    assert ids["sched"] not in {
        d["id"] for d in docs["leaving"]
    }  # not sent, not compared, unless ticked
    assert docs["offered"] == [
        {
            "id": ids["sched"],
            "title": docs["offered"][0]["title"],
            "part": "Schedule C",
            "why": "cited by this paper; tick to compare it",
            "ticked": False,
        }
    ]


def test_ticking_the_offered_schedule_puts_it_on_the_list_that_is_shown_and_stored(
    real_roles,
):
    ids = _world(real_roles)
    _unlink(ids)
    docs = _docs(ids, "contract", "claude", project=[ids["sched"]])
    ref = [d for d in docs["leaving"] if d["id"] == ids["sched"]]
    assert len(ref) == 1 and ref[0]["kind"] == R.KIND_WORDS, str(docs)[:1500]
    assert ref[0]["why"] == "cited by this paper; chosen by you to compare"
    assert docs["offered"][0]["ticked"] is True
    # the start caps what was shown against the plan NOW: with the same choice the ticked id is kept
    from app import review_shown

    plan = {"documents": docs}
    assert ids["sched"] in review_shown.cap(plan, [ids["sched"], ids["contract"]])
    # and what is stored with the run holds no title of an offered paper
    stored = review_shown.without_titles(plan)["documents"]
    assert "offered" not in stored and "title" not in str(stored["leaving"])


def test_a_tied_schedule_is_listed_not_offered_and_automatic_offers_no_send(real_roles):
    ids = _world(real_roles)  # same recorded project: tied
    docs = _docs(ids, "contract", "claude")
    assert ids["sched"] in {d["id"] for d in docs["leaving"]}
    assert docs.get("offered") == []
    auto = _docs(ids, "contract", "automatic")
    assert ids["sched"] not in {d["id"] for d in auto["leaving"]}


def test_an_offered_schedule_the_viewer_may_not_read_is_never_named(real_roles):
    ids = _world(real_roles)
    _unlink(ids)
    reader = _user("rf_rdr2", [ids["contract"]])
    docs = _docs(ids, "contract", "claude", headers=reader)
    assert docs.get("offered") == [] and ids["sched"] not in str(docs)


def _start_and_stored(ids, project):
    import json

    body = {
        "submittal_document_id": ids["contract"],
        "engine": "claude",
        "shown_document_ids": [ids["contract"], ids["sched"]],
        "project_document_ids": project,
    }
    r = TestClient(app).post("/api/reviews/start", json=body, headers=ids["admin"])
    assert r.status_code in (200, 201, 202), r.text
    with db.connect() as conn:
        row = conn.execute("SELECT documents_json FROM review_shown_lists").fetchone()
    return json.loads(row[0])


def test_the_start_stores_the_ticked_schedule_on_the_shown_list(real_roles):
    """The ticked Schedule is a chosen project paper: the start's plan lists it, so the stored shown list (what the run may send and
    compare) holds it."""
    ids = _world(real_roles)
    _unlink(ids)
    stored = _start_and_stored(ids, [ids["sched"]])
    assert ids["sched"] in stored and ids["contract"] in stored


def test_an_unticked_schedule_is_dropped_from_the_stored_list_even_if_the_screen_sent_its_id(
    real_roles,
):
    ids = _world(real_roles)
    _unlink(ids)
    stored = _start_and_stored(ids, [])
    assert ids["sched"] not in stored and ids["contract"] in stored
