"""A Word file read for the datasheet fact reader (#1473, PAGE_READ_BY_READING_ENABLED).

The pages are `docx_reader`'s own reading pages - the pages `extract._docx_rows`
stores a Word file's chunks under - so a fact cites the page its chunk and
citation use. Workbooks are not pulled in (DATASHEET_OFFICE_INPUT also indexes
CRS template workbooks). Ids and counts only; never logs page text.
"""

from __future__ import annotations

from pathlib import Path

from . import datasheet_inputs, docx_reader
from .config import settings


def applies(path: str | None) -> bool:
    """True when the switch and DOCX_INPUT_ENABLED are on, DATASHEET_OFFICE_INPUT
    is not, and `path` is a Word document."""
    if (
        not path
        or not settings.page_read_by_reading_enabled
        or not settings.docx_input_enabled
        or (settings.datasheet_office_input and not settings.word_page_markers_enabled)
    ):
        return False
    try:
        st = Path(path).stat()
    except OSError:
        return False
    return datasheet_inputs._kind_cached(str(path), st.st_mtime_ns, st.st_size) == (
        datasheet_inputs.KIND_DOCX
    )


def reading(path: str) -> datasheet_inputs.Reading:
    """The Word file as `docx_reader` pages it, in the rules reader's shape:
    each page's lines, a table line (`| a | b |`) split into its cells."""
    structure = docx_reader.read_structure(path)
    pages = []
    for number, text in enumerate(structure.pages, start=1):
        rows = []
        for line in text.split("\n"):
            if line.startswith("| ") and line.endswith(" |"):
                cells = [c.strip() for c in line[2:-2].split(" | ")]
            else:
                cells = [line.strip()]
            cells = tuple(c for c in cells if c)
            if cells:
                rows.append(cells)
        pages.append(
            datasheet_inputs.PageText(
                page_no=number,
                text=text,
                source=datasheet_inputs.SOURCE_DOCX,
                rows=tuple(rows),
            )
        )
    return datasheet_inputs.Reading(pages=pages, notes=list(structure.notes))
