"""Engineering knowledge where a rule book is not held (the method's rule; the lead, 18 Nov 2026): S3 writes knowledge items for
each governing or needed standard the library does not hold, still with NO paper, labelled "engineering knowledge (book not
held)", with the standard's public name and no clause quote or number; a kind with no main equipment reaches the coverage floor;
the items are never Met / Not met; a saved checklist is not reused once a book it was written without is held. Invented papers;
no paid call, no socket."""

from __future__ import annotations

import pytest

from app import aim_review, aim_review_store
from app.aim_review import checklist as CL
from app.aim_review import engine as E
from app.aim_review import library as L
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    PAPER_PAGES,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


NOT_HELD = [{"name": "API 9990", "why": "method book of this kind; not held"}]


def _knowledge_answer(n):
    return {"items": [
        {"topic": f"invented topic {i}", "what_to_check": "x", "applies_when": "always", "paper_fields": ["section"],
         "kind": "procedure", "source": "held standard", "clause": "5.2.1", "rule_quote": "an invented clause quote",
         "stands_in_for": "API 9990" if i % 2 else ""}
        for i in range(n)
    ]}  # fmt: skip


class _Model:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def ask(self, **kw):
        self.asked.append(kw)
        return self.answer


def _made(n):
    return {
        "items": [
            {"id": f"C{i:03d}", "topic": f"held topic {i}", "source": CL.HELD}
            for i in range(1, n + 1)
        ]
    }


def test_knowledge_items_carry_the_label_the_public_name_and_no_clause():
    model = _Model(_knowledge_answer(40))
    sel = {"not_held": NOT_HELD, "books": [{"alias": "B01", "book": BOOK_A}]}
    got = CL.s3_knowledge(
        model, {"kind": "procedure"}, sel, _made(14), "claude-sonnet-5-5"
    )
    new = got["items"][14:]
    assert new and all(
        it["source"] == "engineering knowledge (book not held)" for it in new
    )
    assert all(
        it["clause"] == "" and it["rule_quote"] == "" and it["book"] == "" for it in new
    )
    assert {it["stands_in_for"] for it in new} == {"API 9990", "engineering practice"}
    assert [it["id"] for it in new][:2] == ["C015", "C016"]
    assert (
        len(got["items"]) >= CL.FLOOR_ITEMS and got["floor"] == 30
    )  # the floor is met
    ask = model.asked[0]
    assert (
        ask["cached"] is None
        and "API 9990" in ask["prompt"]
        and ask["carries"] == {BOOK_A}
    )  # no paper, listed books


def test_the_floor_is_the_kinds_with_no_main_equipment():
    assert CL.floor_for("procedure") == 30 and CL.floor_for("contract") == 30
    assert CL.floor_for("datasheet") == 0 and CL.floor_for(None) == 0


def test_no_knowledge_call_when_every_book_is_held_and_the_floor_is_met():
    model = _Model(_knowledge_answer(5))
    got = CL.s3_knowledge(
        model,
        {"kind": "procedure"},
        {"not_held": [], "books": []},
        _made(31),
        "claude-sonnet-5-5",
    )
    assert model.asked == [] and len(got["items"]) == 31


@pytest.mark.parametrize("label", ["Met", "Not met", "Question", "AI opinion"])
def test_a_knowledge_item_is_never_met_or_not_met(label):
    it = {
        "id": "C020",
        "book": "",
        "clause": "",
        "source": CL.KNOWLEDGE_NOT_HELD,
        "topic": "t",
        "kind": "procedure",
    }
    pages = {1: "Section 4 of the invented procedure: the isolation steps are listed\n"}
    d = S._decide(
        it,
        {"label": label, "page": 1, "quote": "the isolation steps are listed"},
        Paper("doc_k", pages),
        {},
        "",
    )
    assert d["label"] not in ("Met", "Not met")


def test_an_invented_procedure_with_no_held_governing_book_gets_knowledge_items_through_run(
    aim_db,
):
    model = E.FakeModel(kind="procedure", subject_key="test_procedure",
                        answers={"aim_checklist_knowledge": _knowledge_answer(30)})  # fmt: skip
    store = MemoryStore()
    r = aim_review.run(aim_db, run_id="run_aim_k", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                       max_usd=5.0, model=model)  # fmt: skip
    assert r.status == "done", r.stop_reason
    saved = store.get(r.checklist_key)
    assert (
        saved["built_from"] == aim_review_store.BUILT_FROM_KNOWLEDGE
        and len(saved["items"]) >= CL.FLOOR_ITEMS
    )
    know = [ln for ln in r.lines if ln["source"] == CL.KNOWLEDGE_NOT_HELD]
    assert know and all(ln["label"] not in ("Met", "Not met") for ln in know)
    # the paper is never in any build request (S2, S3, the knowledge step, the attack)
    words = [
        ln.strip() for t in PAPER_PAGES.values() for ln in t.splitlines() if ln.strip()
    ]
    for c in model.asked:
        if c["step"] in (
            "aim_select",
            "aim_checklist",
            "aim_checklist_knowledge",
            "aim_checklist_retry",
            "aim_attack",
        ):
            assert (
                not c["cached"]
                and PAPER not in c["carries"]
                and not any(w in c["prompt"] for w in words)
            ), c["step"]


