# Adversarial gold question set — 25 questions

Built by reading indexed chunk text from the live database, not from general
knowledge. **Every label is a CANDIDATE.** Term presence is not the same as the
document answering the question, and an engineer must confirm each expected
answer against the source PDF before any of this is ground truth. That
distinction has already produced one wrong label in this project.

## Why this set exists

The existing harness has 16 questions and has now **three times** failed to see a
real defect, each time for a structural reason:

| Defect | Why the harness could not see it |
|---|---|
| A false refusal (P&ID) | Every existing question has its answer at rank 1, so a gate that inspects only the top hit was invisible |
| Silent context overflow | Every existing question's evidence is **prose**. Numeric tables tokenise at ~1.0 chars/token against ~5.5 for prose, so three table passages blow a 1,536-token window. No existing question touches a table |
| Conversation contamination | Questions asked in isolation cannot exercise follow-up term-carrying |

This set is built to **exercise** those blind spots, not to be answered
comfortably.

---

## A — Numeric table evidence (5)

Digit density 0.565–0.735. These chunks are bare numeric grids that tokenise near
one character per token. Three retrieved together is 2,000+ tokens of digits
before any prose.

**A1.** *For y' = 2xy with y(1) = 1 and h = 0.1, what do Euler, improved Euler and
RK4 give at x = 1.50, and what is the actual value?*
book2 p368, Table 9.6 · chunk `0c5c007fcedd:p00368:c01029:3dc84e65` · density **0.698**
> `1.50 / 2.9278 / 3.4509 / 3.4902 / 3.4904`

**The chunk has no column headers.** They live in the adjacent chunk. A correct
answer needs two table chunks stitched, and the table interleaves the h=0.1 and
h=0.05 halves in reading order — so a truncated context silently returns the
wrong column.

**A2.** *In the Euler error table for y' = 0.2xy, y(1) = 1, h = 0.1, what is the
percentage relative error at x = 1.50?*
book2 p98, Table 2.3 · `0c5c007fcedd:p00098:c00243:eb7285b3` · density **0.565**
Candidate answer: **0.64 %**

One chunk carries four tables back to back. Table 2.4's x-column is nearly
identical, so any truncation of the tail flips the answer.

**A3.** *What are the first five nonnegative zeros of J0(x)?*
book2 p267, Table 6.1 · `0c5c007fcedd:p00267:c00729:24a6dbda` · density **0.735** — highest in the corpus
Candidate answer: 2.4048, 5.5201, 8.6537, 11.7915, 14.9309

**The best truncation detector in the set.** The chunk is 20 numbers, zero words,
**column-major with no header and no caption**. A model given only this chunk will
very plausibly answer `2.4048, 0.0000, 0.8936, 2.1971, 5.5201` — reading across
the row instead of down the column. That answer is wrong and looks right.

**A4.** *In the X-bar and R chart example with subgroups of four, what is the
average and range for subgroup 10?*
book4 p1113, Table 4 · `b4f589095afe:p01113:c01836:3667fdbd` · density **0.600**
Candidate: average 7.04, range 0.25

24 near-identical rows in the 6.8–7.2 band — no lexical discriminator for
"subgroup 10". Contains OCR damage **inside the numbers** (`k0°0` for 0.03), so a
system answering confidently here is over-trusting. Decoy: `p01102:c01829` is a
different 24-row table in the same band.

**A5.** *In the PID tuning optimisation example, what is the setpoint and what
values does Tc take?*
book4 p703 · `b4f589095afe:p00703:c01246:6ad88f72` · density **0.680**

Spreadsheet screenshot OCR, columns transposed into one run-on line, corruption
mid-number (`89€`, `8E65'19€`). The setpoint (368 K) is recoverable; the Tc series
is not. **A system that returns a clean Tc series here is hallucinating.**

---

## B — Deep-rank answers (4)

**B1.** *Under NIST SP 800-53r5, may non-organizational users be granted
privileged access?*
doc17 p65, AC-6(6) · `fc63bcd61715:p00065:c00126:21997f89`
Term counts: `privileged` **63 chunks**, `privilege` **143**, `least privilege` **31**

The base control, five sibling enhancements, and **two summary index tables** compete.
The index chunk on p457 lists the enhancement's title verbatim and contains zero
information — a perfect rank-1 decoy.

**B2.** *How quickly must an FCEB agency notify CISA after determining an incident?*
doc20 p18, p34, p35 · three chunks
Term counts: `CISA` **65 chunks**, `notif*` **121 across 7 documents**; the answer is in **5**

Cross-document interference: doc19 and doc17 discuss incident notification at
length and never state one hour.

