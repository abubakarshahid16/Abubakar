# Gold question set — the 8-document corpus

Five questions with hand-checked relevance labels. This file is the ground
truth the coverage tests measure against, so it states how each label was
arrived at rather than only what the label is.

## How these labels were made, and what that is worth

Each label was checked by searching the **indexed chunk text** — the same text
retrieval sees — for the question's distinguishing terms, and reading the
sections they landed in. That is evidence a document *contains* the subject.

It is not proof the document *answers the question*. Presence and relevance are
different properties, and only a reader can settle the second. **An engineer
must confirm every row below before these labels are used to pass or fail
anything.** Until that happens this is a candidate set, not ground truth.

The corpus at the time of labelling:

| Document | Pages | Chunks | Collection |
|---|---|---|---|
| NORSOKM501Rev5.pdf | 24 | 80 | coatings |
| book1-professionalpractices.pdf | 546 | 1,093 | engineering practice |
| book2-Differential-Equations.pdf | 613 | 1,467 | mathematics |
| book4ChemicalProcessDynamicsAndControls.pdf | 1,400 | 2,147 | process control |
| doc02.pdf — DOE/NETL Mixed-Salt Process | 89 | 229 | `process_feed` |
| doc17.pdf — NIST SP 800-53r5 | 492 | 963 | `it_security` |
| doc18.pdf — NIST SP 800-207 Zero Trust | 59 | 134 | `it_security` |
| doc19.pdf — NIST SP 800-61r3 Incident Response | 48 | 85 | `it_security` |

---

## Q1 — single subject, one document

> **What are the logical components of a zero trust architecture, and what does the policy engine do?**

**Relevant: doc18 only.**

`policy engine` appears in 15 chunks, all of them in doc18, concentrated in
clause 3 *Logical Components of Zero Trust Architecture* (pages 18–19) and
carried through 3.1.1, 3.2, 3.3 and 3.4.1. No other document in the corpus
contains the phrase.

`zero trust` also appears once in doc19. **That chunk is labelled NOT relevant** —
a passing reference in an incident-response document is not an answer to a
question about architecture. This distinction is the point of the question: a
system that returns doc19 here is finding a word, not an answer.

---

## Q2 — single subject, a different collection

> **What carbon capture technology does this project use, and what did it cost to capture CO2?**

**Relevant: doc02 only.**

`carbon capture` appears in 14 chunks, all doc02, including 3 *Executive
Summary* (p11), 7.1.2 *Process Overview & Scope of Analysis* (pp38–40), 7.7.2
*Cost of Capture* (p68) and 9.2.2 *Carbon Capture System (CCS) Island* (p76).
`flue gas` appears in 47 doc02 chunks against 1 elsewhere.

doc02 is **fully scanned** — 89 pages, no text layer, every page recognised by
OCR. So this question also tests that a recognised-text answer carries its
provenance to the reader. An answer here must be labelled recognised, never
quoted verbatim.

---

## Q3 — single subject, the original corpus

> **How is a stripe coat applied, and to what?**

**Relevant: NORSOKM501Rev5 only.**

`stripe coat` appears in exactly one chunk in the entire corpus. This is the
narrowest question in the set and the one most likely to be answered by the
lexical path alone.

---

## Q4 — cross-document, same collection

> **What should an organisation do to contain and eradicate a security incident?**

**Relevant: doc17 and doc19. Both are required.**

`incident response` appears in 49 doc17 chunks and 54 doc19 chunks;
`eradication` in 3 of each; `containment` in 3 of each plus unrelated uses in
book4 (physical containment, a different sense) and doc02.

Neither document alone is a complete answer: doc19 is the procedural
recommendation, doc17 the controls catalogue that mandates it. **An answer
citing only one is incomplete, not wrong** — and the coverage report must say
so rather than presenting a partial answer as whole.

**Caution on doc17.** Its citations point at chapter headings rather than
control identifiers — see `docs/limitations.md`. Judge this question on whether
the right document and region were found, not on whether the section string
names a control.

---

## Q5 — nothing answers this

> **What vibration limits does API 610 specify for centrifugal pumps?**

**Relevant: none. The correct answer is a refusal.**

Verified absent from all 8 documents: `api 610` — 0 chunks, `hydrostatic test` —
0, `flare stack` — 0, `wellhead` — 0, `subsea` — 0, `asme b31.3` — 0,
`nace mr0175` — 0.

The question is deliberately plausible: API 610 is a real standard a petroleum
engineer would reasonably ask about, and the corpus contains pumps, vibration
and standards as general subjects. A system that answers this from adjacent
material has failed in the way that matters most.

---

## What this corpus cannot yet test

**There is no genuine cross-collection question.** Process, coatings and IT
security share no engineering subject, so a question spanning collections would
have to be artificial — and an artificial question produces an artificial
measurement.

The four blocked USACE and CISA downloads were the civil collection, and civil
standards would overlap the coatings and process material through materials,
inspection and submittal requirements. Until those are ingested, a
cross-collection coverage claim is not supported by this corpus, and the
coverage feature should be demonstrated within a collection and described that
way.

`risk assessment` does span doc17, doc19, doc02 and book1, and could carry a
cross-collection question — but the four documents mean four different things
by it, and a question that retrieves all four would be testing vocabulary
rather than comprehension.
