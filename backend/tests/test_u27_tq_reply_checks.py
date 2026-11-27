# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""A technical query's draft reply is COMPANY's words to a contractor (owner, 27 Nov 2026 12:32 PKT, on the live Queries page: "hard to
read, too much text, some answers look wrong"; lead-4's order). Four checks, `technical_query_reply_checks`: no first-person advice in
the reply, every [Sn] a source the reply was given, a COMPANY position with no source marked, one cost / schedule message. Invented
values; no model."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import db
from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app import technical_query_reply_checks as RC
from app.api import technical_queries as api
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import (  # noqa: F401 - the ready-query fixture
    QUOTE,
    _run,
    query,
)

ADVICE = "What I'd do: ask the contractor for the invented coating test record before replying."


# ------------------------------------------------------------------ the checks themselves


def test_first_person_advice_is_cut_out_of_the_reply_and_kept_for_the_engineer():
    reply, advice = RC.split_advice(f"1. Class 300 applies [S1].\n\n**{ADVICE}**\n- Then check the invented rating table.")
    assert reply == "1. Class 300 applies [S1]."
    assert advice.startswith("What I'd do: ask the contractor") and advice.endswith("check the invented rating table.")
    # a numbered answer after the advice stays in the reply; numbered steps inside the advice paragraph go with it
    reply, advice = RC.split_advice(f"1. Class 300 applies [S1].\n{ADVICE}\n1. Ask for the record.\n\n2. Not found in the documents searched.")
    assert reply == "1. Class 300 applies [S1].\n2. Not found in the documents searched." and "Ask for the record." in advice
    # "- **Request 3 ...**" after the advice is the reply again, even as a bullet
    reply, _ = RC.split_advice(f"{ADVICE}\n\n- **Request 3 (invented valve):** Not found in the documents searched.")
    assert reply == "- **Request 3 (invented valve):** Not found in the documents searched."
    assert RC.split_advice("1. Class 300 applies [S1].") == ("1. Class 300 applies [S1].", None)
    for head in ("**What I would do**: ask.", "My recommendation: ask.", "- My advice is to ask."):
        assert RC.split_advice(f"1. Class 300 applies [S1].\n\n{head}")[1], head


def test_the_first_person_is_found_outside_quotes_and_a_numeral_i_is_not_a_person():
    assert RC.first_person("COMPANY has reviewed the request. I recommend a hold point [S1].")
    assert RC.first_person("In my view the rating is too low.")
    assert RC.first_person("We note the request; I'd ask for the record.")
    assert not RC.first_person("COMPANY confirms that Schedule I would apply [S1].")  # a part numeral
    assert not RC.first_person('The standard says "I will not be used" [S1].')  # quoted words are the source's
    assert not RC.first_person("COMPANY has reviewed the invented datasheet [S1].")


def test_every_source_tag_must_be_one_the_reply_was_given():
    given = [{"text": "a"}, {"text": "b"}]
    assert RC.unknown_sources({"answer": "1. Applies [S1].", "cited": [1], "passages": given}) == []
    assert RC.unknown_sources({"answer": "1. Applies [S1] [S3].", "cited": [1], "passages": given}) == [3]  # past the sources given
    assert RC.unknown_sources({"answer": "1. Applies [S2].", "cited": [1], "passages": given}) == [2]  # given but not among its cited
    # the answer lane dropped a tag it did not supply, leaving the sentence with no source: a fault here, never silent
    assert RC.unknown_sources({"answer": "1. Applies.", "cited": [1], "passages": given, "rejected_citations": [7]}) == [7]


def test_a_company_position_with_no_source_is_counted_and_one_with_a_source_is_not():
    assert RC.unsourced_positions("COMPANY accepts the invented deviation.") == 1
    assert RC.unsourced_positions("COMPANY accepts the invented deviation [S1]. COMPANY does not accept the rest.") == 1
    assert RC.unsourced_positions("COMPANY to confirm the invented position.") == 0  # leaves it open
    assert RC.unsourced_positions('The contractor writes "COMPANY accepts" in its letter.') == 0  # quoted


