"""'Question in the email' by the CURRENT rules (lead-4, 26 Nov 2026, owner fault on update 12): a forwarded mail whose own text only
points to the attached form showed its header block, a 43-name Cc list, a classification line, a signature and a notice. The question
is recomputed from the stored mail at every display, a long To/Cc list is folded to one count line, and pictures inside stored mail are
marked as signature pictures from the stored original. Invented content only."""

from __future__ import annotations

from email.message import EmailMessage

from app import db, gmail_import_jobs
from app.config import settings
from app.technical_queries import get, import_message
from app.technical_query_mail import email_question, page_body

from .test_technical_queries import (
    temp_storage,  # noqa: F401 - the fixture is used by name
)

PEOPLE = [f"Invented Person {n} <person{n}@invented.example>" for n in range(43)]
CC_BLOCK = "Cc: " + ";\n".join("; ".join(PEOPLE[i : i + 4]) for i in range(0, 40, 4))
HEADER = (
    "From: Invented Sender <sender@invented.example>\nSent: Monday, 2 November 2026 09:00\n"
    f"To: {PEOPLE[40]}; {PEOPLE[41]}; {PEOPLE[42]}\n{CC_BLOCK}\nSubject: TQ-2 invented header question\n"
    "Classification: Internal\n"
)
NOTICE = "DISCLAIMER: This e-mail is confidential and intended only for the addressee. If received in error, notify the sender."
COVER = (
    "-----Original Message-----\n"
    + HEADER
    + "\nDear Sir,\n\nPlease find attached TQ-2 for your review and response.\n\n"
    "Best Regards,\nInvented Engineer\nInvented Company\n\n" + NOTICE
)


def _gmail_query(body: str, stored: str | None) -> dict:
    item, _ = import_message(
        {
            "provider": "gmail", "mailbox_id": "mb", "provider_message_id": "m-1", "provider_thread_id": "t-1",
            "from_address": "sender@invented.example", "to_addresses": [p.split("<")[1][:-1] for p in PEOPLE[:3]],
            "cc_addresses": [p.split("<")[1][:-1] for p in PEOPLE[3:]], "subject": "FW: TQ-2 invented", "body": body,
            "attachments": [{"filename": "tq-form-2.docx", "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size_bytes": 10}],
        },
        "u1", False, True,
    )  # fmt: skip
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('form','tq-form-2.docx',?,1,'f','ready','x')",
            ("b" * 64,),
        )
        conn.execute("UPDATE query_attachments SET document_id='form'")
        # what the first import stored by its older rules
        conn.execute("UPDATE technical_queries SET extracted_question=?", (stored,))
    return get(item["id"], "u1", True, True)


def test_a_cover_note_forward_shows_no_header_list_signature_or_notice_and_names_the_form():
    query = _gmail_query(
        COVER,
        "\n".join(HEADER.splitlines()[3:])
        + "\nBest Regards,\nInvented Engineer\n"
        + NOTICE,
    )
    shown = query["extracted_question_main"]
    assert shown == "", (
        shown
    )  # the mail itself asks nothing: the old stored copy is never shown
    assert query["email_question_note"] == (
        "No question in the email text. The question is in the attachment: tq-form-2.docx; "
        "Prepare evidence to get a proposed question from it."
    )
    body = query["messages"][0]["body_main"]
    assert (
        "To/Cc: 4" in body and "person7@invented.example" not in body
    )  # the forward's Cc list is one count line
    assert (
        "person7@invented.example" in query["messages"][0]["body_folded"]
    )  # kept behind "show"


def test_a_forward_with_a_real_question_keeps_only_the_question_text():
    mail = (
        "-----Original Message-----\n"
        + HEADER
        + "\nDear Sir,\nPlease confirm the invented flange rating for the header?\n\nRegards,\nInvented\n\n"
        + NOTICE
    )
    got = email_question(mail)
    assert "Please confirm the invented flange rating for the header?" in got
    for leak in (
        "@",
        "Classification",
        "Subject:",
        "Invented Person",
        "DISCLAIMER",
        "Regards",
    ):
        assert leak not in got, leak


def test_a_short_to_list_is_shown_and_a_long_one_is_counted():
    short, _ = page_body("To: a@invented.example; b@invented.example\n\nHello?")
    assert "a@invented.example" in short
    long_main, long_folded = page_body(f"To: {'; '.join(PEOPLE[:10])}\n\nHello?")
    assert "To/Cc: 10 people" in long_main and "person9@invented.example" in long_folded


def _stored_mail(path) -> None:
    mail = EmailMessage()
    mail["Subject"] = "invented"
    mail.set_content("See the logo.")
    mail.add_related(
        b"GIF89a-invented",
        maintype="image",
        subtype="gif",
        cid="<logo1>",
        filename="logo1.gif",
        disposition="inline",
    )
    mail.add_attachment(
        b"GIF89a-photo", maintype="image", subtype="gif", filename="site-photo.gif"
    )
    path.write_bytes(mail.as_bytes())


