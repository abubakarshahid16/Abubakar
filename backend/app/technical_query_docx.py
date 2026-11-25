"""Small dependency-free DOCX response renderer for approved query drafts."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .aim_review_gate import AI_MARK
from .config import settings
from .technical_queries import original_email_question

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


APPROVED_STATES = {"approved", "sent", "awaiting_confirmation", "resolved"}


def _p(text: str, bold: bool = False) -> str:
    # Word shows a newline inside one text run as a space, so each line is its own
    # run with an explicit break between them.
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    runs = "<w:r><w:br/></w:r>".join(
        f'<w:r>{props}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>'
        for line in lines
    )
    return f"<w:p>{runs}</w:p>"


def _document_names(ids: set[str]) -> dict[str, str]:
    """File names for the cited documents: a contractor cannot read an internal id."""
    if not ids:
        return {}
    from .db import connect

    marks = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT id,filename FROM documents WHERE id IN ({marks})", tuple(ids)
        ).fetchall()
    return {row["id"]: row["filename"] for row in rows}


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
    citations = __import__("json").loads(draft.get("citations_json") or "[]")
    names = _document_names(
        {e["document_id"] for e in query.get("evidence", [])}
        | {c["document_id"] for c in citations}
    )
    paragraphs = [
        _p(
            "Technical Query Response"
            if query["status"] in APPROVED_STATES
            else "DRAFT Technical Query Response — engineer review required",
            True,
        ),
        _p(f"Subject: {query['subject']}"),
        # Until a reviewer approves, the words are an AI's: say so in the file (one home for the label: aim_review_gate.AI_MARK)
        *([_p(f"{AI_MARK}: not yet approved by an engineer.", True)] if query["status"] not in APPROVED_STATES else []),
        _p("Original question (from the email)", True),
        _p(original_email_question(query.get("extracted_question")) or "Not stated in the email text."),
    ]
    for part in query.get("attachment_context") or []:
        paragraphs += [
            _p(f"Attachment text: {part['filename']}, page {part['page']}", True),
            _p(part["text"]),
        ]
    confirmed = (query.get("confirmed_question") or "").strip()
    if confirmed:
        paragraphs += [_p("Question answered (confirmed by the engineer)", True), _p(confirmed)]
    paragraphs += [
        _p("Proposed answer", True),
        _p(draft["answer"]),
    ]
    assumptions = __import__("json").loads(draft.get("assumptions_json") or "[]")
    if assumptions:
        paragraphs += [_p("Assumptions", True)] + [_p(f"- {x}") for x in assumptions]
    unresolved = __import__("json").loads(draft.get("unresolved_json") or "[]")
    if unresolved:
        paragraphs += [_p("Unresolved points", True)] + [_p(f"- {x}") for x in unresolved]
    if citations:
        paragraphs += [_p("Cited passages", True)] + [
            _p(
                f"[{c['label']}] {names.get(c['document_id'], c['document_id'])} page {c['page']}: {c['exact_quote']}"
            )
            for c in citations
        ]
    paragraphs += [_p("Evidence", True)]
    coverage = query.get("evidence_coverage") or {}
    if coverage.get("line"):
        paragraphs.append(_p(str(coverage["line"])))
    if coverage.get("likely_not_covered"):
        paragraphs.append(_p(str(coverage.get("not_covered_line") or "")))
    listed = [e for e in query.get("evidence") or [] if e.get("evidence_state", "verified") == "verified"]
    if not listed:
        paragraphs.append(
            _p(
                "No verified source evidence is recorded. The engineer must resolve this before issue."
            )
        )
    else:
        paragraphs += [
            _p(
                f"{names.get(e['document_id'], e['document_id'])}"
                + (f", {e['locator']}" if e.get("locator") else "")
                + f", p{e.get('page_start') or '?'} "
                + (f"({e['match_count']} of {e['match_terms']} key terms) " if e.get("match_terms") else "")
                + f"[{e.get('evidence_state', 'unknown')}; {e.get('supersession_state', 'unknown')}]: "
                f"{e['exact_quote']}"
            )
            for e in listed
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