def test_the_old_cost_and_schedule_stand_in_goes_since_the_page_offers_companys_sentence():
    assert RC.drop_cost_standin("1. Class 300 applies [S1].\n\nCOMPANY to confirm the cost and schedule position.") == "1. Class 300 applies [S1]."
    assert RC.drop_cost_standin("1. Applies [S1]. **COMPANY to confirm the cost and schedule position.**") == "1. Applies [S1]."
    from app import answer as A

    with A.query_reply():
        prompt = " ".join(A._fit(A.SYSTEM_PROMPT).split())
    assert "COMPANY to confirm the cost and schedule position" not in prompt and "the engineer adds COMPANY's position" in prompt
    assert "Never write \"I\" and never \"What I'd do\"" in prompt


# ------------------------------------------------------------------ the two ways a draft is written


def _answers(monkeypatch, *answers):
    left = list(answers)
    calls = []
    base = {"answer_type": "generated", "cited": [1], "model": "synthetic-local",
            "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": QUOTE}]}  # fmt: skip

    def fake(_q, **_k):
        calls.append(1)
        return {**base, **left.pop(0)} if len(left) > 1 else {**base, **left[0]}

    monkeypatch.setattr("app.answer.answer", fake)
    return calls


def test_a_system_draft_keeps_its_reply_and_puts_the_advice_beside_it(query, monkeypatch):
    item, scope, _asked = query
    _answers(monkeypatch, {"answer": f"1. Class 300 applies [S1].\n\nCOMPANY to confirm the cost and schedule position.\n\n{ADVICE}"})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    assert [d["answer"] for d in got["drafts"]] == ["1. Class 300 applies [S1]."]  # no advice, no stand-in
    assert any(m.startswith(RC.ADVICE_MARK) and "coating test record" in m for m in json.loads(got["drafts"][-1]["unresolved_json"]))


def test_a_draft_that_speaks_as_i_is_written_again_once_then_stopped(query, monkeypatch):
    item, scope, _asked = query
    calls = _answers(monkeypatch, {"answer": "1. I recommend class 300 [S1]."}, {"answer": "1. Class 300 applies [S1]."})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    assert len(calls) == 2 and [d["answer"] for d in tq.get(item["id"], "u1", False, False)["drafts"]] == ["1. Class 300 applies [S1]."]
    calls = _answers(monkeypatch, {"answer": "1. I recommend class 300 [S1]."})
    with db.connect() as conn:
        conn.execute("UPDATE technical_queries SET status='drafting' WHERE id=?", (item["id"],))
    assert auto.write_draft(item["id"], frozenset({"d1"}), "u1", False, False) == RC.FIRST_PERSON_NOTE and len(calls) == 2


def test_a_draft_whose_only_words_are_advice_is_not_a_reply(query, monkeypatch):
    item, scope, _asked = query
    _answers(monkeypatch, {"answer": ADVICE})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    assert got["drafts"] == [] and got["ready"]["draft_note"] == RC.FIRST_PERSON_NOTE


def test_a_draft_that_named_a_source_it_was_not_given_is_never_kept_neither_automatic_nor_generated(query, monkeypatch):
    item, scope, _asked = query
    _answers(monkeypatch, {"answer": "1. Class 300 applies [S1]. The test is waived.", "rejected_citations": [4]})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    assert got["drafts"] == [] and got["ready"]["draft_note"] == RC.UNKNOWN_SOURCE_NOTE
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert "a source it was not given" in str(refused.value.detail)


def test_the_generate_route_cuts_the_advice_and_marks_an_unsourced_company_position(query, monkeypatch):
    item, scope, _asked = query
    _answers(monkeypatch, {"answer": "1. Class 300 applies [S1]."})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    _answers(monkeypatch, {"answer": f"1. Class 300 applies [S1]. COMPANY accepts the invented deviation.\n\n{ADVICE}"})
    api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    draft = tq.get(item["id"], "u1", False, False)["drafts"][-1]
    assert draft["answer"] == "1. Class 300 applies [S1]. COMPANY accepts the invented deviation."
    unresolved = json.loads(draft["unresolved_json"])
    assert RC.UNSOURCED_MARK in unresolved and any(m.startswith(RC.ADVICE_MARK) for m in unresolved)


