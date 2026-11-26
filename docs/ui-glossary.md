# EPC Intelligence UI glossary

One concept has one label everywhere:

| Concept | Approved term | Avoid |
| --- | --- | --- |
| A submitted engineering file | Document | file, upload, attachment |
| A tracked engineering output | Deliverable | item |
| A document-based review result | Finding | issue, comment, defect |
| A date that needs action | Due date | deadline, target date |
| A person accountable for delivery | Owner | assignee, responsible |
| A person who validates a deliverable | Reviewer | checker, verifier |
| A person who accepts a deliverable | Approver | sign-off person |
| A risk requiring attention | Risk | concern, problem |
| A contractor document sent for review | Submittal | - |

**"Submittal" was on the avoid list and is not any more.** The ban was written
against the DELIVERABLES vocabulary - a tracked engineering output is a
Deliverable - and it was right about that. It then collided with the AI
Submittal Review workflow (master plan section 16), whose name contains the
word and whose subject is a contractor's submittal: a document somebody sends
for review, which is a different thing from a deliverable being tracked. The
navigation says "AI Submittal Review", so a rule forbidding the word was
forbidding the product from naming itself.  enforces the
rest of this table and additionally bans the old client name, which CLAUDE.md
forbids in code, docs and UI and which nothing had been checking.

Status labels use the shared badge vocabulary: Ready, In progress, Needs
attention, Overdue, Approved, and Not configured.

## Everyday words (E3, owner 26 Nov 2026, goal "easy to use")

The client's engineer reads every screen. The words the system uses for its own
insides are not shown outside **Advanced** (the Admin screen and the folded
technical-details parts). The screen says the everyday word instead:

| The system's word | The screen says |
| --- | --- |
| passage, chunk | part of a page (parts of pages) |
| ingestion, ingest, ingested | reading uploaded files, read |
| engine | who reviews it (Claude / this computer) |
| model, local model, model names | AI; the AI on this computer; Claude |
| general review | review (its history: "Current method" / "Earlier version") |
| kind (as a label) | type ("this kind of paper" stays: it is everyday English) |
| scope, in scope | what it covers, that apply |
| checklist | list of checks |
| judge, attack (second model) | checked twice / a second AI checks the list |
| worker | background reader |
| queue, queued | waiting |
| job | task |
| stage | step |
| routing, routed (technical queries) | who it goes to |
| corpus | library |
| embedding, vector | making searchable, search index |
| egress, payload | sending outside this computer, what is sent |
| provider | AI service, mail service, data service |
| run id | review number |
| token (sign-in reset) | one-time code |
| a setting's code name (AI_..., ..._ENABLED) | what the setting does |

`frontend/src/everydayWords.test.ts` reads every screen's source with a real
parser and fails when one of these words is shown outside Advanced. It leaves
to their owners the Shell, menu and screen headings, and the answer panels.
Routes, API paths, field names and stored codes keep their names: only the
words a person reads change.
