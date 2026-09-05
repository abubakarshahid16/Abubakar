# Gold questions — the ingested corpus, 12 documents

**Status: candidate set with verified citations, NOT yet ground truth.**
Every quoted span below was read out of `chunks` in the live database on
2026-09-05 and carries the filename, page and section the row records. What
has **not** happened is a live run: no question here has been asked through
`/api/conversations/{id}/ask` and had its answer compared to the expectation.
Until that run happens this file is a fixture, not a result, and nothing in it
may be quoted as a measurement.

That distinction is the whole reason this file exists. `docs/gold-questions.md`
says of itself: *"this is a candidate set, not ground truth"* — and it was
built against an 8-document corpus that is no longer what is ingested.

## What is actually ingested

| Document | Pages | Passages | Domain |
|---|---:|---:|---|
| NORSOKM501Rev5.pdf | 24 | 81 | Surface preparation and protective coating |
| doc02.pdf | 89 | 247 | Process / compression engineering |
| doc13.pdf | 311 | 747 | Civil and site design criteria |
| doc15.pdf | 42 | 83 | Design analysis and submittal requirements |
| doc16.pdf | 49 | 96 | BIM submittal standards |
| doc17.pdf | 492 | 979 | NIST SP 800-53 security controls |
| doc18.pdf | 59 | 139 | Zero-trust architecture |
| doc19.pdf | 48 | 85 | Incident response |
| doc20.pdf | 44 | 76 | Federal incident reporting |
| book1-professionalpractices.pdf | 546 | 1,107 | Ethics / professional practice |
| book2-Differential-Equations.pdf | 613 | 1,748 | Mathematics textbook |
| book4ChemicalProcessDynamicsAndControls.pdf | 1,400 | 2,268 | Process control textbook |

**12 documents, 7,656 passages.** The plan's §15.2 step 5 asks for a 20→15→10
proof. It cannot be run against this corpus: there are twelve documents, and
the plan's A05/A30 fixture does not exist.

**The corpus is heterogeneous on purpose, and that is its most useful
property.** A coatings standard, three US federal design manuals, three
security documents and three textbooks share almost no subject matter. So a
question that touches two of them is a genuine test of whether the system can
say *"these are different subjects"* rather than manufacturing a comparison.
A corpus of twenty coatings specifications would not test that at all.

---

## A · Single-fact retrieval

The floor. If these fail, nothing else matters.

### A1 — Metal coating thickness
**Ask:** What is the minimum coating thickness for structural items and outfitting steel?

**Expect:** 125 μm and 900 g/m².

> "Minimum coating thickness for structural items and outfitting steel shall be 125 μm and 900 g/m2."
> — NORSOKM501Rev5.pdf, p.9, §4.11 Metal coating

**Passes if:** the answer states 125 μm, cites p.9, and does not silently convert to mm.
**Fails if:** it returns the *1000 μm* figure from p.17/p.20 — that is a different clause about specialised systems, and confusing the two is the near-miss failure this corpus is good at producing.

### A2 — Stainless-to-carbon steel
**Ask:** How far beyond the weld zone must stainless steel be coated where it connects to carbon steel?

**Expect:** 50 mm.

> "If stainless steel is connected to carbon steel, the stainless steel part shall be coated 50 mm beyond the weld zone onto the stainless steel."
> — NORSOKM501Rev5.pdf, p.8, §4.8 Unpainted surfaces

### A3 — Edge preparation
**Ask:** What is the minimum radius for rounding sharp edges before blasting?

**Expect:** 2 mm.

> "Sharp edges, fillets, corners and welds shall be rounded or smoothened by grinding (minimum radius 2 mm)."
> — NORSOKM501Rev5.pdf, p.9, §6.1 Pre-blasting preparations

### A4 — Incident reporting deadline
**Ask:** How quickly must CISA receive a major incident report?

**Expect:** Within 1 hour of major incident declaration.

> "Regardless of the internal reporting chain of the organization, CISA must receive the major incident report within 1 hour of major incident declaration."
> — doc20.pdf, p.35

**Note:** this sentence appears in two passages. The answer should cite one, not
list the same span twice — a duplicate citation is a defect worth watching for.

### A5 — Drawing size
**Ask:** What sheet size must revision drawings be?

**Expect:** A4 metric, 210 mm × 297 mm, ANSI "A" equivalent.

> "Such drawings shall be A4 metric size, 210 mm x 297 mm (8" x 11"), an ANSI "A" equivalent sheet, and must be legible."
> — doc13.pdf, p.10, §3.3.3.2

### A6 — Fire hydrant branches
**Ask:** What is the minimum diameter for fire hydrant branches?

**Expect:** 6 inches (150 mm).

> "Fire hydrant branches are to be a minimum of 6 inches (150 mm) in diameter, and shall be as short in length as possible, and shall have a gate valve."
> — doc13.pdf, p.66, §8.1.12

**Also tests:** dual units in one sentence. The claim engine should record one
measurement with both spellings, not two conflicting measurements.

### A7 — RAM pressure drop
**Ask:** What maximum pressure drop was the RAM sized for?

**Expect:** 10 kPa across the RAM for each process flow stream; 8 kPa across the sectors, leaving 2 kPa for the duct transitions.

> "The RAM for Case 12V was sized based on a 10 kPa maximum pressure drop across the RAM for each process flow stream."
> — doc02.pdf, p.49, §7.4.2 RAM Sizing and Target Performance

**Also tests:** three related figures in adjacent sentences. A good answer
distinguishes them; a bad one averages or conflates.

### A8 — Control families
**Ask:** How many control families in NIST SP 800-53 align with the FIPS 200 minimum security requirements?

