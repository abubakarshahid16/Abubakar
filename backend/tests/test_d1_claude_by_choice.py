"""D1 (owner, 12 Nov 2026, #1584: "button is enough"): a review started with the EXPLICIT choice of Claude sends exactly the documents
the screen listed, of any kind; Automatic never sends a contract; the register stays blocked. Invented documents; no call is made."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    claude_approved,
    claude_spend,
    contract_yes,
    db,
    review_engine,
    review_engine_start,
    review_shown,
)
from app.config import settings
from app.main import app
from tests.test_b1_review_engine import _doc, open_facts
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

REGISTER_FILE = f"{claude_approved.REGISTER_NAME_KEY} (1).pdf"


@pytest.fixture
def lib(world, monkeypatch):  # noqa: F811
    """The p3 paper plus a cited contract, a cited specification, a cited procedure and a register-named file; the approved list is
    enforced and holds NOTHING: only the explicit choice can send them."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    docs = {
        "con": _doc(
            "con_1",
            "72" * 32,
            "CONTRACT_DOCUMENT",
            filename="SAES-C-001 invented contract.pdf",
        ),
        "spec": _doc(
            "spec_1",
            "71" * 32,
            "SPECIFICATION",
            filename="SAES-Q-001 invented spec.pdf",
        ),
        "proc": _doc(
            "proc_1",
            "73" * 32,
            "SUPPORTING_DOCUMENT",
            filename="SAES-P-001 invented procedure.pdf",
        ),
        "reg": _doc("reg_1", "74" * 32, "SUPPORTING_DOCUMENT", filename=REGISTER_FILE),
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,1,0)",
            (world["sub"], "Per SAES-C-001, SAES-Q-001 and SAES-P-001."),
        )
        conn.execute(
            "UPDATE chunks SET text = text || ' Also SAES-C-001, SAES-Q-001, SAES-P-001.' WHERE document_id = ?",
            (world["sub"],),
        )
        conn.execute(
            "UPDATE documents SET filename = 'API 610 invented.pdf' WHERE id = ?",
            (world["std"],),
        )
    world.update(docs)
    world["scope"] = world["scope"] | set(docs.values())
    return world


def _plan(w, engine):
    return review_engine.plan_for(db.connect(), w["sub"], w["scope"], engine)[
        "documents"
    ]


def _start(w, engine, shown):
    return review_engine_start.start(
        w["sub"], w["scope"], "adm", engine, shown_document_ids=tuple(shown)
    )


def _gate(run_id, ids):
    with claude_approved.carrying(sorted(ids)), claude_spend.for_run(run_id):
        return claude_approved.refusal()


def test_a_listed_contract_with_the_explicit_choice_is_listed_sent_and_recorded(lib):
    docs = _plan(lib, "claude")
    ids = {d["id"] for d in docs["leaving"]}
    assert lib["con"] in ids and lib["spec"] in ids
    assert next(d for d in docs["leaving"] if d["id"] == lib["con"])["contract"] is True
    run_id, _ = _start(lib, "claude", ids)
    assert (
        _gate(run_id, [lib["sub"], lib["con"], lib["spec"]]) is None
    )  # sent: the older per-upload yes is not needed
    got = review_shown.consent_of(db.connect(), run_id)
    assert got["user_id"] == "adm" and got["at"]
    assert {d["id"] for d in got["documents"].values()} == ids
    assert (
        got["documents"][lib["con"]]["role"] == "CONTRACT_DOCUMENT"
        and got["documents"][lib["con"]]["sha256"]
    )
    stored = json.dumps(got)
    assert (
        "invented contract" not in stored
    )  # ids, kinds, roles and hashes: never a title


def test_the_same_with_automatic_lists_no_contract_and_sends_nothing_of_it(lib):
    docs = _plan(lib, "automatic")
    assert lib["con"] not in {d["id"] for d in docs["leaving"]}
    assert any(n.get("id") == lib["con"] for n in docs["not_sent"])
    run_id, _ = _start(lib, "automatic", {d["id"] for d in docs["leaving"]})
    assert (
        review_shown.consent_of(db.connect(), run_id) is None
    )  # no consent without the explicit choice
    assert _gate(run_id, [lib["sub"], lib["con"]]) is not None
    plan = review_engine.plan_for(db.connect(), lib["sub"], lib["scope"], "automatic")
    assert plan[
        "parts"
    ]  # the paper itself is not a contract here; a contract PAPER resolves to Local (test_b1_review_engine)


def test_a_contract_not_on_the_shown_list_is_not_sent_even_with_the_explicit_choice(
    lib,
):
    run_id, _ = _start(lib, "claude", {lib["sub"], lib["spec"]})
    found = _gate(run_id, [lib["sub"], lib["con"]])
    assert found is not None and lib["con"] in found[1]


