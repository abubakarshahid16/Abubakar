# Frontend review — `frontend/src` + `contracts/types.ts`

Static review of the full text of the priority files, plus three read-only
checks actually executed on the device (`tsc`, two single test files). Commands
and their real output are at the bottom. Nothing on the device was modified.

**Headline correction to the brief.** The brief says `DashboardView.test.tsx`
fails "because it does not mock `classification.coverage()`". It does mock
coverage — the diff adds a `/classification/coverage` branch to `mockApi`. The
actual cause is `/classification/vocabulary`, which is *not* routed and falls
through to `: []`, and the failure is not an assertion but an uncaught
`TypeError` thrown inside `DocumentsView`. Finding 2. And
`DocumentsView.test.tsx` is failing too (15 of 29) — that was not mentioned.

---

## 1. CRITICAL — Confirming a document's type silently erases its discipline, its doc_class and every subject

**`frontend/src/views/DocumentsView.tsx:208`**

```tsx
const result = await classification.confirm(doc.id, { doc_type: docType });
```

**What is wrong.** The confirm body carries only `doc_type`, but the backend
treats the body as a complete replacement, so the three fields the frontend
omits are written as null/empty.

**The failure.** `ClassificationUpdate` on the backend defaults every other
field (`backend/app/schemas.py:434-437`):

```python
    doc_type: str | None = None
    discipline: str | None = None
    doc_class: str | None = None
    subject_ids: list[str] = Field(default_factory=list)
```

and `confirm()` (`backend/app/classification.py:396-412`) writes all of them
unconditionally:

```python
            " ON CONFLICT(document_id) DO UPDATE SET"
            " doc_type=excluded.doc_type, discipline=excluded.discipline,"
            " doc_class=excluded.doc_class, confirmed_by=excluded.confirmed_by,"
...
        conn.execute("DELETE FROM document_subjects WHERE document_id = ?",
                     (document_id,))
        for subject_id in subject_ids or ():
```

So an admin clicking **Confirm** on a document the register correctly
classified as `discipline: "Electrical"`, `doc_class: "P&ID"`, with three
subjects attached, gets: `doc_type` confirmed, `discipline` → NULL,
`doc_class` → NULL, all three `document_subjects` rows deleted, and
`suggested_by` overwritten with `SOURCE_NONE` — so a register-authoritative
classification is recorded as having come from nothing.

On screen the card shows exactly what the admin wanted: the amber guess chip
goes plain and neutral. Nothing says anything was lost. The document then
vanishes from the discipline axis of `/classification/coverage` (the `by_disc`
query is `AND c.discipline IS NOT NULL`) and from every subject-scoped
analysis run — `disciplines_spanned`, the measurement that made subject the
comparison axis for gap analysis, is computed off the table this click just
emptied. This is a destructive write disguised as a confirmation, and the more
correct the register's suggestion was, the more it destroys.

**Smallest fix.** Send the classification the card is already holding:

```tsx
const c = classifications[doc.id];
const result = await classification.confirm(doc.id, {
  doc_type: docType,
  discipline: c?.discipline ?? null,
  doc_class: c?.doc_class ?? null,
  subject_ids: (c?.subjects ?? []).map((s) => s.id),
});
```

(Belt and braces on the backend: make `ClassificationUpdate` fields
`| None`-with-no-default and treat an absent key as "leave alone". But the
frontend call is the one line that stops the data loss today.)

**Vacuous-test note.** `DocumentsView.test.tsx:221-229` cannot produce this
condition. Its PUT mock *preserves* what the real backend wipes:

```tsx
        const posted = init?.body ? JSON.parse(init.body as string) : {};
        const base = byId?.[id] ?? defaultClassification(id);
        return jsonResponse({
          ...base,
          doc_type: posted.doc_type ?? base.doc_type,
```

`...base` carries `discipline` and `subjects` straight back. No test in the
file inspects the PUT body at all. Mutation that should go red and does not:
change the call to `classification.confirm(doc.id, {})` — the test
"lets an admin confirm a guessed type" still passes, because the mock's
`posted.doc_type ?? base.doc_type` falls back to the base fixture.

