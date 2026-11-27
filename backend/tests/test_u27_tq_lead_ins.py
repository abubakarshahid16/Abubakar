"""The requests found on a contractor's form, tidied (the planner's 15:18 fault, 27 Nov 2026, traced by builder F to the question splitter):
items 2 and 3 of some queries were lead-in lines, and the real question was missing. Invented forms only; no model (its list is given)."""

from __future__ import annotations

from app import technical_queries as tq
from app import technical_query_questions as Q

PAGE = """INVENTED CLARIFICATION FORM CFC-90012

CONTRACTOR requests COMPANY confirmation on the following two points:
- The invented pump casing may be ductile iron.
- The invented seal plan may be Plan 53B.

CONTRACTOR understands that the invented tank roof needs no inert gas blanket, because the stored liquid is not volatile.
COMPANY confirmation is kindly requested on the above understanding.

The invented relief valve is sized for fire case only.

COMPANY to confirm.

Yes / No
"""


def test_a_lead_in_is_a_lead_not_an_item():
    found = ["CONTRACTOR requests COMPANY confirmation on the following two points:", "- The invented pump casing may be ductile iron."]
    assert Q.tidy(found, PAGE) == [
        {"question": "CONTRACTOR requests COMPANY confirmation on the following two points:", "lead": True},
        {"question": "- The invented pump casing may be ductile iron."},
    ]


def test_a_request_that_points_back_is_replaced_by_the_words_it_points_at():
    # the understanding is in the same paragraph, before the request
    got = Q.tidy(["COMPANY confirmation is kindly requested on the above understanding."], PAGE)
    assert got == [{"question": "CONTRACTOR understands that the invented tank roof needs no inert gas blanket, because the stored "
                                "liquid is not volatile."}]
    # a bare "COMPANY to confirm." in its own paragraph: the paragraph above it
    assert Q.tidy(["COMPANY to confirm."], PAGE) == [{"question": "The invented relief valve is sized for fire case only."}]
    # what it is replaced by still stands on the page word for word (from_pages keeps only such words)
    for item in got:
        assert Q._squash(item["question"]) in Q._squash(PAGE)


def test_an_answer_choice_cell_is_never_a_question_and_a_real_request_stays():
    assert Q.tidy(["Yes / No", "Y/N"], PAGE) == []
    real = "COMPANY is kindly requested to confirm the invented flange rating."
    assert Q.tidy([real], PAGE + "\n" + real) == [{"question": real}]
    # a request that names what to confirm is not a back-pointer, even with "confirm" in it
    named = "COMPANY to confirm that the invented feed data is frozen for the design:"
    assert Q.tidy([named], PAGE)[0]["lead"] is True


def test_from_pages_keeps_the_lead_and_brings_the_real_questions(monkeypatch):
    monkeypatch.setattr(Q, "_ask", lambda page: [
        "CONTRACTOR requests COMPANY confirmation on the following two points:",
        "COMPANY confirmation is kindly requested on the above understanding.",
        "Yes / No",
    ])
    out, note = Q.from_pages([{"text": PAGE, "filename": "invented.pdf", "page": 1}])
    words = [(p["question"], bool(p.get("lead"))) for p in out]
    assert note == ""
    assert words[0] == ("CONTRACTOR requests COMPANY confirmation on the following two points:", True)
    assert ("The invented pump casing may be ductile iron.", False) in words  # its list, brought by the lead-in (as before)
    assert any(w.startswith("CONTRACTOR understands that the invented tank roof") for w, _ in words)  # the real question
    assert not any("Yes / No" in w or "above understanding" in w for w, _ in words)


def test_the_composed_question_numbers_only_the_requests():
    proposals = [
        {"question": "CONTRACTOR requests COMPANY confirmation on the following two points:", "lead": True},
        {"question": "- The invented pump casing may be ductile iron."},
        {"question": "- The invented seal plan may be Plan 53B."},
        {"question": "Further, CONTRACTOR asks about the invented tank:", "lead": True},
        {"question": "Does the invented tank roof need an inert gas blanket?"},
    ]
    text = tq.propose_question("", proposals, "Invented pump")
    assert text.split("\n") == [
        "CONTRACTOR requests COMPANY confirmation on the following two points:",  # the form's own lead-in is the lead
        "1. - The invented pump casing may be ductile iron.",
        "2. - The invented seal plan may be Plan 53B.",
        "",  # a blank line: the next lead-in never reads as the end of item 2
        "Further, CONTRACTOR asks about the invented tank:",
        "3. Does the invented tank roof need an inert gas blanket?",
    ]
    from app.technical_query_items import items_of

    assert len(items_of(text)) == 3  # the per-item search sees three requests, no lead-in among them
    # a lead-in with nothing after it introduces nothing: it stays a numbered request
    assert tq.propose_question("", [{"question": "Please confirm the following:", "lead": True}], "X") .split("\n")[-1] == \
        "1. Please confirm the following:"