def test_the_register_is_refused_even_when_listed_and_consented_and_shown_blocked_by_the_owner(
    lib,
):
    docs = review_engine.plan_for(
        db.connect(), lib["sub"], lib["scope"], "claude", project_ids=(lib["reg"],)
    )["documents"]
    assert lib["reg"] not in {d["id"] for d in docs["leaving"]}
    assert any(
        n.get("id") == lib["reg"] and "blocked by the owner" in n["reason"]
        for n in docs["not_sent"]
    )
    run_id, _ = _start(lib, "claude", {lib["sub"]})
    with db.connect() as conn, conn:  # a client that lists it anyway
        review_shown.record_in(conn, run_id, [lib["sub"], lib["reg"]], "t")
        review_shown.record_consent_in(
            conn,
            run_id,
            "adm",
            [
                {
                    "id": lib["reg"],
                    "kind": "x",
                    "role": "SUPPORTING_DOCUMENT",
                    "sha256": "74" * 32,
                }
            ],
            "t",
        )
    found = _gate(run_id, [lib["sub"], lib["reg"]])
    assert found is not None and "blocked" in found[1]


def test_a_start_without_a_list_behaves_as_today(lib):
    run_id, _ = review_engine_start.start(lib["sub"], lib["scope"], "adm", "claude")
    assert review_shown.consent_of(db.connect(), run_id) is None
    found = _gate(run_id, [lib["sub"], lib["con"]])
    assert found is not None  # no contract without the owner's yes
    contract_yes.grant(lib["con"], "owner")  # the older per-upload yes still works
    assert (
        _gate(run_id, [lib["con"]]) is None
    )  # a contract yes still satisfies the contract check; the list says the rest


def test_the_consent_of_another_run_or_another_user_does_not_carry_over(lib):
    ids = {d["id"] for d in _plan(lib, "claude")["leaving"]}
    first, _ = _start(lib, "claude", ids)
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status='completed' WHERE id = ?", (first,))
    second, _ = _start(
        lib, "claude", {lib["sub"]}
    )  # the same paper, a new screen with a shorter list
    assert _gate(first, [lib["sub"], lib["con"]]) is None
    assert (
        _gate(second, [lib["sub"], lib["con"]]) is not None
    )  # run one's consent is not run two's
    assert _gate("some-other-run", [lib["con"]]) is not None


def test_a_listed_document_that_is_blocked_or_replaced_after_the_start_is_refused_at_send_time(
    lib,
):
    ids = {d["id"] for d in _plan(lib, "claude")["leaving"]}
    run_id, _ = _start(lib, "claude", ids)
    assert _gate(run_id, [lib["con"]]) is None
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["72" * 32]})
    )
    found = _gate(run_id, [lib["con"]])
    assert found is not None and "blocked" in found[1]
    claude_approved.block_file_path().write_text(json.dumps({"blocked_sha256": []}))
    with (
        db.connect() as conn
    ):  # the file was replaced by another revision after the start
        conn.execute(
            "UPDATE documents SET sha256 = ? WHERE id = ?", ("99" * 32, lib["con"])
        )
    assert _gate(run_id, [lib["con"]]) is not None


def test_a_procedure_and_a_specification_go_on_the_explicit_choice_and_not_on_automatic(
    lib,
):
    on = {d["id"] for d in _plan(lib, "claude")["leaving"]}
    off = {d["id"] for d in _plan(lib, "automatic")["leaving"]}
    assert {lib["proc"], lib["spec"]} <= on
    assert (
        lib["proc"] not in off and lib["spec"] not in off
    )  # not on the approved list: Automatic does not send them


def test_the_start_route_records_the_consent_and_the_plan_route_marks_a_contract(lib):
    client = TestClient(app)
    with (
        db.connect() as conn
    ):  # the paper under review is itself a contract (the caller may read it)
        conn.execute(
            "UPDATE document_classification SET document_role='CONTRACT_DOCUMENT' WHERE document_id = ?",
            (lib["sub"],),
        )
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": lib["sub"], "engine": "claude"},
        headers=lib["admin"],
    ).json()
    ids = [d["id"] for d in plan["documents"]["leaving"]]
    assert any(d["contract"] for d in plan["documents"]["leaving"])
    started = client.post(
        "/api/reviews/start",
        json={
            "submittal_document_id": lib["sub"],
            "engine": "claude",
            "shown_document_ids": ids,
        },
        headers=lib["admin"],
    )
    assert started.status_code == 200, started.text
    assert (
        review_shown.consent_of(db.connect(), started.json()["review_run_id"])
        is not None
    )