def test_an_older_ai_draft_that_speaks_as_i_is_marked_and_never_approved(query):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:  # a draft kept before these checks
        conn.execute("UPDATE query_drafts SET answer=? WHERE query_id=?", (f"1. Class 300 applies [S1].\n\n{ADVICE}", item["id"]))
    evidence = tq.get(item["id"], "u1", False, False)["evidence"][0]  # kept and confirmed: only the first person stands in the way
    tq.update_evidence(item["id"], evidence["id"], "verified", "current", None, "u1", "u1", False, False, reviewer=True)
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET confirmed_by='u1' WHERE document_id='d1'")
    got = tq.get(item["id"], "u1", False, False)
    assert RC.FIRST_PERSON_MARK in got["ready"]["marks"]
    with pytest.raises(ValueError, match="speaks as"):
        tq.decide(item["id"], "approve", "u1", None, got["drafts"][-1]["id"], "u1", False, False, reviewer=True)
    assert not RC.stored_first_person({"model": None, "answer": ADVICE})  # an engineer's own reply is the engineer's


# ------------------------------------------------------------------ builder H's table of the 34 queries (27 Nov 2026)


def test_a_bold_numbered_heading_or_a_request_label_keeps_its_number_through_the_figure_check():
    """Fault 4: "**3. Title**" lost "**3. " (its 3 was checked as a figure and removed), and a "Request 3:" line whose source prints no
    3 lost its whole answer. The number of a list marker or request label is a label, never a figure; an invented figure still goes."""
    from app import answer as A

    passages = [{"text": "Invented clause: the flange rating shall be class 300.", "page_start": 1, "page_end": 1}]
    for kept in ("**3. Flange rating**\nCOMPANY confirms class 300 [S1].", "**1. Flange rating:** COMPANY confirms class 300 [S1].",
                 "- **Request 3 (invented valve):** COMPANY confirms class 300 [S1].", "Items 1 and 2: COMPANY confirms class 300 [S1]."):
        assert A.ground_numbers(kept, passages)[0] == kept, kept
    for gone in ("1. The limit is 400 [S1].", "**2. Rating:** the limit is 400 [S1].", "Request 3: the limit is 400 [S1]."):
        assert "400" not in A.ground_numbers(gone, passages)[0], gone


def test_a_reply_cut_off_mid_sentence_or_with_a_bare_no_is_not_shown():
    assert RC.cut_off({"answer": "1. Class 300 applies [S1].", "truncated": True})
    assert RC.cut_off({"answer": "1. Class 300 applies [S1].\n2. The invented test is required by the"})
    assert not RC.cut_off({"answer": "1. Class 300 applies [S1].\n2. See Schedule B, clause 7.2"})
    assert RC.bare_answer("1. **No.**\n2. Class 300 applies [S1].") and RC.bare_answer("No.")
    assert not RC.bare_answer("No. The invented datasheet does not state a rating [S1].")


def test_an_unsourced_cost_or_schedule_position_leaves_the_reply_and_a_sourced_one_stays():
    reply, moved = RC.split_unsourced_cost("1. Class 300 applies [S1]. COMPANY will issue a change order for the extra cost.")
    assert reply == "1. Class 300 applies [S1]." and moved == "COMPANY will issue a change order for the extra cost."
    sourced = "1. Under the invented clause a change order covers the extra cost [S2]."
    assert RC.split_unsourced_cost(sourced) == (sourced, None)
    assert RC.split_unsourced_cost("1. The pipe is schedule 80 [S1].")[1] is None  # a pipe schedule is not a schedule position
    from app.technical_query_position import POSITION_LINE, offer

    assert offer("Who pays the extra cost?", sourced) == {"line": POSITION_LINE, "hint": None, "reply_speaks": True}  # one message
    assert offer("Who pays the extra cost?", "1. Class 300 applies [S1].")["hint"] and not offer("x", "y")["reply_speaks"]


def test_a_long_question_is_cut_after_a_whole_word_with_a_plain_sentence():
    from app.technical_query_items import ITEM_CUT, cut_whole_words

    assert cut_whole_words("invented words here", 11, ITEM_CUT) == "invented" + ITEM_CUT  # never "invented wo"
    assert cut_whole_words("short", 11, ITEM_CUT) == "short"
    assert "cut here" not in ITEM_CUT and ITEM_CUT.endswith("is in the email files.")


def test_a_cost_sentence_with_no_source_is_kept_beside_a_system_draft_for_the_engineer(query, monkeypatch):
    item, scope, _asked = query
    _answers(monkeypatch, {"answer": "1. Class 300 applies [S1].\n\nCOMPANY accepts the extra cost and an extension of time."})
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    draft = tq.get(item["id"], "u1", False, False)["drafts"][-1]
    assert draft["answer"] == "1. Class 300 applies [S1]."
    assert any(m.startswith(RC.COST_MARK) for m in json.loads(draft["unresolved_json"]))
