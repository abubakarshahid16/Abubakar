"""A REALISTIC technical-query mailbox of INVENTED content (owner's standing rule T1, 26 Nov 2026: the first stand-in was 35 plain messages,
the real mail looked very different). Every name, number, company, address and sentence below is invented; only the SHAPES are real:

- a TQ message whose question sits in a Word (.docx) query form, with its PDF twin, five inline signature pictures (cid) and a legal
  notice in two languages;
- a forward of a forward of that TQ from another person (joins the same query);
- the company's own reply in the same thread (sent from the mailbox);
- a CFC message;
- the "log" mail with no TQ or CFC number;
- a message with one broken (corrupt) PDF;
- a message with a Word file that carries a macro.

`MAILBOX` is the connected mailbox; `FakeGmail(messages())` answers like the Gmail client (`list_message_ids`, `message`, `raw_message`,
`attachment`). Pure: builds bytes in memory, no network.
"""

from __future__ import annotations

import base64
import io
import zipfile

MAILBOX = "tq-box@owner-invented.example"
LABEL = "Label_TQ"
PROJECT, CONTRACTOR, OWNER = "54321", "INVCO", "OWNCO"
TQ_NUMBER = f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00011"
CFC_NUMBER = f"{PROJECT}-{CONTRACTOR}-{OWNER}-CFC-00004"
#: The question the Word form asks (the page and the PDF twin carry the same words).
FORM_QUESTION = (
    "What is the invented design pressure of the invented cooling water header?"
)
CFC_QUESTION = "Which invented drawing governs the invented valve pit depth?"
#: A forwarded query: its question sits only below the forwarded-message header (review of update 12, N5).
FORWARDED_QUESTION = "Is the invented spare impeller included in the invented scope?"
#: A query with a rule line above its question (review of update 12, N5).
RULED_QUESTION = "May the invented flange rating be lowered to invented class 150?"
#: A query whose question starts "Important:" (recheck of update 12, R4: it is not a notice).
IMPORTANT_QUESTION = "Can the invented bolt material be changed to invented grade B7M?"
#: A clause of the held (invented) contract that answers the TQ.
#: The live shape of 26 Nov 2026 (lead-4's walk on update 12): the mail is an introduction that only points to the attached form; the
#: question stands only in the form's own field.
INTRO_FORM_QUESTION = (
    "Confirm the invented grout thickness under the invented pump base plate."
)
INTRO_BODY = (
    "Classification: Internal\n\nDear All,\n\nPlease find attached our TQ-00018 - MEC_Invented base plate grouting for your review.\n\n"
    "[cid:image001.png@01DB0000.00000000]\nThanks & Best Regards,\nInvented Engineer\nInvented Contractor Company"
)
CONTRACT_CLAUSE = "The invented cooling water header shall be designed for 12 bar(g)."

