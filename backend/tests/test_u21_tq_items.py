"""A request of many numbered items is answered item by item (lead-4's blind test of seven of the owner's approved answers, 27 Nov 2026:
1 of 7 matched; the numbered items were dropped from the question, the whole list was searched once, and the local draft read 3
passages). Invented mails, forms and passages; no model, no network."""

from __future__ import annotations

from app import answer as A
from app import technical_query_auto as auto
from app import technical_query_items as items
from app import technical_query_questions as Q
from app.technical_query_mail import LIST_CUT, email_question

LIST_MAIL = """Dear Sir,

We note the following conflicts between the invented documents:

1. Invented spec A gives a spacing of 2 m, while invented drawing B shows
1.5 m.
2. Invented spec A requires a flanged nozzle, while invented datasheet C shows a welded one.

Accordingly, COMPANY is requested to confirm the applicable requirement for each item above.

Regards,
Invented Contractor"""


def test_the_numbered_items_and_their_lead_in_stay_in_the_question():
    q = email_question(LIST_MAIL)
    assert (
        q.startswith("We note the following conflicts")
        and "1. Invented spec A gives a spacing" in q
    )
    assert "2. Invented spec A requires a flanged nozzle" in q and q.endswith(
        "for each item above."
    )
    assert "Regards" not in q and "Dear" not in q


def test_a_choice_between_positions_is_a_question_however_long_and_a_long_list_is_cut_with_a_mark():
    options = "\n".join(
        f"{n}) Position {n}: "
        + "the invented change is handled in an invented way " * 4
        for n in (1, 2, 3)
    )
    q = email_question(
        f"Dear Sir,\n\nPlease confirm which of the following positions shall apply:\n\n{options}\n\nRegards"
    )
    assert (
        q.startswith("Please confirm which of the following positions shall apply:")
        and "3) Position 3" in q
    )
    many = "\n".join(
        f"{n}. " + "an invented conflict between two invented documents " * 3
        for n in range(1, 60)
    )
    cut = email_question(
        f"Dear Sir,\n\nPlease confirm each item below:\n\n{many}\n\nRegards"
    )
    assert cut.endswith(LIST_CUT)  # never dropped for its length, never cut silently
    assert (
        email_question("Hello,\n\nFor your information:\n\n1. One\n2. Two\n\nRegards")
        == ""
    )  # a list that asks nothing


def test_items_are_split_with_their_wrapped_lines_and_a_sentence_after_the_list_is_not_an_item():
    q = email_question(LIST_MAIL)
    assert items.items_of(q) == [
        "Invented spec A gives a spacing of 2 m, while invented drawing B shows 1.5 m.",
        "Invented spec A requires a flanged nozzle, while invented datasheet C shows a welded one.",
    ]
    assert items.items_of("Please confirm the coating.") == []


def test_each_item_is_searched_on_its_own_and_its_best_passages_come_first(monkeypatch):
    from app import technical_query_contracts as tqc

    def search_all(question, allowed, progress=None, cited_from=None):
        if (
            "spacing" in question and "nozzle" in question
        ):  # the whole request: a cited clause and two generic finds
            return {"hits": [{"document_id": "c", "page_start": 1, "text": "cited clause", "cited": True},
                             {"document_id": "g", "page_start": 9, "text": "generic"}], "coverage": {"line": "Searched 2 of 2 contracts."}}  # fmt: skip
        word = "spacing" if "spacing" in question else "nozzle"
        return {
            "hits": [
                {"document_id": "s", "page_start": n, "text": f"{word} {n}"}
                for n in range(1, 6)
            ],
            "coverage": {},
        }

    monkeypatch.setattr(tqc, "search_all", search_all)
    out = items.search(email_question(LIST_MAIL), frozenset({"c", "g", "s"}), None, [])
    texts = [(h["text"], h.get("item")) for h in out["hits"]]
    assert texts[0] == ("cited clause", None)  # the form's citation first, as before
    assert texts[1:4] == [
        ("spacing 1", 1),
        ("spacing 2", 1),
        ("spacing 3", 1),
    ] and texts[4:7] == [("nozzle 1", 2), ("nozzle 2", 2), ("nozzle 3", 2)]
    assert texts[-1] == ("generic", None)
    assert (
        "The 2 numbered items were also searched one by one." in out["coverage"]["line"]
    )


def test_the_draft_takes_its_passages_item_by_item():
    found = [
        {"id": "a1", "item_no": 1},
        {"id": "a2", "item_no": 1},
        {"id": "b1", "item_no": 2},
        {"id": "w"},
        {"id": "b2", "item_no": 2},
    ]
    assert [e["id"] for e in auto.by_item(found)] == ["a1", "b1", "a2", "b2", "w"]


def test_a_form_page_request_brings_its_numbered_items_never_its_references(
    monkeypatch,
):
    page = ("INVENTED FORM\nReferences:\n1. Invented spec A\n2. Invented drawing B\n\nThe following conflicts were found:\n"
            "1. Spec A gives 2 m, while drawing B\nshows 1.5 m.\n2. Spec A requires a flanged nozzle.\n\n"
            "Accordingly, COMPANY is requested to confirm each item above.")  # fmt: skip
    monkeypatch.setattr(
        Q,
        "_ask",
        lambda text: ["Accordingly, COMPANY is requested to confirm each item above."],
    )
    out, note = Q.from_pages([{"filename": "f.pdf", "page": 1, "text": page}])
    assert [o["question"] for o in out] == [
        "Accordingly, COMPANY is requested to confirm each item above.",
        "Spec A gives 2 m, while drawing B shows 1.5 m.",
        "Spec A requires a flanged nozzle.",
    ] and note == ""


def test_a_query_draft_reads_more_passages_in_a_larger_window_and_chat_keeps_its_own(
    monkeypatch,
):
    from app import chat_model, model_transport

    assert (
        A.query_reply_sizes() is None
        and A.context_budget_for_lane()["passages"]
        == A.settings.generated_context_passages
    )
    sent = []
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, timeout=0: sent.append(body["options"]) or {"response": "x"},
    )
    monkeypatch.setattr(
        chat_model, "provider", lambda preference=None: object()
    )  # the local engine
    chat_model.generate("s", "p", temperature=0.0)
    with A.query_reply():
        assert A.context_budget_for_lane()["passages"] == A.QUERY_REPLY_PASSAGES
        chat_model.generate("s", "p", temperature=0.0)
    assert (
        sent[0]["num_ctx"] == A.settings.num_ctx
        and sent[0]["num_predict"] == A.settings.max_output_tokens
    )  # Chat unchanged
    assert (
        sent[1]["num_ctx"] == A.QUERY_REPLY_NUM_CTX
        and sent[1]["num_predict"] == A.QUERY_REPLY_MAX_OUTPUT
    )


def test_the_page_gets_the_items_to_group_the_sources_by():
    q = email_question(LIST_MAIL)
    assert auto.ready({"proposed_question": q, "evidence": [], "drafts": []})[
        "items"
    ] == items.items_of(q)
