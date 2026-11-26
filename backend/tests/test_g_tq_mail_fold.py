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


def test_quoted_earlier_mail_and_a_notice_paragraph_start_the_rest():
    quoted = f"{QUESTION}\nOn Mon, 1 Jan 2026 at 10:00, Invented Sender <a@example.test> wrote:\n> older text"
    assert split_body(quoted)[0] == QUESTION
    header = (
        f"{QUESTION}\nFrom: Invented Sender\nSent: Monday\nTo: someone\nSubject: older"
    )
    assert split_body(header)[0] == QUESTION
    notice = f"{QUESTION}\nThis message is confidential and intended only for the invented addressee."
    assert split_body(notice)[0] == QUESTION


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
