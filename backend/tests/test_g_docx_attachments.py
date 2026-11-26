"""Word (.docx) attachments of a technical query are read, after the same kind of static "no active content" check the PDFs get
(lead-4, 26 Nov 2026: 22 Word attachments of the first import were not read). Invented files built in memory; no Gmail, no network."""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

from app import attachment_safety as S

TYPES = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
DOC = '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Invented answer.</w:t></w:r></w:p></w:body></w:document>'


def docx(extra: dict[str, str] | None = None, types: str = TYPES) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("word/document.xml", DOC)
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return out.getvalue()


def test_a_plain_word_file_is_clean():
    assert S.check_before_library(docx())["status"] == S.CLEAN


def test_macros_activex_embedded_objects_and_macro_types_are_flagged():
    assert S.check_before_library(docx({"word/vbaProject.bin": "x"}))["findings"] == [
        "word/vbaProject.bin"
    ]
    assert (
        S.check_before_library(docx({"word/activeX/activeX1.xml": "x"}))["status"]
        == S.FLAGGED
    )
    assert (
        S.check_before_library(docx({"word/embeddings/oleObject1.bin": "x"}))["status"]
        == S.FLAGGED
    )
    macro_types = TYPES.replace(
        "application/xml", "application/vnd.ms-word.document.macroEnabled.main+xml"
    )
    assert (
        "macro_content_type"
        in S.check_before_library(docx(types=macro_types))["findings"]
    )


def test_a_relationship_that_loads_from_outside_is_flagged():
    rels = ('<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate"'
            ' Target="http://invented.example/t.dotm" TargetMode="External"/></Relationships>')  # fmt: skip
    assert S.check_before_library(docx({"word/_rels/settings.xml.rels": rels}))[
        "findings"
    ] == ["external_link"]
    link = rels.replace(
        "attachedTemplate", "hyperlink"
    )  # an ordinary web link in the text is not active content
    assert (
        S.check_before_library(docx({"word/_rels/document.xml.rels": link}))["status"]
        == S.CLEAN
    )


def test_a_zip_that_is_not_word_or_is_damaged_could_not_be_checked():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/workbook.xml", "x")
    assert S.check_before_library(out.getvalue())["status"] == S.UNREADABLE
    assert S.check_before_library(b"PK\x03\x04damaged")["status"] == S.UNREADABLE


def test_a_file_object_is_rewound_after_the_word_check():
    f = io.BytesIO(docx())
    S.check_before_library(f)
    assert f.tell() == 0


def test_the_mailbox_import_reads_a_word_attachment_but_not_a_picture(monkeypatch):
    from app import gmail_worker as W

    checked, ingested = [], []
    monkeypatch.setattr(
        W.attachment_safety,
        "check_before_library",
        lambda content: (
            checked.append(content[:2]) or {"status": S.CLEAN, "findings": []}
        ),
    )

    class Stop(Exception):
        pass

    def ingest(stream, filename):
        ingested.append(filename)
        raise Stop  # stop right after the hand-over: what matters is which files reach the library

    monkeypatch.setattr(W.upload_mod, "ingest", ingest)
    monkeypatch.setattr(W, "_store_raw_email", lambda raw: ("h", "ref"))
    attachments = [{"filename": "logo.png", "attachment_id": "a1", "size_bytes": 2, "media_type": "image/png"},
                   {"filename": "answer.docx", "attachment_id": "a2", "size_bytes": 2, "media_type": "application/vnd.openxmlformats"}]  # fmt: skip
    message = SimpleNamespace(provider_message_id="m1", thread_id="t1", from_address="a@vendor.example", to_addresses=[], cc_addresses=[],
                              subject="PRJ-INV-TQ-7 - Invented", body="b", received_at="2026-11-20T10:00:00Z", attachments=attachments,
                              label_ids=["L1"])  # fmt: skip
    stored = {
        "messages": [
            {
                "provider_message_id": "m1",
                "attachments": [
                    {"id": "s1", "document_id": None},
                    {"id": "s2", "document_id": None},
                ],
            }
        ]
    }
    monkeypatch.setattr(W, "import_message", lambda *a, **k: (stored, False))
    client = SimpleNamespace(
        message=lambda mid: message,
        raw_message=lambda mid: b"raw",
        attachment=lambda mid, aid: b"PK",
    )
    try:
        W._process_message(
            client,
            "m1",
            mailbox_id="mb",
            actor_user_id="u1",
            admin_role=None,
            label_id="L1",
            mailbox_address="box@example.test",
        )
    except Stop:
        pass
    assert ingested == [
        "answer.docx"
    ]  # the picture is never handed over; the Word file is, after the check
    assert checked == [b"PK"]
