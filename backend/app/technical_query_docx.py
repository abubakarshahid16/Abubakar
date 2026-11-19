"""Small dependency-free DOCX response renderer for approved query drafts."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .config import settings

_CONTENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""


def _p(text: str, bold: bool = False) -> str:
    value = escape(text)
    run = (
        f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{value}</w:t></w:r>'
        if bold
        else f'<w:r><w:t xml:space="preserve">{value}</w:t></w:r>'
    )
    return f"<w:p>{run}</w:p>"


def render(query: dict, output: Path | None = None) -> Path:
    draft = query.get("drafts", [])[-1] if query.get("drafts") else None
    if draft is None:
        raise ValueError("a draft is required before generating a response")
    target = output or (
        settings.data_dir
        / "query_responses"
        / f"{query['id']}-v{draft['version']}.docx"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = [
        _p(
            "Technical Query Response"
            if query["status"]
            in {"approved", "sent", "awaiting_confirmation", "resolved"}
            else "DRAFT Technical Query Response — engineer review required",
            True,
        ),
        _p(f"Subject: {query['subject']}"),
        _p(f"Status: {query['status']}"),
        _p("Original question", True),
        _p(query.get("extracted_question") or "Not extracted"),
        _p("Proposed answer", True),
        _p(draft["answer"]),
    ]
    if draft.get("assumptions_json"):
        paragraphs += [_p("Assumptions", True)] + [
            _p(f"- {x}") for x in __import__("json").loads(draft["assumptions_json"])
        ]
    if draft.get("unresolved_json"):
        paragraphs += [_p("Unresolved points", True)] + [
            _p(f"- {x}") for x in __import__("json").loads(draft["unresolved_json"])
        ]
    paragraphs += [_p("Evidence", True)]
    if not query.get("evidence"):
        paragraphs.append(
            _p(
                "No verified source evidence is recorded. The engineer must resolve this before issue."
            )
        )
    else:
        paragraphs += [
            _p(
                f"{e['document_id']} p{e.get('page_start') or '?'} "
                f"[{e.get('evidence_state', 'unknown')}; {e.get('supersession_state', 'unknown')}]: "
                f"{e['exact_quote']}"
            )
            for e in query["evidence"]
        ]
    body = "".join(paragraphs)
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr/></w:body></w:document>"""
    with ZipFile(target, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _CONTENT)
        package.writestr("_rels/.rels", _RELS)
        package.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        package.writestr("word/document.xml", document)
    return target
