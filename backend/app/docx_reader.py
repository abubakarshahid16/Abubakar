"""A structure-preserving reader for Word (.docx) documents (W5b-01, #525).

WHY THIS EXISTS. A Word file is not pages: it is headings, numbered lists and
tables, and the numbers are not in the text (Word computes them). Opened with
MuPDF, or read as a flat run of paragraphs, a Word document loses its heading
levels, its list numbers and its table cells, and a citation can only say "page
7" of a document that has no page 7. This reader keeps what Word knows:

  * HEADING LEVELS and the heading path of every block ("4 > 4.2"), from the
    paragraph style chain (Heading N, outline level), numbered or not.
  * NUMBERED AND BULLETED LISTS WITH THEIR NUMBERS, computed from
    `numbering.xml` the way Word counts them (levels reset, formats decimal,
    letters, roman numerals, bullets). The number is written into the text.
  * TABLES as real rows and cells (merged cells handled), never as a run of
    paragraphs.
  * PAGE and SECTION BREAKS (as the boundary of a reading page, since Word has
    no fixed pages; a long stretch without one is cut at a block boundary).
  * HEADERS and FOOTERS, marked as such and kept OUT of the body.
  * TRACKED CHANGES: deleted text is NEVER part of the body (it is recorded
    beside it as a tracked change, with what was deleted); inserted text is
    the body's current text and the paragraph is marked as carrying a change.
  * COMMENTS, kept beside the body with the paragraph they are anchored to.
  * The table of contents is kept apart (it repeats the headings).

WHAT IT DOES NOT READ, said out loud in `Structure.notes` (counts, never
document text): pictures and text boxes, footnote and endnote bodies, embedded
objects, and number formats it does not know. A limit that leaves content out
is reported; it never makes the document look complete.

GENERIC. Nothing here knows any one document or discipline. HOSTILE FILES: the
same limits as `datasheet_inputs` (declared unpacked size and entry count are
checked before anything is decompressed, a macro project is refused, a DOCTYPE
or entity declaration is refused so no entity can be defined).
"""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .datasheet_inputs import (
    DOCX_REQUIRED_ENTRY,
    MAX_DOCX_BLOCKS,
    InputError,
    _parse_bounded,
    check_zip_bounds,
    refuse_doctype,
)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: A reading page is cut at the next block boundary past this many characters
#: when the author put no break in. Not a Word page: a unit to cite and show.
FLOW_PAGE_CHARS = 6_000
#: A heading label kept in a path is cut here (a long unnumbered title).
PATH_LABEL_CHARS = 60

KIND_HEADING = "heading"
KIND_PARAGRAPH = "paragraph"
KIND_LIST_ITEM = "list_item"
KIND_TABLE = "table"

#: Parts kept BESIDE the body, never in it.
FURNITURE_HEADER = "header"
FURNITURE_FOOTER = "footer"
FURNITURE_TRACKED = "tracked_change"
FURNITURE_COMMENT = "comment"
FURNITURE_TOC = "toc"


@dataclass
class DocBlock:
    kind: str
    text: str = ""
    #: Heading level 1..9 for a heading; the list level (1..) for a list item.
    level: int = 0
    #: The computed number or bullet ("4.2", "a)", "•"), or "".
    label: str = ""
    #: Compact heading path in effect for this block ("4", "4.2"); for a
    #: heading it includes the heading itself.
    path: tuple[str, ...] = ()
    #: The same path as full "number title" labels (index text, never cited).
    chain: tuple[str, ...] = ()
    #: 1-based ordinal among the paragraphs and list items of the innermost
    #: section; None for headings and tables.
    para_no: int | None = None
    #: 1-based ordinal among the tables of the innermost section.
    table_no: int | None = None
    rows: list[list[str]] = field(default_factory=list)
    #: The reading page this block sits on (1-based).
    page: int = 1
    #: This paragraph carries an inserted run (a tracked insertion).
    tracked: bool = False


@dataclass
class Furniture:
    """Text kept beside the body: header, footer, tracked change, comment, toc."""

    kind: str
    text: str
    #: Where it belongs: "header", "footer", or the locator of the anchor.
    locator: str
    page: int = 1


@dataclass
class Structure:
    blocks: list[DocBlock]
    furniture: list[Furniture]
    #: One rendered text per reading page, in order.
    pages: list[str]
    notes: list[str]


