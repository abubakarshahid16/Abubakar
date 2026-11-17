"""Order 14 LPD (P3; owner, 17 Nov 2026): when a CONTRACT paper is reviewed, the general terms paper of its own package is its
contract rule book, with the contract checklist CT-01 to CT-08; every line from either says "AI draft, engineer to confirm", is
internal only and never a Pass or Fail; behind `contract_rule_book_enabled` (default off); listed on the plan before the start.

INVENTED papers, numbers and words only (no client data). No network, no key: the model is a fake.
"""

from __future__ import annotations

import json

import pytest

from app import (
    agent_claude,
    agent_general_job,
    agent_review_jobs,
    agent_review_kind,
    claude_approved,
    contract_checks,
    contract_rule_book,
    db,
    review_engine,
    review_shown,
)
from app import agent_general_review as core
from app.config import settings
from tests import test_agent_general_review as g
from tests.test_agent_general_review import world  # noqa: F401 - the fixture

DRAFT = "AI draft, engineer to confirm"
NO_A, NO_B = "INV-77-001", "INV-88-002"
GT, SPECIAL, PRICE, FOREIGN, SPEC = (
    "doc_gt",
    "doc_special",
    "doc_price",
    "doc_foreign_gt",
    "doc_spec_gt",
)


def _head(no: str, heading: str) -> str:
    return (
        f"Invented Works Project   CONTRACT No. {no}\n{heading}\nPage 1 of 3\nRev 01\n"
    )


def _contract(conn, doc, filename, no, heading, body="Body text of the invented paper, long enough to be read. " * 6,
              role="CONTRACT_DOCUMENT"):  # fmt: skip
    g._add(conn, doc, filename, {1: _head(no, heading) + body, 2: body})
    conn.execute(
        "INSERT OR REPLACE INTO document_classification (document_id, suggested_by, document_role) VALUES (?,?,?)",
        (doc, "test", role),
    )


def _record(folder, monkeypatch, choices, raw=None):
    """A recorded choice in a throwaway file (the real one is git-ignored and local): {paper: rule book}."""
    path = folder / "contract_rule_book.local.json"
    body = {"format": "contract-rule-book/1", "choices": [{"papers": [p], "rule_book": b, "chosen_by": "engineer-x",
            "chosen_at": "2026-11-17"} for p, b in choices.items()]}  # fmt: skip
    path.write_text(raw if raw is not None else json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(contract_rule_book, "RECORD_FILE", path)
    return path


@pytest.fixture
def pkg(world, monkeypatch):  # noqa: F811
    """The world of the general review tests, its paper made a contract of package A, and a library around it."""
    monkeypatch.setattr(settings, "contract_rule_book_enabled", True)
    _record(world, monkeypatch, {g.PAPER: GT})
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM pages WHERE document_id = ? AND page_no = 1", (g.PAPER,)
        )
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,1,0)",
            (g.PAPER, _head(NO_A, "Form of Agreement") + g.PAGES[1]),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, document_role) VALUES (?,?,?)",
            (g.PAPER, "test", "CONTRACT_DOCUMENT"),
        )
        _contract(
            conn,
            GT,
            "08 - Schedule A - General Terms and Conditions - Rev 01.pdf",
            NO_A,
            "SCHEDULE A - General Terms and Conditions",
        )
        _contract(
            conn,
            SPECIAL,
            "15 - Schedule H - Special Terms and Conditions - Rev 01.pdf",
            NO_A,
            "SCHEDULE H - Special Terms and Conditions",
        )
        _contract(
            conn,
            PRICE,
            "10 - Schedule C - Contract Price - Rev 01.pdf",
            NO_A,
            "SCHEDULE C - Contract Price",
        )
        _contract(
            conn,
            FOREIGN,
            "08 - Schedule A - General Terms and Conditions - Rev 03.pdf",
            NO_B,
            "SCHEDULE A - General Terms and Conditions",
        )
        conn.commit()  # fmt: skip
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: g.reading("contract")
    )
    # the paper is a contract: at send time the gate wants the start's consent; these tests are about what is CARRIED and labelled
    monkeypatch.setattr(
        claude_approved, "contracts_without_yes", lambda _ids: frozenset()
    )
    return world


