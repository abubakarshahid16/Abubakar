# Corpus provenance — what has actually been ingested, and what that means for any claim made to a client

**Status:** current as of 2026-09-06, verified directly against `backend/data/nabaa.sqlite`
(tables `documents`, `pages`, `page_ocr`, `document_role_access`, `roles`) and against the
twelve source PDFs in `backend/data/uploads/`.

This document exists so that nobody — the team, a reviewer, or the client — can be misled
about what this system has been tested on. It states the corpus exactly, and it separates
the claims that carry over to a client's documents from the claims that do not.

---

## 1. What is in the corpus

Twelve documents. All twelve are `status = ready`; all twelve have every retrievable chunk
embedded (`chunk_count = embedded_count` in every row).

| Filename | Publisher | Subject | Pages | Status | Granted to (discipline role) |
|---|---|---|---:|---|---|
| `NORSOKM501Rev5.pdf` | Standards Norway, for OLF / TBL (Norwegian petroleum industry) | NORSOK M-501 Rev. 5 (June 2004), surface preparation and protective coating | 24 | ready | Mechanical |
| `book1-professionalpractices.pdf` | Pearson | Baase & Henry, *A Gift of Fire: Social, Legal, and Ethical Issues for Computing Technology*, 5th ed. | 546 | ready | IT |
| `book2-Differential-Equations.pdf` | Cengage / Brooks-Cole | Zill & Cullen, *Differential Equations with Boundary-Value Problems*, 7th ed. | 613 | ready | Civil Engineering, Mechanical, Chemical-Process, IT |
| `book4ChemicalProcessDynamicsAndControls.pdf` | University of Michigan (CC BY 3.0 open textbook) | *Chemical Process Dynamics and Controls* | 1400 | ready | Chemical-Process |
| `doc02.pdf` | NRG Energy Inc. for the U.S. Department of Energy, NETL (Award DE-FE0026581) | *NRG CO2NCEPT* final technical report on post-combustion carbon capture | 89 | ready | Chemical-Process |
| `doc13.pdf` | U.S. Army Corps of Engineers, Norfolk District (CENAO-TS-E) | Engineering Branch *Design Guide*, May 2010 | 311 | ready | Civil Engineering |
| `doc15.pdf` | U.S. Army Corps of Engineers (CEMP-EA) | ER 1110-345-700, *Design Analysis, Drawings and Specifications*, 30 May 1997 | 42 | ready | Civil Engineering |
| `doc16.pdf` | U.S. Army Corps of Engineers, New York District (NANP-1110-02-01) | Official Manual for Building Information Modeling (BIM) Projects, v1.0, May 2009 | 49 | ready | Civil Engineering |
| `doc17.pdf` | NIST (U.S. Department of Commerce) | SP 800-53 Rev. 5, *Security and Privacy Controls for Information Systems and Organizations* | 492 | ready | IT |
| `doc18.pdf` | NIST | SP 800-207, *Zero Trust Architecture* | 59 | ready | IT |
| `doc19.pdf` | NIST | SP 800-61r3, *Incident Response Recommendations and Considerations for Cybersecurity Risk Management* | 48 | ready | IT |
| `doc20.pdf` | CISA (U.S. Cybersecurity and Infrastructure Security Agency), TLP:CLEAR | *Cybersecurity Incident & Vulnerability Response Playbooks*, November 2021 | 44 | ready | IT |

Total: 3,717 pages, 7,656 chunks, of which 7,187 are marked retrievable.

Two details worth recording because they affect how the corpus behaves:

- **`doc02.pdf` has no PDF text layer at all.** Every one of its 89 pages is empty in
  `pages.text` and every one has a row in `page_ocr`. It is the only document in the corpus
  that is entirely recognised text rather than extracted text. Anything measured on `doc02`
  is a measurement of the OCR path, not the extraction path.
- **`book2-Differential-Equations.pdf` is granted to all four discipline roles.** Every other
  document is granted to exactly one. That makes it the only document that appears in every
  role's retrieval scope, and it is the document with the largest known section-labelling
  defect (see ISSUE-019).

### Every document is a public, English-language publication

All twelve are government, standards-body, or academic publications that are free to
redistribute or were obtained as published copies. Verified directly:

- The corpus contains **zero Arabic characters** — across `pages`, `chunks` and `page_ocr`,
  and across the text layers of all twelve source PDFs. No PDF in the corpus embeds an
  Arabic-capable font.
- The only non-Latin codepoint found anywhere in `pages.text` is `U+FEFF` (a byte-order
  mark) on two lines of page 400 of `book1`. It is invisible formatting, not a script.

So the corpus is monolingual English by construction, not by assumption.

---

## 2. No client document has ever been ingested

There is no Saudi Aramco document in this corpus. There never has been. The `documents`
table has twelve rows and they are the twelve above.

The direct consequence, stated plainly:

> **No measurement in this project has been taken against client material.** Retrieval
> quality, section-citation accuracy, answer latency, refusal rate, OCR accuracy, table
> handling, coverage — every number in `docs/benchmarks.md`, `docs/limitations.md` and the
> commit history was measured on the twelve public documents listed above.

Any figure quoted to a client is a figure about *this* corpus. It is not a prediction about
theirs until it has been re-measured on theirs.

---

## 3. Why the corpus is public documents, and why that is the right call

Client engineering specifications are controlled documents. Ingesting them would mean
copying them onto a development machine, into a local SQLite database, a vector cache, a
directory of rendered page images, and a set of evaluation fixtures — all of which are
working files that get copied, backed up and shared during development. A development
machine is not an environment where controlled client material should live, and the
authorization boundary that would make it acceptable (see `docs/adr/ADR-0002-privacy-boundary.md`
and the security review recorded as a production gate in `docs/limitations.md`) is not yet
in place.

