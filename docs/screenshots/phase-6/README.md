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

## Closing Phase 6: the entry point and the final code

Captured the same day, signed in as an ordinary **non-admin engineer** - which
is how the admin gate on the final-code route was found (see the commit).

| file | what it shows |
|---|---|
| `F-dashboard.png` | CLAUDE.md rule 10 on screen: exactly four cards, each with its denominator (`0 of 2 awaiting review`, `21 of 21 cited standards are not in the library`, `0 running · 8 awaiting an engineer's code`), the Needs Attention tile listing **why** rather than a bare 9, one button, one compact Recent Reviews table |
| `G-run-from-dashboard.png` | the one button opened in place: pick a loaded submittal and run, with upload sent to the Documents page where upload progress actually lives |
| `H-review-code.png` | both codes side by side - the system's recommendation with its reason verbatim, including the NOMINAL-estimate note, beside `Not decided yet.` |
| `I-override-needs-reason.png` | choosing a code that differs from the recommendation makes the reason field appear, marked required |
| `J-override-refused.png` | pressing Record with no reason: the refusal is shown, not swallowed |
| `K-decided.png` | after the decision: **both** codes still on screen, the override reason, who decided and when, and the line explaining that this run can no longer be re-run - a new review starts a new run |

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
