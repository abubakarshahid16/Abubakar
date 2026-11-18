"""Builder C (order 14): the contract code checks and the fixed contract checklist (`app.aim_review.contract_code`).
Every paper here is INVENTED text: no client, project, number or sentence of a real paper."""

from __future__ import annotations

from types import SimpleNamespace

from app.aim_review import contract_code as K
from app.aim_review.fail_words import PROVEN_FAIL
from app.aim_review.steps import KNOWLEDGE
from app.aim_review.verify import quote_in
from app.aim_review_store import FAIL_BY_CODE, shown_label

C = {"kind": "contract"}


def _only(lines, item):
    return [ln for ln in lines if ln["item_id"] == K.IDS[item]]


def _quotes_verify(lines, pages):
    for ln in lines:
        assert ln["page"] in pages and quote_in(ln["quote"], pages[ln["page"]]), ln


def _firm(ln):
    assert ln["label"] == "Not met"
    assert ln["comment"].startswith(PROVEN_FAIL)
    assert (
        ln["code_compare"]["read_from"] == "verified quotes"
        and ln["code_compare"]["result"] == "fail"
    )
    assert (
        shown_label(ln["label"], ln["code_compare"], ln["deferred"], ln["code"])
        == FAIL_BY_CODE
    )


# ------------------------------------------------------------------ amounts in words and figures


def test_amount_words_differ_from_figures_is_proven():
    pages = {
        2: "The Buyer shall pay the Seller Euros Seventy-Two Thousand Five Hundred (EUR 72,050.00) as the price."
    }
    lines = _only(K.lines(pages, C), "amount_words")
    assert len(lines) == 1
    _firm(lines[0])
    assert lines[0]["page"] == 2 and "72,500" in lines[0]["comment"]
    _quotes_verify(lines, pages)


def test_amount_words_currency_differs_is_proven():
    pages = {1: "a price of Euros Forty Thousand (GBP 40,000) for the goods."}
    lines = _only(K.lines(pages, C), "amount_words")
    assert (
        len(lines) == 1
        and "EUR" in lines[0]["comment"]
        and "GBP" in lines[0]["comment"]
    )
    _firm(lines[0])


def test_amount_words_consistent_gives_no_line():
    pages = {1: "a price of Euros Forty Thousand (EUR 40,000) and a retention of five percent (5%) of each invoice, "
                "within twenty-one (21) days."}  # fmt: skip
    assert _only(K.lines(pages, C), "amount_words") == []


def test_percentage_words_differ_from_figures_is_proven():
    pages = {1: "The Seller shall give a bond of seven percent (9%) of the price."}
    lines = _only(K.lines(pages, C), "amount_words")
    assert len(lines) == 1 and "percentage" in lines[0]["comment"]
    _firm(lines[0])


def test_value_left_open_or_forged_gives_no_verdict():
    pages = {1: "a price of Euros ____________ (EUR ..........), a bond of ten percent (TBA) and Ten (By Contractor) "
                "spares; a fee of Ten (10/12) units."}  # fmt: skip
    assert _only(K.lines(pages, C), "amount_words") == []


# ------------------------------------------------------------------ dates and durations


def test_end_before_start_is_proven():
    pages = {4: "The Seller shall start on 5 May 2031 (the “Start Date”) and finish by 2 February 2031 "
                "(the “Completion Date”)."}  # fmt: skip
    lines = _only(K.lines(pages, C), "dates")
    assert len(lines) == 1 and "before the start" in lines[0]["comment"]
    _firm(lines[0])
    _quotes_verify(lines, pages)


def test_duration_not_matching_dates_is_proven():
    pages = {4: "The Seller shall commence on 1 April 2030 (the “Commencement Date”) and complete within "
                "Ten (10) months, not later than 31 December 2031 (the “Completion Date”)."}  # fmt: skip
    lines = _only(K.lines(pages, C), "dates")
    assert len(lines) == 1 and "01 February 2031" in lines[0]["comment"]
    _firm(lines[0])


def test_consistent_dates_and_ambiguous_forms_give_no_line():
    ok = {4: "The Seller shall commence on 1 April 2030 (the “Commencement Date”) and complete within "
             "Ten (10) months, not later than 31 January 2031 (the “Completion Date”)."}  # fmt: skip
    ambiguous = {4: "The Seller shall commence on 03/04/2031 (the “Commencement Date”) and complete not later "
                    "than 02/01/2031 (the “Completion Date”)."}  # fmt: skip
    assert _only(K.lines(ok, C), "dates") == []
    assert _only(K.lines(ambiguous, C), "dates") == []


# ------------------------------------------------------------------ percentages


def test_equal_split_with_unequal_parts_is_proven_and_equal_split_is_not():
    bad = {
        3: "The fee shall be shared equally (65% North / 35% South) between the two offices."
    }
    good = {
        3: "The fee shall be shared equally (50% North / 50% South) between the two offices."
    }
    lines = _only(K.lines(bad, C), "splits")
    assert len(lines) == 1
    _firm(lines[0])
    assert _only(K.lines(good, C), "splits") == []


def _bond(cap_a: str, cap_b: str, subject_b: str = "total bond") -> dict[int, str]:
    return {
        5: "7.1 Bond\nThe Seller gives a bond. The total bond shall not exceed " + cap_a + " of the Contract Price.",
        6: "Further text of the bond clause follows here. The " + subject_b + " shall not exceed " + cap_b
        + " of the Contract Price.",
    }  # fmt: skip