NOTICE = (
    "DISCLAIMER: This e-mail and any attachments are confidential and intended only for the invented addressee. "
    "If you received it by mistake, delete it.\n"
    "HAFTUNGSAUSSCHLUSS: Diese erfundene E-Mail ist vertraulich und nur fuer den erfundenen Empfaenger bestimmt."
)
#: A footer every mail of the mailbox carries (live shape, 26 Nov 2026): it holds "please" but asks nothing; repeated, it is boilerplate.
FOOTER = "Please be aware that this invented mailbox is watched and the safety of our invented systems is in our hands."
SIGNATURE = (
    "Best regards,\nInvented Engineer\nInvented Contractor Company\nInvented Street 1, Invented City\n\n"
    + FOOTER
)
#: The live shape of lead-4's walk on update 13: a forward whose own words only introduce the form ("Please, find attached our TQ: ..."),
#: a link wrapper holding "?", the footer; the form holds a "Question" heading, a references block, and requests with no question mark.
LIVE_FORM_REQUEST = "Confirm that the invented coupling guard may be made of invented aluminium instead."
LIVE_BODY = (
    "Subject: FW: TQ-00019 invented\n________________________________\nFrom: Invented Sender <sender13@contractor-invented.example>\n"
    "Sent: Monday, 2 November 2026 09:00\nTo: Invented Desk <desk@owner-invented.example>\n"
    "Cc: Invented A <a@contractor-invented.example>; Invented B <b@contractor-invented.example>\n\nDear All,\n\n"
    "Please, find attached our TQ: TQ-00019 - MEC_Invented pump coupling guard\n\n<https://invented-link.example/?u=1&d=2>\n"
    "Thanks & Best Regards,\nInvented Engineer\n\n" + FOOTER
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def docx(
    paragraphs: list[str], *, macro: bool = False, header_field: bool = False
) -> bytes:
    """A small valid Word file (python-docx and the app's Word reader open it); `macro` adds a VBA part, as a macro file carries."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>",
        )
        if macro:
            z.writestr("word/vbaProject.bin", b"invented macro part")
        if header_field:  # a field that fetches from outside, split over two runs, in a HEADER (recheck of update 12, R1 and R2)
            z.writestr(
                "word/header1.xml",
                '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p>'
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> INCLUDE</w:instrText></w:r>'
                '<w:r><w:instrText>PICTURE "http://invented.example/logo.png"</w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>',
            )
    return out.getvalue()


def pdf(lines: list[str]) -> bytes:
    """A small valid one-page PDF with a text layer (built by hand: no PDF library is opened here)."""
    text = " ".join(f"({line}) Tj T*" for line in lines)
    stream = f"BT /F1 11 Tf 14 TL 50 780 Td {text} ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=="
)


class Message:
    """One invented Gmail message: its payload as the Gmail API gives it, and its attachments' bytes by attachment id."""

    def __init__(
        self,
        mid,
        thread,
        sender,
        subject,
        body,
        attachments=(),
        inline_pictures=0,
        when=1764000000000,
    ):
        self.mid, self.thread, self.files = mid, thread, {}
        parts = [{"mimeType": "text/plain", "body": {"data": _b64(body.encode())}}]
        for n in range(
            inline_pictures
        ):  # signature logos shown inside the body (cid), never sent as attachments
            aid = f"{mid}-cid-{n}"
            self.files[aid] = PNG
            parts.append(
                {
                    "mimeType": "image/png",
                    "filename": f"image00{n + 1}.png",
                    "body": {"attachmentId": aid, "size": len(PNG)},
                    "headers": [
                        {"name": "Content-ID", "value": f"<image00{n + 1}@invented>"},
                        {"name": "Content-Disposition", "value": "inline"},
                    ],
                }
            )
        related = {"mimeType": "multipart/related", "parts": parts}
        attached = []
        for n, (filename, mime, data) in enumerate(attachments):
            aid = f"{mid}-att-{n}"
            self.files[aid] = data
            attached.append(
                {
                    "mimeType": mime,
                    "filename": filename,
                    "body": {"attachmentId": aid, "size": len(data)},
                    "headers": [
                        {
                            "name": "Content-Disposition",
                            "value": f'attachment; filename="{filename}"',
                        }
                    ],
                }
            )
        self.payload = {
            "id": mid,
            "threadId": thread,
            "labelIds": [LABEL],
            "internalDate": str(when),
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [related, *attached],
                "headers": [
                    {"name": "From", "value": sender},
                    {"name": "To", "value": MAILBOX},
                    {"name": "Subject", "value": subject},
                ],
            },
        }


def messages() -> list[Message]:
    """The mailbox, newest first (as Gmail lists it): our reply comes before the question it answers."""
    mail = _mail()
    for n, m in enumerate(mail):  # each one minute older than the one listed before it
        m.payload["internalDate"] = str(1764000000000 - n * 60000)
    return mail


