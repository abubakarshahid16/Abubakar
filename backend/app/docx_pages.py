"""A Word file's own pages, and what it holds against what was read
(WORD_PAGE_MARKERS_ENABLED; `docx_reader` walks the file through `PageWalk`).

PAGES. Word saves where its last layout broke the pages (`w:lastRenderedPageBreak`)
beside the breaks the author typed (`w:br w:type="page"`, page-break-before, a
section break). A file that holds them is paged by them: a block's page is the page
it STARTS on, a table row the page its row starts on, and page N's stored text is
what started on page N, so a quote cited to page N is found there. A page nothing
started on stays, empty, so no number shifts. No markers at all: the reading parts
stay, and `Pagination.source` says "none", so nothing may print one as a page. Fewer
pages than Word's own saved count (`docProps/app.xml`): "partial", and said. Pages
are never extrapolated.

READ PROOF. Tables and pictures are counted from `word/document.xml` and set against
what reached the reader. A picture is read only when text came back (rule 4).

Off: `PageWalk.open` gives a walk that changes nothing. Counts and places only.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .config import settings
from .datasheet_inputs import InputError, _blocks, _parse_bounded

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V = "{urn:schemas-microsoft-com:vml}"

PAGES_MARKERS = "markers"  # every page Word saved is accounted for
PAGES_PARTIAL = "partial"  # some are not: the numbers may be low, and that is said
PAGES_NONE = "none"  # no page is available: the section heading is shown instead

PICTURE_IMAGE = "image"  # an image stored in the file, which a recogniser can be given
PICTURE_LINKED = "linked"  # an image that lives outside the file
PICTURE_SHAPE = "shape"  # a drawn shape, chart or object with no image in it

#: Said for a picture with no reading, by what it is. A stored reason wins.
WHY_NOT_SENT = "not sent to the local picture recogniser yet"
WHY_NOT_IMAGE = {
    PICTURE_LINKED: "the image is linked from outside the file, so it is not in the file to read",
    PICTURE_SHAPE: "a drawn shape, chart or object: it holds no image to recognise",
}
WHY_TABLE_EMPTY = "the table holds no text"
WHY_TABLE_IN_TEXT_BOX = "the table sits inside a text box, which is not read"
WHY_NOT_WALKED = "it sits where the reader does not walk"


@dataclass
class Pagination:
    """Where this file's page numbers come from. Counts only."""

    source: str
    #: `w:lastRenderedPageBreak` in the body (text boxes not counted).
    saved_markers: int = 0
    #: Breaks the author typed: page breaks, page-break-before, section breaks.
    typed_breaks: int = 0
    #: The page count Word saved in `docProps/app.xml`; None when it saved none.
    word_pages: int | None = None
    #: The last page the markers reach; never more than they prove.
    last_page: int = 1


@dataclass
class Picture:
    """One picture of the body, in document order."""

    no: int
    kind: str
    page: int
    heading: str
    #: The stored image parts ("word/media/x.png") behind it.
    targets: tuple[str, ...] = ()


@dataclass
class NotRead:
    kind: str  # "table" or "picture"
    no: int | None
    page: int | None
    heading: str
    reason: str


@dataclass
class ReadProof:
    """What the file holds against what reached the reader. Counts and places."""

    tables_in_file: int = 0
    tables_read: int = 0
    pictures_in_file: int = 0
    #: A picture counts only when OCR or vision text came back (rule 4).
    pictures_read: int = 0
    #: Pictures in headers and footers, kept beside the body and not sent.
    furniture_pictures: int = 0
    #: Image parts stored in the zip, whether used once, many times or never.
    media_files: int = 0
    not_read: list[NotRead] = field(default_factory=list)


@dataclass
class PictureReading:
    """What the recogniser gave for one picture; `text` empty means no reading."""

    text: str = ""
    reason: str | None = None


def _first_choice(alternate: ET.Element) -> ET.Element | None:
    """`mc:AlternateContent` holds one thing twice: its first choice is the one."""
    return next(
        (c for c in alternate if c.tag in (_MC + "Choice", _MC + "Fallback")), None
    )


def _para_events(el: ET.Element):
    """A paragraph in document order: "marker", "break", "text" and pictures
    (the element). A text box is never entered: its markers and text are not
    the body's."""
    for child in el:
        tag = child.tag
        if tag == _W + "pPr":
            continue
        if tag == _W + "lastRenderedPageBreak":
            yield "marker"
        elif tag == _W + "br":
            if child.get(_W + "type") == "page":
                yield "break"
        elif tag == _W + "t":
            if (child.text or "").strip():
                yield "text"
        elif tag in (_W + "drawing", _W + "pict", _W + "object"):
            yield child
        elif tag == _MC + "AlternateContent":
            first = _first_choice(child)
            if first is not None:
                yield from _para_events(first)
        else:
            yield from _para_events(child)


