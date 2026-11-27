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
    assert texts[1] == (
        "generic",
        None,
    )  # then the WHOLE request's own best (never crowded out by the items' lists)
    assert texts[2:5] == [("spacing 1", 1), ("spacing 2", 1), ("spacing 3", 1)]
    assert texts[5:8] == [("nozzle 1", 2), ("nozzle 2", 2), ("nozzle 3", 2)]
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


def test_roman_numerals_and_bullets_split_into_items_like_the_extractor_keeps_them():
    """Fresh review of PR #1936: the extractor kept "i) ii) iii)" items that the splitter did not split, so the per-item search quietly
    fell back to one search of the whole list. One shared marker now."""
    roman = "Please confirm each item:\n\ni) first invented item\nii) second invented item\niii) third\niv) fourth\nix) ninth\nx) tenth"
    assert items.items_of(roman) == [
        "first invented item",
        "second invented item",
        "third",
        "fourth",
        "ninth",
        "tenth",
    ]
    assert items.items_of("Please confirm:\n\nI. upper one\nII. upper two") == [
        "upper one",
        "upper two",
    ]
    assert items.items_of("Please confirm:\n\n- bullet one\n- bullet two") == [
        "bullet one",
        "bullet two",
    ]
    mail = "Dear Sir,\n\nPlease confirm each item:\n\ni) first invented item\nii) second invented item\n\nRegards"
    assert items.items_of(email_question(mail)) == [
        "first invented item",
        "second invented item",
    ]  # extractor and splitter agree


def test_an_item_too_long_is_cut_with_a_visible_mark_never_silently():
    long_item = (
        "Please confirm:\n\n1. an invented item\n"
        + "that wraps on and on " * 200
        + "\n2. the next"
    )
    first, second = items.items_of(long_item)
    assert (
        first.endswith(items.ITEM_CUT)
        and len(first) <= items.ITEM_CAP + len(items.ITEM_CUT)
        and second == "the next"
    )


def test_a_draft_that_leaves_a_numbered_item_unanswered_says_so():
    """Lead-4's blind re-score (27 Nov 2026): a draft silently dropped item 3 instead of writing "Not found" for it."""
    q = "Please confirm each item:\n\n1. first\n2. second\n3. third"
    assert auto.unanswered_mark(
        "**1.** COMPANY confirms ... [S1]\n**2.** COMPANY ... [S2]", q
    ) == ("The draft does not answer request item 3; check it by hand.")
    assert (
        auto.unanswered_mark(
            "Items 1 and 2: ... Item 3: Not found in the documents searched.", q
        )
        is None
    )
    assert (
        auto.unanswered_mark("Items 1 to 3 are answered together: ...", q) is None
    )  # grouped, as COMPANY does
    assert "does not say which" in auto.unanswered_mark(
        "COMPANY confirms the rule applies.", q
    )
    assert (
        auto.unanswered_mark("anything", "Please confirm the coating.") is None
    )  # a single request: nothing to count


def test_each_item_is_searched_with_its_lead_line_so_the_search_carries_the_subject(
    monkeypatch,
):
    """Lead-4's re-score (27 Nov 2026): an option "Position 1: handled as ..." searched alone found a higher-scoring, unrelated contract
    clause; the request's subject is in its lead line."""
    from app import technical_query_contracts as tqc

    asked = []
    monkeypatch.setattr(
        tqc,
        "search_all",
        lambda q, *a, **k: asked.append(q) or {"hits": [], "coverage": {}},
    )
    q = "Please confirm which of the following positions shall apply to the invented flare material:\n\n1) Position one\n2) Position two"
    items.search(q, frozenset(), None, [])
    lead = "Please confirm which of the following positions shall apply to the invented flare material:"
    assert asked == [
        q,
        f"{lead} Position one",
        f"{lead} Position two",
    ]  # the whole request once, then each item with its lead
    assert (
        items.lead_of("1. a\n2. b") == ""
    )  # no lead line: the item is searched on its own


def test_evidence_found_by_an_older_search_is_out_of_date_and_is_searched_again_at_the_next_start(
    monkeypatch,
):
    """Lead-4 (27 Nov 2026): after the per-item search changed, the live queries kept the old single search's evidence and nothing on
    the page said so, nor offered "Find the sources again". The search version is stamped like a draft's prompt version."""
    from app.technical_query_items import SEARCH_VERSION

    q = "Please confirm the coating."
    old = {
        "proposed_question": q,
        "evidence_question": q,
        "evidence_search_version": None,
        "evidence": [],
        "drafts": [],
    }
    ready = auto.ready(old)
    assert (
        ready["evidence_outdated"]
        and not ready["evidence_fresh"]
        and auto.OUTDATED_MARK in ready["marks"]
    )
    now = {**old, "evidence_search_version": str(SEARCH_VERSION)}
    assert (
        not auto.ready(now)["evidence_outdated"] and auto.ready(now)["evidence_fresh"]
    )
    assert not auto.evidence_outdated(
        {**old, "evidence_question": None}
    )  # never prepared: nothing out of date


def test_many_items_never_crowd_out_the_whole_requests_best_passages(monkeypatch):
    """F's live redo (27 Nov 2026): 7 items x 3 passages filled the listing and cut the whole request's best, the passages its earlier
    draft rested on."""
    from app import technical_query_contracts as tqc

    q = "Please confirm each item:\n\n" + "\n".join(
        f"{n}. invented item {n}" for n in range(1, 8)
    )

    def search_all(question, allowed, progress=None, cited_from=None):
        if question == q:
            return {
                "hits": [
                    {"document_id": "w", "page_start": n, "text": f"whole {n}"}
                    for n in range(1, 6)
                ],
                "coverage": {},
            }
        return {
            "hits": [
                {"document_id": "i", "page_start": n, "text": f"{question[-6:]} {n}"}
                for n in range(1, 4)
            ],
            "coverage": {},
        }

    monkeypatch.setattr(tqc, "search_all", search_all)
    hits = items.search(q, frozenset(), None, [])["hits"]
    assert [h["text"] for h in hits[:3]] == [
        "whole 1",
        "whole 2",
        "whole 3",
    ]  # first, so under the listing limit
    assert sum(1 for h in hits if h.get("item")) == 21 and [
        h["text"] for h in hits[-2:]
    ] == ["whole 4", "whole 5"]


def test_an_item_answered_in_prose_without_its_number_is_not_marked_unanswered():
    """The owner's regression query (27 Nov 2026): item 3 was answered in a paragraph after "1." and "2."; the mark wrongly said it was not."""
    q = "Please confirm each invented point:\n\n1. the invented flange class\n2. the invented gasket type\n3. invented as-built drawings before invented completion"
    prose = "1. COMPANY confirms the flange class [S1].\n2. The gasket type is stated [S2].\n\nThe invented as-built drawings are due before invented completion [S3]."
    assert auto.unanswered_mark(prose, q) is None
    assert auto.unanswered_mark(
        "1. COMPANY confirms the flange class [S1].\n2. The gasket type is stated [S2].",
        q,
    ) == ("The draft does not answer request item 3; check it by hand.")
