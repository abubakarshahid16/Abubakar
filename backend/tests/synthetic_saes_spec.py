"""Synthetic SAES-style specification PDFs for chunking tests. NO CLIENT DATA.

Every document here is invented. The LAYOUT imitates the features of company
engineering standards that broke chunking on the owner's corpus (brief
2026-09-27): a three-line running header ("Document Responsibility: ... /
SAES-X-NNN / Issue Date ..."), a "Page n of N" footer, numbered clauses
(4.1, 4.1.1) with a gap in the numbering, ruled tables (one ending at the foot
of a page, one continued across a page break), paint-system data sheets in
"Label : value" rows (including the value-on-its-own-line form ": 4:1 by
Volume"), paragraphs that run across a page break mid-sentence, words
hyphenated at a line break ("galvan-" / "ized") next to genuine compounds
("carbon-steel"), and long numbered requirement lines ("4.3.1 ... shall ...").

Text is placed LINE BY LINE with `insert_text`, so the extracted line breaks are
exactly the ones written here and a test can reason about them.

    python -m tests.synthetic_saes_spec <out_dir>     # writes the corpus
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

W, H = 612, 792
LM, RM = 72, 540
TOP, BOT = 104, 730
LINE = 13.0
WRAP = 88  # characters per body line

_FILL = [
    "The Contractor shall submit the coating procedure to the Company for review before any work starts.",
    "Surface preparation shall achieve Sa 2.5 cleanliness per ISO 8501-1 with a profile of 50 to 75 micrometres.",
    "Dry film thickness shall be measured in accordance with SSPC-PA 2 and recorded on the inspection plan.",
    "Holiday detection shall be carried out on all immersion service surfaces at the voltage stated on the data sheet.",
    "Coating materials shall be stored in a ventilated area at temperatures between 5 C and 35 C.",
    "Any deviation from this standard requires written approval through the waiver process.",
    "Repairs shall use the same system as the original coating unless the Company approves an alternative.",
    "The relative humidity shall not exceed 85 percent during application and curing of the coating.",
    "Steel temperature shall be at least 3 C above the dew point throughout surface preparation and application.",
    "Abrasives shall be free of oil, moisture and soluble salts, and shall not contain more than 25 ppm chlorides.",
]


def _para(seed: int, n: int) -> str:
    return " ".join(_FILL[(seed * 7 + k * 3) % len(_FILL)] for k in range(n))


def wrap(text: str, width: int = WRAP) -> list[str]:
    """Greedy word wrap. A '|' inside a word forces a line break there, which is
    how a hyphenated line break ("galvan-|ized") is written."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        parts = word.split("|")
        for k, part in enumerate(parts):
            candidate = f"{cur} {part}".strip() if cur else part
            if len(candidate) > width and cur:
                lines.append(cur)
                cur = part
            else:
                cur = candidate
            if k < len(parts) - 1:
                lines.append(cur)
                cur = ""
    if cur:
        lines.append(cur)
    return lines