class _PageCount:
    """The page counter. A typed break and the marker Word saved after it are
    ONE new page: the break waits (`pending`) until the marker or the next
    content takes it. An empty paragraph takes nothing: it holds no run to carry
    a marker, and the content after it may."""

    def __init__(self) -> None:
        self.page = 1
        self.pending = False
        self.markers = 0
        self.breaks = 0
        #: The last table row ran over the page (`_plan_row`).
        self.row_ran_over = False

    def marker(self) -> None:
        self.page += 1
        self.pending = False
        self.markers += 1

    def typed_break(self) -> None:
        if self.pending:  # two breaks in a row: a blank page between them
            self.page += 1
        self.pending = True
        self.breaks += 1

    def content(self) -> None:
        if self.pending:
            self.page += 1
            self.pending = False

    def last(self) -> int:
        """The last page; a typed break with nothing after it still opened one."""
        return self.page + (1 if self.pending else 0)


@dataclass
class _PagePlan:
    pagination: Pagination
    #: id(block element) -> the page it starts on.
    starts: dict[int, int] = field(default_factory=dict)
    #: id(table element) -> the page of each of its `w:tr`.
    rows: dict[int, list[int]] = field(default_factory=dict)
    #: id(block element) -> its pictures as (element, page).
    pictures: dict[int, list[tuple[ET.Element, int]]] = field(default_factory=dict)
    #: `_section_page_starts`.
    section_starts: dict[int, bool] = field(default_factory=dict)


def _para_breaks(p: ET.Element) -> tuple[bool, bool]:
    """(page break before, does this paragraph end a section?)."""
    ppr = p.find(_W + "pPr")
    if ppr is None:
        return False, False
    before = ppr.find(_W + "pageBreakBefore")
    return (
        before is not None and before.get(_W + "val") not in ("0", "false"),
        ppr.find(_W + "sectPr") is not None,
    )


def _section_page_starts(body: ET.Element) -> dict[int, bool]:
    """id(paragraph ending a section) -> does the NEXT section open a page? A section's
    `w:type` says how that section itself starts, and it is held at the section's END,
    so the break after a section is the next one's. `continuous` and `nextColumn` stay
    on the page; `nextPage` (also when no type is given) and the odd and even kinds open one."""
    ends = [
        node for node in _blocks(body) if node.tag == _W + "p" and _para_breaks(node)[1]
    ]
    sections = [p.find(_W + "pPr").find(_W + "sectPr") for p in ends]
    sections.append(body.find(_W + "sectPr"))
    out: dict[int, bool] = {}
    for end, following in zip(ends, sections[1:], strict=True):
        kind = following.find(_W + "type") if following is not None else None
        out[id(end)] = kind is None or kind.get(_W + "val") not in (
            "continuous",
            "nextColumn",
        )
    return out


def _plan_para(p: ET.Element, count: _PageCount, plan: _PagePlan) -> None:
    before, _ = _para_breaks(p)
    if before:
        count.typed_break()
    start: int | None = None
    for event in _para_events(p):
        if event == "marker":
            count.marker()
        elif event == "break":
            count.typed_break()
        elif event == "text":
            count.content()
            start = count.page if start is None else start
        else:
            count.content()
            plan.pictures.setdefault(id(p), []).append((event, count.page))
    plan.starts[id(p)] = start if start is not None else count.page
    if plan.section_starts.get(id(p)):
        count.typed_break()


def _cell_paragraphs(el: ET.Element):
    """A cell's paragraphs, nested tables included. A text box sits inside a
    paragraph and is never entered: its markers are not the body's."""
    for child in el:
        if child.tag == _W + "p":
            yield child
        else:
            yield from _cell_paragraphs(child)


def _plan_row(
    tr: ET.Element, count: _PageCount, tbl: ET.Element, plan: _PagePlan
) -> int:
    """The page this row starts on. One page crossing can leave several markers,
    and they must count once: Word can save one in several cells of a row, so a
    row advances by the most any one cell holds, never the sum; and a row that
    runs over the page (a marker after text in a cell) leaves a second marker at
    the start of the row after it, which is that same crossing. The second was
    checked against a saved table of contents: counted twice, every heading after
    such a table came out one page high per crossing."""
    advance = 0
    at_start = False
    runs_over = False
    holds = False
    pictures: list[ET.Element] = []
    for tc in tr.findall(_W + "tc"):
        cell = _PageCount()
        seen_text = False
        for p in _cell_paragraphs(tc):
            for event in _para_events(p):
                if event in ("marker", "break"):
                    runs_over = runs_over or seen_text
                    at_start = at_start or not seen_text
                    cell.marker() if event == "marker" else cell.typed_break()
                elif event == "text":
                    seen_text = holds = True
                    cell.content()
                else:
                    holds = True
                    cell.content()
                    pictures.append(event)
        advance = max(advance, cell.last() - 1)
        count.markers += cell.markers
        count.breaks += cell.breaks
    at_start = at_start and not runs_over
    if at_start and (
        count.pending or count.row_ran_over
    ):  # the same crossing, counted once
        advance -= 1
    count.row_ran_over = runs_over
    if holds or at_start:
        count.content()
    if at_start and advance > 0:
        count.page += 1
        advance -= 1
    page = count.page
    count.page += max(0, advance)
    if pictures:
        plan.pictures.setdefault(id(tbl), []).extend((pic, page) for pic in pictures)
    return page


