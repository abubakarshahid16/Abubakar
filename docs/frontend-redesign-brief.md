# RAG Intelligence System — frontend redesign brief

You are redesigning the interface for a working product. The backend is
finished and will not change for you. Everything below is a description of
what already exists and what the screens must do with it.

Read the whole brief before drawing anything. The **Rules** section is not
style guidance — those rules exist because breaking them puts a false
statement in front of an engineer, which is the one thing this product cannot
do.

---

## 1 · What the product is

**RAG Intelligence System** answers questions about engineering documents — coating
specifications, design manuals, security standards — and shows the exact page
every sentence came from.

It runs **entirely on the user's laptop**. No cloud, no API key, no telemetry.
Documents never leave the building. That constraint is the product's reason to
exist and the thing a client's security reviewer checks first.

The consequence you must design around: **it is slow.** A cited extract takes
about 2 seconds. A generated summary takes **60–90 seconds** on a 15 W laptop
CPU with no GPU. This is not a bug to hide behind a spinner — it is the visible
cost of the privacy guarantee, and the interface should say so.

**Who uses it:** engineers and reviewers checking what a specification
requires. They are technical, but not necessarily in the document's discipline
— a procurement officer reading a coatings standard will not know what NDFT
means. They are checking a fact they will act on, so they need to see the
source, not just the answer.

---

## 2 · Rules — non-negotiable

These are correctness rules, not preferences. A design that breaks one is
wrong even if it looks better.

1. **Every claim on screen carries a document and a page.** An uncited
   sentence must not be renderable. If the data has no citation, the sentence
   does not appear.

2. **A null renders as nothing.** Never a zero, never a dash, never "N/A",
   never an empty box. An absent value must be *visibly absent*. A zero the
   system never measured is a lie that looks like data.

3. **`complete` is never `true`.** Coverage completeness is `false` or `null`
   only. There is no way to know a corpus is complete, so the interface must
   never claim it.

4. **`confidence` is only "low", "medium", or null. Never "high."**

5. **A sample is always labelled as a sample.** Market findings are synthetic
   fixtures. Every row, everywhere it appears, must be impossible to mistake
   for a real source.

6. **Refusal is a first-class answer, not an error.** When the documents do
   not support an answer, the system says so. That screen should look
   deliberate and trustworthy — not like a failure state.

7. **"Backend offline" and "that request failed" must never look the same.**
   They have different causes and different fixes. This has already been a
   recorded defect.

8. **The quoted passage is the product.** It gets the most typographic care on
   any screen it appears on. Everything else is quieter than it.

---

## 3 · Hard constraints

| | |
|---|---|
| **No outbound requests, ever** | No Google Fonts link, no CDN, no remote images, no analytics. Fonts must be self-hosted as woff2 files shipped with the app. A `fonts.googleapis.com` link breaks the product's central guarantee. |
| **Stack** | React 19 + TypeScript + Vite + **Tailwind CSS v4** (`@theme` tokens in `index.css`) |
| **Both themes** | Light and dark, both fully designed, driven from one token set. Do not treat either as an afterthought. |
| **Contrast** | Body text ≥ 7:1, secondary ≥ 4.5:1 at its size. The current secondary text is **4.1:1** and is the top complaint. |
| **Every colour is a token** | No hex values inside components. Changing the accent must be one line. |
| **Responsive** | Works from 1280px down to a tablet. Sidebar collapses below ~900px. |
| **Keyboard + a11y** | Visible focus rings, `aria-current` on nav, `role="status"` on live regions, `prefers-reduced-motion` respected. |
| **Tabular numerals** | Every figure in a column must align. This is a specification tool; wandering digits look careless. |

---

## 4 · The screens

Six screens in a left sidebar. Design **every state listed**, not just the
happy one.

### 4.1 Sidebar (persistent)

- Product name **RAG Intelligence System**, subtitle "private document intelligence"
- Six items, each a **label over a one-line hint**:

| Label | Hint |
|---|---|
| Documents | Upload, inspect, verify |
| Chat | Ask questions with citations |
| Analysis | Summary, gaps, advice |
| Ingestion | Queue and throughput |
| Dashboard | System metrics |
| Reports | Frozen evidence, as PDF |

**Keep the hints.** Six bare nouns do not tell a first-time user what each
screen is for. This was tried and was worse.