Building against public documents that resemble the target material — a petroleum-industry
coating specification with numbered clauses, three U.S. Army Corps of Engineers design
standards, four NIST/CISA control documents, and three technical textbooks — exercises the
same structural problems (clause numbering, split-line headings, contents pages, tables,
scanned pages, mathematics) without moving anyone's controlled documents anywhere.

That is a deliberate engineering decision and it is the correct one. It has one cost, and
this document names it rather than leaving it to be discovered: the measurements are about
stand-in documents.

---

## 4. What transfers to a client corpus, and what does not

### Likely to transfer

- **Retrieval and answer latency.** Latency is dominated by embedding, keyword search,
  reranking and generation over a chunk of roughly fixed token size. It is a function of
  corpus *size* and hardware, not of who wrote the documents. A client corpus of comparable
  page count on comparable hardware should behave comparably. Re-measure anyway, because
  page count and chunk count are what drive it and those will differ.
- **Ingestion throughput per page**, with the same caveat, and with the OCR path measured
  separately — it is roughly five times slower per page than extraction and how much of a
  corpus needs it is entirely document-dependent.
- **Refusal behaviour on out-of-corpus questions.** The system refuses when retrieval
  returns nothing that grounds an answer. That is a property of the answering logic, not of
  the documents, and the adversarial gold question C5 (`docs/gold-questions-corpus.md`) —
  which asks about a plausible-sounding Aramco standard number that is deliberately not in
  the corpus — tests exactly this. It transfers.
- **Access-control behaviour.** Role-scoped retrieval is enforced on document IDs and is
  independent of document content.
- **The classes of failure that exist.** Every failure mode named in `docs/limitations.md`
  is a real mechanism in the code. A client corpus will not be free of them; it will exhibit
  them in different proportions.

### Does not transfer

- **Section-heading and clause-citation accuracy.** This is the important one. Section
  assignment is driven by the *typographic layout* of headings — a clause number alone on
  one line with the title beneath it, running headers and footers, contents pages, the shape
  of chapter openers. Those are format properties of a specific publisher's template. The
  headline figures for this corpus were measured on NORSOK, USACE and NIST layouts. A Saudi
  Aramco specification uses a different template, and the accuracy figure will be different —
  possibly better, possibly worse. **Do not quote a section-accuracy number to a client as a
  prediction about their documents.**
- **The contents-page and index detector.** It is positional: front 6% for contents, back
  15% for index. That is a property of bound books and single-part standards. Multi-part
  compilations with contents pages part-way through — which client specifications often are —
  will defeat it. Already recorded in `docs/limitations.md`.
- **OCR accuracy.** No accuracy claim is made at all, and none should be. The pages in this
  corpus that needed OCR are book covers and software UI screenshots, not scanned
  specification prose. The system has not been tested on the kind of scanned material a
  client corpus would actually contain.
- **Table extraction quality.** Tables are currently isolated as blocks of text, not parsed
  into rows and cells. How well that reads depends entirely on the table style of the source
  document.
- **Anything about Arabic.** The corpus contains none, so nothing about Arabic extraction,
  retrieval, or rendering has been measured. Not "measured and found working" — *not
  measured*, for want of any input to measure. See ISSUE-020 and `docs/adr/ADR-0005-ocr-engine-selection.md`,
  whose recogniser choice is explicitly held open pending exactly this question.
- **Domain vocabulary and synonym coverage.** Already visible in this corpus: a question
  about "salt" on a surface misses because NORSOK says *chlorides* and *NaCl*. A client's
  house vocabulary is unknown and untested.
- **Coverage and answer quality on client subject matter.** The corpus is coatings, civil
  design guides, information-security controls, differential equations and process control.
  It is not a client's plant, process or asset documentation.

---

## 5. What would change when real documents arrive

1. **Re-measure the headline figures on the real corpus** — section-citation accuracy,
   retrieval quality against a gold question set written from the client's documents, answer
   latency, refusal rate — and publish both numbers, this corpus's and theirs.
2. **Re-tune or extend the heading and contents detectors** against the client's template.
   Expect the split-line-heading rule and the positional contents detector to need new
   discriminating conditions, and expect the NORSOK clause-heading tests to have to stay
   green while that happens (ISSUE-019).
3. **Answer the Arabic question with data instead of a client interview**, and close or
   revise ADR-0005's recogniser decision on the measured answer. If Arabic is present, the
   retrieval quality gate must be fixed before any Arabic content can be retrieved at all
   (ISSUE-020).
4. **Re-run the OCR engine comparison on real scanned specification pages**, and make the
   first honest OCR accuracy claim the project has been able to make.
5. **Write a new gold question set from the client's documents.** The current sets are
   written against public material and do not exercise client subject matter.
6. **Move ingestion behind the authorization boundary** before any controlled document is
   loaded — this is a production gate, not a step in this document's scope.
7. **Revisit table parsing** once the shape of real client tables is known, rather than
   guessing at it now.

---

## 6. How to re-verify this document

```sql
-- the corpus, exactly
SELECT filename, page_count, chunk_count, status FROM documents ORDER BY filename;

-- who each document is granted to
SELECT d.filename, r.name, a.permission
FROM document_role_access a
JOIN documents d ON d.id = a.document_id
JOIN roles r ON r.id = a.role_id
ORDER BY d.filename;

-- the front matter that identifies each publisher
SELECT page_no, substr(text, 1, 400) FROM pages
WHERE document_id = ? AND page_no <= 3 ORDER BY page_no;
-- for doc02.pdf, which has no text layer, read page_ocr instead
```

`backend/data/nabaa.sqlite` raises `disk I/O error` when opened across a network mount.
Copy it to local disk and open the copy read-only.