---

## 2. CRITICAL — A vocabulary response without `types` takes the whole Documents screen down; this is what is actually breaking 24 Dashboard tests

**`frontend/src/views/DocumentsView.tsx:298`** and
**`frontend/src/components/classification/TypeFilter.tsx:94`**

```tsx
      {vocabulary && vocabulary.types.length > 0 && load.state === "ready" && (
```

```tsx
  if (failed || !vocab) return null;
  ...
    types: vocab.types,
```

**What is wrong.** `useTypeVocabulary` guards that the response *exists* but
never that it has the shape it claims, so any body that is truthy but lacks
`types` yields `{ types: undefined }`, and the two `.types.length` reads throw.

**The failure.** Observed, not inferred. `DashboardView.test.tsx`'s `mockApi`
routes `/classification/coverage`, `/metrics` and `/health`, and everything
else — including `/classification/vocabulary` — falls to `: []`. `request()`
resolves `{ok: true, data: []}`, `vocab` is a truthy array, `vocab.types` is
`undefined`. The test renders `<App />`, whose default view is `documents`, so
`DocumentsView` mounts before the Dashboard click and throws:

```
TypeError: Cannot read properties of undefined (reading 'length')
 ❯ DocumentsView src/views/DocumentsView.tsx:298:39
```

24 of 26 tests in the file fail with 25 uncaught errors. In production the same
body — a proxy returning `[]`, a partial response, or the next backend rename
of `types`, which is the `payload`/`payloads` defect verbatim — gives the
reader a blank Documents screen. The type filter's own doc comment promises the
opposite: *"a filter that cannot load is a filter that is not offered, and the
screen behind it works exactly as it did before classification existed."* A
missing `types` field does not degrade to no filter; it takes the screen.

**Smallest fix.** Two lines, both needed.

Product (`TypeFilter.tsx:92`):
```tsx
  if (failed || !vocab || !Array.isArray(vocab.types)) return null;
```

Test (`DashboardView.test.tsx`, in `mockApi`'s router, before the `/metrics`
branch):
```tsx
    if (url.includes("/classification/vocabulary")) {
      return Promise.resolve(new Response(JSON.stringify({
        register_revision: null, types: [], disciplines: [],
        subjects: [], needs_classification: 0,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
```

The product fix alone would turn the 24 failures green, which is precisely why
both are needed: with only the guard, the suite would pass while never once
exercising a real vocabulary.

---

## 3. HIGH — "Awaiting a type" is printed over a count of documents awaiting *confirmation*, next to a different number under the identical label

**`frontend/src/views/DocumentsView.tsx:319-320`** and
**`frontend/src/views/DashboardView.tsx:529-531`**

```tsx
            <FilterChip
              label={AWAITING_TYPE_LABEL}
              count={vocabulary.needsClassification}
```

```tsx
                {coverageInScope && coverage!.needs_classification > 0 && (
                  <span className="ml-1 text-warn-500">
                    · {nf.format(coverage!.needs_classification)} awaiting a type
```

**What is wrong.** `needs_classification` counts documents with no *confirmed*
classification; both sites label it as documents with no *type*. Those are
different sets, and the screen shows both numbers at once.

**The failure.** `backend/app/classification.py:567-572`:

```python
        f"   AND (c.document_id IS NULL OR c.confirmed_by IS NULL)",
```

— every unconfirmed document, including the ones that already carry a guessed
type. The group heading immediately below the chip is built by `groupByType`
(`DocumentsView.tsx:125-138`), which buckets on `doc_type !== null`, so it
counts only documents with no type at all. On a 12-document corpus where 10
carry an unconfirmed guess and 2 carry nothing, the screen reads:

> Type · All · Document 6 · Drawing 4 · **Awaiting a type 12**
> …
> **AWAITING A TYPE  2**