ALL = frozenset({g.PAPER, g.PROJ, g.OTHER, GT, SPECIAL, PRICE, FOREIGN})


def _book(scope=ALL):
    """What the title rule SUGGESTS (never used by itself)."""
    return contract_rule_book.suggest(db.connect(), g.PAPER, scope)


def _used(scope=ALL, kind="contract"):
    return contract_rule_book.rule_book_of(db.connect(), g.PAPER, scope, kind)


# ---------------------------------------------------------------- the general rule that finds the rule book


def test_the_general_terms_paper_of_the_same_package_is_the_rule_book(pkg):
    got = _book()
    assert got == {"id": GT, "why": contract_rule_book.WHY_SUGGESTED}
    assert set(contract_rule_book.package_papers(db.connect(), g.PAPER, ALL)) == {
        GT,
        SPECIAL,
        PRICE,
    }


def test_switch_off_or_a_paper_that_is_not_a_contract_has_no_rule_book(
    pkg, monkeypatch
):
    assert _used()["id"] == GT  # the recorded choice
    assert _used(kind="procedure")["id"] is None
    monkeypatch.setattr(settings, "contract_rule_book_enabled", False)
    assert _used()["id"] is None


def test_another_package_special_terms_and_a_paper_the_caller_may_not_read_are_never_chosen(
    pkg,
):
    assert (
        _book()["id"] != FOREIGN
    )  # the same title in another package (another contract number)
    without = ALL - {GT}
    got = _book(
        scope=without
    )  # rule 5: a filter only narrows; the foreign one is still another package
    assert got == {"id": None, "why": contract_rule_book.NONE_FOUND}


def test_two_general_terms_papers_in_one_package_choose_none_and_say_why(pkg):
    with db.connect() as conn:
        _contract(
            conn,
            "doc_gt2",
            "General Conditions of Contract.pdf",
            NO_A,
            "GENERAL CONDITIONS OF CONTRACT",
        )
    got = _book(scope=ALL | {"doc_gt2"})
    assert got["id"] is None and got["why"] == contract_rule_book.SEVERAL.format(n=2)


def test_the_title_decides_before_the_heading_and_a_heading_decides_when_no_title_does(
    pkg,
):
    with (
        db.connect() as conn
    ):  # a paper whose title says nothing of terms; its page-1 heading IS the general conditions
        _contract(
            conn,
            "doc_heads",
            "Schedule B.pdf",
            NO_A,
            "SCHEDULE B - General Conditions of Contract",
        )
        # a paper whose heading only REFERS to the general conditions is not them
        _contract(
            conn,
            "doc_refers",
            "Schedule D.pdf",
            NO_A,
            "SCHEDULE D - read with the General Conditions",
        )
        conn.commit()
    # (A) alone decides only when exactly one paper passes it: two pass, so none (the safe side)
    assert _book(scope=ALL | {"doc_heads"}) == {
        "id": None,
        "why": contract_rule_book.SEVERAL.format(n=2),
    }
    assert _book(scope=(ALL - {GT}) | {"doc_heads", "doc_refers"})["id"] == "doc_heads"
    assert (
        _book(scope=(ALL - {GT}) | {"doc_refers"})["why"]
        == contract_rule_book.NONE_FOUND
    )


def test_a_paper_that_is_not_a_contract_by_role_is_never_in_the_package(pkg):
    with db.connect() as conn:
        _contract(
            conn,
            SPEC,
            "General Terms for Suppliers.pdf",
            NO_A,
            "General Terms",
            role="SPECIFICATION",
        )
    assert SPEC not in contract_rule_book.package_papers(
        db.connect(), g.PAPER, ALL | {SPEC}
    )
    assert _book(scope=(ALL - {GT}) | {SPEC})["id"] is None


# ---------------------------------------------------------------- the plan lists it before the start (rule 1)


def _plan(choice, monkeypatch, scope=ALL):
    from tests.test_b1_review_engine import open_facts

    monkeypatch.setattr(review_engine, "read_facts",
                        lambda *a, **k: (open_facts(kind="contract", is_contract=True, contract_yes=True), None))  # fmt: skip
    return review_engine.plan_for(db.connect(), g.PAPER, scope, choice)["documents"]