class SpecWriter:
    """Places lines top to bottom, starting new pages with the running header."""

    def __init__(self, doc_no: str, title: str, committee: str, total_hint: int,
                 header_box: bool = False):
        self.doc = pymupdf.open()
        #: Draw the ruled box a standard prints round its header on every
        #: page - which a table finder reads as a table on every page.
        self.header_box = header_box
        self.doc_no = doc_no
        self.title = title
        self.committee = committee
        self.total = total_hint
        self.page: pymupdf.Page | None = None
        self.y = TOP

    # -- page furniture ---------------------------------------------------
    def new_page(self) -> None:
        self.page = self.doc.new_page(width=W, height=H)
        n = self.doc.page_count
        p = self.page
        p.insert_text((LM, 40), f"Document Responsibility: {self.committee}", fontsize=8)
        p.insert_text((LM, 52), self.doc_no, fontsize=8, fontname="hebo")
        p.insert_text((LM, 64), "Issue Date: 12 March 2024", fontsize=8)
        p.insert_text((300, 64), "Next Planned Update: 12 March 2029", fontsize=8)
        p.insert_text((LM, 76), self.title, fontsize=8)
        p.insert_text((LM, 770), "Saudi Aramco: Company General Use", fontsize=7)
        p.insert_text((480, 770), f"Page {n} of {self.total}", fontsize=7)
        if self.header_box:
            p.draw_rect(pymupdf.Rect(LM - 4, 30, RM, 82), width=0.6)
            p.draw_line((LM - 4, 56), (RM, 56), width=0.6)
            p.draw_line((296, 30), (296, 82), width=0.6)
        self.y = TOP

    def need(self, h: float) -> None:
        if self.page is None or self.y + h > BOT:
            self.new_page()

    def line(self, text: str, bold: bool = False, size: float = 10) -> None:
        self.need(LINE)
        self.page.insert_text((LM, self.y), text, fontsize=size,
                              fontname="hebo" if bold else "helv")
        self.y += LINE

    def gap(self, h: float = 5) -> None:
        self.y += h

    # -- content ------------------------------------------------------------
    def heading(self, num: str, title: str) -> None:
        self.need(LINE * 3)
        self.gap(4)
        self.line(f"{num} {title}", bold=True)
        self.gap(2)

    def para(self, text: str) -> None:
        for ln in wrap(text):
            self.line(ln)
        self.gap(4)

    def table(self, caption: str | None, header: list[str], rows: list[list[str]],
              widths: list[float], rowh: float = 14, keep_caption_on_break: bool = True) -> None:
        self.need(rowh * 3 + 16)
        if caption:
            self.line(caption, bold=True, size=9)

        def draw(cells: list[str], bold: bool = False) -> None:
            x = LM
            top = self.y - 10
            for c, w in zip(cells, widths):
                self.page.draw_rect(pymupdf.Rect(x, top, x + w, top + rowh), width=0.5)
                self.page.insert_text((x + 3, top + 10), str(c), fontsize=8,
                                      fontname="hebo" if bold else "helv")
                x += w
            self.y += rowh

        draw(header, bold=True)
        for r in rows:
            if self.y + rowh > BOT + 10:
                self.new_page()
                if caption and keep_caption_on_break:
                    self.line(f"{caption} (continued)", bold=True, size=9)
                draw(header, bold=True)
            draw(r)
        self.gap(8)

    def save(self, path: Path) -> Path:
        # fix the page total in the footer hint if the guess was wrong: the
        # footer text is already placed, and a wrong total is harmless here.
        self.doc.save(str(path))
        self.doc.close()
        return path