def test_pictures_inside_stored_mail_are_marked_from_the_stored_original():
    folder = settings.data_dir / "technical_query_mail"
    folder.mkdir()
    _stored_mail(folder / "invented.eml")
    import_message(
        {
            "provider": "gmail", "mailbox_id": "mb", "provider_message_id": "m-2", "from_address": "sender@invented.example",
            "to_addresses": [], "cc_addresses": [], "subject": "TQ-3 invented", "body": "Please confirm?",
            "raw_storage_ref": str(folder / "invented.eml"),
            "attachments": [{"filename": "logo1.gif", "media_type": "image/gif", "size_bytes": 15}, {"filename": "site-photo.gif", "media_type": "image/gif", "size_bytes": 12}],
        },
        "u1", False, True,
    )  # fmt: skip
    assert gmail_import_jobs.mark_stored_inline_pictures("mb") == 1
    with db.connect() as conn:
        marked = dict(
            conn.execute("SELECT filename, inline_picture FROM query_attachments")
        )
    assert marked == {
        "logo1.gif": 1,
        "site-photo.gif": 0,
    }  # a picture sent as an attachment stays an attachment
    assert gmail_import_jobs.mark_stored_inline_pictures("mb") == 0  # safe to run again


def test_the_form_question_section_and_why_nothing_was_proposed(monkeypatch):
    # lead-4, 26 Nov 2026 (live shapes, invented words): a "Question" heading, a references block, requests with no question mark
    from app import technical_query_questions as Q

    page = (
        "Technical Query\nRev. 01\nQuestion\nReferences:\n1.\nInvented spec XS-100 clause 4.2\n\n"
        "The invented guard is shown in invented steel.\nConfirm that invented aluminium may be used.\n\nApproved\nName: Invented"
    )
    got = Q.form_question([{"text": page, "filename": "f.docx", "page": 1}])
    assert (
        got
        == "The invented guard is shown in invented steel. Confirm that invented aluminium may be used."
    )
    cfc = "Comment For Clarification (CFC)\nRev. 01\nDate:\nContractor Clarification Request Invented\nInvented point to clarify.\nApproved"
    assert Q.form_question([{"text": cfc}]) == "Invented point to clarify."
    assert (
        Q.form_question([{"text": "Technical Query\nInvented title only\nApproved"}])
        == ""
    )  # a title is not a question field
    monkeypatch.setattr(Q, "_ask", lambda text: [])
    assert Q.from_pages([{"text": page}]) == ([], Q.NONE_FOUND)
    monkeypatch.setattr(Q, "_ask", lambda text: ["A question the page does not hold?"])
    assert Q.from_pages([{"text": page}]) == ([], Q.NOT_ON_PAGE)


def test_a_line_every_mail_carries_and_a_link_s_question_mark_ask_nothing():
    from app import technical_query_mail as M

    footer = (
        "Please be aware that this invented mailbox is watched by the invented team."
    )
    bodies = tuple(f"Invented message {n}.\n\n{footer}" for n in range(6))
    common = M._repeated(bodies)
    assert M._norm(footer) in common
    mail = f"Dear All,\n\nPlease, find attached our TQ: TQ-00099 - Invented title\n\n<https://invented.example/?a=1>\n\n{footer}"
    assert M.email_question(mail, common) == ""
    assert (
        M._repeated(bodies[:4]) == frozenset()
    )  # too few messages to call anything boilerplate
    real = f"Dear All,\nPlease confirm the invented flange rating.\nInvented Name\n+00 000 000\n\n{footer}"
    assert (
        M.email_question(real, common)
        == "Please confirm the invented flange rating.\nInvented Name\n+00 000 000"
    )


def test_a_template_line_with_an_address_and_a_long_block_are_not_the_question():
    # F's end-to-end test on update 13 (shapes; invented words): the shown question was a third of the mail, with template address lines
    from app import technical_query_mail as M

    template = (
        "For invented queries write to invented.desk@owner-invented.example please."
    )
    long_block = "\n".join(
        f"Invented line {n} of a forwarded mail, kept for the record."
        for n in range(20)
    )
    mail = f"Dear All,\n\n{template}\n\nPlease confirm the invented flange rating.\n\n{long_block}"
    got = M.email_question(mail)
    assert "@" not in got and len(got) <= M.QUESTION_CAP
    assert "Please confirm the invented flange rating." in got
    asking_block = "\n".join(
        f"Please keep invented line {n} of a forwarded mail in mind." for n in range(20)
    )
    assert (
        M.email_question(f"Dear All,\n\n{asking_block}") == ""
    )  # longer than a question even line by line: none


def test_a_reference_number_line_is_never_the_form_s_question():
    from app import technical_query_questions as Q

    form = "Technical Query No: 123456789012\nRev. 01\nInvented title\nApproved"
    assert Q.form_question([{"text": form}]) == ""
    assert Q.form_question([{"text": "Question: 1234-5678-9012\nApproved"}]) == ""


def test_a_question_with_semicolons_and_a_cover_line_that_asks_stay_question_text():
    # review of update 14, R2 (invented words)
    from app import technical_query_mail as M

    asks = (
        "Please confirm: (a) invented size; (b) invented rating; (c) invented material?"
    )
    assert asks in M.email_question(f"Dear All,\n\n{asks}")
    pointer = "We submit the attached TQ-00077; please confirm the invented rating."
    assert pointer in M.email_question(f"Dear All,\n\n{pointer}")
    assert (
        M.email_question(
            "Dear All,\n\nWe submit the attached TQ-00077 for your records."
        )
        == ""
    )
    assert M._address_list(
        "Invented One; Invented Two; Invented Three"
    )  # a list of people is still a list of people