Two numbers, one label, ten apart. On the Dashboard the same count sits under
per-type chips that already account for every document: `Documents 6` /
`Drawing 4  Specification 2` / `· 6 awaiting a type` — the chips say all six
have a type and the amber line says none do. A reader cannot tell which
sentence is lying, and the filter chip is worse than the tile: ticking it
returns 2 rows against a promise of 12, which reads as ten missing documents.

This is the audit's own shape — a field derived from something adjacent
(`confirmed_by IS NULL`) rather than from the thing the label names
(`doc_type IS NULL`).

**Smallest fix.** Relabel both sites to what the number counts, and separate
the group heading's words from the chip's:

```tsx
export const AWAITING_TYPE_LABEL = "Awaiting a type";      // the group: doc_type IS NULL
// chip and tile:
label="Awaiting confirmation"   /   `· ${n} awaiting confirmation`
```

(The stronger fix is a `needs_type` field on `ClassificationCoverage`, but the
copy change removes the false claim today and the label then matches the query
behind it.)

---

## 4. HIGH — `ClassificationSource` declares three values the backend never sends and omits the one it does; the type is written so tsc can never catch it

**`contracts/types.ts:1246` and `contracts/types.ts:1255`**, rendered at
**`frontend/src/components/DocumentCard.tsx:116, 408-418`**

```ts
export type ClassificationSource = "register" | "filename" | "content" | "none";
...
  suggested_by: ClassificationSource | string;
```

Backend, `backend/app/classification.py:76-78` — the complete set:

```python
SOURCE_REGISTER = "register"
SOURCE_PATTERN = "pattern"
SOURCE_NONE = "none"
```

**What is wrong.** `"filename"` and `"content"` do not exist on the wire;
`"pattern"` does and is not declared. And `ClassificationSource | string`
collapses to `string`, so the enum is decorative — no rename on either side can
break the build.

**The failure.** `sourceLabel` switches on the two values that never arrive:

```tsx
function sourceLabel(source: string): string {
  switch (source) {
    case "filename":  return "the title";
    case "content":   return "the content";
    default:          return source;
```

so every real unconfirmed guess takes the `default` and the raw wire word
reaches the chip:

> **Drawing? · guessed from pattern**

Both intended branches are dead code. This is the `payload`/`payloads` defect
reproduced exactly — including the part where the contract file's own header,
added in this same diff, promises it cannot happen: *"these names are copied
from the Python, not invented here, and a rename on either side must break the
build."* Copied names would have produced `"pattern"`; `| string` guarantees a
rename never breaks anything.

**Vacuous-test note, same finding.** `DocumentsView.test.tsx:657-663, 712-717`
fixes `suggested_by: "filename"` and asserts

```tsx
    const guessChip = screen.getByText(/Drawing\? · guessed from the title/i);
```

The fixture uses a value the backend cannot emit, so the test asserts against
its own mock's shape and would pass unchanged against a backend that had never
heard of `filename`. It is the 23-market-panel-tests failure mode, and `| string`
is what let the fixture compile. (This assertion is *currently* red for a
different reason — see finding 9 — but fixing that would leave it green over the
wrong string.)

**Smallest fix.**
```ts
export type ClassificationSource = "register" | "pattern" | "none";
...
  suggested_by: ClassificationSource;      // no `| string`
```
then `sourceLabel`'s exhaustive cases become `case "pattern": return "the
filename and content";` and the fixtures stop compiling until they say
`"pattern"`.

---

## 5. MEDIUM-HIGH — A verbatim claim asserted from a negative predicate, printed beside the label that just refused it

**`frontend/src/components/chat/Provenance.tsx:112`**

```ts
export function provenanceDetail(passage: AnswerPassage): string {
  if (!isRecognised(passage)) return "quoted directly, no AI rewriting";
```

**What is wrong.** `"quoted directly, no AI rewriting"` is one of the two
strings this very file exists to police (`VERBATIM_STRINGS`, line 20-23), and it
is returned from `!isRecognised` — the absence of one provenance value, not the
presence of the other.

