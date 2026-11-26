"""A static check of a contractor's PDF (and Word .docx) attachment for active content.

THIS IS NOT AN ANTIVIRUS SCAN, and nothing here says it is. It looks inside the PDF's own
objects (compressed ones included, because MuPDF resolves them) for features a question
document has no reason to carry: scripts, launch actions, embedded files, rich media and
form submission. A PDF that carries one is flagged; its text is then not pulled into a
proposed question automatically, and the screen says why. A clean result means only "none
of these features were found".

All PyMuPDF work goes through pdf_guard.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import pdf_guard

log = logging.getLogger(__name__)

#: PDF names that mean active or hidden content. /OpenAction alone is common and harmless, so it
#: is not listed: an action that runs a script or launches a program names one of these anyway.
ACTIVE_CONTENT = (
    "/JavaScript",
    "/JS",
    "/Launch",
    "/EmbeddedFile",
    "/RichMedia",
    "/SubmitForm",
    "/ImportData",
    "/GoToR",
    "/GoToE",
    "/XFA",
)
MAX_OBJECTS = 200_000
CLEAN = "static_check_clean"
FLAGGED = "static_check_flagged"
UNREADABLE = "static_check_unreadable"
NOT_SCANNED = "not_scanned"

LABELS = {
    CLEAN: "static check found no active content (not an antivirus scan)",
    FLAGGED: "static check found active content: text not used automatically",
    UNREADABLE: "could not be checked",
    NOT_SCANNED: "not checked",
}


#: A Word (.docx) part that carries active or hidden content: macros, ActiveX controls, embedded objects (an OLE object can run).
DOCX_ACTIVE_PARTS = ("word/vbaProject.bin", "word/activeX/", "word/embeddings/")
#: A relationship that fetches something from outside the file when it opens (a remote template, frame, sub-document or object).
DOCX_EXTERNAL_TYPES = ("attachedTemplate", "oleObject", "frame", "subDocument")
MAX_DOCX_ENTRIES = 5_000
_ZIP = b"PK\x03\x04"


def check_docx(data: bytes) -> dict[str, Any]:
    """The static check of a Word (.docx) file: flagged when it carries macros, ActiveX, an embedded object, a macro content type or a
    relationship that loads from outside; "could not be checked" when it is not a readable Word file. NOT an antivirus scan."""
    import io
    import re
    import zipfile

    findings: set[str] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = package.namelist()
            if "word/document.xml" not in names:
                return {"status": UNREADABLE, "findings": ["not_a_word_document"]}
            if (
                len(names) > MAX_DOCX_ENTRIES
            ):  # only part would be looked at: "could not be checked", never "clean"
                return {"status": UNREADABLE, "findings": ["too_many_parts"]}
            for name in names:
                findings.update(
                    part.rstrip("/")
                    for part in DOCX_ACTIVE_PARTS
                    if name == part or name.startswith(part)
                )
            if (
                "macroenabled"
                in package.read("[Content_Types].xml")
                .decode("utf-8", "replace")
                .lower()
            ):
                findings.add("macro_content_type")
            for name in (n for n in names if n.endswith(".rels")):
                rels = package.read(name).decode("utf-8", "replace")
                for rel in re.findall(r"<Relationship\b[^>]*>", rels):
                    if 'TargetMode="External"' in rel and any(
                        f'/{t}"' in rel for t in DOCX_EXTERNAL_TYPES
                    ):
                        findings.add("external_link")
    except Exception as exc:  # noqa: BLE001 - not a zip, encrypted (an encrypted Word file is not a zip), damaged
        log.info(
            "attachment check: Word file could not be checked (%s)", type(exc).__name__
        )
        return {"status": UNREADABLE, "findings": []}
    return {"status": FLAGGED if findings else CLEAN, "findings": sorted(findings)}


def check_before_library(source) -> dict[str, Any]:
    """The static check on a file BEFORE it enters the library: `source` is bytes or a binary file object (read from its start, then rewound).
    A Word (.docx) file (a zip by its first bytes) gets `check_docx`; anything else the PDF check. A flagged file is never ingested: it does
    not become a library document, is not indexed and cannot be searched."""
    import tempfile

    if isinstance(source, bytes | bytearray):
        head = bytes(source[:4])
    else:
        source.seek(0)
        head = source.read(4)
        source.seek(0)
    if head == _ZIP:
        data = bytes(source) if isinstance(source, bytes | bytearray) else source.read()
        if not isinstance(source, bytes | bytearray):
            source.seek(0)
        return check_docx(data)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        if isinstance(source, bytes | bytearray):
            tmp.write(source)
        else:
            source.seek(0)
            for block in iter(lambda: source.read(1024 * 1024), b""):
                tmp.write(block)
            source.seek(0)
        tmp.flush()
        return check_pdf(tmp.name)


def check_pdf(path: str | Path) -> dict[str, Any]:
    findings: set[str] = set()
    try:
        with pdf_guard.open_pdf(str(path)) as doc:
            if doc.is_encrypted:
                return {"status": UNREADABLE, "findings": ["encrypted"]}
            if doc.embfile_count():
                findings.add("/EmbeddedFile")
            if (
                doc.xref_length() > MAX_OBJECTS
            ):  # only part would be looked at: that is "could not be checked", never "clean"
                return {"status": UNREADABLE, "findings": ["too_many_objects"]}
            for xref in range(1, doc.xref_length()):
                try:
                    body = doc.xref_object(xref, compressed=False)
                except Exception as exc:  # noqa: BLE001 - one damaged object must not hide the rest
                    log.debug(
                        "attachment check: object %s unreadable (%s)",
                        xref,
                        type(exc).__name__,
                    )
                    continue
                for name in ACTIVE_CONTENT:
                    # a name token ends at a delimiter, so /JS does not match /JSON
                    index = body.find(name)
                    while index >= 0:
                        end = index + len(name)
                        if end >= len(body) or body[end] in " \t\r\n/<>[]()%":
                            findings.add(name)
                            break
                        index = body.find(name, end)
    except Exception as exc:  # noqa: BLE001 - not a PDF, damaged, or unreadable
        log.info("attachment check: file could not be checked (%s)", type(exc).__name__)
        return {"status": UNREADABLE, "findings": []}
    return {"status": FLAGGED if findings else CLEAN, "findings": sorted(findings)}