**Expect:** 17 of 20.

> "Of the 20 control families in NIST SP 800-53, 17 are aligned with the minimum security requirements in [FIPS 200]."
> — doc17.pdf, p.35, §2.2

**Watch for:** the stored passage begins "The 25 Of the 20 control families…" —
a page number bled into the text during extraction. If the answer reports 25,
that is an extraction defect surfacing as a wrong answer.

---

## B · Cross-document — where the honest answer is "different subjects"

The gap engine's central claim is that it will not manufacture a conflict.
These questions invite one.

### B1 — Coating thickness across the corpus
**Ask:** What coating thickness is required, and what does each document say?

**Expect:** NORSOK M-501 gives 125 μm for structural steel (p.9) and more than
1000 μm for pre-qualified specialised systems in exposed areas (p.17, p.20).
doc13 discusses insulation R-values, which is a different subject entirely.

**Passes if:** the two NORSOK figures are distinguished by their scope, and any
doc13 material is labelled not comparable rather than conflicting.
**Fails if:** 125 and 1000 are reported as a contradiction, or an insulation
value is compared against a coating value.

### B2 — Minimum separation distances
**Ask:** What minimum separation distances are specified?

**Expect:** doc13 p.65 gives 6 ft (1.8 m) horizontal water/sewer separation with
the water main at least 12 inches (300 mm) above the sewer. NORSOK p.11 gives
30–40 cm sweep-blast distance from a weld zone. **These are unrelated.**

**Passes if:** both are reported with their subject attached and no comparison
is attempted between them.

### B3 — What is "evidence"?
**Ask:** How is evidence defined?

**Expect:** doc19 p.37 quotes *"grounds for belief or disbelief; data on which
to base proof or to establish truth or falsehood"*. Other documents use the word
in ordinary senses.

**Tests:** whether a definition is retrieved as a definition, rather than the
word being matched across three unrelated documents.

---

## C · Refusal — the corpus cannot answer these

**These are the most important questions in this file.** A system that answers
them has invented something, and no citation check will catch it.

| # | Question | Why it must be refused |
|---|---|---|
| C1 | What is the maximum allowable chloride concentration in the feedwater? | No document specifies feedwater chemistry |
| C2 | What torque should the flange bolts be tightened to? | No bolt torque tables in any of the twelve |
| C3 | What is the project's completion date? | No schedule document is ingested |
| C4 | Who is the appointed coating inspector? | No personnel or role assignments anywhere |
| C5 | What does the Aramco standard SAES-H-001 require? | Not in the corpus. **Tests whether a plausible-sounding standard number induces a fabricated answer.** |
| C6 | What is the warranty period for the applied coating? | NORSOK M-501 does not cover warranty |

**Passes if:** each returns a refusal that names what is missing, and cites
nothing.
**Fails if:** any returns an answer, however hedged. A hedged fabrication is
worse than a refusal because it looks considered.

C5 is the sharpest of the six. It is shaped exactly like a real Aramco standard
reference, and a system that pattern-matches rather than retrieves will produce
something confident and wrong.

---

## D · Traps this corpus produces naturally

### D1 — The mangled micro sign
Four passages store `Pm` where `µm` is meant, e.g.

> "the coating thickness is  1000 Pm NDFT" — NORSOKM501Rev5.pdf, p.20

The same sentence appears in another passage **with** the `>` intact. So the
comparator is lost inconsistently, on one extraction path and not another.

**One of the four `Pm` hits is not a defect at all:** book2 p.— contains
`Pm(x)Pn(x)`, which is Legendre polynomials. The P is genuinely a P. Any fix
that repairs the three must leave this one untouched, and this file exists
partly to hold that counter-example where a future fix will trip over it.

### D2 — Designator suffixes
"coating system no. 5A and 5B" was read as **5 amperes** before commit
`4aafe2d`. Ask *"what tests apply to coating system 5A?"* and confirm no
measurement of 5 A appears anywhere in the response.

### D3 — Textbook contamination
Three of the twelve documents are textbooks totalling 5,123 passages — **67% of
the corpus by passage count.** A question about "systems", "control" or
"analysis" will pull textbook material ahead of the engineering standards.

**Ask:** What are the requirements for control systems?
**Watch:** whether book4 (process control theory) crowds out doc17 (NIST
security controls) and NORSOK. This is a ranking problem the corpus creates by
construction, and it is worth measuring before a client asks a broad question.

---

## How to run this

Ask each question through the API, not the harness, so the measurement is of
the product:

```
POST /api/conversations           -> conversation id
POST /api/conversations/{id}/ask  {"question": "...", "tier": "extract"}
```

Record for each: the answer, every citation, whether it refused, and elapsed
seconds. Then fill the result column below.

| # | Answered correctly | Cited correctly | Refused when it should | Notes |
|---|---|---|---|---|
| A1 | | | n/a | |
| A2 | | | n/a | |
| A3 | | | n/a | |
| A4 | | | n/a | |
| A5 | | | n/a | |
| A6 | | | n/a | |
| A7 | | | n/a | |
| A8 | | | n/a | |
| B1 | | | n/a | |
| B2 | | | n/a | |
| B3 | | | n/a | |
| C1 | n/a | n/a | | |
| C2 | n/a | n/a | | |
| C3 | n/a | n/a | | |
| C4 | n/a | n/a | | |
| C5 | n/a | n/a | | |
| C6 | n/a | n/a | | |
| D1 | | | n/a | |
| D2 | | | n/a | |
| D3 | | | n/a | |

**An empty table is the honest state of this file.** Do not report a pass rate
from it until the column is filled from a real run.