def test_the_store_takes_a_knowledge_checklist_and_still_refuses_one_that_saw_the_paper(
    aim_db,
):
    store = aim_review_store.DbChecklistStore(aim_db)
    body = {
        "built_from": aim_review_store.BUILT_FROM_KNOWLEDGE,
        "items": [],
        "identity": {},
    }
    sha = store.put("procedure__x", body, run_id="r1", usd=0.0)
    assert store.get("procedure__x")["sha256"] == sha and "procedure__x" in store.keys()
    with pytest.raises(ValueError):
        store.put(
            "procedure__y",
            {"built_from": "the paper and the standards", "items": []},
            run_id="r2",
            usd=0.0,
        )


def test_a_saved_checklist_is_built_again_when_a_book_it_lacked_is_now_held(aim_db):
    store = MemoryStore()
    first = aim_review.run(aim_db, run_id="run_k1", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                           max_usd=5.0, model=E.FakeModel(kind="procedure", subject_key="test_procedure"))  # fmt: skip
    again = aim_review.run(aim_db, run_id="run_k2", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                           max_usd=5.0, model=E.FakeModel(kind="procedure", subject_key="test_procedure"))  # fmt: skip
    assert again.checklist_reused and len(store.puts) == 1  # nothing changed: reused
    key = first.checklist_key
    sha, body = store.saved[key][-1]
    store.saved[key][-1] = (
        sha,
        {**body, "not_held": [*body.get("not_held", []), *NOT_HELD]},
    )  # written without a book
    third = aim_review.run(aim_db, run_id="run_k3", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                           max_usd=5.0, model=E.FakeModel(kind="procedure", subject_key="test_procedure"))  # fmt: skip
    assert (
        not third.checklist_reused and len(store.puts) == 2
    )  # that book is now held (not in the current not-held set)


# ---- light check e1c61001: the plan lists newly held books; an AI name never forces a rebuild; the attack's cap ---------------


def test_with_a_saved_checklist_the_plan_also_lists_books_now_held_and_wanted_earlier(
    aim_db, monkeypatch
):
    from app import agent_review_kind
    from app.aim_review import library as L
    from tests.test_aim_method_helpers import BOOK_C

    type_id = sorted(L.type_ids())[
        0
    ]  # a typed kind: the plan finds the saved checklist by its key
    monkeypatch.setattr(agent_review_kind, "read_kind",
                        lambda conn, doc: {"kind": "datasheet", "known": True, "method": "title_cue", "guess": False})  # fmt: skip
    monkeypatch.setattr(
        agent_review_kind,
        "read_equipment",
        lambda doc, allowed: (type_id, "classification"),
    )
    lib_c = {"id": BOOK_C, "filename": "QX-STD-303.pdf"}
    monkeypatch.setattr(
        L, "method_books", lambda lib, kind: [(lib_c, "QX-STD-303"), (None, "API 9990")]
    )
    store = MemoryStore()
    key = L.checklist_key("datasheet", type_id)
    store.put(key, {"built_from": "standards only, no paper", "items": [], "books": [{"alias": "B01", "book": BOOK_A}]},
              run_id="r0", usd=0.0)  # fmt: skip
    every = frozenset({BOOK_A, BOOK_B, BOOK_C})
    c = aim_review.candidates(aim_db, PAPER, every, store, frozenset({BOOK_B}))
    assert c.checklist_saved
    # the saved book first, then the method book now held (held after the checklist was saved), then the earlier review's
    assert [(b["id"], b["why"]) for b in c.books] == [
        (BOOK_A, L.WHY_SAVED),
        (BOOK_C, L.WHY_METHOD),
        (BOOK_B, L.WHY_LAST),
    ]
    assert "API 9990" in [n["name"] for n in c.not_held]
    narrow = aim_review.candidates(
        aim_db, PAPER, frozenset({BOOK_A}), store, frozenset({BOOK_B})
    )
    assert [b["id"] for b in narrow.books] == [
        BOOK_A
    ] and narrow.unreadable == 2  # counted, never named


def test_an_ai_needed_name_never_forces_a_rebuild_whatever_its_why_says():
    table = {
        "name": "API 9990",
        "why": "method book of this kind; not held",
        "source": CL.WANTED_METHOD,
    }
    ai = {
        "name": "API 9991",
        "why": "governs the equipment type, the AI says",
        "source": "AI: needed, not in the catalog",
    }
    legacy = {
        "name": "API 9992",
        "why": "governs the equipment type; not held",
    }  # saved before the key existed
    assert L.wanted_not_held([table, ai, legacy]) == frozenset({"API 9990", "API 9992"})
    assert L.wanted_not_held([table, ai]) == L.wanted_not_held([table])


def test_the_attack_adds_at_most_ten_knowledge_items_and_a_knowledge_item_names_no_clause(
    aim_db,
):
    from app.aim_review import library as L

    adds = [{"topic": f"t{i}", "what_to_check": "x", "source": "not from a held standard", "clause": "4.2", "kind": "procedure"}
            for i in range(15)]  # fmt: skip
    model = _Model({"add": adds})
    sel = {"books": [], "not_held": NOT_HELD, "_pool": []}
    got = CL.s3_attack(
        model,
        {"kind": "procedure"},
        sel,
        {"items": []},
        L.BookText(aim_db),
        "claude-opus-5-5",
    )
    assert (
        len(got["items"]) == CL.MAX_ATTACK_KNOWLEDGE == 10
        and len(got["attack"]["rejected"]) == 5
    )
    assert all(it["clause"] == "" for it in got["items"])
    assert (
        "API 9990" in model.asked[0]["prompt"]
    )  # the not-held standards are shown for the coverage check
