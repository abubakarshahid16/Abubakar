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
    # the method book now held FIRST (governing, method and cited books lead and are never cut by the cap: owner, 18 Nov 2026),
    # then the saved book, then the earlier review's
    assert [(b["id"], b["why"]) for b in c.books] == [
        (BOOK_C, L.WHY_METHOD),
        (BOOK_A, L.WHY_SAVED),
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


def test_a_knowledge_item_another_paper_carries_is_set_aside_not_checked_here():
    """A not-held book may govern a neighbouring paper (a study, another item's datasheet): its items that THIS paper does not
    carry are set aside with "for <kind> paper", never checked here; an item with no "carried_by" stays (as before)."""
    rows = _knowledge_answer(4)["items"]
    rows[0]["carried_by"] = "this paper"
    rows[1]["carried_by"] = "an invented study"
    rows[2]["carried_by"] = "Invented other datasheet paper"
    sel = {"not_held": NOT_HELD, "books": [{"alias": "B01", "book": BOOK_A}]}
    got = CL.s3_knowledge(
        _Model({"items": rows}),
        {"kind": "procedure"},
        sel,
        _made(14),
        "claude-sonnet-5-5",
    )
    kept = [it["topic"] for it in got["items"][14:]]
    assert kept == ["invented topic 0", "invented topic 3"]
    assert [it["id"] for it in got["items"][14:]] == ["C015", "C016"]
    assert got["dropped"] == [
        {"topic": "invented topic 1", "why": "for an invented study paper"},
        {"topic": "invented topic 2", "why": "for Invented other datasheet paper"},
    ]


def test_the_knowledge_step_asks_which_paper_carries_each_item():
    assert (
        '"carried_by": "HERE"' in CL.P.KNOWLEDGE_TASK
        and "not checked here" in CL.P.KNOWLEDGE_TASK
    )


def test_an_item_this_type_of_paper_carries_is_kept_in_any_of_its_words():
    """The build rewords "this paper" to "a paper of this type" in every task (no paper is shown): the answer "HERE" and those
    words both mean this paper, so the item is kept; the asked word survives the rewording."""
    rows = _knowledge_answer(3)["items"]
    rows[0]["carried_by"], rows[1]["carried_by"], rows[2]["carried_by"] = (
        "HERE",
        "a paper of this type",
        "This paper",
    )
    sel = {"not_held": NOT_HELD, "books": [{"alias": "B01", "book": BOOK_A}]}
    got = CL.s3_knowledge(
        _Model({"items": rows}),
        {"kind": "procedure"},
        sel,
        _made(14),
        "claude-sonnet-5-5",
    )
    assert len(got["items"]) == 17 and not got.get("dropped")
    assert '"carried_by": "HERE"' in CL._for_type(CL.P.KNOWLEDGE_TASK)


def test_a_needed_held_book_outside_the_catalog_gets_an_alias_and_the_checklist_step_runs(
    aim_db, monkeypatch
):
    """A book the AI names as needed, held and on the list, with no rule for this type, is not in the catalog: its chosen line
    gets the next alias, so the checklist step maps it (the vessel fault of 18 Nov: KeyError 'alias' before any S3 call)."""
    from app.aim_review import book_names as BN

    cat = [{"book": BOOK_A, "alias": "B01", "identifier": "API 9991", "committee": "", "rules": 1, "tagged": 0,
            "subjects": [], "required": True}]  # fmt: skip
    lines = BN.as_chosen(aim_db, [BOOK_A, BOOK_B], cat, "AI: needed; held")
    assert [x["alias"] for x in lines] == ["B01", "B02"]
    sel = {"books": lines, "_pool": [], "not_held": []}
    model = E.FakeModel(kind="procedure", subject_key="test_item")
    from app import claude_approved

    monkeypatch.setattr(
        claude_approved, "refusal", lambda *a, **k: None
    )  # the fake sends nothing
    made = CL.s3_checklist(
        model, {"kind": "procedure"}, sel, L.BookText(aim_db), "claude-sonnet-5-5"
    )
    assert isinstance(made["items"], list)


def test_the_largest_checklist_fits_and_a_cut_answer_is_asked_again_in_halves():
    """No key. The largest stored checklist (a valve paper: about 300 clause rules, 123 items) is asked with room for 32,000
    tokens; an answer cut at the limit applies nothing and its batch is asked again as two halves, each answered whole, so every
    rule is answered once; any other failure still stops the build."""
    import re

    rows = [{"rule": f"R{i:03d}", "book": "B01", "clause": f"5.{i}", "page": 1 + i // 10, "text": "x" * 600}
            for i in range(320)]  # fmt: skip
    asked = []

    class _Cut:
        def ask(self, **kw):
            asked.append(kw)
            rules = re.findall(r'"rule": "(R\d{3})"', kw["prompt"])
            if len(rules) > 40:  # an answer this long is cut at its limit
                raise E.StepFailed("aim_checklist: stop_max_tokens")
            return {"items": [{"topic": r, "source": "held standard"} for r in rules]}

    sel = {
        "books": [
            {
                "alias": "B01",
                "book": BOOK_A,
                "identifier": "API 9991",
                "chosen_subjects": "all",
            }
        ]
    }
    got = [
        x for i, b in enumerate(CL._batches(rows)) for x in CL._answers(_Cut(), {"kind": "datasheet"}, sel, b, i == 0, {BOOK_A}, "m")
    ]  # fmt: skip
    answered = [it["topic"] for out, _part in got for it in out["items"]]
    assert sorted(answered) == sorted(
        r["rule"] for r in rows
    )  # every rule once, none lost, none twice
    assert {kw["max_tokens"] for kw in asked} == {CL.S3_MAX_TOKENS} == {32_000}
    assert (
        sum(
            "ALSO add the items" in kw["prompt"]
            for kw in asked
            if "R000" in kw["prompt"]
        )
        >= 1
    )

    class _Down:
        def ask(self, **kw):
            raise E.StepFailed("aim_checklist: transport ReadTimeout")

    with pytest.raises(E.StepFailed):
        CL._answers(_Down(), {"kind": "datasheet"}, sel, rows[:10], True, {BOOK_A}, "m")


class _Metered(_Model):
    def __init__(self, answer, fail=None):
        super().__init__(answer)
        self.meter, self.fail = E.Meter(cap=0.0), fail

    def ask(self, **kw):
        if self.fail:
            raise E.StepFailed(f"aim_checklist_knowledge: {self.fail}")
        return super().ask(**kw)


def _notes(model):
    return [c.code for c in model.meter.calls if c.model == "code"]


def test_no_knowledge_item_while_books_are_not_held_is_said_in_the_run_record():
    """The silent-loss guard (18 Nov: a prompt rewording set every knowledge item aside and nothing said so): books needed but
    not held and NO knowledge item written leaves "knowledge items: 0 of N expected (cause)" in the run's calls."""
    sel = {"not_held": NOT_HELD, "books": [{"alias": "B01", "book": BOOK_A}]}
    rows = _knowledge_answer(3)["items"]
    for r in rows:
        r["carried_by"] = "an invented study"
    aside = _Metered({"items": rows})
    CL.s3_knowledge(aside, {"kind": "procedure"}, sel, _made(14), "m")
    assert _notes(aside) == [
        "knowledge items: 0 of 1 expected (3 set aside as carried by another paper)"
    ]
    empty = _Metered({"items": []})
    CL.s3_knowledge(empty, {"kind": "procedure"}, sel, _made(14), "m")
    assert _notes(empty) == [
        "knowledge items: 0 of 1 expected (the answer held no items)"
    ]
    failed = _Metered({}, fail="transport ReadTimeout")
    CL.s3_knowledge(failed, {"kind": "procedure"}, sel, _made(14), "m")
    assert _notes(failed)[0].startswith(
        "knowledge items: 0 of 1 expected (the call failed: transport ReadTimeout"
    )


def test_no_note_when_items_are_written_or_no_book_is_missing():
    sel = {"not_held": NOT_HELD, "books": [{"alias": "B01", "book": BOOK_A}]}
    ok = _Metered(_knowledge_answer(3))
    CL.s3_knowledge(ok, {"kind": "procedure"}, sel, _made(14), "m")
    assert _notes(ok) == []
    held = _Metered({"items": []})
    CL.s3_knowledge(
        held, {"kind": "procedure"}, {"not_held": [], "books": []}, _made(14), "m"
    )  # below the floor, none missing
    assert _notes(held) == []


def test_the_guard_reaches_a_run_and_the_how_made_tab(aim_db):
    """Through a whole run: the note is one of the run's calls (the run record and the How-made tab list every call)."""
    from tests.test_aim_method_helpers import MemoryStore

    def select(step, cached, prompt):
        import re

        ids = re.findall(r'"alias": "(B\d+)"', prompt)[:10]
        return {"books": [{"alias": a, "why": "x", "subjects": "all"} for a in ids],
                "not_held_needed": [{"name": "API 9990 invented practice", "why": "needed"}]}  # fmt: skip

    know = {
        "items": [
            {"topic": "t", "what_to_check": "w", "carried_by": "an invented study"}
        ]
    }
    model = E.FakeModel(kind="datasheet", subject_key="test_item",
                        answers={"aim_select": select, "aim_checklist_knowledge": know})  # fmt: skip
    r = aim_review.run(aim_db, run_id="run_guard", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    codes = [c.get("code") or "" for c in r.calls]
    assert any(
        c.startswith("knowledge items: 0 of 1 expected (1 set aside") for c in codes
    ), codes


def test_a_checklist_that_lost_every_knowledge_item_is_used_once_never_saved(aim_db):
    """Books needed but not held and the knowledge step wrote NO item: the checklist serves this run only and is never saved, so
    the next run builds again instead of reusing the loss (18 Nov: a HAZOP checklist saved with every knowledge item set aside)."""
    from tests.test_aim_method_helpers import MemoryStore

    def select(step, cached, prompt):
        import re

        ids = re.findall(r'"alias": "(B\d+)"', prompt)[:10]
        return {"books": [{"alias": a, "why": "x", "subjects": "all"} for a in ids],
                "not_held_needed": [{"name": "API 9990 invented practice", "why": "needed"}]}  # fmt: skip

    lost = {
        "items": [
            {"topic": "t", "what_to_check": "w", "carried_by": "an invented study"}
        ]
    }
    store = MemoryStore()
    for run_id in ("run_lost1", "run_lost2"):
        model = E.FakeModel(kind="procedure", subject_key="test_procedure",
                            answers={"aim_select": select, "aim_checklist_knowledge": lost})  # fmt: skip
        r = aim_review.run(aim_db, run_id=run_id, paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                           max_usd=5.0, model=model)  # fmt: skip
        assert r.status == "done" and not r.checklist_reused and store.puts == []
        assert any(c["step"] == "aim_checklist_knowledge" for c in model.asked)


def test_every_table_of_values_gets_one_item_that_checks_every_row():
    """One general instruction (no kind named) in both checklist asks: a table of values gets ONE consistency item over EVERY row
    (order across categories, units and decades, the order of magnitude of public practice); the checklist method is bumped."""
    assert CL.P.TABLE_ROWS_ASK in CL.P.KNOWLEDGE_ASK
    prompt = CL._for_type(CL.P.KNOWLEDGE_TASK) % {"identity": "x", "not_held": "x", "have": 0, "topics": "[]", "floor": 1,
                                                  "most": 1, "kinds": "[]", "table_rows": CL.P.TABLE_ROWS_ASK}  # fmt: skip
    assert "checks EVERY row" in prompt and "order of magnitude" in prompt
    assert CL.CHECKLIST_METHOD == "2026-11-18.2"
