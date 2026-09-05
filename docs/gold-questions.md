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

---

## Confirmed against the live system — 2026-09-05

All five questions run at Tier 2 against the 8-document corpus and checked by a
reader. **These labels are now ground truth, not candidates** — the caveat at
the top of this file is discharged for these five rows.

| Q | Expected | Returned | |
|---|---|---|---|
| Q1 | doc18, pp. 18–19 | doc18, clause *3 Logical Components of Zero Trust Architecture*, p. 18 — all three Tier 2 citations land on pp. 18–19 | ✅ |
| Q2 | doc02, OCR-labelled | doc02 p. 68, `text_source=recognised`, OCR confidence 0.51 | ✅ |
| Q3 | NORSOK M-501 | NORSOK, clause 7.3, p. 10 | ✅ |
| Q4 | doc17 **and** doc19 | **doc19 only** | ⚠️ see below |
| Q5 | refusal | refused, and named API 610 as the absent subject | ✅ |

### Q4 returned one document of two, and that is not a retrieval failure

The label says an answer needs **both** doc17 (SP 800-53r5, the controls) and
doc19 (SP 800-61r3, the incident-response process). The system returned doc19,
correctly, and did not return doc17.

**Multi-document coverage does not exist.** Retrieval selects the best passages
and the answer is built from them; nothing asks whether a question needs
evidence from more than one source, and nothing reports when it found only
part. So doc17 was not missed — it was never sought. Calling this a retrieval
miss would blame the wrong component and send the next person to tune the
reranker.

**This row is the BEFORE number for that feature.** When multi-document
coverage is built, Q4 is the question that measures it: 1 of 2 required
documents today.

#### Measured, 2026-09-05: doc17 was sought, retrieved, and ranked fifth

The paragraph above says doc17 "was never sought". That was a reasonable
reading of the code and it is **wrong about the facts**, which only became
visible once `search()` began recording what it dropped
(`shortlist_excluded`). Measured on the 12-document corpus:

| | |
|---|---|
| Candidates fused into the pool | 52 |
| doc17's best candidate, by RRF | **rank 7 of 52** |
| doc17 candidates in the 16-slot shortlist | **4** |
| doc17 candidates cut before the rerank | 3 |
| doc17's best candidate, after rerank | **rank 5 of 16, score +2.104** |
| The passage | doc17 p179, *3.8 INCIDENT RESPONSE* |
| Passages the answer takes | 3 |

doc17's right passage is the fifth-best passage in the field, with a healthy
positive rerank score, sitting above four doc19 candidates that also did not
make the answer. It loses to nothing but the passage count.

**Three consequences.**

1. Q4 is not a retrieval failure. Retrieval found the correct doc17 section
   and scored it credibly.
2. Q4 is not a shortlist-composition failure either, so **the
   document-diverse shortlist named as "what comes second" in
   `docs/design-multi-document-coverage.md` would not change this answer** -
   doc17 is already in the shortlist at rank 5. That plan needs re-deriving
   from this measurement before any of it is built.
3. What is missing is exactly what section F reports and does not fix: nothing
   asks whether the question needs more than one document, and nothing says so
   when the answer used one. The number to quote stays **1 of 2**, and the
   claim behind it changes from "never sought" to "retrieved, ranked fifth,
   and not reported".

Q2 is worth noting for a second reason: doc02 has no text layer at all, so that
answer came entirely from OCR, arrived labelled as recognised, and carried its
confidence — the lowest of the five, 0.51 — through to the reader.

---

## Q6 — Civil collection only  (CANDIDATE LABEL)

> **What must a contractor submit for review, and in what form?**

**Relevant: doc13 (USACE Design Guide Manual), with doc16 (BIM Submission
Manual) second.**

Checked against the indexed chunk text: `submittal` appears in **185 chunks of
doc13, 49 of doc16, 2 of doc15, and NOWHERE ELSE IN THE CORPUS** — zero in the
IT documents, zero in Process, zero in Coatings. It is the cleanest
single-collection subject the corpus has.

**Candidate, not ground truth.** Term presence proves doc13 *contains* the
subject. Only a reader can confirm it *answers this question*, and the caveat
at the top of this file applies until an engineer does.

---

## Q7 — the cross-collection gap: I could NOT close it honestly

The gap stated at the bottom of this file is that Process, Coatings and IT
share no engineering subject, so no question can require two collections at
once. Civil was expected to bridge them through materials, inspection and
submittal requirements. **On this corpus it does not, and the reason is worth
recording rather than papering over with a question that looks cross-collection
and is not.**

**What I checked.** Every term appearing in both a Civil and an IT document,
by indexed-chunk count:

| Term | Civil | IT |
|---|---|---|
| `contractor` | doc13 **93**, doc16 15, doc20 11 | doc17 **35** |
| `training` | doc13 **40**, doc20 4 | doc17 **69** |
| `documentation` | doc13 **66**, doc16 11 | doc17 **70** |
| `inspection` | doc13 15 | doc17 23 |

`contractor` looked like the bridge — one subject, contractor obligations,
substantial on both sides. **Reading the chunks defeated it.** doc13's hits are
real requirements (*"specifications shall be Corps of Engineers Guide
Specifications"*). doc17's are generic prose — *"the Federal Government and
their contractors"* — a word in a sentence, not a section that answers a
contractor question. That is **term presence, not relevance**, which is the
distinction this file opens with and the reason the first five labels needed
confirming by hand.

**One further trap, which would have produced a false success.** doc20 (CISA
Incident and Vulnerability Response Playbooks) sits in the Civil collection by
filing, but its SUBJECT is cyber incident response. A question spanning doc20
and doc19 (NIST SP 800-61r3) would look cross-collection in the manifest and be
same-subject in substance. It would have satisfied the letter of this gap and
none of its purpose.

**So the gap stands.** Closing it needs a document that genuinely requires
another collection to answer — not a term the two happen to share. A Civil
specification that cites a security control by number, or an IT policy that
imposes a materials or submittal requirement, would do it. This corpus has
neither.
