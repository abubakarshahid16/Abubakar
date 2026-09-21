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