def test_the_plan_lists_the_rule_book_before_an_explicit_claude_start(pkg, monkeypatch):
    docs = _plan("claude", monkeypatch)
    got = {d["id"]: d for d in docs["leaving"]}
    assert (
        got[GT]["kind"] == "contract"
        and got[GT]["why"] == contract_rule_book.WHY_LISTED
    )
    assert {SPECIAL, PRICE, FOREIGN}.isdisjoint(got)


def test_automatic_never_sends_it(pkg, monkeypatch):
    docs = _plan("automatic", monkeypatch)
    assert GT not in {
        d["id"] for d in docs["leaving"]
    }  # Automatic never sends a contract by itself (rule 1)
    held = {d.get("id"): d for d in docs["not_sent"]}
    assert GT not in held or held[GT]["why"] == contract_rule_book.WHY_LISTED


def test_switch_off_the_plan_is_unchanged(pkg, monkeypatch):
    on = _plan("claude", monkeypatch)
    monkeypatch.setattr(settings, "contract_rule_book_enabled", False)
    off = _plan("claude", monkeypatch)
    assert GT not in {d["id"] for d in off["leaving"]}
    assert [d for d in on["leaving"] if d["id"] != GT] == off["leaving"]


# ---------------------------------------------------------------- the run: what it may carry


def test_a_claude_run_carries_the_rule_book_only_when_the_list_shown_names_it(pkg):
    conn = db.connect()
    review_shown.record_in(conn, "run-listed", [g.PAPER, GT], "2026-11-17T00:00:00Z")
    review_shown.record_in(conn, "run-unlisted", [g.PAPER], "2026-11-17T00:00:00Z")
    conn.commit()
    got = contract_rule_book.for_run(
        conn, "run-listed", g.PAPER, "contract", ALL, [], local=False
    )
    assert (
        got["book"] == GT
        and [a["document_id"] for a in got["accepted"]] == [GT]
        and got["lines"] == []
    )
    got = contract_rule_book.for_run(
        conn, "run-unlisted", g.PAPER, "contract", ALL, [], local=False
    )
    assert got["book"] is None and got["accepted"] == []
    assert got["lines"][0]["text"].endswith(contract_rule_book.NOT_LISTED)
    assert got["lines"][0]["verdict_class"] == core.CLASS_NOT_REVIEWED
    # an older route with no list: a contract goes only with the owner's recorded yes
    got = contract_rule_book.for_run(
        conn, "run-none", g.PAPER, "contract", ALL, [], local=False
    )
    assert got["book"] is None and got["lines"][0]["text"].endswith(
        contract_rule_book.NO_YES
    )
    # a local run sends nothing: it may read it
    assert (
        contract_rule_book.for_run(
            conn, "run-none", g.PAPER, "contract", ALL, [], local=True
        )["book"]
        == GT
    )


def test_a_blocked_rule_book_is_never_used(pkg, monkeypatch):
    monkeypatch.setattr(
        claude_approved, "blocked_by_name", lambda name: "General Terms" in str(name)
    )
    got = contract_rule_book.for_run(
        db.connect(), "r", g.PAPER, "contract", ALL, [], local=True
    )
    assert got["book"] is None and "blocked" in got["lines"][0]["text"]


def test_switch_off_the_run_gets_nothing(pkg, monkeypatch):
    monkeypatch.setattr(settings, "contract_rule_book_enabled", False)
    got = contract_rule_book.for_run(
        db.connect(), "r", g.PAPER, "contract", ALL, [], local=True
    )
    assert got == {
        "book": None,
        "accepted": [],
        "items": [],
        "code_lines": [],
        "lines": [],
    }


# ---------------------------------------------------------------- the label on every line from them


def _ct_answers(_last):
    return {"answers": [{"item_id": "CT-01", "paper_page": 2, "paper_quote": "", "status": "absent", "note": "", "concern": ""},
                        {"item_id": "CT-07", "paper_page": 2, "paper_quote": "", "status": "unclear", "note": "", "concern": ""}]}  # fmt: skip


