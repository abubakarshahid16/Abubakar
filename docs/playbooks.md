# Review playbooks: HAZOP and SIL procedures (#679, W5b-04)

A **playbook** is a data file that says what a kind of document is expected to
contain. The review reads a procedure the system already holds (a Word file
through the #668 reader, or a PDF) and reports, **per element**, what it found.
This is a completeness check on a written procedure (required steps, roles,
records, worksheet fields, the SIL method, verification). It is not a datasheet
value check.

## Where things are

| what | where |
|---|---|
| playbooks | `backend/app/reference/playbooks/hazop_procedure.json`, `sil_procedure.json` |
| the loader and the review | `backend/app/playbooks.py` |
| list the playbooks | `GET /api/playbooks` |
| review one document | `POST /api/documents/{id}/playbook-review` with `{"playbook_id": "hazop_procedure", "use_ai": false}` |
| tests | `backend/tests/test_w5b_679_playbooks.py` (invented documents only) |

## The file format, `review-playbook/1`

```json
{"format": "review-playbook/1", "id": "hazop_procedure", "title": "...", "version": "1",
 "document_kind": "procedure",
 "applies_when": ["hazop", "hazard and operability"],
 "sign_off": {"status": "draft", "by": null, "date": null},
 "clauses_verified": false,
 "elements": [
   {"id": "H02", "title": "Team and roles", "expects": "what the document should state",
    "source": {"standard": "IEC 61882", "clause": "6.2"},
    "evidence": [{"label": "study leader", "any": ["leader", "chairman"]},
                 {"label": "scribe", "any": ["scribe", "secretary"]}]}]}
```

* `source.standard` and `source.clause` are **required**. A check without a clause
  citation is **rejected when loaded**, by element id (W5b-10, #547). A playbook
  file that cannot be loaded is listed with its reason, never dropped.
* `evidence` is a list of cue groups. A cue is a word or phrase (whole words; a
  trailing `*` means any ending, `revalidat*`; a space or hyphen in the text
  matches either). An element is **present** when one passage holds a cue of
  **every** group.
* `applies_when` (#527) is a list of cues (same cue rules) saying a document is
  about this playbook's subject. When the document router's kind (confirmed,
  or suggested and then named a guess) equals `document_kind` AND the
  document's text holds one of these cues, the standards the elements cite are
  **mandatory** in applicability selection: included as `playbook` when the
  playbook is signed off, considered and NOT included as `playbook_draft`
  while it is a draft, and listed under `mandatory_not_held` when the library
  does not hold them. No cues: the playbook is never chosen on its own.
* `sign_off.status` is `draft` until a client discipline engineer is recorded
  (`by` and `date` are then required). A draft playbook's report carries the
  sentence "This playbook has not been signed off by a client discipline
  engineer". `clauses_verified: false` says no clause number has been checked
  against the standard's text.

## What the report says, per element

| state | meaning |
|---|---|
| `present` | the cues of every group were found together in one passage; the passage's locator (`4.2 > para 3`, or `page 3` for a PDF) and a verbatim quote are shown |
| `unclear` | part of what the element expects was found, never all together; the missing groups are named |
| `missing` | nothing found, in a document read in full: said **"not found in the pages read"**, about the pages, never about the author |
| `could_not_be_checked` | the document was not read in full (still processing, pages needing recognition) or has no text, so absence proves nothing |
| `standard_not_held` | the element's source standard is **not in the library**. This is **never "met"**: the clause could not be checked against its text. Where the topic appears is listed as a pointer for the engineer, not as a verdict |

The counts state their total ("11 elements"). Footers, tracked changes, comments
and the table of contents are stored beside the body and are not the document's
content here: text only in them does not make an element present.

## A model proposes, code checks

By default nothing is sent to a model. With `use_ai`, for an element the cue
words did not settle, the **local** model (the AI task runner, #662; the model,
its word limit and retry are its settings, #683) is shown the few passages that
share the most words with what the element expects and is asked for one quote. A
proposal is **kept only when its quote is found verbatim in the passage it
names**; anything else is dropped and counted (`ai.rejected`). The model never
writes a check, a clause or a verdict.

## Which standards are held

IEC 61511 and IEC 61508 are **not** in the library today (owner action). Until
they are, every SIL element reports `standard not held`, and the same holds for
IEC 61882 for the HAZOP playbook. Add the standard to the library and the same
document is re-reviewed with no other change.

## What the shipped playbooks are

**Drafts written by Claude as a starting point.** Every cue list and every clause
number needs a client discipline engineer to confirm or change it (W5b-10). The
clause numbers are the author's reading of each standard's table of contents; the
standards are not held, so none has been checked. They were not tested on the
hidden exam's two procedures or on the owner's reserved Word document: only
invented documents were used.

## Not done

* A screen. The review is an API result for now.
* Playbooks for other document types, and a playbook editor.
* Storing a review result on the document.
* Measured accuracy on a real procedure (guessed, not measured).
