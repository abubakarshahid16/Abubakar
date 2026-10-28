// Saved once by scripts/board_export_run.py when the run finished. Holds document text: this machine only.
window.BOARD = window.BOARD || { runs: {} };
window.BOARD.runs["run1"] = window.BOARD.runs["run1"] || {};
window.BOARD.runs["run1"].decisions = [
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
 }
];