def _p4_against_book(_last):
    return {"findings": [
        {"document": GT, "kind": "silent", "quote_paper": None, "quote_other": {"page": 2, "text": "Body text of the invented paper"},
         "what": "The general terms ask for something the paper does not address."},
        {"document": g.PROJ, "kind": "silent", "quote_paper": None, "quote_other": {"page": 1, "text": g.Q_REQ},
         "what": "Owner and due date are not addressed."},
    ]}  # fmt: skip


def _run_with_book(pkg_world, monkeypatch):
    items = [
        i
        for i in contract_rule_book.checklist_items()
        if i["item_id"] in ("CT-01", "CT-07")
    ]
    fake = g.GFake(
        p2=_ct_answers,
        p3=lambda _l: {"findings": []},
        p4=_p4_against_book,
        p5=lambda _l: {"comments": []},
    )
    gr, runner = g.build(pkg_world, fake, project=(g.PROJ, GT), items=items)
    gr.draft_books = frozenset({GT})
    gr.draft_items = frozenset({"CT-01", "CT-07"})
    with (
        claude_approved.carrying([g.PAPER, g.PROJ, GT]),
        g.claude_spend.for_run("gr-test"),
    ):
        runner.gate = g.request_mod.AppStepGate(g.request_mod.app_cap(), 0.0)
        gr.run_all()
    return gr.lines


def test_every_line_from_the_rule_book_or_the_checklist_says_ai_draft_and_is_internal(
    pkg, monkeypatch
):
    lines = _run_with_book(pkg, monkeypatch)
    book = [ln for ln in lines if ln.get("other_document") == GT]
    checklist = [ln for ln in lines if ln.get("checklist_item") in ("CT-01", "CT-07")]
    assert book and len(checklist) == 2
    for ln in [*book, *checklist]:
        assert (
            ln["rule_state"] == DRAFT
            and DRAFT in ln["text"]
            and ln["internal_only"] is True
        )
        assert (
            ln["word"] not in ("Pass", "Fail") and ln["verdict_class"] in core.CLASSES
        )
    other = [ln for ln in lines if ln.get("other_document") == g.PROJ]
    assert other and all(
        "rule_state" not in ln and DRAFT not in ln["text"] for ln in other
    )


def test_the_checklist_is_ct01_to_ct08_from_the_draft_file_each_marked_draft():
    items = contract_rule_book.checklist_items()
    assert [i["item_id"] for i in items] == [f"CT-0{n}" for n in range(1, 9)]
    assert all(DRAFT in i["topic"] and i["draft"] == DRAFT for i in items)
    assert (
        contract_checks.checklist()["approved"] is False
    )  # still a draft: the label must stay


# ---------------------------------------------------------------- what code decides (CT-01..CT-03): a Query, never Pass or Fail

STAGES = (
    "Invented Works Project   CONTRACT No. INV-77-001\nForm of Agreement\n"
    "5.1 The price is paid in three stages.\n"
    "5.2 Advance payment of 40% of the price.\n"
    "5.3 Progress payment of 30% of the price.\n"
    "5.4 Final payment of 20% of the price on acceptance.\n"
)


def test_a_code_result_is_a_query_with_its_verified_quote_never_a_pass_or_fail(pkg):
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 2",
            (STAGES, g.PAPER),
        )
        conn.commit()
    lines = contract_rule_book.code_lines(db.connect(), g.PAPER, [])
    ct01 = [ln for ln in lines if ln["checklist_item"] == "CT-01"]
    assert (
        ct01
        and ct01[0]["verdict_class"] == core.CLASS_QUERY
        and ct01[0]["reason"] == "inconsistent"
    )
    assert (
        ct01[0]["quotes_verified_by_code"] is True and ct01[0]["quote_a"]["page"] == 2
    )
    out = contract_rule_book.mark(
        core.finalize_line(ct01[0]), [], contract_rule_book.checklist_ids()
    )
    assert (
        out["word"] == "Query"
        and out["rule_state"] == DRAFT
        and out["text"].startswith(f"contract checklist ({DRAFT})")
    )


# ---------------------------------------------------------------- the job: the carrier, the label, nothing on the contractor copy


def _start_contract(scope):
    run_id, job_id = agent_review_jobs.enqueue(
        g.PAPER, allowed_document_ids=scope, requested_by=None, project_document_ids=()
    )
    assert agent_review_jobs.claim_next("w") == job_id
    return run_id, job_id