- Foot of the sidebar: current user and role (or "Authentication disabled — no
  user identity"), a connection indicator, and the answer model's state.
- Active item must be unmistakable. The current version differs from its
  neighbours by a 3% lighter background — nearly invisible.

### 4.2 Documents

Upload and inspect. **States: empty · uploading · processing · ready ·
failed · backend offline.**

- Drop zone for PDFs, with the reassurance "Files stay on this machine"
- A worker strip: pending, oldest waiting, time since progress, completed
- **A filter field.** There are 12–20 documents and currently no way to search
  them.
- Per document: filename, status, page count, passages **searchable / total**,
  embedded count, keyword index state, finish time
- Per-document actions: Passages · Pages · Excluded · **Delete**
  → Delete must not look identical to the other three. It currently does.
- Warnings that need to be visible but not dominant:
  - *"N characters are not searchable"* — front matter and contents pages are
    excluded deliberately; anything else is worth checking
  - *"Page N was a scan, so it was read with recognition (OCR)"* — text from a
    scan can contain reading errors, and the original page image must be one
    click away

### 4.3 Chat — the primary screen

Left: conversation list. Right: the exchange.

**Conversation list.** Question text, message count, relative time.
**Repeated identical questions must collapse into one row with a count** —
seven rows reading "what does NDFT stand for" is noise, not a list.

**An answer consists of:**
- The question asked
- **The quoted passage** — verbatim from the document. Serif, generous
  leading, ~60 character measure. This is the most important element on the
  screen.
- Citation chips: `doc02.pdf · p.36`, clickable to open that page image
- A **Save as report** button (generates the PDF — see 4.6)
- An **Explain in plain language** button, which upgrades the extract to a
  generated answer and takes 60–90 seconds
- Where relevant: *"One credible passage was not used"* — a passage that
  scored above the cut but was dropped at the shortlist limit, with a way to
  show it

**Answer types you must design for** — these are the real enum values:

| `answer_type` | What the screen shows |
|---|---|
| `extract` | A verbatim quotation with citations |
| `generated` | Model prose, every sentence cited |
| `insufficient_evidence` | **A refusal.** The documents do not support an answer. Must look deliberate and trustworthy. |
| `model_unavailable` | The local model is not running — a setup problem, not a document problem |
| *(chitchat)* | The input was never a document question. Nothing was searched, so nothing is shown as considered. |

**The waiting state — design this carefully.** A generated answer takes 60–90
seconds. The backend reports real stages, so the screen shows what is actually
happening:

```text
Searching 12 documents  →  Ranking 16 of 53 candidates
  →  Reading 3 passages  →  Writing the answer
```

- An elapsed counter, and a typical range ("usually 60–90s")
- **No percentage bar.** The length of a generation is unknown until it ends,
  so a bar would be an invention.
- One line explaining *why* it is slow: a 15 W laptop CPU, no GPU, nothing
  leaving the machine. **The honest slow answer is a selling point when the
  screen says why.**

**Evidence panel.** Opens beside an answer: the full passage, its section
heading, the page image, and whether the text was extracted or recognised by
OCR.

### 4.4 Analysis

One question, three engines, one screen. **Modes: Summary · Recommendation ·
Gap analysis.**

- A question field and a Run action
- Optionally, a baseline document to compare the others against

**Summary** — cited sentences, each with document and page.

**Claim comparison table** — the distinctive feature. Columns: source ·
what it says · converted value · verdict.

Verdicts are `agreement` · `addition` · `possible_conflict` · `unresolved`.

> **`possible_conflict`, never `conflict`.** The documents carry no revision
> or approval status, so which supersedes the other cannot be determined.
> The interface must never imply it can.

The most important row type is the one that says **"different subjects."**
`1,5 mm` in one document and `280 µm` in another are not a conflict if one
describes equipment tag V-2104 and the other piping class 300#. The design
must make that distinction obvious, because a false conflict is worse than no
comparison.

**Recommendation** — advisory only. Carries `confidence: "low" | "medium" |
null` and never "high".

**Coverage ledger** — how many documents of the total were searched, and which
credible passages were found but not used.

**Market findings** — synthetic sample rows. Every one labelled. The response
itself carries a `notice` and an `egress` state — surface both.

**States: nothing run yet · running · complete · partial (one engine failed) ·
insufficient evidence.**

> Note: a summary takes ~78 s and a recommendation ~63 s, but gap analysis
> returns in about 7 s because it needs no model. **Show the fast result
> immediately rather than making the user wait for all three.**

### 4.5 Dashboard

Measured system state. Currently sixteen identically-weighted boxes with no
hierarchy.

- **Four headline figures**, larger than everything else: searchable
  percentage, typical answer time, document count, items needing attention
- Attention items say what happened and carry the action that fixes it.
  **Never show internal codes** like `NEEDS_OCR` — those are database
  identifiers, not words for a client.
- Supporting metrics — corpus counts, processing speed, retrieval latency —
  as a scannable list where figures align in a column, not sixteen cards
- Header note: *"Every value is measured. Anything unmeasured says so rather
  than showing a zero."* Keep this. It is the dashboard's whole thesis.

### 4.6 Reports

A report is **one question, its quoted evidence, and the documents it came
from, frozen at the moment it was generated.**

- List of reports: title, generation time, documents cited, passage count,
  file size
- **Download PDF** and **Verify**
- **Verify is the most valuable thing in this product.** It returns
  `snapshot_intact`, `file_intact` and `evidence_drift`. A report can prove
  its evidence has not changed since it was made. Design this so it reads as
  the guarantee it is, not as a minor utility.
- When a cited document has been re-uploaded since: *"A document cited here
  has changed. The PDF still shows the evidence as it stood — it has not
  silently changed underneath you."*
- *"N reports are not shown here — they cite documents you do not have access
  to."* The user must be able to see that something is hidden without seeing
  what it is.

### 4.7 Login

Appears only when the deployment requires authentication.

- Email and password, sign-in action
- **"Wrong password" and "the backend is unreachable" must look different.**
  This is a recorded defect.
- Rate-limit state: too many attempts, retry in ~30 seconds
- No account creation, no password reset — this is a local deployment
- Sits **above** the main shell, carrying no navigation to screens the user
  cannot reach

### 4.8 Ingestion

Queue and throughput while documents are processed. Per-document stage
progress, pages per second, failures with a reason.

---

## 5 · Data shapes

Use these exact values. They are the real contracts.

```ts
type AnswerType =
  | "extract" | "generated" | "insufficient_evidence"
  | "model_unavailable" | "chitchat";

type ClaimLabel =
  | "agreement" | "addition" | "possible_conflict" | "unresolved";

type GapItemStatus =
  | "met" | "possible_gap" | "conflict"
  | "insufficient_evidence" | "not_applicable";

type GapApplicability =
  | "applicable" | "not_applicable" | "insufficient_baseline";

type Confidence = "low" | "medium";          // never "high"
type TextSource = "extracted" | "recognised" | "mixed";
type AuthMode   = "disabled" | "demo_required";

type ProgressStage =
  | "retrieving" | "reranking" | "reading" | "generating" | "done";

interface EvidenceItem {
  evidence_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  section: string | null;
  exact_span: string;          // verbatim from the document
  text_source: TextSource;
  ocr_min_conf: number | null;
  relevance_score: number;
  relevance_score_type: "rerank" | "fused";
}

interface ClaimRow {
  evidence_id: string;
  filename: string;
  page_start: number;
  section: string | null;
  exact_span: string;
  raw_value: string | null;        // "1,5"
  raw_unit: string | null;         // "mm"
  normalized_value: number | null; // 1500
  normalized_unit: string | null;  // "um"
}

interface ClaimCluster {
  facet: string;                   // e.g. "coating thickness (µm)"
  label: ClaimLabel;
  rows: ClaimRow[];
  note: string | null;             // why, in the system's own words
}

interface Coverage {
  complete: false | null;          // NEVER true
  documents_searched: number;
  documents_total: number;
  credible_not_cited: EvidenceItem[];
}
```

**Every one of these fields can be `null`, and a null renders as nothing.**

---

## 6 · What to deliver

1. **A design system** — colour tokens (light + dark), a type scale with named
   steps, spacing scale, radii, shadows, focus treatment. Tailwind v4 `@theme`
   format.
2. **Every screen in section 4**, in both themes, in **every state listed** —
   including empty, loading, refused, partial and offline. The error states
   are not optional; they are where this interface currently fails.
3. **A component inventory** — buttons with a real hierarchy (one primary per
   row; destructive quiet until hovered), status pills, citation chips, the
   quoted-passage block, the claim table, metric tiles, the progress panel,
   inline notices, empty states.
4. **The typeface choice, self-hosted.** Name it, and say which weights are
   needed so the woff2 files can be bundled. **Do not link to a font CDN.**
5. **Notes on what you changed and why**, keyed to the problems in section 7.

Deliver as HTML/CSS or a component spec. **Do not deliver a Figma link** — the
output has to become React and Tailwind.

---

## 7 · What is wrong with the current interface

Fix these specifically. Do not reintroduce them.

| # | Problem |
|---|---|
| 1 | **Secondary text is 4.1:1** on the background — below the accessibility floor for the size it is used at. This is the top complaint. |
| 2 | **The ground is a blue-black** (`#070b10`). The hue tints every grey above it and reads cold and muddy. A neutral ground is better; the accent should be the only chroma. |
| 3 | **No type scale.** Headings, body and labels all sit within 4px of each other, so nothing leads the eye. |
| 4 | **No measure.** Text runs the full width of a 1900px monitor. ~60% of some screens is empty space to the right. |
| 5 | **Sixteen identical cards** on the Dashboard. Headline figures and supporting details get the same box, border and weight. |
| 6 | **Delete looks like Passages.** Five equal-weight buttons, one of which destroys a document. |
| 7 | **Full-width warning slabs** per document make every page look like a fault log. |
| 8 | **Empty states dominate.** A 200px dashed void is the largest object on three screens. |
| 9 | **Internal codes on screen** — `NEEDS_OCR`, `EQUATION_PAGES`. |
| 10 | **Duplicate conversations** — seven identical rows in the sidebar. |
| 11 | **The active nav item** differs by a 3% lighter background. Nearly invisible. |
| 12 | **The long wait is opaque.** "Searching the documents · 0s…" for 78 seconds reads as broken. |
| 13 | **Jargon is unexplained.** NDFT, OCR, Sa 2½, NDFT — the reader may not be in that discipline. |

---

## 8 · The single thing to get right

A user reads an answer, and needs to know **whether to trust it.**

Everything else on the screen serves that: the verbatim quotation, the page
number they can open, the note saying a credible passage was not used, the
refusal when the documents do not support an answer, the report that proves
its own evidence has not changed.

**A design that makes this product look confident is a worse design than one
that makes it look checkable.**