def test_two_caps_for_the_same_item_are_asked_never_proven():
    same = _bond("four percent (4%)", "eight percent (8%)")
    lines = _only(K.lines(same, C), "percent_values")
    assert (
        len(lines) == 1 and lines[0]["label"] == "Question"
    )  # the same item is a layout reading (review B2)
    other = _bond(
        "four percent (4%)", "eight percent (8%)", subject_b="total cash bond"
    )
    lines = _only(K.lines(other, C), "percent_values")
    assert len(lines) == 1 and lines[0]["label"] == "Question"
    assert (
        _only(
            K.lines(_bond("four percent (4%)", "four percent (4%)"), C),
            "percent_values",
        )
        == []
    )


def test_delay_rate_times_days_against_cap_is_a_question():
    pages = {7: "9.2 Delay Damages\nThe Seller shall pay delay damages at the rate of 0.5% of the Contract Price per day "
                "for a maximum of 20 days. The delay damages shall not exceed 15% of the Contract Price."}  # fmt: skip
    lines = _only(K.lines(pages, C), "delay_cap")
    assert (
        len(lines) == 1
        and lines[0]["label"] == "Question"
        and "10%" in lines[0]["comment"]
    )
    pages[7] = pages[7].replace("15%", "10%")
    assert _only(K.lines(pages, C), "delay_cap") == []


# ------------------------------------------------------------------ schedules


def _deal(ranked: list[str], listed: list[str]) -> dict[int, str]:
    lst = "\n".join(f'SCHEDULE "{x}"\nTitle words of part {x}' for x in listed)
    order = "\n".join(
        f'{i}.\nSchedule "{x}" and its Attachments' for i, x in enumerate(ranked, 1)
    )
    return {
        1: "1.1 This Agreement consists of this document and the following attached schedules:\n" + lst
        + "\nA reference to any of the schedules listed above includes its attachments and all documents they name.",
        2: "1.4 In the event of any conflict among the documents the following order of precedence shall govern:\n" + order
        + "\n2.\nWORK",
    }  # fmt: skip


def test_schedule_ranked_but_not_listed_and_listed_but_not_ranked_are_questions():
    pages = _deal(["A", "B", "Z"], ["A", "B", "C"])
    lines = _only(K.lines(pages, C, held={"A", "B", "C"}), "schedules")
    assert len(lines) == 2
    for (
        ln
    ) in lines:  # an absence from a list read by layout is never a proof (review B2)
        assert ln["label"] == "Question" and PROVEN_FAIL not in ln["comment"]
    assert (
        "Schedule Z is ranked" in lines[0]["comment"]
        and "Schedule C is listed" in lines[1]["comment"]
    )
    _quotes_verify(lines, pages)


def test_schedules_consistent_give_no_line_and_package_gap_is_one_question():
    pages = _deal(["A", "B", "C"], ["A", "B", "C"])
    assert _only(K.lines(pages, C, held={"A", "B", "C"}), "schedules") == []
    assert _only(K.lines(pages, C, held=None), "schedules") == []
    gap = _only(K.lines(pages, C, held={"A"}), "schedules")
    assert (
        len(gap) == 1 and gap[0]["label"] == "Question" and "B, C" in gap[0]["comment"]
    )


# ------------------------------------------------------------------ defined terms


def test_defined_term_in_another_form_is_one_question():
    pages = {1: 'The firm Alpha Works ("SELLER") agrees to sell. The SELLER shall deliver.',
             2: "The Seller shall then invoice. The SELLER is paid."}  # fmt: skip
    lines = _only(K.lines(pages, C), "terms")
    assert len(lines) == 1 and lines[0]["label"] == "Question" and lines[0]["page"] == 2
    _quotes_verify(lines, pages)
    pages[2] = (
        "The SELLER shall then invoice. The seller of spare parts is paid."  # lower case: the plain word, not the term
    )
    assert _only(K.lines(pages, C), "terms") == []


# ------------------------------------------------------------------ kind gate, checklist, hook


def test_other_kinds_get_nothing():
    pages = {1: "a price of Euros Forty Thousand (GBP 40,000)."}
    assert K.lines(pages, {"kind": "datasheet"}) == []
    assert K.checklist_items({"kind": "procedure"}) == []


def test_fixed_checklist_items_are_knowledge_items_with_unique_ids():
    items = K.checklist_items(C)
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)) >= 16
    assert all(it["source"] == KNOWLEDGE and it["what_to_check"] for it in items)
    topics = " ".join(it["topic"].lower() for it in items)
    for word in ("parties", "signature", "scope", "price", "payment", "securities", "delay", "warranty", "assignment",
                 "termination", "governing law", "disputes", "notices", "safety", "quality", "local content"):  # fmt: skip
        assert word in topics, word


def test_add_lines_appends_to_the_decided_lines():
    state = SimpleNamespace(identity=C, paper_id="doc_x", decided=[{"item_id": "1"}])
    paper = SimpleNamespace(pages={1: "a price of Euros Forty Thousand (GBP 40,000)."})

    class NoConn:
        def execute(self, *a, **k):
            raise RuntimeError("no database here")

    assert K.add_lines(NoConn(), state, paper) == 1
    assert (
        state.decided[-1]["item_id"] == K.IDS["amount_words"]
        and len(state.decided) == 2
    )