# ------------------------------------------------------------------ styles


@dataclass
class _Style:
    name: str = ""
    based_on: str | None = None
    outline: int | None = None
    num_id: str | None = None
    ilvl: int | None = None


def _val(el: ET.Element | None, attr: str = "val") -> str | None:
    return None if el is None else el.get(_W + attr)


def _read_styles(root: ET.Element | None) -> dict[str, _Style]:
    styles: dict[str, _Style] = {}
    if root is None:
        return styles
    for st in root.findall(_W + "style"):
        sid = st.get(_W + "styleId")
        if not sid:
            continue
        s = _Style(name=(_val(st.find(_W + "name")) or sid))
        s.based_on = _val(st.find(_W + "basedOn"))
        ppr = st.find(_W + "pPr")
        if ppr is not None:
            ol = _val(ppr.find(_W + "outlineLvl"))
            if ol is not None and ol.isdigit():
                s.outline = int(ol)
            numpr = ppr.find(_W + "numPr")
            if numpr is not None:
                s.num_id = _val(numpr.find(_W + "numId"))
                il = _val(numpr.find(_W + "ilvl"))
                s.ilvl = int(il) if il and il.isdigit() else None
        styles[sid] = s
    return styles


def _style_chain(styles: dict[str, _Style], sid: str | None):
    seen: set[str] = set()
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        yield styles[sid]
        sid = styles[sid].based_on


# --------------------------------------------------------------- numbering

_BULLETS = {"": "•", "": "▪", "": "➢", "": "❖", "o": "◦", "·": "•"}


