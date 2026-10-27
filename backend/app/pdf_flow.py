"""Text that never falls off a PDF page (#633 item 6).

`page.insert_textbox` draws nothing past its rectangle and `page.insert_text`
draws past the page edge, where nothing is visible. Both lose text with no
sign. The review PDF (`review.render_report`) draws through this module
instead: every string is wrapped to the printable width by MEASURED glyph
widths, and a block that does not fit the page continues on the next page
under a "(continued)" line. Layout only: nothing here decides what a report
says.
"""

from __future__ import annotations

import pymupdf

from . import pdf_guard

LEFT, RIGHT, TOP, BOTTOM = 48.0, 548.0, 48.0, 790.0
#: Inside a box the text is inset from the border on both sides.
BOX_PAD = 8.0
CONTINUED = "(continued from the previous page)"


def wrap(text: str, width: float, fontsize: float, fontname: str = "helv") -> list[str]:
    """`text` as lines no wider than `width` points, paragraph breaks kept.

    Greedy word wrap on measured widths; a single word wider than the line
    (a long id, a URL) is split between characters rather than dropped.
    """

    def fits(s: str) -> bool:
        with pdf_guard.held():
            return (
                pymupdf.get_text_length(s, fontname=fontname, fontsize=fontsize)
                <= width
            )

    out: list[str] = []
    for paragraph in (text or "").replace("\r", "").split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if fits(candidate):
                line = candidate
                continue
            if line:
                out.append(line)
            while not fits(word):
                cut = next(
                    (i for i in range(len(word) - 1, 0, -1) if fits(word[:i])), 1
                )
                out.append(word[:cut])
                word = word[cut:]
            line = word
        out.append(line)
    return out


class Flow:
    """A cursor down a PDF that opens a new page when the next piece of text
    would not fit, so a caller never positions text below the page."""

    def __init__(self, pdf: pymupdf.Document) -> None:
        self.pdf = pdf
        self.page = pdf.new_page()
        self.y = TOP

    def _room(self, height: float) -> None:
        if self.y + height > BOTTOM:
            self.page = self.pdf.new_page()
            self.y = TOP

    def gap(self, points: float) -> None:
        self.y += points

    def text(
        self,
        text: str,
        *,
        fontsize: float,
        fontname: str = "helv",
        color: tuple | None = None,
        lineheight: float = 1.25,
        x: float = LEFT,
        width: float | None = None,
    ) -> None:
        """One paragraph, wrapped to the printable width, page breaks allowed
        between its lines."""
        step = fontsize * lineheight
        for line in wrap(text, width or (RIGHT - x), fontsize, fontname):
            self._room(step)
            self.y += fontsize
            self.page.insert_text(
                (x, self.y),
                line,
                fontsize=fontsize,
                fontname=fontname,
                **({"color": color} if color else {}),
            )
            self.y += step - fontsize

    def box(
        self,
        text: str,
        *,
        fontsize: float = 8.5,
        fontname: str = "helv",
        color: tuple | None = None,
        border: tuple | None = None,
        fill: tuple | None = None,
        lineheight: float = 1.25,
    ) -> int:
        """A bordered block of wrapped text that CONTINUES on the next page
        when it does not fit, never cut. Returns the number of pages it spans."""
        step = fontsize * lineheight
        lines = wrap(text, RIGHT - LEFT - 2 * BOX_PAD, fontsize, fontname)
        pages = 0
        while lines:
            self._room(step + 2 * BOX_PAD)
            if pages:
                lines = [CONTINUED, *lines]
            room = int((BOTTOM - self.y - 2 * BOX_PAD) // step)
            chunk, lines = lines[: max(1, room)], lines[max(1, room) :]
            height = len(chunk) * step + 2 * BOX_PAD
            self.page.draw_rect(
                pymupdf.Rect(LEFT, self.y, RIGHT, self.y + height),
                color=border,
                fill=fill,
                width=0.5,
            )
            self.page.insert_text(
                (LEFT + BOX_PAD, self.y + BOX_PAD + fontsize * 0.9),
                chunk,
                fontsize=fontsize,
                fontname=fontname,
                lineheight=lineheight,
                **({"color": color} if color else {}),
            )
            self.y += height
            pages += 1
            if lines:
                self.page = self.pdf.new_page()
                self.y = TOP
        return pages
