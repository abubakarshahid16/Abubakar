"""B3 hooks: the leaving list names the project context only with the nine-role switch on; "whole chapters" words; project papers
for a datasheet only with it on. Invented documents; no call."""

from __future__ import annotations

from app import db, nine_context, review_leaving
from tests.test_b1_review_engine import _doc
from tests.test_d1_leaving_list import _plan, lib  # noqa: F401 - fixtures
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures


def _setup(w):
    rel = _doc("rel_1", "81" * 32, None, filename="Invented layout drawing.pdf")
    sp2 = _doc(
        "spec_2", "84" * 32, "SPECIFICATION", filename="Invented project spec.pdf"
    )
    old = _doc("old_1", "82" * 32, None, filename="Invented datasheet rev A.pdf")
    reg = _doc("reg_1", "83" * 32, None, filename="Invented blocked register.pdf")
    with db.connect() as conn:
        for d in (rel, old, reg, sp2):
            conn.execute(
                "INSERT OR IGNORE INTO document_classification (document_id, suggested_by) VALUES (?, 'test')",
                (d,),
            )
        for d in (w["sub"], w["spec"], w["con"], rel, sp2):
            conn.execute(
                "UPDATE document_classification SET project = 'P-1' WHERE document_id = ?",
                (d,),
            )
        conn.execute(
            "UPDATE document_classification SET project = 'P-1', superseded_by = ? WHERE document_id = ?",
            (w["sub"], old),
        )
        conn.execute(
            "UPDATE document_classification SET project = 'P-1' WHERE document_id = ?",
            (reg,),
        )
    w["scope"] = w["scope"] | {rel, old, reg, sp2}
    return rel, old, reg


def _ids(plan):
    return {r["id"]: r for r in plan["leaving"] + plan["not_sent"] if "id" in r}


def test_off_lists_no_project_context(lib, monkeypatch):  # noqa: F811
    monkeypatch.setattr(nine_context, "nine_on", lambda: False)
    rel, old, _reg = _setup(lib)
    plan = _plan(lib, engine="claude")
    assert rel not in _ids(plan) and old not in _ids(plan)
    assert "whole chapters" not in plan["summary"]


def test_on_lists_project_context_with_kind_and_why(lib, monkeypatch):  # noqa: F811
    from app import claude_approved

    real = claude_approved.blocked_by_name
    monkeypatch.setattr(
        claude_approved,
        "blocked_by_name",
        lambda n: "blocked register" in (n or "") or real(n),
    )
    monkeypatch.setattr(nine_context, "nine_on", lambda: True)
    rel, old, reg = _setup(lib)
    plan = _plan(lib, engine="claude")
    rows = _ids(plan)
    assert (
        rows[rel]["kind"] == review_leaving.PROJECT_PAPER
        and rows[rel]["why"] == review_leaving.WHY_RELATED
    )
    assert rows[old]["why"] == review_leaving.WHY_EARLIER
    assert rows["spec_2"]["why"] == review_leaving.WHY_PROJECT_SPEC
    assert rows[lib["con"]]["kind"] == review_leaving.CONTRACT
    assert reg not in rows  # the register is never listed
    assert "whole chapters" in plan["summary"]


def test_datasheet_project_papers_need_the_switch(monkeypatch):
    from fastapi import HTTPException

    from app.api import agent_review as ar
    from app.api import agent_review_schemas as c

    body = c.AgentRunRequest(submittal_document_id="d", project_document_ids=["x"])
    monkeypatch.setattr(nine_context, "nine_on", lambda: False)
    try:
        ar._checked_project_papers(body, "d", None, False)
        raise AssertionError(
            "a datasheet's project papers were accepted with the switch off"
        )
    except HTTPException as exc:
        assert exc.status_code == 422


def test_the_register_held_only_by_checksum_is_never_listed(lib, monkeypatch):  # noqa: F811
    monkeypatch.setattr(nine_context, "nine_on", lambda: True)
    _rel, _old, reg = _setup(lib)
    sha = "83" * 32
    from app import claude_approved

    monkeypatch.setattr(claude_approved, "blocked_hashes", lambda: frozenset({sha}))
    plan = _plan(lib, engine="claude")
    assert reg not in _ids(plan)


def test_an_unscored_related_paper_is_not_leaving_under_automatic(lib, monkeypatch):  # noqa: F811
    monkeypatch.setattr(nine_context, "nine_on", lambda: True)
    monkeypatch.setattr(nine_context, "paper_scored", lambda conn, d: False)
    rel, _old, _reg = _setup(lib)
    from tests.test_b1_review_engine import open_facts

    def listing(explicit):
        return _ids(
            review_leaving.leaving_for(
                db.connect(),
                lib["sub"],
                lib["scope"],
                open_facts(),
                equipment_type=None,
                leaves=True,
                explicit=explicit,
            )
        )

    assert listing(False)[rel]["reason"] == nine_context.WHY_UNSCORED
    assert "reason" not in listing(True)[rel]  # the explicit choice of Claude lists it


def test_a_datasheets_project_papers_are_checked_the_same_way_with_the_switch_on(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import agent_review as ar
    from app.api import agent_review_schemas as c

    monkeypatch.setattr(nine_context, "nine_on", lambda: True)
    seen = {}

    def fake(conn, paper, ids, allowed):
        seen["args"] = (paper, list(ids), frozenset(allowed))
        return [], ["no such document for this caller"]

    monkeypatch.setattr(ar.agent_general_review, "check_project_papers", fake)
    monkeypatch.setattr(ar, "require_document", lambda d, scope: None)

    class Scope:
        allowed_document_ids = frozenset({"a"})

    body = c.AgentRunRequest(submittal_document_id="d", project_document_ids=["x"])
    try:
        ar._checked_project_papers(body, "d", Scope(), False)
        raise AssertionError("a refused paper was accepted")
    except HTTPException as exc:
        assert exc.status_code == 422 and "no such document" in str(exc.detail)
    assert seen["args"] == (
        "d",
        ["x"],
        frozenset({"a"}),
    )  # the same access and kinds checks run


def test_a_related_paper_already_listed_by_the_paper_is_not_listed_twice(
    lib,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(nine_context, "nine_on", lambda: True)
    monkeypatch.setattr(nine_context, "paper_scored", lambda conn, d: False)
    rel = _doc("cit_1", "85" * 32, None, filename="SAES-D-002 invented layout.pdf")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, project) VALUES (?, 'test', 'P-1')",
            (rel,),
        )
        conn.execute(
            "UPDATE document_classification SET project = 'P-1' WHERE document_id = ?",
            (lib["sub"],),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,2,?,1,0)",
            (lib["sub"], "Also per SAES-D-002."),
        )
    lib["scope"] = lib["scope"] | {rel}
    from tests.test_b1_review_engine import open_facts

    out = review_leaving.leaving_for(
        db.connect(),
        lib["sub"],
        lib["scope"],
        open_facts(),
        equipment_type=None,
        leaves=True,
        explicit=False,
    )
    ids = [r["id"] for r in out["leaving"] + out["not_sent"] if r.get("id")]
    assert ids.count(rel) == 1