def _roman(n: int) -> str:
    out = ""
    for value, sym in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                       (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sym
            n -= value
    return out


def _letters(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = "%1."


class _Numbering:
    """Word's list counters. One counter set per abstract list, restarted when
    a `num` carries a start override for that level."""

    def __init__(self, root: ET.Element | None, notes: list[str]) -> None:
        self._notes = notes
        self._abstract: dict[str, dict[int, _Level]] = {}
        self._num: dict[str, tuple[str, dict[int, int]]] = {}
        self._counters: dict[str, list[int | None]] = {}
        self._unknown_formats: set[str] = set()
        if root is None:
            return
        for ab in root.findall(_W + "abstractNum"):
            aid = ab.get(_W + "abstractNumId")
            levels: dict[int, _Level] = {}
            for lvl in ab.findall(_W + "lvl"):
                try:
                    ilvl = int(lvl.get(_W + "ilvl") or 0)
                except ValueError:
                    continue
                start = _val(lvl.find(_W + "start"))
                levels[ilvl] = _Level(
                    start=int(start) if start and start.lstrip("-").isdigit() else 1,
                    fmt=_val(lvl.find(_W + "numFmt")) or "decimal",
                    text=_val(lvl.find(_W + "lvlText")) or "")
            if aid is not None:
                self._abstract[aid] = levels
        for num in root.findall(_W + "num"):
            nid = num.get(_W + "numId")
            aid = _val(num.find(_W + "abstractNumId"))
            overrides: dict[int, int] = {}
            for ov in num.findall(_W + "lvlOverride"):
                so = _val(ov.find(_W + "startOverride"))
                try:
                    if so is not None:
                        overrides[int(ov.get(_W + "ilvl") or 0)] = int(so)
                except ValueError:
                    pass
            if nid is not None and aid is not None:
                self._num[nid] = (aid, overrides)

    def known(self, num_id: str | None) -> bool:
        return bool(num_id) and num_id != "0" and num_id in self._num

    def _format(self, n: int, fmt: str) -> str:
        if fmt == "decimal":
            return str(n)
        if fmt == "decimalZero":
            return f"{n:02d}"
        if fmt == "lowerLetter":
            return _letters(n).lower()
        if fmt == "upperLetter":
            return _letters(n)
        if fmt == "lowerRoman":
            return _roman(n).lower()
        if fmt == "upperRoman":
            return _roman(n)
        if fmt == "none":
            return ""
        self._unknown_formats.add(fmt)
        return str(n)

    def label(self, num_id: str, ilvl: int) -> tuple[str, bool]:
        """(label, is_bullet) for the next item at `ilvl` of list `num_id`."""
        aid, overrides = self._num[num_id]
        levels = self._abstract.get(aid, {})
        level = levels.get(ilvl, _Level())
        key = aid if not overrides else f"{aid}:{num_id}"
        counters = self._counters.setdefault(key, [None] * 9)
        ilvl = max(0, min(ilvl, 8))
        if level.fmt == "bullet":
            for deeper in range(ilvl + 1, 9):
                counters[deeper] = None
            text = level.text or "•"
            return _BULLETS.get(text, text if text.strip() else "•"), True
        if counters[ilvl] is None:
            counters[ilvl] = overrides.get(ilvl, level.start)
        else:
            counters[ilvl] += 1
        for deeper in range(ilvl + 1, 9):
            counters[deeper] = None
        template = level.text or f"%{ilvl + 1}."

        def fill(match: re.Match) -> str:
            idx = int(match.group(1)) - 1
            lv = levels.get(idx, _Level())
            value = counters[idx] if 0 <= idx < 9 and counters[idx] is not None else lv.start
            return self._format(value, lv.fmt)

        return re.sub(r"%(\d)", fill, template).strip(), False

    def finish(self) -> None:
        if self._unknown_formats:
            self._notes.append(f"{len(self._unknown_formats)} list number format(s) not known; "
                               "counted as plain numbers")


# --------------------------------------------------------------- paragraphs


@dataclass
class _Para:
    text: str = ""
    deleted: str = ""
    inserted: bool = False
    inserted_text: str = ""
    comment_ids: list[str] = field(default_factory=list)
    page_break_inside: bool = False
    figures: int = 0
    text_boxes: int = 0


def _collect(el: ET.Element, para: _Para, parts: list[str], dels: list[str], in_del: bool) -> None:
    for child in el:
        tag = child.tag
        if tag in (_W + "del", _W + "moveFrom"):
            _collect(child, para, parts, dels, True)
        elif tag in (_W + "ins", _W + "moveTo"):
            para.inserted = True
            inner: list[str] = []
            _collect(child, para, inner, dels, in_del)
            parts.extend(inner)
            para.inserted_text += "".join(inner)
        elif tag == _W + "r":
            for node in child:
                t = node.tag
                if t == _W + "t" and not in_del:
                    parts.append(node.text or "")
                elif t == _W + "delText" and in_del:
                    dels.append(node.text or "")
                elif t == _W + "tab" and not in_del:
                    parts.append(" ")
                elif t == _W + "br" and not in_del:
                    if node.get(_W + "type") == "page":
                        para.page_break_inside = True
                    else:
                        parts.append(" ")
                elif t == _W + "cr" and not in_del:
                    parts.append(" ")
                elif t == _W + "noBreakHyphen" and not in_del:
                    parts.append("-")
                elif t == _W + "commentReference":
                    cid = node.get(_W + "id")
                    if cid is not None:
                        para.comment_ids.append(cid)
                elif t in (_W + "drawing", _W + "pict", _W + "object"):
                    para.figures += 1
                    para.text_boxes += sum(1 for _ in node.iter(_W + "txbxContent"))
        elif tag in (_W + "hyperlink", _W + "smartTag", _W + "fldSimple", _W + "customXml",
                     _W + "sdt", _W + "sdtContent", _W + "bdo", _W + "dir"):
            _collect(child, para, parts, dels, in_del)


def _read_para(p: ET.Element) -> _Para:
    para = _Para()
    parts: list[str] = []
    dels: list[str] = []
    _collect(p, para, parts, dels, False)
    para.text = " ".join("".join(parts).split())
    para.deleted = " ".join("".join(dels).split())
    return para


def _para_props(p: ET.Element):
    ppr = p.find(_W + "pPr")
    style = num_id = None
    ilvl: int | None = None
    outline: int | None = None
    page_before = False
    section_break = False
    if ppr is not None:
        style = _val(ppr.find(_W + "pStyle"))
        numpr = ppr.find(_W + "numPr")
        if numpr is not None:
            num_id = _val(numpr.find(_W + "numId"))
            il = _val(numpr.find(_W + "ilvl"))
            ilvl = int(il) if il and il.isdigit() else None
        ol = _val(ppr.find(_W + "outlineLvl"))
        outline = int(ol) if ol and ol.isdigit() else None
        pb = ppr.find(_W + "pageBreakBefore")
        page_before = pb is not None and _val(pb) not in ("0", "false")
        sect = ppr.find(_W + "sectPr")
        if sect is not None:
            kind = _val(sect.find(_W + "type"))
            section_break = kind != "continuous"
    return style, num_id, ilvl, outline, page_before, section_break


def _blocks(body: ET.Element):
    for child in body:
        if child.tag in (_W + "p", _W + "tbl"):
            yield child
        elif child.tag == _W + "sdt":
            content = child.find(_W + "sdtContent")
            if content is not None:
                yield from _blocks(content)


def _cell_text(tc: ET.Element) -> tuple[str, bool]:
    texts: list[str] = []
    changed = False
    for p in tc.iter(_W + "p"):
        para = _read_para(p)
        changed = changed or para.inserted or bool(para.deleted)
        if para.text:
            texts.append(para.text)
    return " ".join(texts), changed


def _table(tbl: ET.Element, notes: list[str]) -> tuple[list[list[str]], bool, list[str]]:
    """(rows, any inserted/changed cell, deleted-row texts). A deleted row (a
    tracked row deletion) is not part of the table; its text is returned so it
    can be recorded as a tracked change."""
    rows: list[list[str]] = []
    deleted_rows: list[str] = []
    changed = False
    above: dict[int, str] = {}
    for tr in tbl.findall(_W + "tr"):
        trpr = tr.find(_W + "trPr")
        cells: list[str] = []
        col = 0
        for tc in tr.findall(_W + "tc"):
            span, vmerge = 1, None
            props = tc.find(_W + "tcPr")
            if props is not None:
                gs = _val(props.find(_W + "gridSpan"))
                if gs and gs.isdigit():
                    span = max(1, min(int(gs), 100))
                vm = props.find(_W + "vMerge")
                if vm is not None:
                    vmerge = _val(vm) or "continue"
            text, ch = _cell_text(tc)
            changed = changed or ch
            if vmerge == "continue" and not text:
                text = above.get(col, "")
            above[col] = text
            cells.append(text)
            cells.extend([""] * (span - 1))
            col += span
        if trpr is not None and trpr.find(_W + "del") is not None:
            deleted_rows.append(" | ".join(c for c in cells if c))
            continue
        if any(cells):
            while cells and not cells[-1]:
                cells.pop()
            rows.append(cells)
    return rows, changed, deleted_rows


# ----------------------------------------------------------------- the walk


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PATH_LABEL_CHARS else text[: PATH_LABEL_CHARS - 1].rstrip() + "…"


_LEADING_NUMBER = re.compile(r"^((?:\d+\.)*\d+|[A-Z]\.\d+(?:\.\d+)*|[IVXLC]+\.)[.)]?\s+\S")


def _compact(label: str, title: str) -> str:
    """The short name of a heading in a path: its number when it has one,
    otherwise its title. A typed number ("4.2 Pipes") counts as a number."""
    label = label.strip().rstrip(".:)").strip()
    if label:
        return label
    m = _LEADING_NUMBER.match(title.strip())
    if m:
        return m.group(1).rstrip(".")
    return _short(title)


def _heading_level(styles, style_id, outline) -> int | None:
    if outline is not None and outline < 9:
        return outline + 1
    for s in _style_chain(styles, style_id):
        name = s.name.lower()
        m = re.match(r"^(?:heading|titre|überschrift)\s*(\d)$", name)
        if m:
            return int(m.group(1))
        if s.outline is not None and s.outline < 9:
            return s.outline + 1
    return None


def _is_toc(styles, style_id) -> bool:
    for s in _style_chain(styles, style_id):
        n = s.name.lower()
        if n.startswith("toc ") or n in ("toc heading", "table of contents"):
            return True
    return False


def _opt_part(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return _parse_bounded(zf, name)
    except KeyError:
        return None
    except ET.ParseError as exc:
        raise InputError("not_office", f"{name} is not well-formed") from exc


def _furniture_parts(zf: zipfile.ZipFile, notes: list[str]) -> list[Furniture]:
    out: list[Furniture] = []
    seen: set[tuple[str, str]] = set()
    for name in sorted(zf.namelist()):
        low = name.lower()
        if not (low.startswith("word/header") or low.startswith("word/footer")) \
                or not low.endswith(".xml"):
            continue
        kind = FURNITURE_HEADER if low.startswith("word/header") else FURNITURE_FOOTER
        root = _opt_part(zf, name)
        if root is None:
            continue
        text = " ".join(t for t in (_read_para(p).text for p in root.iter(_W + "p")) if t)
        if text and (kind, text) not in seen:
            seen.add((kind, text))
            out.append(Furniture(kind, text, kind))
    return out


def _comments(zf: zipfile.ZipFile) -> dict[str, tuple[str, str]]:
    root = _opt_part(zf, "word/comments.xml")
    found: dict[str, tuple[str, str]] = {}
    if root is None:
        return found
    for c in root.findall(_W + "comment"):
        cid = c.get(_W + "id")
        if cid is None:
            continue
        text = " ".join(t for t in (_read_para(p).text for p in c.iter(_W + "p")) if t)
        found[cid] = (c.get(_W + "author") or "", text)
    return found


def read_structure(path: str | os.PathLike) -> Structure:
    """Read a .docx into blocks, furniture, reading pages and notes.

    Raises `datasheet_inputs.InputError` for a file it refuses (not a Word
    document, a DOCTYPE, a macro, a zip bomb); the ingest records it as failed
    with that reason."""
    check_zip_bounds(path)
    notes: list[str] = []
    with zipfile.ZipFile(path) as zf:
        refuse_doctype(zf)
        try:
            root = _parse_bounded(zf, DOCX_REQUIRED_ENTRY)
        except KeyError as exc:
            raise InputError("not_office", "no word/document.xml") from exc
        except ET.ParseError as exc:
            raise InputError("not_office", "word/document.xml is not well-formed") from exc
        styles = _read_styles(_opt_part(zf, "word/styles.xml"))
        numbering = _Numbering(_opt_part(zf, "word/numbering.xml"), notes)
        comments = _comments(zf)
        furniture = _furniture_parts(zf, notes)
        has_notes = any(n in zf.namelist() for n in ("word/footnotes.xml", "word/endnotes.xml"))
    body = root.find(_W + "body")

    blocks: list[DocBlock] = []
    heading_stack: list[tuple[int, str, str]] = []   # (level, compact, "label title")
    para_no = 0
    table_no = 0
    page = 1
    page_chars = 0
    figures = text_boxes = 0
    count = 0
    toc_lines: list[str] = []
    skipped_empty_headings = 0

    def path_now() -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (tuple(c for _, c, _ in heading_stack), tuple(f for _, _, f in heading_stack))

    def locator_now() -> str:
        return " > ".join(c for _, c, _ in heading_stack)

    def new_page() -> None:
        nonlocal page, page_chars
        if page_chars:
            page += 1
            page_chars = 0

    for node in _blocks(body if body is not None else root):
        count += 1
        if count > MAX_DOCX_BLOCKS:
            raise InputError("too_many_blocks", f"more than {MAX_DOCX_BLOCKS} paragraphs/rows")
        if node.tag == _W + "tbl":
            rows, changed, deleted_rows = _table(node, notes)
            if deleted_rows:
                furniture.append(Furniture(FURNITURE_TRACKED,
                                           "deleted table row(s): " + " / ".join(deleted_rows),
                                           locator_now() or "document start", page))
            if rows:
                table_no += 1
                chain_path, chain_full = path_now()
                blocks.append(DocBlock(KIND_TABLE, rows=rows, path=chain_path, chain=chain_full,
                                       table_no=table_no, page=page, tracked=changed))
                page_chars += sum(len(" ".join(r)) for r in rows)
            continue

        para = _read_para(node)
        style_id, num_id, ilvl, outline, page_before, section_break = _para_props(node)
        figures += para.figures
        text_boxes += para.text_boxes
        if page_before:
            new_page()
        if _is_toc(styles, style_id):
            if para.text:
                toc_lines.append(para.text)
        elif para.text:
            level = _heading_level(styles, style_id, outline)
            # numbering: the paragraph's own numPr, else its style chain's
            eff_num, eff_lvl = num_id, ilvl
            if eff_num is None:
                for s in _style_chain(styles, style_id):
                    if s.num_id is not None:
                        eff_num, eff_lvl = s.num_id, s.ilvl
                        break
            label, is_bullet = "", False
            if numbering.known(eff_num):
                label, is_bullet = numbering.label(eff_num, eff_lvl or 0)
            if page_chars >= FLOW_PAGE_CHARS and (level is not None or label == ""):
                new_page()
            if level is not None and len(para.text) < 400:
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, _compact("" if is_bullet else label, para.text),
                                      f"{'' if is_bullet else label} {para.text}".strip()))
                para_no = 0
                table_no = 0
                chain_path, chain_full = path_now()
                blocks.append(DocBlock(KIND_HEADING, para.text, level,
                                       "" if is_bullet else label, chain_path, chain_full,
                                       page=page, tracked=para.inserted))
            elif label:
                para_no += 1
                chain_path, chain_full = path_now()
                blocks.append(DocBlock(KIND_LIST_ITEM, para.text, (eff_lvl or 0) + 1, label,
                                       chain_path, chain_full, para_no=para_no, page=page,
                                       tracked=para.inserted))
            else:
                para_no += 1
                chain_path, chain_full = path_now()
                blocks.append(DocBlock(KIND_PARAGRAPH, para.text, 0, "", chain_path, chain_full,
                                       para_no=para_no, page=page, tracked=para.inserted))
            page_chars += len(para.text) + len(label) + 1
            anchor = " > ".join(filter(None, [locator_now(),
                                              f"para {para_no}" if para_no and blocks[-1].kind != KIND_HEADING else ""]))
            anchor = anchor or "document start"
            if para.deleted:
                furniture.append(Furniture(FURNITURE_TRACKED, f"deleted: {para.deleted}", anchor, page))
            if para.inserted_text:
                furniture.append(Furniture(FURNITURE_TRACKED, f"inserted: {para.inserted_text}",
                                           anchor, page))
            for cid in para.comment_ids:
                if cid in comments:
                    author, ctext = comments[cid]
                    furniture.append(Furniture(
                        FURNITURE_COMMENT,
                        (f"comment by {author}: " if author else "comment: ") + ctext, anchor, page))
        else:
            if para.deleted:
                furniture.append(Furniture(FURNITURE_TRACKED, f"deleted: {para.deleted}",
                                           locator_now() or "document start", page))
            if _heading_level(styles, style_id, outline) is not None:
                skipped_empty_headings += 1

        if para.page_break_inside or section_break:
            new_page()

    numbering.finish()
    if toc_lines:
        furniture.append(Furniture(FURNITURE_TOC, "\n".join(toc_lines), "table of contents", 1))
    if figures:
        notes.append(f"{figures} picture(s) or drawing(s) not read")
    if text_boxes:
        notes.append(f"{text_boxes} text box(es) not read")
    if has_notes:
        notes.append("footnote and endnote bodies not read")
    if skipped_empty_headings:
        notes.append(f"{skipped_empty_headings} empty heading(s) skipped")
    # Reading pages are dense (1..n): a stretch with only furniture has none.
    dense = {old: new for new, old in enumerate(sorted({b.page for b in blocks}), start=1)}
    for b in blocks:
        b.page = dense[b.page]
    for f in furniture:
        f.page = dense.get(f.page, 1)
    return Structure(blocks=blocks, furniture=furniture,
                     pages=_render_pages(blocks, len(dense)), notes=notes)


# ---------------------------------------------------------------- rendering


def block_lines(b: DocBlock) -> list[str]:
    """The block as text lines: the form stored as page text and cited."""
    if b.kind == KIND_TABLE:
        width = max(len(r) for r in b.rows)
        return ["| " + " | ".join(list(r) + [""] * (width - len(r))) + " |" for r in b.rows]
    if b.kind == KIND_HEADING:
        return [f"{b.label} {b.text}".strip() if b.label and not b.text.startswith(b.label)
                else b.text]
    if b.kind == KIND_LIST_ITEM:
        return [f"{b.label} {b.text}".strip()]
    return [b.text]


def _render_pages(blocks: list[DocBlock], last_page: int) -> list[str]:
    by_page: dict[int, list[str]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).extend(block_lines(b))
    pages = ["\n".join(by_page[n]) for n in range(1, last_page + 1) if n in by_page]
    return pages or [""]