def test_the_job_carries_the_listed_rule_book_and_nothing_else(pkg, monkeypatch):
    from app import access

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (g.full_fake(), g.s.ENV))
    seen = []

    def stop(*_a, **_k):
        seen.append(claude_approved.carried())
        raise agent_claude.AgentBudgetStop("stop_for_test")

    monkeypatch.setattr(agent_claude, "_call", stop)
    run_id, job_id = _start_contract(ALL)
    with db.connect() as conn:
        review_shown.record_in(conn, run_id, [g.PAPER, GT], "2026-11-17T00:00:00Z")
        conn.commit()
    agent_review_jobs.run(job_id, "w")
    assert seen and set(seen) == {frozenset({g.PAPER, GT})}
    general = (
        db.connect()
        .execute(
            "SELECT project_json FROM agent_review_general WHERE run_id = ?", (run_id,)
        )
        .fetchone()
    )
    assert [p["document_id"] for p in json.loads(general[0])] == [GT]


def test_the_job_with_the_switch_off_carries_only_the_paper(pkg, monkeypatch):
    from app import access

    monkeypatch.setattr(settings, "contract_rule_book_enabled", False)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (g.full_fake(), g.s.ENV))
    seen = []

    def stop(*_a, **_k):
        seen.append(claude_approved.carried())
        raise agent_claude.AgentBudgetStop("stop_for_test")

    monkeypatch.setattr(agent_claude, "_call", stop)
    run_id, job_id = _start_contract(ALL)
    with db.connect() as conn:
        review_shown.record_in(conn, run_id, [g.PAPER, GT], "2026-11-17T00:00:00Z")
        conn.commit()
    agent_review_jobs.run(job_id, "w")
    assert seen and set(seen) == {frozenset({g.PAPER})}


def test_no_line_from_them_reaches_the_contractor_copy(pkg, monkeypatch):
    from openpyxl import load_workbook

    from app import access

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(
        agent_review_jobs,
        "lane",
        lambda: (g.GFake(p2=_ct_answers, p4=_p4_against_book), g.s.ENV),
    )
    run_id, job_id = _start_contract(ALL)
    with db.connect() as conn:
        review_shown.record_in(conn, run_id, [g.PAPER, GT], "2026-11-17T00:00:00Z")
        conn.commit()
    assert agent_review_jobs.run(job_id, "w") == "done"
    rows = (
        db.connect()
        .execute("SELECT line_json FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchall()
    )
    drafts = [
        json.loads(r[0]) for r in rows if json.loads(r[0]).get("rule_state") == DRAFT
    ]
    assert (
        len({ln.get("checklist_item") for ln in drafts if ln.get("checklist_item")})
        == 8
    )  # CT-01..CT-08, each said
    assert all(
        DRAFT in ln["text"] and ln["word"] not in ("Pass", "Fail") for ln in drafts
    )
    wb = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx")
    cells = [[c.value for c in row] for row in wb["CRS"].iter_rows()]
    head = next(i for i, r in enumerate(cells) if r[0] == "Item No")
    assert cells[head + 1 :] == []
    assert agent_general_job  # the job module is the one that wires it


# ---------------------------------------------------------------- review of #1880: the exit order, the part-5 prompt, the real gate


def test_the_draft_label_never_hides_a_verdict_word_from_the_exit(pkg):
    gr, _runner = g.build(
        pkg,
        g.full_fake(),
        project=(g.PROJ,),
        items=contract_rule_book.checklist_items()[:1],
    )
    gr.draft_items = frozenset({"CT-01"})
    with pytest.raises(core.GeneralModeViolation):
        gr.add({"part": 2, "verdict_class": core.CLASS_QUERY, "subkind": core.SUB_CHECKLIST, "document": g.PAPER,
                "item_id": "CT-01", "checklist_item": "CT-01", "text": "Fail: the stages do not add up"})  # fmt: skip


SENTINEL = "SENTINEL-WORDS-FROM-AN-UNLISTED-PACKAGE-PAPER"


def test_on_a_claude_run_no_prompt_holds_the_words_of_a_code_check(pkg):
    code = {"part": 2, "document": g.PAPER, "item_id": "CT-02", "checklist_item": "CT-02", "topic": f"CT-02 x ({DRAFT})",
            "verdict_class": core.CLASS_QUERY, "subkind": contract_rule_book.SUB_CODE, "text": f"CT-02 x: {SENTINEL}"}  # fmt: skip
    fake = g.full_fake()
    gr, runner = g.build(pkg, fake, project=(g.PROJ,))
    gr.code_lines = [code]
    with claude_approved.carrying([g.PAPER, g.PROJ]), g.claude_spend.for_run("gr-test"):
        runner.gate = g.request_mod.AppStepGate(g.request_mod.app_cap(), 0.0)
        gr.run_all()
    assert any(SENTINEL in ln["text"] for ln in gr.lines)  # on the sheet
    assert fake.calls_of("experienced engineer commenting") >= 1
    assert SENTINEL not in fake.texts()  # never in any request


def test_automatic_with_text_leaving_holds_the_contract_rule_book_with_the_contract_words(
    pkg, monkeypatch
):
    from app import review_leaving
    from tests.test_b1_review_engine import open_facts

    # the paper's own facts let Automatic send text; the rule book is a contract, so the real gate holds it
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(kind="contract"), None)
    )
    docs = review_engine.plan_for(db.connect(), g.PAPER, ALL, "automatic")["documents"]
    assert docs["leaving"] and GT not in {d["id"] for d in docs["leaving"]}
    held = {d.get("id"): d for d in docs["not_sent"]}
    assert (
        held[GT]["reason"] == review_leaving.CONTRACT_WORDS
        and held[GT]["why"] == contract_rule_book.WHY_LISTED
    )


