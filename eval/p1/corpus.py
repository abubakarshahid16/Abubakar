"""The P1 invented corpus: seven made-up standards, no client text.

Every name, number and sentence here is invented. The set is small on purpose
and built to hit the failure classes found in this project: a reworded
question, an abbreviation, a document named in the question, the same
boilerplate in two documents, a value that lives in a table, a condition that
limits a rule, an old revision beside a new one, and a topic one document has
and another does not.

`build(folder)` writes the PDFs deterministically. Page numbers below are the
ground truth the question set points at; `questions.json` is checked against
this text by `check_labels` so a label can never drift from the corpus.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

# filename -> list of pages -> list of lines
DOCS: dict[str, list[list[str]]] = {
    "STD-A-001.pdf": [
        [
            "STD-A-001 Rotating Equipment Inspection and Vibration, Revision 1",
            "1 Scope",
            "1.1 This standard covers centrifugal pumps in continuous service.",
            "1.2 It does not cover reciprocating pumps.",
            "2 Abbreviations",
            "RMS means root mean square.",
            "MTBF means mean time between failures.",
        ],
        [
            "3 Inspection",
            "3.1 Each pump shall be inspected at intervals not exceeding 4000",
            "operating hours.",
            "3.2 Any exceedance shall be reported to the area engineer before the",
            "pump is returned to service.",
        ],
        [
            "4 Vibration",
            "4.1 Vibration measured at the bearing housing shall not exceed",
            "3.0 mm/s RMS during continuous operation at rated flow.",
            "4.2 Readings shall be taken monthly.",
            "Table 2 Bearing temperature limits",
            "Item  Alarm  Trip",
            "Drive end bearing  85 degC  95 degC",
            "Non drive end bearing  80 degC  90 degC",
        ],
    ],
    "STD-A-001-REV0.pdf": [
        [
            "STD-A-001 Rotating Equipment Inspection and Vibration, Revision 0",
            "This revision was replaced by Revision 1.",
            "4 Vibration",
            "4.1 Vibration measured at the bearing housing shall not exceed",
            "2.5 mm/s RMS during continuous operation at rated flow.",
        ],
    ],
    "STD-B-002.pdf": [
        [
            "STD-B-002 Protective Coating of Piping, Revision 2",
            "1 Scope",
            "1.1 This standard applies to carbon steel piping only.",
            "1.2 Stainless steel piping is not coated under this standard.",
            "2 Abbreviations",
            "DFT means dry film thickness.",
        ],
        [
            "3 Surface preparation",
            "3.1 Surfaces shall be blast cleaned to Sa 2.5 before coating.",
            "3.2 Coating shall be applied within 4 hours of blast cleaning.",
        ],
        [
            "4 Coating system",
            "4.1 The minimum DFT of the primer coat shall be 250 micrometres.",
            "4.2 The finish coat shall be applied after the primer has cured.",
        ],
    ],
    "STD-C-003.pdf": [
        [
            "STD-C-003 Pressure Vessel Testing and Heat Treatment, Revision 3",
            "1 Scope",
            "1.1 This standard covers fabricated pressure vessels.",
            "2 Abbreviations",
            "PWHT means post weld heat treatment.",
            "MAWP means maximum allowable working pressure.",
        ],
        [
            "6 Heat treatment",
            "6.1 PWHT shall be carried out when the shell thickness exceeds",
            "32 mm.",
            "6.2 The holding temperature shall be recorded on a chart.",
        ],
        [
            "7 Hydrostatic test",
            "7.1 The hydrostatic test pressure shall be 1.3 times the design",
            "pressure.",
            "7.2 The test pressure shall be held for 30 minutes.",
            "7.3 Any exceedance shall be reported to the area engineer.",
        ],
    ],
    "STD-D-004.pdf": [
        [
            "STD-D-004 Electrical Enclosure Protection, Revision 1",
            "1 Scope",
            "1.1 This standard covers electrical enclosures installed outdoors.",
            "2 Protection rating",
            "2.1 Outdoor enclosures shall have a minimum rating of IP66.",
            "2.2 The design ambient temperature shall be 50 degC.",
        ],
        [
            "3 Cable entries",
            "3.1 Unused cable entries shall be closed with certified plugs.",
        ],
    ],
    "STD-E-005.pdf": [
        [
            "STD-E-005 Fire Water Pump Testing, Revision 1",
            "1 Scope",
            "1.1 This standard covers diesel driven fire water pumps.",
            "2 Weekly test",
            "2.1 Each pump shall be run for 30 minutes every week.",
        ],
        [
            "3 Annual test",
            "3.1 Each pump shall deliver 150 percent of rated flow at not less",
            "than 65 percent of rated head.",
            "3.2 Any exceedance shall be reported to the area engineer.",
        ],
    ],
    "STD-F-006.pdf": [
        [
            "STD-F-006 Noise Control, Revision 1",
            "1 Scope",
            "1.1 This standard covers noise exposure in process areas.",
        ],
        [
            "4 Limits",
            "4.1 Areas where noise exceeds 85 dB(A) shall be marked as hearing",
            "protection zones.",
            "4.2 Noise exposure shall not exceed 90 dB(A) for any worker.",
        ],
    ],
}


def build(folder: Path) -> list[Path]:
    """Write every PDF into `folder`, in a fixed order, and return the paths."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in sorted(DOCS):
        pdf = pymupdf.open()
        for lines in DOCS[name]:
            page = pdf.new_page()
            for i, line in enumerate(lines):
                page.insert_text((72, 100 + i * 18), line, fontsize=11)
        path = folder / name
        pdf.save(str(path))
        pdf.close()
        paths.append(path)
    return paths


def page_text(filename: str, page: int) -> str:
    return " ".join(DOCS[filename][page - 1])