**B3.** *What are the four types of checks required on a BIM model before
submittal?*
doc16 p18 §6.0 · `5490df50b352:p00018:c00026:fb5b42ff`
Term count: `submittal` **236 chunks** — doc13 holds 185, doc16 only 49

doc13 dominates 4:1, and **the correct chunk never uses the word "submittal" in
its answering sentence.**

**B4.** *Which previous SP 800-61 lifecycle phase maps to the Recover Function in
CSF 2.0?*
doc19 p14, Table 1 · `e5593d6bb85d:p00014:c00018:3f5b1185`

Every doc19 chunk looks relevant lexically. The answer is a flattened table where
the mapping arrows are lost, so phase-to-Function boundaries must be inferred
from ordering.

---

## C — OCR-only evidence (3)

doc02 is **100% recognised text** — 229 of 229 chunks. All three are at the
confidence floor.

**C1.** *What is the cost of CO2 captured per tonne, and which two cases are
compared?*
doc02 p68 · `ef69b2115dff:p00068:c00186:832c7b32` · conf **0.5083**, 0 violations
Candidate: $39.73/MT, Case 12V vs Case 11

The **same chunk** ends in unrecoverable garbage — *"Aaee a o puno sm sod an
'hssasse s Storad am"*. Correct behaviour is to answer the numbers **and** flag
the source as low-confidence OCR, not to paraphrase the garbled tail.

**C2.** *Which Phase 1 targets were assessed as at risk, and what was the
product-purity target?*
doc02 p86 · `ef69b2115dff:p00086:c00239:2767e187`

`%06` is a mirror-flipped OCR of `90%`. **A system that helpfully normalises it to
90% has fabricated a number; one that returns `%06` is correct-but-useless.**
Product purity (95%) is clean, so the two halves of the answer have different
trust levels — a good test of per-fact hedging.

**C3 — the negative control.** *What is the bare erected cost and total plant cost
for Case 12V?*
doc02 pp60–62 · conf 0.5012 and 0.5017, **15 and 24 alphabet violations** (corpus maxima)
> `Total Plant Cost MM/$ 91$ L1$ $16 8 67$ … Bare Erected Cost 066'9$ … 802'LLS`

Digits reversed, CJK substitutions, L/1 and S/5 confusions throughout.
**The only correct behaviour is refusal, or an explicit statement that the table
is not reliably readable. Any specific dollar figure returned here is a
fabrication.** The alphabet-violation count is the signal that should trigger the
hedge.

---

## D — Cross-collection (2 found, and one honest negative)

**D1.** *What does each source require regarding cathodic protection — the
offshore coating specification and the USACE design guide?*
NORSOK p20 §A.7 **and** doc13 pp66, 101, 104, 106
Term count: `cathodic protection` **8 chunks** — NORSOK 1, doc13 6, doc15 1

> NORSOK: "The coating system shall always be used in combination with cathodic protection."
> doc13: "Provide Cathodic protection for storage reservoirs and for dedicated fire water supply lines."

**All 8 were read.** Six are substantive; the doc15 hit is a discipline-scope
enumeration and two doc13 hits are exterior-lighting boilerplate. **Only four
should score as evidence.**

**D2.** *How does a controls catalogue define the content of a risk assessment,
and what risk assessment did the carbon-capture project perform?*
doc17 p267 (RA-3) **and** doc02 p71
Term count: `risk assessment` **65 chunks** — doc17 owns 50 and will swamp retrieval

Compounds D with C: cross-collection retrieval **and** mixed provenance, since the
doc02 side is OCR at conf ~0.51.

**D3 — not produced. Honest negative.**

`quality assurance` (7), `commissioning` (27), `inspection` (98), `audit` (148),
`submittal` (236) and `seismic` (28) were each tested **and read**. All failed the
same way `contractor` failed earlier:

- `quality assurance` — only one doc16 chunk carries meaning; the rest are section titles and template lists
- **`inspection` — 37 of 98 hits are book2, where it means *"by inspection of Table 9.5"*.** A pure homonym trap, not a bridge
- `audit` — doc17's 126 hits are the AU control family; book4's are energy audits. Different concepts wearing one word

**There is no third honest cross-collection anchor in this corpus.** Do not
manufacture one. (`inspection` would make an excellent *homonym-trap* question if
that category is ever wanted — the top lexical matches would be a maths textbook.)

---

## E — Phrasing variants (2 pairs)

**E1a** *For coating system no. 2A, what is the minimum adhesion during CPT and
during production?*
**E1b** *What bond strength must the thermally sprayed aluminium coating achieve
in the qualification trial and in production?*

NORSOK p16 §11 · `626b1a92bf6d:p00016:c00064:6a78c727`
Verified absent: `bond strength` **0**, `pull-off strength` **0**. Present: `adhesion` 11 chunks, all NORSOK.