def test_a_blocked_rule_book_is_held_under_an_explicit_claude_start(pkg, monkeypatch):
    from app import review_leaving

    monkeypatch.setattr(
        claude_approved,
        "name_is_blocked",
        lambda name, *_a: "General Terms" in str(name),
    )
    docs = _plan("claude", monkeypatch)
    assert GT not in {d["id"] for d in docs["leaving"]}
    held = {d.get("id"): d for d in docs["not_sent"]}
    assert held[GT]["reason"] == review_leaving.BLOCKED_WORDS


# ---------------------------------------------------------------- with the one LPC finder (`contract_package`)


def test_a_same_package_paper_with_no_role_but_the_contract_kind_is_found(pkg):
    with db.connect() as conn:
        _contract(
            conn,
            "doc_norole",
            "General Terms and Conditions.pdf",
            NO_A,
            "GENERAL TERMS AND CONDITIONS",
        )
        conn.execute(
            "DELETE FROM document_classification WHERE document_id = 'doc_norole'"
        )
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, routed_at) VALUES ('doc_norole', 'contract', 'decided', '2026-11-17')"
        )
        conn.commit()
    assert "doc_norole" in contract_rule_book.package_papers(
        db.connect(), g.PAPER, ALL | {"doc_norole"}
    )
    assert _book(scope=(ALL - {GT}) | {"doc_norole"})["id"] == "doc_norole"


def test_the_heading_fallback_never_picks_a_special_terms_paper(pkg):
    with (
        db.connect() as conn
    ):  # its title says nothing; its heading names the general conditions it supplements
        _contract(
            conn,
            "doc_sp2",
            "Schedule H.pdf",
            NO_A,
            "SCHEDULE H - Special Conditions, read with the General Conditions",
        )
        conn.commit()
    assert _book(scope=(ALL - {GT}) | {"doc_sp2"}) == {
        "id": None,
        "why": contract_rule_book.NONE_FOUND,
    }
    assert _book(scope=ALL | {"doc_sp2"})["id"] == GT


# ---------------------------------------------------------------- round 2 of #1880: the title IS the general terms (structural)

QUALIFIED = (
    "Supplementary General Conditions",
    "Amendments to the General Conditions",
    "Addendum to General Terms",
    "Special Provisions to the General Conditions",
    "Exceptions to General Terms",
)


