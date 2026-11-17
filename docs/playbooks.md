# Review playbooks: HAZOP, SIL and general contractor procedures (#679, W5b-04; order 14 lane P)

A **playbook** is a data file that says what a kind of document is expected to
contain. The review reads a procedure the system already holds (a Word file
through the #668 reader, or a PDF) and reports, **per element**, what it found.
This is a completeness check on a written procedure (required steps, roles,
records, worksheet fields, the SIL method, verification). It is not a datasheet
value check.

## Where things are

| what | where |
|---|---|
| playbooks | `backend/app/reference/playbooks/hazop_procedure.json`, `sil_procedure.json`, and the drafts of order 14 lane P: `pressure_test_procedure.json`, `welding_procedure.json`, `pmi_procedure.json` |
| check the source quotes on the held books | `python scripts/playbook_quote_check.py --db <COPY of the database>` (read only; ids, pages and PASS / FAIL, never text) |
| the loader and the review | `backend/app/playbooks.py` |
| list the playbooks | `GET /api/playbooks` |
| review one document | `POST /api/documents/{id}/playbook-review` with `{"playbook_id": "hazop_procedure", "use_ai": false}` |
| tests | `backend/tests/test_w5b_679_playbooks.py`, `test_o14_p_procedure_playbooks.py` (invented documents only) |

## The file format, `review-playbook/1`

```json
{"format": "review-playbook/1", "id": "hazop_procedure", "title": "...", "version": "1",
 "document_kind": "procedure",
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
* `source.page`, `source.quote` and `source.verified` are optional (order 14 lane P): the
  page of the cited book and a short quote of it. A quote without its page, a page that
  is not a page number, and `verified: true` without a quote are **rejected when
  loaded**, by element id. `verified` is set only after `scripts/playbook_quote_check.py`
  found the quote on that stored page of a held book with THE quote check of gate G1
  (`compiled_rule_proof.quote_verified`, through `playbooks.source_quote_checks`). An
  element whose book is not held carries no quote; it reads "standard not held" (on the
  CRS: book missing, with its clause). The report's `source` shows the page and
  `quote_verified` where the file has them.
* `evidence` is a list of cue groups. A cue is a word or phrase (whole words; a
  trailing `*` means any ending, `revalidat*`; a space or hyphen in the text
  matches either). An element is **present** when one passage holds a cue of
  **every** group.
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

## The general procedure drafts (order 14 lane P, 17 Nov 2026)

Built ONLY from rule books the library holds. Each book's own scope clause says it governs the work the procedure describes:

| playbook (title cue) | elements | held books cited | quotes verified on the stored page | book missing |
|---|---|---|---|---|
| `pressure_test_procedure` ("pressure test") | 21 | SAES-A-004 (pressure testing, scope 1.1), SAES-A-007 (test water and lay-up, scope 1.1) | 20 of 20 | GI-0002.102 5.1.2.5 (named by SAES-A-004 5.8.2) |
| `welding_procedure` ("welding") | 18 | SAES-W-011 (welding of on-plot piping to ASME B31.3, scope 1.1) | 17 of 17 | ASME Section IX QW-482 and QW-483 (the suggested WPS and PQR forms SAES-W-011 7.1.2 names; the form numbers are the author's reading) |
| `pmi_procedure` ("pmi") | 13 | SAES-A-206 (positive material identification, scope 1) | 13 of 13 | none |

Each element says in one sentence what any procedure of that type must contain (never one paper's wording, CLAUDE.md rule 13).
The four held books are listed for the kind `procedure` in `reference/kind_books.json` (gate G2). A playbook reaches a paper's CRS
only when its title cue is in the paper's cover lines (`procedure_playbook_rows`): a cover "Hydrostatic Test Procedure" without the
word "pressure", or "Welding Procedure Specification" spelt "WPS" only, does not choose it. Every row stays an engineer row: never
compliant, never a firm Pass or Fail.

Common contractor procedures with NO held book found (a look-up of each name with `find_standard`, and a search of the held
books' first pages): NDT procedures (ASME Section V, SAEP-1140 and SAEP-1142 not held), lifting and rigging, commissioning and
pre-commissioning, bolt tightening, method statements in general. Held but not drafted in this round: painting and coating
application (SAES-H-001 and the other SAES-H books), chemical cleaning (SAES-A-008), piping construction and flushing
(SAES-L-350), pipeline pressure testing (SAES-L-150). Not scored against an engineer's answer key: none exists for a procedure of these types.

## What the shipped playbooks are

**Drafts written by Claude as a starting point.** Every cue list and every clause
number needs a client discipline engineer to confirm or change it (W5b-10). The
clause numbers are the author's reading of each standard's table of contents; the
standards are not held, so none has been checked. They were not tested on the
hidden exam's two procedures or on the owner's reserved Word document: only
invented documents were used.

## Not done

* A screen. The review is an API result for now.
* Playbooks for other document types (see the list of procedures with no held book above), and a playbook editor.
* Storing a review result on the document.
* Measured accuracy on a real procedure (guessed, not measured).