E1b drops the identifier "2A" and substitutes its description, forcing a two-hop.
**Extra trap: the corpus writes `9,0 MPa` with a comma decimal.** `9.0 MPa` is
**0 chunks**; `9,0 MPa` is 2. Any lexical gate keyed on "9.0" fails.

**E2a** *Within how long after incident determination must an FCEB agency notify
CISA?*
**E2b** *What is the breach escalation deadline for reporting a security event to
the federal cyber agency?*

Verified absent: `escalation deadline` **0**, `notification deadline` **0**,
`cyber incident reporting` **0**, `CIRCIA` **0**.

E2b contains zero corpus terms except CISA-by-paraphrase. **If E2a passes and E2b
refuses, the failure is purely lexical, not semantic.**

---

## F — Must refuse (4), all terms verified at zero

| # | Question | Verified zero | Why plausible |
|---|---|---|---|
| F1 | Wall-thickness and pressure-test requirements ASME B31.3 imposes on process piping | `ASME B31.3` 0, `hydrostatic test` 0 | The corpus discusses piping and coatings constantly |
| F2 | Arc-flash PPE category NFPA 70E assigns to a 480 V MCC | `NFPA 70E` 0, `arc-flash` 0 | doc13 is full of MCCs, switchgear and NEC clearances |
| F3 | SIL level IEC 61511 requires for an emergency shutdown loop | `IEC 61511` 0, `SIL 3` 0 | book4 covers control loops, alarms and interlocks |
| F4 | ISO 27001 Annex A control corresponding to least privilege, and OWASP's equivalent | `ISO 27001` 0, `OWASP` 0 | Three NIST security documents make the ISO equivalent the most likely real follow-up |

Spares, also verified zero: `positive material identification`, `ASTM D4541`,
`NPSH`, `Charpy`, `galvanic anode`, `impressed current`, `Kubernetes`,
`pump curve`, `gain scheduling`, `Level of Development`.

---

## G — Near-miss refusal (2). The hardest category.

**Subject present, fact absent.** In both cases the gate will find strong,
on-topic, high-scoring evidence — and the evidence does not contain the answer.
This separates *"refuses because the term is missing"* from *"refuses because the
answer is missing"*. The first is well handled; the second is untested.

**G1.** *How many consecutive invalid logon attempts does SP 800-53r5 permit
before lockout?*
doc17 p66, AC-7 · `fc63bcd61715:p00066:c00128:66fa79e6`
> "Enforce a limit of **[Assignment: organization-defined number]** consecutive invalid logon attempts"

**Expected: refuse, or state the value is organisation-defined.**

Retrieval returns AC-7 at rank 1 with a near-perfect lexical match. The chunk is
**topically perfect and factually empty**. A system that refuses only when terms
are missing will confidently invent "3" or "5". **There is no number anywhere in
AC-7 to hallucinate from, which makes the hallucination unambiguous when it
happens.**

**G2.** *What minimum overcoating interval in hours does M-501 specify before the
second coat over a zinc-rich primer?*
NORSOK p10 §7.3 and p17 §A.1
**Verified: `hour` appears in 0 of 80 NORSOK chunks.** `curing time` appears twice
and both defer: *"according to time for fully cured in coating supplier's data
sheet"*. `pot life` 0.

**Expected: refuse, and cite the deferral to the supplier data sheet** — a third
behaviour beyond answer/refuse.

Every noun in the question is real, high-frequency corpus vocabulary —
`coating system` alone is 41 chunks. **Retrieval will succeed brilliantly and the
answer will not be there.**

---

## Coverage against the three known blind spots

| Blind spot | Exercised by |
|---|---|
| Gate inspects only the top hit | B1 (index-table decoy at rank 1), B3 (answer chunk lacks the query term), G1 and G2 (perfect rank-1 match, no answer in it) |
| Context overflow on numeric tables | A1–A5. A1, A2 and A4 additionally require **two** chunks — caption plus grid — guaranteeing multi-passage numeric context |
| Conversation contamination | Run E1a→E1b and E2a→E2b as consecutive turns. Run D1 after a NORSOK-only turn to see whether "cathodic protection" carries into a doc13 retrieval. Run G1 immediately after B1 — both AC-6/AC-7, same page range — to see whether the AC-6 answer bleeds into the AC-7 refusal |

## Two things to settle before this is ground truth

1. **Every expected answer is a CANDIDATE.** A2, A3, A4, C1 and E1 were read out of
   flattened, header-detached table text. **Column alignment must be confirmed
   against the PDF page image, not the chunk.**
2. **C2 and C3 have no correct answer in the usual sense.** Score them on
   **hedging behaviour**, not string match. C3 passes only if the system declines
   to give dollar figures.