@pytest.mark.parametrize("title", QUALIFIED)
def test_a_title_that_qualifies_the_general_terms_is_never_them(pkg, title):
    with db.connect() as conn:
        _contract(
            conn,
            "doc_q",
            f"09 - Schedule J - {title} - Rev 02.pdf",
            NO_A,
            f"SCHEDULE J - {title}",
        )
        conn.commit()
    assert contract_rule_book.title_state(title) == contract_rule_book.NO
    assert _book(scope=(ALL - {GT}) | {"doc_q"}) == {
        "id": None,
        "why": contract_rule_book.NONE_FOUND,
    }
    assert _book(scope=ALL | {"doc_q"})["id"] == GT


@pytest.mark.parametrize(
    "title",
    (
        "General Terms and Conditions",
        "08 - Schedule A - General Terms _ Conditions - Rev 07",
        "General Conditions of Contract",
    ),
)
def test_a_title_that_is_the_general_terms_is_them(title):
    assert contract_rule_book.title_state(title) == contract_rule_book.YES


def test_a_general_terms_paper_whose_heading_names_the_special_conditions_is_still_chosen(
    pkg,
):
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1",
            (
                _head(
                    NO_A,
                    "SCHEDULE A - General Terms and Conditions\nto be read with the Special Conditions",
                )
                + "Body.",
                GT,
            ),
        )
        conn.commit()
    assert _book() == {"id": GT, "why": contract_rule_book.WHY_SUGGESTED}
    assert (
        contract_rule_book.NONE_FOUND
        == "no general terms paper recognised in this package"
    )


# ---------------------------------------------------------------- round 3 of #1880: (A) the strict title, (B) the paper names it

LEAKED = (
    "General Conditions - Supplement",
    "Amendment No. 1 - General Conditions",
    "Supplement: General Conditions",
    "General Conditions (Amended)",
    "Deviations - General Terms and Conditions",
    "Addendum 2 (General Conditions)",
    "Summary - General Terms",
    "Supplementary General Conditions",
)


@pytest.mark.parametrize("title", LEAKED)
def test_a_title_with_any_other_word_is_not_the_general_terms(pkg, title):
    assert contract_rule_book.title_state(title) == contract_rule_book.NO
    with db.connect() as conn:
        _contract(
            conn, "doc_q", f"{title}.pdf", NO_A, "GENERAL CONDITIONS"
        )  # a heading cannot undo a title that decides
        conn.commit()
    assert _book(scope=(ALL - {GT}) | {"doc_q"}) == {
        "id": None,
        "why": contract_rule_book.NONE_FOUND,
    }


@pytest.mark.parametrize(
    ("title", "state"),
    (
        ("General Conditions of Contract 2024", "yes"),  # a year is a label
        ("General Conditions of Contract Rev 2", "yes"),  # a revision is a label
        (
            "Volume 1 Section 3 General Conditions of Contract",
            "yes",
        ),  # labels only around the phrase
        ("General Terms & Conditions v2", "yes"),
        (
            "General Conditions of Contract for Construction",
            "no",
        ),  # a word is left: a SAFE no (none is used, the run says so)
    ),
)
def test_true_titles_pass_when_only_labels_are_around_the_phrase_else_a_safe_no(
    title, state
):
    assert contract_rule_book.title_state(title) == state


def test_a_silent_title_with_a_yes_and_a_no_heading_line_is_a_safe_no(pkg):
    with db.connect() as conn:
        _contract(
            conn,
            "doc_mix",
            "Schedule E.pdf",
            NO_A,
            "GENERAL CONDITIONS\nAmendments to the General Conditions",
        )
        conn.commit()
    assert (
        contract_rule_book.says_general_terms(db.connect(), "doc_mix")
        == contract_rule_book.NO
    )
    assert (
        _book(scope=(ALL - {GT}) | {"doc_mix"})["why"] == contract_rule_book.NONE_FOUND
    )


def _paper_lists(label: str, name: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = 2",
            (
                f'\nThe contract documents are:\nSCHEDULE "{label}"\n{name} and its Attachments\n',
                g.PAPER,
            ),
        )
        conn.commit()