**The failure.** `AnswerCard.tsx:568-593` gets the positive predicate right and
then contradicts itself two lines later:

```tsx
    const recognised = isRecognised(p);
    const extracted = p?.text_source === "extracted";
...
            <Label tone="ocr">Provenance unknown — source not attached</Label>
...
              {p ? provenanceDetail(p) : "this answer arrived without its source passage — it cannot be checked"}
```

For a passage that exists but whose `text_source` is neither value — a replayed
message from a build before the field, a trimmed payload, a proxy that dropped
it — the card renders, on one line:

> **PROVENANCE UNKNOWN — SOURCE NOT ATTACHED**  ·  2.8s · quoted directly, no AI rewriting

The label refuses the claim and the meta text makes it anyway, in the stronger
of the two policed phrasings. The card's own comment beside it states the rule
being broken: *"Branch on provenance, never on anything else… Absence of
provenance is not evidence of provenance."* `provenanceDetail` is the one place
in the module that does not follow it.

**Smallest fix.**
```ts
  if (passage.text_source === "extracted") return "quoted directly, no AI rewriting";
  if (!isRecognised(passage)) return "provenance not recorded — this cannot be checked";
```

---

## 6. MEDIUM — A failed per-document classification fetch renders as the affirmative claim "Awaiting a type", permanently

**`frontend/src/views/DocumentsView.tsx:106`** with
**`frontend/src/components/classification/useDocumentClassifications.ts:78-83`**

```tsx
function typeOf(doc: DocumentRecord, byId: Record<string, DocumentClassification>): string | null {
  return byId[doc.id]?.doc_type ?? null;
}
```

**What is wrong.** A missing entry (request failed, or never answered) is
collapsed with `doc_type: null` (a real server answer), and the hook's own
contract forbids exactly that.

**The failure.** The hook says so in its interface doc:

> *"Absent (not `null`) while the request is in flight or has not been started
> yet — callers must not read a missing entry as 'awaiting a type', which is a
> real answer the server gives, not a loading state."*

`typeOf` does read it that way, and `groupByType` files the result under the
heading `AWAITING_TYPE_LABEL`. A document whose single classification request
returned 500 sits under a heading asserting the server said it has no type. It
never recovers: the hook's effect depends on `idsKey` alone, so an id that
failed is never in `byIdRef.current`, is re-added to `pending` only if the effect
re-runs, and the effect will not re-run while the id list is unchanged — which is
every poll tick on a settled corpus. A refusal and an empty look identical, for
the life of the mount.

**Smallest fix.** Have the hook record failures and expose them, then group them
apart:
```ts
if (result.ok) setById(...); else setFailed((prev) => ({ ...prev, [id]: true }));
```
and render those documents under "Type could not be read" rather than "Awaiting
a type". Minimum viable version: keep them in their own group keyed on
`!(doc.id in byId)`.

---

## 7. MEDIUM — A page image that fails to load leaves the sentence "This is the real page" over a broken image

**`frontend/src/components/chat/EvidencePanel.tsx:227-250`**

```tsx
        <p className="mt-1 text-xs text-slateish-500">
          {boxed
            ? "The answering sentence is outlined on the real page. …"
            : "Extraction flattens tables and drops equation operators. This is the real page."}
        </p>
...
            onLoad={() => setImageLoading(false)}
            onError={() => setImageLoading(false)}
```

**What is wrong.** `onError` is handled identically to `onLoad` — the spinner
clears and nothing records that the render failed.

**The failure.** The page image is, by this file's own opening comment, *"the
only way to verify a citation for certain."* When `/pages/...` 404s or the
renderer errors, the reader gets a broken-image glyph, or nothing, directly
beneath a sentence asserting that the real page is on screen. A citation that
could not be shown is indistinguishable from a page that is genuinely blank —
and blank pages exist in this corpus (the audit's entry 8 table lists page 23
of NORSOK as "genuinely blank"). The one control that lets a reader falsify an
answer fails silently.

