"""A query page shows each paragraph of the thread once (lead-4, 26 Nov 2026: legal notices and the quoted earlier mail were shown in full
up to five times on one page). Invented mails only."""

from __future__ import annotations

from app.technical_query_mail import REPEAT_CHARS, page_bodies, split_body

NOTICE = (
    "The information contained in this message is meant only for the intended recipient and is confidential. If you received it by "
    "mistake, tell the sender and remove it."
)
ASK = "Please confirm the invented flange rating for the invented line before the next issue of the invented sheet?"
FIRST = f"Dear team,\n\n{ASK}\n\nBest regards,\nA. Sender\n\n{NOTICE}"
REPLY = (
    "We will answer next week, the invented calculation is with the checker now and goes out soon.\n\n"
    f"From: someone@invented.example\nSent: Monday\n\n> {ASK}\n\n{NOTICE}"
)


def test_the_second_shape_of_legal_notice_is_folded_and_a_question_never_is():
    main, folded = split_body(FIRST)
    assert NOTICE not in main and NOTICE in folded and ASK in main
    asks_and_names = "Please confirm the intended recipient of the confidential invented report?"
    assert split_body(f"Hello,\n\n{asks_and_names}\n\nRegards,\nB")[0].count(asks_and_names) == 1


def test_an_earlier_mail_quoted_in_a_reply_is_shown_once_with_a_mark_and_the_full_text_folded():
    (first_main, _), (reply_main, reply_folded) = page_bodies([FIRST, REPLY])
    assert ASK in first_main
    assert ASK not in reply_main and ASK in reply_folded  # shown above, so folded here: nothing is cut without the mark
    assert "1 paragraph of earlier mail already shown above on this page: under show" in reply_main
    assert reply_main.startswith("We will answer next week")  # the reply's own words stay
    assert NOTICE not in reply_main


def test_short_lines_and_a_page_of_one_mail_are_left_as_they_are():
    short = "Thanks, noted."
    assert len(short) < REPEAT_CHARS
    (one, _), (two, _) = page_bodies([f"{short}\n\nA first invented mail.", f"{short}\n\nA second invented mail."])
    assert one.count(short) == 1 and two.count(short) == 1
    assert page_bodies([FIRST]) == [page_bodies([FIRST])[0]]
    assert page_bodies([]) == []