def test_b_the_paper_names_its_general_terms_and_the_labelled_paper_agrees(pkg):
    with (
        db.connect() as conn
    ):  # a second paper passes (A): alone, (A) would choose none
        _contract(
            conn,
            "doc_gt2",
            "General Conditions of Contract.pdf",
            NO_A,
            "GENERAL CONDITIONS OF CONTRACT",
        )
        conn.commit()
    assert _book(scope=ALL | {"doc_gt2"})["id"] is None
    _paper_lists("A", "General Terms and Conditions")
    assert contract_rule_book.named_general_terms(db.connect(), g.PAPER) == {
        ("schedule", "A")
    }
    assert _book(scope=ALL | {"doc_gt2"}) == {
        "id": GT,
        "why": contract_rule_book.WHY_SUGGESTED,
    }


def test_b_disagreeing_with_a_chooses_none(pkg):
    _paper_lists(
        "K", "General Terms and Conditions"
    )  # the paper says its general terms are Schedule K; the titled one is A
    assert _book() == {"id": None, "why": contract_rule_book.NONE_FOUND}


# ---------------------------------------------------------------- round 4 of #1880: a RECORDED choice, never the code's own guess


def test_with_no_recorded_choice_only_a_suggestion_line_is_written_and_nothing_is_used(
    pkg, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        contract_rule_book, "RECORD_FILE", tmp_path / "absent.local.json"
    )
    got = contract_rule_book.for_run(
        db.connect(), "r", g.PAPER, "contract", ALL, [], local=True
    )
    name = "08 - Schedule A - General Terms and Conditions - Rev 01.pdf"
    assert got["book"] is None and got["accepted"] == []
    assert [ln["text"] for ln in got["lines"]] == [
        f"not reviewed: {contract_rule_book.SUGGESTED.format(name=name)}"
    ]
    assert got["items"] and len(got["items"]) == 8  # the checklist needs no rule book
    docs = _plan("claude", monkeypatch)
    assert GT not in {d["id"] for d in docs["leaving"]} or (
        {d["id"]: d for d in docs["leaving"]}[GT]["why"]
        != contract_rule_book.WHY_LISTED
    )
    _record(
        tmp_path, monkeypatch, {"doc_someone_else": GT}
    )  # a file with no entry for this paper: no choice either
    assert _used() == {
        "id": None,
        "why": contract_rule_book.SUGGESTED.format(name=name),
        "suggested": GT,
    }


def test_a_recorded_choice_is_used_and_listed_on_the_plan(pkg, monkeypatch):
    assert _used()["id"] == GT and _used()["chosen_by"] == "engineer-x"
    got = {d["id"]: d for d in _plan("claude", monkeypatch)["leaving"]}
    assert got[GT]["why"] == contract_rule_book.WHY_LISTED


@pytest.mark.parametrize(
    "raw",
    (
        "{not json",
        json.dumps({"format": "other/9", "choices": []}),
        json.dumps({"format": "contract-rule-book/1", "choices": [{"papers": ["doc_proc"], "rule_book": "doc_gt"}]}),
        json.dumps({"format": "contract-rule-book/1", "choices": [
            {"papers": ["doc_proc"], "rule_book": "doc_gt", "chosen_by": "a", "chosen_at": "2026-11-17"},
            {"papers": ["doc_proc"], "rule_book": "doc_price", "chosen_by": "b", "chosen_at": "2026-11-17"}]}),
    ),
)  # fmt: skip
def test_a_malformed_record_uses_nothing_and_says_so(pkg, monkeypatch, tmp_path, raw):
    _record(tmp_path, monkeypatch, {}, raw=raw)
    got = contract_rule_book.for_run(
        db.connect(), "r", g.PAPER, "contract", ALL, [], local=True
    )
    assert got["book"] is None
    assert (
        "the recorded contract rule book file cannot be read" in got["lines"][0]["text"]
    )


def test_a_recorded_paper_the_caller_may_not_read_or_that_is_not_held_is_not_used(
    pkg, monkeypatch, tmp_path
):
    assert _used(scope=ALL - {GT}) == {
        "id": None,
        "why": contract_rule_book.NOT_READABLE,
    }
    _record(tmp_path, monkeypatch, {g.PAPER: "doc_not_held"})
    assert _used(scope=ALL | {"doc_not_held"}) == {
        "id": None,
        "why": contract_rule_book.NOT_READABLE,
    }