**Smallest fix.** A third state:
```tsx
const [imageFailed, setImageFailed] = useState(false);
// reset alongside imageLoading in the existing effect
onError={() => { setImageLoading(false); setImageFailed(true); }}
{imageFailed && <p role="alert" className="…">The page image could not be
  rendered, so this citation cannot be checked against the page here.</p>}
```

---

## 8. LOW-MEDIUM — The "Awaiting a type" chip count is fetched once and never refreshed, so it stays stale after every confirmation

**`frontend/src/views/DocumentsView.tsx:320`** with
**`TypeFilter.tsx:70-84`** (`useEffect(..., [])`)

**What is wrong.** `useTypeVocabulary` reads vocabulary and coverage exactly once
per mount; `confirmType` patches only the one card via `setOneClassification`.

**The failure.** An admin confirms all seven unconfirmed documents. Each card
updates in place, correctly. The chip above them still reads **"Awaiting a type
7"**, and the per-type counts still read their pre-confirmation values, until the
reader leaves the view and comes back. The document list beside them is polling
(`usePoll(refresh, working)`), so the screen shows a live list next to frozen
counts with nothing distinguishing the two — the "stale numbers presented as
current" failure, scoped to the counts.

**Smallest fix.** Return a refetch from the hook and call it after a successful
confirm:
```tsx
const { vocabulary, reload } = useTypeVocabulary();
...
if (result.ok) { setOneClassification(doc.id, result.data); void reload(); … }
```

---

## 9. LOW — Three new tests assert against text the component splits across elements, so they were never run green

**`frontend/src/views/DocumentsView.test.tsx:672, 640, 624`**

```tsx
    const guessChip = screen.getByText(/Drawing\? · guessed from the title/i);
```

against `DocumentCard.tsx:116`:

```tsx
                  {classification.doc_type}? · guessed from {sourceLabel(classification.suggested_by)}
```

**What is wrong.** Three interpolations produce three text nodes; `getByText`
matches a single node.

**The failure.** Measured: 15 of 29 tests in `DocumentsView.test.tsx` fail, with
`Unable to find an element with the text: /Drawing\? · guessed from the title/i.
This could be because the text is broken up by multiple elements`, and
`Unable to find an element with the text: 1` for the group-count assertion.
Separately, `Found multiple elements with the text: /Awaiting a type/i` is
finding 3 surfacing as a test failure — the chip and the heading collide. Six
further failures are pre-existing tests in blocks B2–B5 (`role="dialog"` not
found, `/confirm delete/i` not found) that the new grouping path appears to have
broken; I did not diagnose those individually.

The conclusion that matters: **this diff's frontend tests have not been run.**
39 tests across two files are red, and the brief describes one file with one
cause.

**Smallest fix.** Use a matcher function or `{ exact: false }` against the chip
element, e.g.
`screen.getByText((_, el) => el?.getAttribute("data-testid") === "type-chip" && /guessed from/.test(el.textContent ?? ""))`,
scope the "Awaiting a type" queries with `getByRole("heading", …)` vs
`getByRole("checkbox", …)`, and run the file.

---

## Test review (rule 2), for the files covering the above

