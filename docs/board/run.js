// Saved once by scripts/board_export_run.py when the run finished. Holds document text: this machine only.
window.BOARD = window.BOARD || { runs: {} };
window.BOARD.runs["run1"] = window.BOARD.runs["run1"] || {};
window.BOARD.runs["run1"].run = {
 "id": "run1",
 "status": "completed",
 "started_at": "2026-10-28T00:00:00Z",
 "completed_at": "2026-10-28T00:00:00Z",
 "model_name": "m1",
 "config_version": "cfg1",
 "run_settings": {
  "settings": {
   "geometry_reader_enabled": true
  }
 },
 "recommended_code": "B",
 "outcome": {
  "recommended_code": "B",
  "reason": "r",
  "requirement_split": {
   "checked": 3,
   "applies_not_checked": 7,
   "note": "x"
  }
 },
 "numbers": [
  {
   "label": "findings",
   "value": 3,
   "source_file": "findings.js",
   "source_path": "count of rows"
  },
  {
   "label": "findings: COMPLIANT",
   "value": 2,
   "source_file": "findings.js",
   "source_path": "count where compliance_status = COMPLIANT"
  },
  {
   "label": "findings: MISSING_INFORMATION",
   "value": 1,
   "source_file": "findings.js",
   "source_path": "count where compliance_status = MISSING_INFORMATION"
  },
  {
   "label": "checked",
   "value": 3,
   "source_file": "run.js",
   "source_path": "outcome.requirement_split.checked"
  },
  {
   "label": "applies not checked",
   "value": 7,
   "source_file": "run.js",
   "source_path": "outcome.requirement_split.applies_not_checked"
  }
 ]
};
