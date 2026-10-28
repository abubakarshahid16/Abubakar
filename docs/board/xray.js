// Saved once by scripts/board_export_run.py when the run finished. Holds document text: this machine only.
window.BOARD = window.BOARD || { runs: {} };
window.BOARD.runs["run1"] = window.BOARD.runs["run1"] || {};
window.BOARD.runs["run1"].xray = [
 {
  "id": "run",
  "title": "The review",
  "note": "The run's own record.",
  "columns": [
   "item",
   "value"
  ],
  "rows": [
   [
    "review run",
    "run1"
   ],
   [
    "datasheet",
    "sheet.pdf"
   ],
   [
    "status",
    "completed"
   ],
   [
    "model",
    "m1"
   ],
   [
    "started",
    "2026-10-28T00:00:00Z"
   ],
   [
    "completed",
    "2026-10-28T00:00:00Z"
   ],
   [
    "config version",
    "cfg1"
   ],
   [
    "requirements: checked",
    "3"
   ],
   [
    "requirements: applies_not_checked",
    "7"
   ],
   [
    "requirements: note",
    "x"
   ]
  ],
  "counts": {},
  "fold": null
 },
 {
  "id": "pages",
  "title": "1. The document: pages",
  "note": "Per page: text layer, OCR, the index, whether fields were read, and why not.",
  "columns": [
   "page",
   "chars",
   "text layer",
   "OCR",
   "index",
   "fields read",
   "picture reader"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "reader_run",
  "title": "2a. The datasheet reader's run",
  "note": "No reader summary is stored for this document.",
  "columns": [
   "item",
   "value"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "facts",
  "title": "2b. Every value read (current)",
  "note": "By method: none. The quote is the sheet's own text the value was read from.",
  "columns": [
   "page",
   "field",
   "value",
   "unit",
   "quote",
   "reader",
   "confidence",
   "check",
   "confirmed by"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "classification",
  "title": "3. Equipment type, title and discipline",
  "note": "No classification is stored.",
  "columns": [
   "what",
   "value",
   "quote",
   "page",
   "how",
   "confidence"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "standards",
  "title": "4. Standards: chosen, dropped, and cited but not held",
  "note": "0 standard(s) the datasheet cites are not in the library (listed last).",
  "columns": [
   "standard",
   "state",
   "route",
   "reason",
   "why dropped",
   "confidence",
   "evidence",
   "part-scope reading"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "coverage",
  "title": "5. Requirements per standard and how each was handled",
  "note": "State: checked / applies, not checked / does not apply. The reason code says which gate (scope, citation, service, table, ...) decided.",
  "columns": [
   "standard",
   "requirements stored",
   "state",
   "gate / reason",
   "count",
   "an example reason"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "pairing",
  "title": "6. Pairing: requirement to sheet field",
  "note": "Method says how the pair was made (name, containment, field name by a model, a question to the model). 0 pairing(s) rejected by an engineer.",
  "columns": [
   "clause",
   "requirement",
   "sheet field",
   "value",
   "page",
   "method",
   "matched phrase"
  ],
  "rows": [
   [
    "",
    "req 0",
    "(no field paired)",
    "",
    "",
    "",
    ""
   ],
   [
    "",
    "req 1",
    "(no field paired)",
    "",
    "",
    "",
    ""
   ],
   [
    "",
    "req 2",
    "(no field paired)",
    "",
    "",
    "",
    ""
   ]
  ],
  "counts": {},
  "fold": null
 },
 {
  "id": "comparison",
  "title": "7. Comparison: required, offered, verdict and the rule",
  "note": "Counts per verdict first (held requirements are in 7b, but counted here). 'Offered, converted' shows the unit conversion the arithmetic used. Rows 'not in document scope' are folded below the table.",
  "columns": [
   "clause",
   "verdict",
   "required",
   "offered",
   "offered, converted",
   "condition",
   "reason code",
   "why"
  ],
  "rows": [
   [
    "",
    "COMPLIANT",
    "(no number)",
    "",
    "",
    "",
    "",
    ""
   ],
   [
    "",
    "COMPLIANT",
    "(no number)",
    "",
    "",
    "",
    "",
    ""
   ],
   [
    "",
    "MISSING_INFORMATION",
    "(no number)",
    "",
    "",
    "",
    "",
    ""
   ]
  ],
  "counts": {
   "COMPLIANT": 2,
   "MISSING_INFORMATION": 1
  },
  "fold": [
   1,
   "NOT_IN_DOCUMENT_SCOPE"
  ]
 },
 {
  "id": "held",
  "title": "7b. Held requirements, by standard and reason",
  "note": "Requirements that apply but were NOT compared with the datasheet (an engineer decides). Grouped; the full list is in the run's scope ledger.",
  "columns": [
   "standard",
   "reason held",
   "requirements",
   "first clauses"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 },
 {
  "id": "crs",
  "title": "8. The comment sheet (contractor rows)",
  "note": "As the review screen builds them (the same code). Built from a temporary copy; the original is untouched.",
  "columns": [
   "no.",
   "kind",
   "priority",
   "page / section",
   "comment",
   "standard",
   "confirmed"
  ],
  "rows": [
   [
    1,
    "missing_information",
    2,
    "p.3",
    "Requirement: \"req 2.\" Datasheet p.3, states no readable value. Contractor to provide the value.",
    "",
    "no"
   ]
  ],
  "counts": {},
  "fold": null
 },
 {
  "id": "ai",
  "title": "9. Steps and AI answers",
  "note": "The AI task cache has no run id, so these counts are for the whole database, not only this review; a call that was answered live and not cached is not recorded anywhere. Steps are from the run's stored trace.",
  "columns": [
   "kind",
   "name",
   "status / model",
   "what",
   "seconds"
  ],
  "rows": [],
  "counts": {},
  "fold": null
 }
];