| Test | Fails if feature deleted? | Mocks the thing under test? | Fixture can reach the condition? | Positive control? |
|---|---|---|---|---|
| `AnalysisModeScreen.typeFilter.test.tsx` — "scope.types in all three bodies" | Yes — removing the `scope` key empties the assertion | No, renders the real screen | Yes | Yes: "sends NO scope key when nothing is ticked" |
| …"renders documents_in_scope … differs from the ledger" | Yes | No | Yes — 7 vs a 1-document ledger is a genuine anti-local-computation control | Yes |
| …"says the filter narrowed the search" | Yes | No | Yes | **Yes** — "keeps the unfiltered empty wording when no filter is active" |
| `DocumentsView.test.tsx` — "lets an admin confirm a guessed type" | No, meaningfully. **Mutation that stays green: `classification.confirm(doc.id, {})`** — the PUT mock's `posted.doc_type ?? base.doc_type` supplies the answer the product failed to send (finding 1) | Yes — the mock preserves `discipline`/`subjects` the real backend deletes | **No** — cannot produce the data-loss condition | n/a |
| `DocumentsView.test.tsx` — "renders an unconfirmed guess in amber" | Would pass over a wire value that cannot occur (finding 4) | Asserts its own fixture's `"filename"` | Cannot produce the real `"pattern"` | Yes (the confirmed-chip half) |
| `DashboardView.test.tsx` — the whole file | Cannot say: 24 of 26 abort before their assertions (finding 2) | — | — | — |
| **Sequencing (`AnalysisModeScreen.tsx:860`, `summaryJob.then(...)`)** | **No test covers it.** `AnalysisModeScreen.run.test.tsx`'s only change relaxes an existing count. **Mutation that stays green:** revert to `analysisApi.recommendations(body).then(...)` — the concurrency the change was made to remove returns and every test passes. A test would need to resolve summary manually and assert `/analysis/recommendations` was not yet called | — | — | — |

---

## Contract drift table

| Frontend field | Backend field | Verdict |
|---|---|---|
| `ClassificationSource = "register" \| "filename" \| "content" \| "none"` | `SOURCE_REGISTER/PATTERN/NONE` = `"register" \| "pattern" \| "none"` (`classification.py:76`) | **DRIFT** — finding 4 |
| `DocumentClassification.suggested_by: ClassificationSource \| string` | `suggested_by: str` (`schemas.py:412`) | **DRIFT** — `\| string` collapses the union; nothing can break the build |
| `ClassificationUpdate.subject_ids?: string[]` (optional) | `subject_ids: list[str] = Field(default_factory=list)`, and `confirm()` DELETEs then re-inserts | **DRIFT with data loss** — optional on one side, destructive default on the other. Finding 1 |
| `ClassificationUpdate.discipline?/doc_class?` (optional) | `= None`, written as `excluded.discipline` / `excluded.doc_class` | **DRIFT with data loss** — finding 1 |
| `ClassificationVocabulary.{register_revision,types,disciplines,subjects,needs_classification}` | `schemas.py:363-383` | Match |
| `SubjectRow.kind: "system"\|"facility"\|"project_wide"` | `Literal[...]`, same three | Match |
| `DocumentSubject.{id,name,kind,suggested_by,confirmed_by}` | `schemas.py:386-391` | Match |
| `DocumentClassification.{document_id,doc_type,discipline,doc_class,register_id,confirmed_by,confirmed_at,confirmed,subjects}` | `schemas.py:394-421` | Match, incl. nullability |
| `CoverageByType.in_register: number \| null` | `int \| None` | Match — and the null is honoured at `TypeFilter.tsx:186` and `DashboardView.tsx:290` |
| `ClassificationCoverage.{register_loaded,register_revision,by_type,by_discipline,by_subject,needs_classification,corpus_wide}` | `schemas.py:467-476` | Match |
| `ClassificationScope.{types,disciplines,subject_ids}` all optional | all `default_factory=list` | Match — absent means "do not filter" on both sides |
| `AppliedScope.{applied,types,disciplines,subject_ids,documents_in_scope}` | `schemas.py:493-509` | Match |
| `AnalysisRequest.scope?: ClassificationScope \| null` | route takes it and passes it to `classification_mod.restrict` (`main.py:485, 684`) | Match |
| `applied_scope` on the three analysis results | present on the backend (`schemas.py:529, 775, 823, 851`; echoed at `main.py:495, 713, 727, 752`) | **Declared on the backend, absent from `contracts/types.ts`.** Not a runtime bug — `applyServerScope` reads it through `unknown` and degrades to no count — but the contract is behind the API, which is the condition the audit's entry 21 describes. Worth adding to the three interfaces |
| `AnswerPassage.text_source: "extracted" \| "recognised"` (non-null) | required on the backend | Match on the wire; the frontend nonetheless has a third rendering branch for it, which is right — and finding 5 is where that branch contradicts itself |

