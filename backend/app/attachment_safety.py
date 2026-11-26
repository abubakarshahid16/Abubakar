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
#: Relationship TYPES (the last part of the type address, any letter case) that bring active or outside content, whatever their
#: target mode or quoting: macros, embedded objects and packages, controls, a template, frame, sub-document or alternative chunk.
DOCX_ACTIVE_TYPES = frozenset(
    t.casefold()
    for t in (
        "vbaProject", "wordVbaData", "oleObject", "package", "control", "activeXControl", "activeXControlBinary",
        "attachedTemplate", "frame", "subDocument", "aFChunk", "keyMapCustomizations",
    )
)  # fmt: skip
#: Content types that name active content.
DOCX_ACTIVE_CONTENT_TYPES = ("vbaproject", "activex", "oleobject", "macroenabled")
#: Field codes that fetch from outside or run something when the document is opened or updated.
DOCX_FETCHING_FIELDS = (
    "DDEAUTO",
    "DDE ",
    "INCLUDETEXT",
    "INCLUDEPICTURE",
    "IMPORT ",
    "LINK ",
)
MAX_DOCX_ENTRIES = 5_000
#: Unpacked size limits: a part or a whole file above them is "could not be checked" (a zip bomb is never read whole).
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
MAX_DOCX_UNPACKED_BYTES = 300 * 1024 * 1024
_ZIP = b"PK\x03\x04"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(package, name: str):
    """One XML part parsed safely (defusedxml: no entities, no DTD); a part too large or not well-formed raises (-> not checked)."""
    from defusedxml import ElementTree as SafeXML

    if package.getinfo(name).file_size > MAX_DOCX_XML_BYTES:
        raise ValueError("part too large")
    return SafeXML.fromstring(package.read(name))


def _field_code(element) -> str:
    """The code of a Word field: the text of an instrText element or the instr attribute of a simple field ("" for anything else)."""
    if _local(element.tag) == "instrText":
        return element.text or ""
    if _local(element.tag) == "fldSimple":
        return next((v for k, v in element.attrib.items() if _local(k) == "instr"), "")
    return ""


def _docx_findings(package) -> set[str] | str:
    """The findings of an open Word package, or the reason it cannot be checked."""
    infos = package.infolist()
    names = {
        i.filename.casefold(): i.filename for i in infos
    }  # package part names are not case-sensitive
    if "word/document.xml" not in names:
        return "not_a_word_document"
    if (
        len(infos) > MAX_DOCX_ENTRIES
        or sum(i.file_size for i in infos) > MAX_DOCX_UNPACKED_BYTES
    ):
        return "too_large"  # only part would be looked at: never "clean"
    if "[content_types].xml" not in names:
        return "no_content_types"
    findings: set[str] = set()
    for name in names:
        if name.endswith(
            ".bin"
        ):  # a binary part (macros, an OLE object, ActiveX data): never in a plain document
            findings.add(
                "macro"
                if name.rsplit("/", 1)[-1] == "vbaproject.bin"
                else "binary_part"
            )
        if "/activex/" in f"/{name}":
            findings.add("activex")
        if "/embeddings/" in f"/{name}":
            findings.add("embedded_object")
    for element in _xml(package, names["[content_types].xml"]).iter():
        kind = (element.get("ContentType") or "").casefold()
        findings.update(
            f"content_type_{t}" for t in DOCX_ACTIVE_CONTENT_TYPES if t in kind
        )
    for name in (n for n in names if n.endswith(".rels")):
        for rel in _xml(package, names[name]).iter():
            if _local(rel.tag) != "Relationship":
                continue
            kind = (rel.get("Type") or "").rstrip("/").rsplit("/", 1)[-1].casefold()
            if kind in DOCX_ACTIVE_TYPES:
                findings.add(f"relationship_{kind}")
            elif (
                rel.get("TargetMode") or ""
            ).casefold() == "external" and kind != "hyperlink":
                findings.add(
                    "external_link"
                )  # anything fetched from outside on opening: a remote picture, template, data
    instr = " ".join(
        _field_code(e) for e in _xml(package, names["word/document.xml"]).iter()
    ).upper()
    findings.update(
        "fetching_field"
        for f in DOCX_FETCHING_FIELDS
        if f.strip() and f in f" {instr} "
    )
    return findings


def check_docx(data: bytes) -> dict[str, Any]:
    """The static check of a Word (.docx) file, by an XML parser over its parts: flagged for macros, binary parts, ActiveX, embedded
    objects or packages, an active content type, an active relationship type (whatever its target mode or quoting), any relationship
    to the outside except a hyperlink, or a field that fetches; "could not be checked" when a part cannot be parsed or the file is not
    a readable Word file or is too large. NOT an antivirus scan."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            found = _docx_findings(package)
    except Exception as exc:  # noqa: BLE001 - not a zip, encrypted, damaged, a part not parsable: logged by class, never "clean"
        log.info(
            "attachment check: Word file could not be checked (%s)", type(exc).__name__
        )
        return {"status": UNREADABLE, "findings": []}
    if isinstance(found, str):
        return {"status": UNREADABLE, "findings": [found]}
    return {"status": FLAGGED if found else CLEAN, "findings": sorted(found)}


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
