"""A query mail's signature, legal notices and quoted earlier mail are folded on the page and never read by the question finder; the
stored text is unchanged (lead-4 and the planner, 26 Nov 2026). Invented mail text only."""

from __future__ import annotations

from app.technical_queries import get, import_message, prepare_evidence
from app.technical_query_mail import message_itself, split_body

from .test_technical_queries import envelope, hold_contract, temp_storage  # noqa: F401 - the fixture is used by name

QUESTION = "Please confirm the invented coating thickness for the invented tank."
NOTICE = "DISCLAIMER: This e-mail and any attachments are confidential and intended only for the invented addressee."
SIGNED = f"{QUESTION}\n\nBest regards,\nInvented Person\nInvented Company\n\n{NOTICE}"


def test_the_message_itself_is_cut_at_its_signoff_and_the_rest_is_kept():
    main, rest = split_body(SIGNED)
    assert main == QUESTION and rest.startswith("Best regards") and NOTICE in rest


def test_quoted_and_forwarded_mail_stays_a_notice_paragraph_goes_and_the_finder_drops_only_header_lines():
    # review of update 12, N5: a forward's question sits below its forwarded-message header; it must stay
    forward = f"FYI\n\n-----Original Message-----\nFrom: Invented Sender\nSent: Monday\nTo: someone\nSubject: older\n\n{QUESTION}\n\n{SIGNED.split(QUESTION, 1)[1]}"
    main, rest = split_body(forward)
    assert QUESTION in main and NOTICE in rest and "Best regards" in rest
    finder = message_itself(forward)
    assert (
        QUESTION in finder
        and "From:" not in finder
        and "Original Message" not in finder
        and "DISCLAIMER" not in finder
    )
    notice = f"{QUESTION}\nThis message is confidential and intended only for the invented addressee."
    assert split_body(notice)[0] == QUESTION


def test_a_rule_line_above_the_question_does_not_hide_it():
    ruled = f"Dear all,\n______________________________\n{QUESTION}\n\nKind regards,\nInvented Person"
    assert QUESTION in split_body(ruled)[0] and QUESTION in message_itself(ruled)


def test_nothing_is_cut_when_there_is_no_marker_or_the_mail_would_be_folded_away_whole():
    assert split_body(QUESTION) == (QUESTION, "")
    assert split_body("Regards,\nInvented Person") == ("Regards,\nInvented Person", "")
    assert split_body(None) == ("", "")


def test_the_page_gets_the_message_itself_and_the_rest_apart_while_the_stored_body_is_whole():
    payload = envelope("fold-1")
    payload["body"] = SIGNED
    item, _ = import_message(payload, "u1", False, False)
    message = get(item["id"], "u1", False, False)["messages"][0]
    assert message["body"] == SIGNED  # stored whole
    assert message["body_main"] == QUESTION and NOTICE in message["body_folded"]


def test_the_question_finder_never_reads_the_signature_or_the_notice(monkeypatch):
    payload = envelope("fold-2")
    payload["body"] = SIGNED
    payload["question"] = None
    payload["attachments"] = []
    item, _ = import_message(payload, "u1", False, False)
    hold_contract("contract-1")
    seen = {}

    def fake_search(question, **kwargs):
        seen["question"] = question
        return {"hits": []}

    monkeypatch.setattr("app.search.search", fake_search)
    result = prepare_evidence(
        item["id"], frozenset({"contract-1"}), "u1", True, False, "u1"
    )
    assert result["extracted_question"] == QUESTION
    assert (
        "DISCLAIMER" not in seen["question"]
        and "regards" not in seen["question"].lower()
    )
    assert message_itself(SIGNED) == QUESTION


def test_a_paragraph_that_asks_is_never_taken_out_but_a_notice_with_its_own_requests_is():
    # recheck of update 12, R4
    important = f"Dear all,\nImportant: {QUESTION}\n\nBest regards,\nInvented Person"
    main, rest = split_body(important)
    assert (
        QUESTION in main
        and QUESTION in message_itself(important)
        and "Best regards" in rest
    )
    request = (
        "Important: please advise the invented flange rating for the invented line."
    )
    assert request in split_body(f"Dear all,\n{request}\n\nRegards,\nX")[0]
    legal = ("Dear all,\nPlease see the attached invented form.\n\nThis e-mail is confidential and intended only for the invented "
             "addressee. If you are not the intended recipient, please notify the sender and delete it.")  # fmt: skip
    main, rest = split_body(legal)
    assert (
        "confidential" in rest
        and "notify the sender" in rest
        and "attached invented form" in main
    )