---

## Verified clean (what I checked and found sound)

- **`Provenance.tsx`** apart from finding 5: `isRecognised` and
  `hasAlphabetViolation` are positive predicates on `text_source`; `OcrConfidence`
  returns null on `ocr_min_conf == null` rather than rendering `0.00`;
  `clauseLabel` returns null unconditionally and every caller renders nothing for
  null (checked all three: `Citation`, `PassageLocation`, and the absence of any
  other call site).
- **`AnswerCard.tsx` extract branch (568-593)** is correct on the point the audit
  records: the verbatim label is asserted from `text_source === "extracted"`, the
  recognised case gets `ProvenanceMark`, and `p === null` gets "Provenance
  unknown". The `p && p.kind !== "table" && view.answer === p.text` guard before
  `Highlighted` is the right conservatism.
- **`AnswerCard` generated branch**: `rejected_citations` shown rather than
  swallowed; `evidence_removed` names each dropped source with a count;
  `truncated` distinguished from a crash; `documentsAnsweredFrom` counts from
  the evidence and over-counts in the safe direction so the comparison notice
  can only be suppressed, never wrongly fired.
- **`AnalysisModeScreen`'s scope handling**: one `scope` built once and sent to
  all three engines; no `scope` key at all when nothing is ticked (verified in
  the code and by a test that asserts `hasOwnProperty` is false); `appliedScope`
  cleared on retick and on `supersede()`, so a stale count cannot survive;
  `applyServerScope` refuses to invent a count when the field is absent;
  `filteredEmptyHint` distinguishes "the filter hid it" from "the documents are
  silent", with a positive control.
- **`TypeFilter.tsx`** apart from finding 2: types come from the register with no
  hardcoded fallback; nothing ticked = no filter; `count != null` guards against
  rendering `0` for "unknown"; the in-scope count is the server's echo only;
  `role="checkbox"` + `aria-checked` on the button, with the fake box
  `aria-hidden` — correct.
- **`DashboardView`'s boundary guard**: `coverage.corpus_wide === metrics.corpus_wide`
  before showing any per-type count, and `needs_classification > 0` before showing
  the amber line, are both the right calls; `TypeCounts` renders whatever `by_type`
  returns in the server's order with no hardcoded names.
- **`DocumentsView`'s empty-group copy** correctly weakens the claim for a
  non-admin ("None of the documents you can open is a X" vs "There are no X"),
  and the boundary sentence under the chips states whose documents the counts
  cover.
- **`useDocumentClassifications`** concurrency: `MAX_CONCURRENT` bound is real,
  the `cancelled` flag is checked after every await, `idsKey` avoids the
  poll-refetch loop, and `byIdRef` avoids the confirm-clobber race the comment
  describes. Only the failure path is wrong (finding 6).
- **`MarketPanel.tsx`** on the two rules it exists for: `preview.data.payloads`
  (plural, from the contract), one rendered block per tier, `payloads.length === 0`
  handled explicitly, sample rows tagged in both the row and a banner, offline
  copy that forbids describing rows as live, and a confirm path that refuses to
  send what it could not show. I read this by targeted search rather than in
  full — see Not reviewed.
- **`GapAnalysisCard.tsx`** null discipline: `noteOf` rejects whitespace-only
  notes so a null cannot render as a blank paragraph; `captionFor` returns null
  when the row does not bear the caption out and both `note !== null` and
  `caption !== null` are guarded at the JSX; the missing-filename case
  (`filename === null && baseline.document_id !== null`) is handled rather than
  rendering an empty name.
- **`tsc -p tsconfig.app.json --noEmit` is clean** — which is the point: every
  contract drift in the table above passed it.

## Not reviewed

- `MarketPanel.tsx` (836 lines) read by targeted search on the honesty strings and
  the payload plumbing, not line by line. `GapAnalysisCard.tsx` (606) likewise, on
  nulls, percentages and status captions. `SummaryCard.tsx`, `ClaimTable.tsx`,
  `CoverageLedger.tsx`, `RecommendationCard.tsx`, `ModeSelector.tsx` not read.