def build_coating_standard(path: Path) -> Path:
    """SAES-H-style coating standard: clauses, tables, gaps, hyphenation."""
    w = SpecWriter("SAES-H-900", "Protective Coating Requirements for Plant Equipment",
                   "Paints and Coatings Standards Committee", 9, header_box=True)
    w.new_page()
    w.heading("1", "Scope")
    w.para(_para(1, 3) + " This standard covers carbon-|steel and low alloy steel surfaces.")
    w.heading("2", "Conflicts and Deviations")
    w.para("Any conflicts between this standard and other applicable Saudi Aramco "
           "Engineering Standards shall be resolved in writing by the Company. " + _para(2, 2))
    w.heading("3", "References")
    w.para("ISO 8501-1 Preparation of steel substrates before application of paints. "
           "SSPC-PA 2 Procedure for determining conformance to dry coating thickness requirements.")
    w.heading("4", "Coating Requirements")
    w.heading("4.1", "General")
    w.para(_para(3, 7) + " Bolting shall be hot-dip galvan-|ized after threading and the "
           "zinc coating shall be free of tempera-|ture damage.")
    w.heading("4.1.1", "Storage")
    w.para(_para(4, 3))
    w.heading("4.1.2", "Mixing")
    w.para("Components shall be mixed by power agitator until homogeneous. " + _para(5, 2))
    # 4.2 is deliberately missing (a deleted clause): 4.3 - 4.6 must keep their labels
    w.heading("4.3", "Surface Preparation")
    w.para(_para(6, 4))
    w.line("4.3.1 Abrasive blast cleaning of carbon steel surfaces for immersion service shall achieve")
    w.line("Sa 3 cleanliness with an angular profile of 75 to 100 micrometres measured by replica tape.")
    w.gap(4)
    w.para("4.3.2 Hand tool cleaning shall only be used for areas smaller than 0.1 square metres.")
    w.table("Table 1 - Minimum Surface Profile", ["Service", "Substrate", "Profile (um)", "Method"],
            [["Immersion", "Carbon steel", "75 - 100", "Replica tape"],
             ["Atmospheric", "Carbon steel", "50 - 75", "Replica tape"],
             ["Buried", "Carbon steel", "50 - 100", "Comparator"],
             ["High temperature", "Stainless steel", "25 - 50", "Comparator"],
             ["Galvanized", "Zinc", "15 - 25", "Sweep blast"]],
            [110, 100, 90, 110])
    w.heading("4.4", "Application")
    w.para(_para(7, 9))
    w.heading("4.5", "Inspection")
    w.para(_para(8, 12))
    # a table that ends at the foot of the page: its last rows' values sit in
    # the last lines of the page, where the running-line stripper looks
    w.need(10 * 14)
    remaining = int((BOT - w.y) // 14) - 3
    rows = [[f"{k}", f"{50 + 25 * k}", f"{100 + 50 * k}", f"{k + 1}"] for k in range(1, max(4, remaining))]
    w.table("Table 2 - Holiday Test Voltage", ["Coats", "DFT (um)", "Voltage (V)", "Passes"],
            rows, [80, 100, 100, 80])
    w.heading("4.6", "Repairs")
    w.para(_para(9, 10))
    w.table("Table 3 - Coating Systems", ["System", "Primer", "Primer DFT (um)", "Total DFT (um)",
                                          "Max temp (C)"],
            [[f"CS-{k:02d}", ["Epoxy zinc", "Inorganic zinc", "TSA", "Epoxy phenolic"][k % 4],
              f"{40 + (k * 7) % 50}", f"{150 + (k * 37) % 200}", f"{[80, 120, 150, 200][k % 4]}"]
             for k in range(1, 45)],
            [70, 120, 90, 90, 80])
    w.heading("5", "Documentation")
    w.para(_para(10, 6))
    return w.save(path)


_APCS = [
    ("APCS-1A", "Epoxy Primer / Epoxy Topcoat System", "Two-component polyamide cured epoxy",
     "4:1 by Volume", "Yellow (RAL 1023)", "CS = Abrasive blast Sa 3, profile 50 - 75 um"),
    ("APCS-2B", "Inorganic Zinc / Epoxy / Polyurethane System", "Ethyl silicate inorganic zinc",
     "3:1 by Volume", "Grey (RAL 7035)", "CS = Abrasive blast Sa 2.5, profile 40 - 75 um"),
    ("APCS-3", "Epoxy Phenolic Tank Lining", "Amine cured epoxy phenolic",
     "2:1 by Volume", "White (RAL 9010)", "CS = Abrasive blast Sa 3, profile 75 - 100 um"),
    ("APCS-4", "High Temperature Silicone System", "Modified silicone aluminium",
     "Single pack", "Aluminium", "SS = Sweep blast, profile 25 - 50 um"),
]


def build_paint_data_sheets(path: Path) -> Path:
    """SAES-H-101V style: one data sheet per page, 'Label : value' rows."""
    w = SpecWriter("SAES-H-901V", "Approved Protective Coating Systems (Data Sheets)",
                   "Paints and Coatings Standards Committee", len(_APCS) + 1)
    w.new_page()
    w.heading("1", "Scope")
    w.para("This standard lists the approved protective coating systems and their data sheets. "
           "Each data sheet states the mandatory properties of one system. " + _para(11, 2))
    w.heading("2", "Use of the Data Sheets")
    w.para(_para(12, 3))
    for code, title, generic, ratio, colour, prep in _APCS:
        w.new_page()
        w.line(code, bold=True, size=11)
        w.line(title, bold=True)
        w.gap(4)
        w.line("1 General")
        w.line(f"1.1 Generic Type : {generic}")
        w.line("1.2 Service : Atmospheric exposure up to 120°C")
        w.line("2 Surface Preparation")
        w.line(f": {prep}")
        w.line("3 Application")
        w.line("3.1 Number of Coats : 2")
        w.line("3.2 DFT per Coat : 125 - 150 um")
        w.line("4 Mixing and Curing")
        w.line("4.1 Mixing Ratio")
        w.line(f": {ratio}")
        w.line("4.2 Induction Time : 15 minutes at 25°C")
        w.line("4.3 Pot Life")
        w.line(": 4 hours at 25°C, 2 hours at")
        w.line(": 35°C (Mixed)")
        w.line(f"4.5 Approved Color/s : {colour}")
        w.line("4.6 Recoat Interval : 16 hours minimum, 7 days maximum")
        w.gap(6)
        w.para("Note: The system shall be applied by airless spray. Brush application is "
               "limited to stripe coats and repairs smaller than 0.1 square metres.")
    return w.save(path)


def build_piping_standard(path: Path) -> Path:
    """SAES-L style: split tables, long requirements, sentences across pages."""
    w = SpecWriter("SAES-L-910", "Piping Material Selection",
                   "Piping Standards Committee", 8)
    w.new_page()
    w.heading("1", "Scope")
    w.para(_para(13, 4))
    w.heading("2", "References")
    w.para("ASME B31.3 Process Piping. API 5L Specification for Line Pipe. "
           "ASTM A106 Seamless Carbon Steel Pipe for High-Temperature Service.")
    w.heading("3", "Definitions")
    w.para("Company : Saudi Aramco. Contractor : the party performing the work. "
           "Shall : indicates a mandatory requirement.")
    w.heading("4", "Materials")
    w.heading("4.1", "Pipe")
    w.para(_para(14, 16))
    w.table("Table 1 - Pipe Material Selection",
            ["Service", "Size range", "Material", "Schedule", "CA (mm)"],
            [["Hydrocarbon", '1/2" - 1 1/2"', "ASTM A106 Gr B", "160", "3.0"],
             ["Hydrocarbon", '2" - 24"', "API 5L Gr B PSL2", "80", "3.0"],
             ["Seawater", '1/2" - 12"', "UNS S32760", "40S", "0.0"],
             ["Instrument air", '1/2" - 2"', "ASTM A312 TP316L", "10S", "0.0"],
             ["Firewater", '2" - 16"', "90/10 CuNi", "Class 200", "0.0"],
             ["Produced water", '2" - 20"', "ASTM A106 Gr B + lined", "STD", "1.5"]],
            [110, 80, 150, 70, 60])
    w.heading("4.2", "Bolting")
    w.para(_para(15, 3))
    w.line("4.2.1 Stud bolts for flanges in hydrocarbon service shall be ASTM A193 Grade B7 with a")
    w.line("minimum yield strength of 725 MPa and shall be supplied with certified mill test reports.")
    w.gap(4)
    w.para("4.2.2 Nuts shall be heavy hex ASTM A194 Grade 2H.")
    w.heading("4.3", "Gaskets")
    w.para(_para(16, 20))
    w.heading("5", "Fabrication")
    w.heading("5.1", "Welding")
    w.para(_para(17, 14))
    w.heading("5.2", "Heat Treatment")
    w.para(_para(18, 5))
    w.table("Table 2 - Post Weld Heat Treatment", ["P-No", "Thickness (mm)", "Temp (C)", "Hold (h/25mm)"],
            [["1", "> 19", "595 - 650", "1"], ["3", "> 16", "595 - 720", "1"],
             ["4", "> 13", "650 - 705", "1"], ["5A", "all", "705 - 760", "1"]],
            [80, 110, 110, 110])
    w.heading("6", "Inspection")
    w.heading("6.1", "Visual Examination")
    w.para(_para(19, 18))
    w.heading("6.2", "Radiography")
    w.para(_para(20, 12))
    w.heading("6.3", "Hardness Testing")
    w.para(_para(21, 16))
    w.heading("7", "Documentation")
    w.para(_para(22, 14))
    return w.save(path)


BUILDERS = {
    "saes_h_900.pdf": build_coating_standard,
    "saes_h_901v.pdf": build_paint_data_sheets,
    "saes_l_910.pdf": build_piping_standard,
}


def build_corpus(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return [fn(out_dir / name) for name, fn in BUILDERS.items()]


if __name__ == "__main__":
    for p in build_corpus(Path(sys.argv[1] if len(sys.argv) > 1 else ".")):
        print("wrote", p)