def word_pages_plan(body: ET.Element, word_pages: int | None) -> _PagePlan:
    """Walk the file's markers once and decide what its pages may say."""
    count = _PageCount()
    plan = _PagePlan(Pagination(PAGES_NONE, word_pages=word_pages))
    plan.section_starts = _section_page_starts(body)
    for node in _blocks(body):
        if node.tag == _W + "tbl":
            count.row_ran_over = False
            pages = [_plan_row(tr, count, node, plan) for tr in node.findall(_W + "tr")]
            plan.rows[id(node)] = pages
            plan.starts[id(node)] = pages[0] if pages else count.page
        else:
            _plan_para(node, count, plan)
    last = count.last()
    found = bool(count.markers or count.breaks)
    if not found:
        # No break in the file: no page numbers, whatever a saved count says.
        source = PAGES_NONE
    elif word_pages == last or (count.markers and word_pages is None):
        # Word's own count agrees; or it saved none to check them against.
        source = PAGES_MARKERS
    else:
        source = PAGES_PARTIAL
    plan.pagination = Pagination(source, count.markers, count.breaks, word_pages, last)
    return plan


def _part(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return _parse_bounded(zf, name)
    except KeyError:
        return None
    except ET.ParseError as exc:
        raise InputError("not_office", f"{name} is not well-formed") from exc


def _saved_page_count(zf: zipfile.ZipFile) -> int | None:
    """The page count Word saved beside the document, or None."""
    root = _part(zf, "docProps/app.xml")
    if root is None:
        return None
    for el in root:
        if el.tag.rsplit("}", 1)[-1] == "Pages" and (el.text or "").strip().isdigit():
            return int(el.text.strip())
    return None


def _count_in_part(root: ET.Element) -> tuple[int, int, int]:
    """(tables, tables inside text boxes, pictures) of a part. Text boxes hold
    their own content, so nothing inside one is counted as a picture of the
    body; `mc:AlternateContent` holds one thing twice and counts once."""
    tables = in_boxes = pictures = 0

    def walk(el: ET.Element, boxed: bool) -> None:
        nonlocal tables, in_boxes, pictures
        for child in el:
            tag = child.tag
            if tag == _W + "tbl":
                tables += 1
                in_boxes += 1 if boxed else 0
            if tag in (_W + "drawing", _W + "pict", _W + "object"):
                pictures += 0 if boxed else 1
                walk(child, True)
            elif tag == _MC + "AlternateContent":
                first = _first_choice(child)
                if first is not None:
                    walk(first, boxed)
            else:
                walk(child, boxed)

    walk(root, False)
    return tables, in_boxes, pictures


def _rels(zf: zipfile.ZipFile) -> dict[str, tuple[str, bool]]:
    """Relationship id -> (zip entry or outside target, is it outside the file?)."""
    root = _part(zf, "word/_rels/document.xml.rels")
    out: dict[str, tuple[str, bool]] = {}
    if root is None:
        return out
    for rel in root:
        rid, target = rel.get("Id"), rel.get("Target") or ""
        if not rid:
            continue
        outside = rel.get("TargetMode") == "External"
        out[rid] = (
            target if outside else "word/" + target.lstrip("/").removeprefix("word/"),
            outside,
        )
    return out


def _picture(el: ET.Element, no: int, page: int, heading: str, rels: dict) -> Picture:
    ids = [b.get(_R + "embed") or b.get(_R + "link") for b in el.iter(_A + "blip")]
    ids += [i.get(_R + "id") for i in el.iter(_V + "imagedata")]
    found = [rels[i] for i in ids if i in rels]
    targets = tuple(t for t, outside in found if not outside)
    kind = PICTURE_IMAGE if targets else PICTURE_LINKED if found else PICTURE_SHAPE
    return Picture(no, kind, page, heading, targets)


def _furniture_pictures(zf: zipfile.ZipFile) -> int:
    total = 0
    for name in zf.namelist():
        low = name.lower()
        if (
            low.startswith("word/header") or low.startswith("word/footer")
        ) and low.endswith(".xml"):
            part = _part(zf, name)
            if part is not None:
                total += _count_in_part(part)[2]
    return total


class PageWalk:
    """What `docx_reader.read_structure` asks as it walks the file. Off: every
    answer leaves the walk as it was, and nothing is counted."""

    def __init__(self) -> None:
        self.on = False
        self.real = False  # the file's own pages decide; False: the reading parts
        self.plan: _PagePlan | None = None
        self.rels: dict[str, tuple[str, bool]] = {}
        self.proof: ReadProof | None = None
        self.readings: dict[int, PictureReading] = {}
        self.pictures: list[Picture] = []

    @classmethod
    def open(
        cls,
        zf: zipfile.ZipFile,
        root: ET.Element,
        path: str | os.PathLike,
        readings: dict[int, PictureReading] | None,
    ) -> PageWalk:
        walk = cls()
        if not settings.word_page_markers_enabled:
            return walk
        if (
            readings is None
        ):  # what is stored, so pages, chunks and facts all read the same text
            from . import word_pictures

            readings = word_pictures.stored_readings(path)
        body = root.find(_W + "body")
        walk.on = True
        walk.plan = word_pages_plan(
            body if body is not None else root, _saved_page_count(zf)
        )
        walk.real = walk.plan.pagination.source != PAGES_NONE
        walk.rels = _rels(zf)
        walk.readings = readings
        walk.proof = ReadProof(
            furniture_pictures=_furniture_pictures(zf),
            media_files=sum(1 for n in zf.namelist() if n.startswith("word/media/")),
        )
        return walk

    def start(self, node: ET.Element, page: int) -> int:
        return self.plan.starts[id(node)] if self.real else page

    def rows_of(self, node: ET.Element, kept: list[int]) -> list[int] | None:
        """The page of each kept row of a table; None: all on the block's page."""
        return [self.plan.rows[id(node)][i] for i in kept] if self.real else None

    def first_row(self, node: ET.Element, kept: list[int], page: int) -> int:
        return self.plan.rows[id(node)][kept[0]] if self.real and kept else page

    def table_read(self, node: ET.Element, rows: list, page: int, heading: str) -> None:
        if self.proof is None:
            return
        if rows:
            nested, boxed, _ = _count_in_part(node)
            self.proof.tables_read += 1 + nested - boxed
        else:
            where = page if self.real else None
            self.proof.not_read.append(
                NotRead("table", None, where, heading, WHY_TABLE_EMPTY)
            )

    def picture_texts(
        self, node: ET.Element, page: int, heading: str
    ) -> list[tuple[str, int]]:
        """Number this block's pictures; (text, page) for each with a reading."""
        out: list[tuple[str, int]] = []
        for element, where in self.plan.pictures.get(id(node), ()) if self.plan else ():
            shown = where if self.real else page
            pic = _picture(element, len(self.pictures) + 1, shown, heading, self.rels)
            self.pictures.append(pic)
            reading = self.readings.get(pic.no)
            if reading is not None and reading.text:
                out.append((f"[picture {pic.no}, read by OCR] {reading.text}", shown))
        return out

    def finish(self, root: ET.Element) -> list[str]:
        """Fill the counts, from the file itself, against what reached the reader.
        A place is a page only when the file has pages. Returns the reader's note."""
        proof = self.proof
        if proof is None:
            return []
        tables, in_boxes, in_file = _count_in_part(root)
        proof.tables_in_file = tables
        proof.pictures_in_file = in_file
        seen = proof.tables_read + sum(1 for n in proof.not_read if n.kind == "table")
        proof.not_read += [
            NotRead("table", None, None, "", WHY_TABLE_IN_TEXT_BOX)
        ] * in_boxes
        proof.not_read += [NotRead("table", None, None, "", WHY_NOT_WALKED)] * max(
            0, tables - in_boxes - seen
        )
        for pic in self.pictures:
            reading = self.readings.get(pic.no) or PictureReading()
            if reading.text:
                proof.pictures_read += 1
                continue
            reason = WHY_NOT_IMAGE.get(pic.kind) or reading.reason or WHY_NOT_SENT
            proof.not_read.append(
                NotRead(
                    "picture",
                    pic.no,
                    pic.page if self.real else None,
                    pic.heading,
                    reason,
                )
            )
        proof.not_read += [NotRead("picture", None, None, "", WHY_NOT_WALKED)] * max(
            0, in_file - len(self.pictures)
        )
        unread = in_file - proof.pictures_read
        return [f"{unread} of {in_file} picture(s) not read"] if unread else []

    def page_numbers(self) -> dict[int, int] | None:
        """The file's own numbers, so no page shifts; None: the parts are made dense."""
        return (
            {n: n for n in range(1, self.plan.pagination.last_page + 1)}
            if self.real
            else None
        )