def _mail() -> list[Message]:
    form = [
        f"Technical query {TQ_NUMBER}",
        "Discipline: PRO",
        f"Question: {FORM_QUESTION}",
        "Requested reply date: invented",
    ]
    return [
        Message(
            "m13-live",
            "t13",
            "Invented Coordinator <coordinator@contractor-invented.example>",
            f"FW: {PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00019 - MEC_Invented pump coupling guard",
            LIVE_BODY,
            [
                (
                    "tq-form-19.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    docx(
                        [
                            "Technical Query",
                            "Rev. 01",
                            "Question",
                            "References:",
                            "1.",
                            "Invented spec XS-100 clause 4.2",
                            "",
                            "The invented coupling guard is shown in invented steel.",
                            LIVE_FORM_REQUEST,
                            "Approved",
                            "Name: Invented",
                        ]
                    ),
                )
            ],
        ),
        Message(
            "m12-intro",
            "t12",
            "Invented Sender <sender12@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00018 - MEC_Invented base plate grouting",
            INTRO_BODY,
            [
                (
                    "tq-form-18.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    docx(
                        [
                            "Technical Query TQ-00018",
                            "Description of query:",
                            INTRO_FORM_QUESTION,
                            "Contractor proposal:",
                            "Invented.",
                        ]
                    ),
                )
            ],
            inline_pictures=1,
        ),
        Message(
            "m11-header-field",
            "t11",
            "Invented Sender <sender11@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00017 - ELE_Invented cable tray",
            "Please see the attached form.\n\n" + SIGNATURE,
            [
                (
                    "tq-form-17.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    docx(["Invented?"], header_field=True),
                )
            ],
        ),
        Message(
            "m10-important",
            "t10",
            "Invented Sender <sender10@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00016 - MEC_Invented bolt material",
            f"Dear all,\nImportant: {IMPORTANT_QUESTION}\n\nKind regards,\nInvented Sender\n\n{NOTICE}",
        ),
        Message(
            "m9-ruled",
            "t9",
            "Invented Sender <sender9@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00015 - MEC_Invented flange rating",
            f"Dear all,\n______________________________\n{RULED_QUESTION}\n\nKind regards,\nInvented Sender\n\n{NOTICE}",
        ),
        Message(
            "m8-forwarded",
            "t8",
            "Invented Coordinator <coordinator@contractor-invented.example>",
            f"FW: {PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00014 - MEC_Invented spare impeller",
            "FYI\n\n-----Original Message-----\nFrom: Invented Engineer\nSent: invented day\nTo: invented desk\n"
            f"Subject: {PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00014\n\nDear Sir,\n{FORWARDED_QUESTION}\n\n{SIGNATURE}\n\n{NOTICE}",
        ),
        Message(
            "m7-macro",
            "t7",
            "Invented Sender <sender7@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00013 - MET_Invented macro form",
            "Please see the attached form.\n\n" + SIGNATURE,
            [
                (
                    "query-form-13.docm.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    docx(["Invented?"], macro=True),
                )
            ],
        ),
        Message(
            "m6-broken",
            "t6",
            "Invented Sender <sender6@contractor-invented.example>",
            f"{PROJECT}-{CONTRACTOR}-{OWNER}-TQ-00012 - CIV_Invented broken file",
            "The attached drawing list applies.\n\n" + SIGNATURE,
            [
                (
                    "drawing-list-12.pdf",
                    "application/pdf",
                    b"%PDF-1.4\n%broken invented bytes",
                )
            ],
        ),
        Message(
            "m5-log",
            "t5",
            "Invented Log <log@contractor-invented.example>",
            "Weekly invented query log 01.02.03",
            "Attached is the invented weekly log.\n\n" + SIGNATURE,
        ),
        Message(
            "m4-cfc",
            "t4",
            "Invented Sender <sender4@contractor-invented.example>",
            f"{CFC_NUMBER} - CIV_Invented valve pit depth",
            f"Dear all,\n{CFC_QUESTION}\n\n{SIGNATURE}\n\n{NOTICE}",
            inline_pictures=2,
        ),
        Message(
            "m3-ours",
            "t1",
            f"Owner Desk <{MAILBOX}>",
            f"RE: {TQ_NUMBER} - PRO_Invented cooling water header",
            "Dear Invented Engineer,\nWe are reviewing the query and will reply.\n\nKind regards,\nInvented Owner Desk",
        ),
        Message(
            "m2-fwfw",
            "t2",
            "Another Person <another@contractor-invented.example>",
            f"FW: FW: {TQ_NUMBER} - PRO_Invented cooling water header",
            "Forwarding for your information.\n\n-----Original Message-----\nFrom: Invented Engineer\nSent: invented day\n"
            + SIGNATURE,
        ),
        Message(
            "m1-tq",
            "t1",
            "Invented Engineer <engineer@contractor-invented.example>",
            f"{TQ_NUMBER} - PRO_Invented cooling water header",
            f"Dear Sir,\nPlease find the attached technical query form.\n\n{SIGNATURE}\n\n{NOTICE}",
            [
                (
                    "tq-form-11.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    docx(form),
                ),
                ("tq-form-11.pdf", "application/pdf", pdf(form)),
            ],
            inline_pictures=5,
        ),
    ]


class FakeGmail:
    """Answers like `gmail_client.GmailApiClient` for the invented mailbox."""

    def __init__(self, mail: list[Message]):
        self.mail = {m.mid: m for m in mail}

    def list_message_ids(self, label_id: str, *, limit: int = 5000) -> list[str]:
        return [
            mid for mid, m in self.mail.items() if label_id in m.payload["labelIds"]
        ]

    def message(self, message_id: str):
        from app.gmail_client import normalize_message

        return normalize_message(self.mail[message_id].payload)

    def raw_message(self, message_id: str) -> bytes:
        return f"Message-ID: <{message_id}@invented>\r\n\r\ninvented raw".encode()

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self.mail[message_id].files[attachment_id]
