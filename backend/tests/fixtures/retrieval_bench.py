"""B6 retrieval benchmark: a small, committed, synthetic corpus with labelled queries.

WHAT THIS IS. Three made-up engineering standards, one numbered clause per
page, written for this benchmark. No client document, identifier or number is
used; public standard names (API 682, ASTM A216, SSPC-PA 2) appear only as the
kind of citation a real specification carries. Results measured on this set
are labelled SYNTHETIC wherever they are reported - they say whether the
pipeline works, not how well it does on the client's corpus. The real-corpus
measurement is `scripts/eval_retrieval.py` on the owner's machine.

THE QUERIES come in three kinds, because each part of the pipeline has a job
the others cannot do:

  EXACT       shares the clause's distinctive words or identifiers - what FTS5
              keyword search is for;
  PARAPHRASE  asks the same thing in other words, sharing no content word with
              the clause - only the dense (semantic) side can find it;
  NEGATIVE    asks something no clause answers - every metric should approach
              zero and the pipeline should say its evidence is weak (ADR-0022).

Each positive query names the ONE page that answers it: (document key, page).
"""
from __future__ import annotations

#: {document key: [(clause heading, clause body), ...]} - one clause per page.
CORPUS: dict[str, list[tuple[str, str]]] = {
    "PUMPSPEC": [
        ("5.3.2 Vibration Limits",
         "Vibration measured at the bearing housing shall not exceed 3.0 mm/s RMS "
         "during continuous operation at rated flow."),
        ("6.1.4 Mechanical Seals",
         "Seals shall be cartridge type per API 682 category 2, with seal flush "
         "plan 11 for clean hydrocarbon service."),
        ("7.1 Materials of Construction",
         "The casing shall be ASTM A216 WCB, the impeller CA6NM and the shaft "
         "AISI 4140 for all centrifugal pumps."),
        ("8.3.2 Hydrostatic Test",
         "Pressure casings shall be hydrotested at 1.5 times the maximum allowable "
         "working pressure for 30 minutes without visible leakage."),
        ("9.2 Noise",
         "The sound pressure level at 1 m from the equipment shall not exceed "
         "85 dB(A) at any operating point."),
        ("10.4 Driver Rating",
         "The motor nameplate rating shall be at least 110 percent of the pump "
         "rated power at the end of curve."),
    ],
    "VESSELSPEC": [
        ("4.2 Design Pressure",
         "Vessels shall be designed for the maximum operating pressure plus "
         "10 percent or 2 bar, whichever is greater."),
        ("4.5 Corrosion Allowance",
         "A minimum corrosion allowance of 3 mm shall be applied to carbon steel "
         "in wet hydrocarbon service."),
        ("6.1 Nozzles",
         "Nozzle necks of 2 inch nominal size and smaller shall be schedule 160 "
         "seamless pipe."),
        ("7.3 Post Weld Heat Treatment",
         "Post weld heat treatment is required when the nominal wall thickness "
         "exceeds 38 mm."),
        ("8.1 Impact Testing",
         "Charpy impact testing shall be performed at the minimum design metal "
         "temperature of -29 C."),
    ],
    "COATSPEC": [
        ("3.1 Surface Preparation",
         "Abrasive blast cleaning to Sa 2.5 with a surface profile of 50 to 75 "
         "micrometres before the first coat."),
        ("3.4 Coating System",
         "Epoxy primer 75 micrometres, epoxy intermediate 150 micrometres and "
         "polyurethane topcoat 50 micrometres dry film thickness."),
        ("5.2 Inspection",
         "Dry film thickness shall be measured per SSPC-PA 2 with at least five "
         "spot readings per 10 square metres."),
        ("6.1 Repair",
         "Damaged areas shall be repaired with the original system after the "
         "edges are feathered back to sound material."),
    ],
}

#: (query, kind, (document key, page)) - page is 1-based.
POSITIVES: list[tuple[str, str, tuple[str, int]]] = [
    # EXACT: identifiers, numbers, distinctive terms
    ("API 682 category 2 seal flush plan", "exact", ("PUMPSPEC", 2)),
    ("ASTM A216 WCB casing CA6NM impeller", "exact", ("PUMPSPEC", 3)),
    ("3.0 mm/s RMS bearing housing vibration", "exact", ("PUMPSPEC", 1)),
    ("schedule 160 nozzle necks", "exact", ("VESSELSPEC", 3)),
    ("post weld heat treatment 38 mm wall", "exact", ("VESSELSPEC", 4)),
    ("Sa 2.5 abrasive blast surface profile", "exact", ("COATSPEC", 1)),
    ("SSPC-PA 2 spot readings", "exact", ("COATSPEC", 3)),
    ("Charpy impact testing minimum design metal temperature", "exact", ("VESSELSPEC", 5)),
    # PARAPHRASE: the same question with none of the clause's content words
    ("how strongly may the machine shake", "paraphrase", ("PUMPSPEC", 1)),
    ("how loud is it allowed to be", "paraphrase", ("PUMPSPEC", 5)),
    ("how big must the electric motor be compared with what it drives",
     "paraphrase", ("PUMPSPEC", 6)),
    ("extra metal thickness to allow for rust", "paraphrase", ("VESSELSPEC", 2)),
    ("how do we fix scratched paint", "paraphrase", ("COATSPEC", 4)),
    ("which layers of paint are applied and how thick is each",
     "paraphrase", ("COATSPEC", 2)),
    ("toughness check in the cold", "paraphrase", ("VESSELSPEC", 5)),
    ("water test to prove the housing holds without leaking",
     "paraphrase", ("PUMPSPEC", 4)),
]

#: Questions no clause answers.
NEGATIVES: list[str] = [
    "helicopter deck lighting levels",
    "cathodic protection anode spacing",
    "cable tray support spacing",
    "HVAC duct insulation",
    "fire alarm panel battery autonomy",
]
