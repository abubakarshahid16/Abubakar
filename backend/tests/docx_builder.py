"""Builds small INVENTED .docx files for tests: raw OOXML in a zip, no
python-docx. Nothing here is a client document."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = f'xmlns:w="{W}"'


def run(text: str, *, deleted: bool = False) -> str:
    tag = "w:delText" if deleted else "w:t"
    return f'<w:r><{tag} xml:space="preserve">{escape(text)}</{tag}></w:r>'


def para(text: str = "", *, style: str | None = None, num: tuple[int, int] | None = None,
         inserted: str | None = None, deleted: str | None = None, page_break: bool = False,
         comment: int | None = None, raw: str = "") -> str:
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if num:
        ppr += f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
    body = run(text) if text else ""
    if inserted:
        body += f'<w:ins w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">{run(inserted)}</w:ins>'
    if deleted:
        body += f'<w:del w:id="2" w:author="A" w:date="2026-01-01T00:00:00Z">{run(deleted, deleted=True)}</w:del>'
    if comment is not None:
        body += f'<w:r><w:commentReference w:id="{comment}"/></w:r>'
    if page_break:
        body += '<w:r><w:br w:type="page"/></w:r>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{body}{raw}</w:p>"


def table(rows: list[list[str]], *, deleted_rows: tuple[int, ...] = ()) -> str:
    out = "<w:tbl>"
    for i, row in enumerate(rows):
        trpr = '<w:trPr><w:del w:id="9" w:author="A" w:date="2026-01-01T00:00:00Z"/></w:trPr>' \
            if i in deleted_rows else ""
        out += f"<w:tr>{trpr}" + "".join(f"<w:tc>{para(c)}</w:tc>" for c in row) + "</w:tr>"
    return out + "</w:tbl>"


STYLES = f"""<?xml version="1.0" encoding="UTF-8"?><w:styles {NS}>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:numPr><w:numId w:val="1"/><w:ilvl w:val="0"/></w:numPr></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:numPr><w:numId w:val="1"/><w:ilvl w:val="1"/></w:numPr></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/></w:style>
<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8"?><w:numbering {NS}>
<w:abstractNum w:abstractNumId="0">
 <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1"/></w:lvl>
 <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="1">
 <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
 <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="2">
 <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="&#xF0B7;"/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
<w:num w:numId="3"><w:abstractNumId w:val="2"/></w:num>
</w:numbering>"""


def build(path: Path, body: str, *, footer: str | None = None, header: str | None = None,
          comments: dict[int, tuple[str, str]] | None = None, styles: str = STYLES,
          numbering: str | None = NUMBERING, extra: dict[str, str] | None = None) -> Path:
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>{body}'
           f'<w:sectPr/></w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc)
        zf.writestr("word/styles.xml", styles)
        if numbering:
            zf.writestr("word/numbering.xml", numbering)
        if footer is not None:
            zf.writestr("word/footer1.xml",
                        f'<?xml version="1.0"?><w:ftr {NS}>{para(footer)}</w:ftr>')
        if header is not None:
            zf.writestr("word/header1.xml",
                        f'<?xml version="1.0"?><w:hdr {NS}>{para(header)}</w:hdr>')
        if comments:
            items = "".join(
                f'<w:comment w:id="{cid}" w:author="{escape(a)}">{para(t)}</w:comment>'
                for cid, (a, t) in comments.items())
            zf.writestr("word/comments.xml", f'<?xml version="1.0"?><w:comments {NS}>{items}</w:comments>')
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path
