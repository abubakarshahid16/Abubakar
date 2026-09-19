# Phase 6 visual record

Captured 2026-09-19 against the real corpus, not fixtures: the drum sheet's
review run `run_c5d5f037538b` (1,580 findings, 2 needing engineer review) and
the standards actually in its scope.

| file | what it shows |
|---|---|
| `A-runs-list.png` | 9 runs: submittal, equipment tag, date, standards in scope, every status count with its denominator, the recommended code with its reason verbatim including the NOMINAL-estimate note |
| `B-findings-table.png` | the 2 findings that need a person, and the 1,578 with no evidence collapsed behind their own count |
| `C-finding-detail.png` | full requirement, the rationale verbatim, both citations, engineer actions |
| `D-citation-1.png` | the standard citation opened at its cited page (SAES-E-014, page 10) |
| `D-citation-2.png` | the submittal citation opened at its cited page (page 4) |
| `E-confirmed.png` | the confirmed badge after a real round-trip: who and when |
| `PDF-headed.png` | **the proof that `#page=N` works** - headed Chromium renders SAES-E-014 at section 7 "Mechanical Design", which is where the cited clause 7.2.4 lives |
| `PDF-headless.png` | the identical view in headless Chromium, blank. The embedded PDF viewer does not paint there. Kept so nobody re-investigates a defect that is in the harness, not the app |

## What is in these images

They are screenshots of the application showing **client document content**:
requirement sentences from the SAES standards, and one submitted value
(`2.2 bar (ga)`) with its field name and equipment tag from the contractor
datasheet. The embedded PDF panes in `D-citation-1` and `D-citation-2` are
blank, because they were captured headless; the only image containing PDF text
is `PDF-headed.png`, which shows a SAES standard's header.

None of it is `Engineering Deliverables.pdf`, which CLAUDE.md rule 3 keeps out
of the repository entirely. Committed at the maintainer's explicit request so
the visual record outlives a temp folder - flagged here because the branch is
pushed to GitHub eventually, and a screenshot is document text like any other.
