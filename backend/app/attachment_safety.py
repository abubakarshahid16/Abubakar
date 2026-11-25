"""A static check of a contractor's PDF attachment for active content.

THIS IS NOT AN ANTIVIRUS SCAN, and nothing here says it is. It looks inside the PDF's own
objects (compressed ones included, because MuPDF resolves them) for features a question
document has no reason to carry: scripts, launch actions, embedded files, rich media and
form submission. A PDF that carries one is flagged; its text is then not pulled into a
proposed question automatically, and the screen says why. A clean result means only "none
of these features were found".

All PyMuPDF work goes through pdf_guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import pdf_guard

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


def check_pdf(path: str | Path) -> dict[str, Any]:
    findings: set[str] = set()
    try:
        with pdf_guard.open_pdf(str(path)) as doc:
            if doc.is_encrypted:
                return {"status": UNREADABLE, "findings": ["encrypted"]}
            if doc.embfile_count():
                findings.add("/EmbeddedFile")
            for xref in range(1, min(doc.xref_length(), MAX_OBJECTS)):
                try:
                    body = doc.xref_object(xref, compressed=False)
                except Exception:  # noqa: BLE001 - one damaged object must not hide the rest
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
    except Exception:  # noqa: BLE001 - not a PDF, damaged, or unreadable
        return {"status": UNREADABLE, "findings": []}
    return {"status": FLAGGED if findings else CLEAN, "findings": sorted(findings)}