- Priority 4 entirely: `ChatView.tsx`, `IngestionView.tsx`, `AdminView.tsx`,
  `AdminScreen.tsx`, `ReportsView.tsx`, `ReportsScreen.tsx`, `LoginView.tsx`,
  `Shell.tsx`, `App.tsx` beyond the one-line `isAdmin={canAdmin}` diff (which is
  correct — it threads `canAdmin` into the prop whose default is the safe `false`).
- `hooks/usePoll.ts`, `components/ChunkInspector.tsx`, `ExcludedViewer.tsx`,
  `PageImageViewer.tsx`, `Uploader.tsx`, `WorkerPanel.tsx`, `LocalWork.tsx`,
  `Drawer.tsx`, `documentStatus.ts`, `states.tsx`.
- The six B2–B5 failures in `DocumentsView.test.tsx` (dialogs and delete
  confirmation) are reported as a count in finding 9 but not diagnosed.
- Backend reading was confined to `schemas.py`, `classification.py` and the
  classification routes in `main.py`, for the drift table. No backend review.
- Nothing was mutated to prove a test red — the brief is read-only on the device,
  so every "mutation that stays green" above is named and argued, not executed.

---

## Commands run, and their output

All three on the device, read-only, in `$HOME/mnt/Rag_chatbot/frontend`.

**1.**
```
npx tsc -p tsconfig.app.json --noEmit
```
No output; exit 0. **Clean.**

**2.**
```
npx vitest run src/views/DashboardView.test.tsx --reporter=dot
```
```
 Test Files  1 failed (1)
      Tests  24 failed | 2 passed (26)
     Errors  25 errors
   Duration  66.62s
```
with, repeatedly:
```
⎯⎯⎯⎯⎯ Uncaught Exception ⎯⎯⎯⎯⎯
TypeError: Cannot read properties of undefined (reading 'length')
 ❯ DocumentsView src/views/DocumentsView.tsx:298:39
    296|           a search it just ran - it does not apply to a list already s…
    297|           on screen. This filter never leaves the browser. */}
    298|       {vocabulary && vocabulary.types.length > 0 && load.state === "re…
       |                                       ^
```

**3.**
```
npx vitest run src/views/DocumentsView.test.tsx --reporter=dot
```
```
 Test Files  1 failed (1)
      Tests  15 failed | 14 passed (29)
   Duration  49.58s
```
Failures (first line of each):
```
B2 documents list > warns only about scanned pages recognition has NOT yet read
  Error: expect(element).toBeInTheDocument()
B2 documents list > requires a second click to delete
  Unable to find an accessible element with the role "button" and name `/confirm delete/i`
B3 chunk inspector > opens, shows full chunk detail, and can filter to excluded chunks
  Unable to find role="dialog"
B4 excluded viewer > groups by rule so a bulk exclusion is visible at a glance
  Unable to find role="dialog"
B4 excluded viewer > is reachable in one click from the low-ratio warning
  Unable to find role="dialog"
B5 page image viewer > shows the rendered page and offers zoom
  Unable to find role="dialog"
B5 page image viewer > closes on Escape
  Unable to find role="dialog"
documents grouped by classification type > groups documents under a heading per register type
  Unable to find an element with the text: 1. … the text is broken up by multiple elements
documents grouped by classification type > puts a document with no classification yet in its own awaiting group…
  Found multiple elements with the text: /Awaiting a type/i
documents grouped by classification type > renders an unconfirmed guess in amber, distinct from a confirmed type
  Unable to find an element with the text: /Drawing\? · guessed from the title/i. … broken up by multiple elements
```
(the listing above is the first ten of the fifteen; the grep used
`grep -E "FAIL|AssertionError|Error:"` and returned these)

**Recommendation: this should not be committed as it stands.** Finding 1
destroys data on a routine admin click, finding 2 can blank the app's default
view, and 39 frontend tests are red.
