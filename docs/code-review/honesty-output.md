# Honesty review — synthesis, analysis, claims, answer, coverage, reports, and their renderers

**This review is static.** Nothing was executed: no pytest, no vitest, no backend, no PDF
rendered. Every finding below is read off the source, and every line quoted is quoted from the
file at the path given. Where I say a test "would still pass" that is a claim about what the
assertion says, not about a run I performed.

Fourteen findings. Three critical, six high, three medium, two low.

---

## 1. CRITICAL — the frozen PDF claims "quoted verbatim" over OCR text

**`backend/app/reports.py:354`**

**Invariant:** "Quoted verbatim" may be claimed ONLY when the characters came from the PDF's own
text layer. (Also standing rule 13: where provenance decides what a claim may say, a test must
assert the ABSENCE of the stronger claim.)

**What is wrong:** The report's answer heading renders the verbatim label unconditionally on
`answer_type == "extract"`, with no branch on the answer passage's `text_source` — the identical
defect to audit entry 6, in the artefact that outlives the session.

```python
    if s["answer_type"] == "extract":
        parts.append('<p class="label">Quoted verbatim from the document</p>')
        parts.append(f'<p class="quote">{_esc(s["answer"])}</p>')
```

The provenance is *right there* in the snapshot. `build_snapshot` computes it
(`reports.py:154-169`, `"text_source": (sources.pop() if len(sources) == 1 else "mixed")`), the
evidence section reads it correctly (`reports.py:264`, `if (p.get("text_source") or "extracted")
== "recognised":`), and `s["passages"][0]` — the cited answer passage, put first by
`_passages_of` — carries it per passage. Section 2 simply does not look.

**The failure:** A Tier 1 extract answer whose passage is `recognised`. Section 2 of the PDF
reads:

> QUOTED VERBATIM FROM THE DOCUMENT
> Coating system no. 1 shall have a nominal dry film thickness of 280 um.

and section 3, two headings later, reads "Read by OCR from a scanned page - not the document's
own text." Both statements are in one frozen document, and the first is the one printed over the
answer. An engineer reads a specification value as the document's own words when it is a guess
about pixels — measured by ADR-0005 producing `≦` where a specification writes `≤`. **The screen
gets this right** (`AnswerCard.tsx:576-584` branches on `isRecognised(p)` / `p?.text_source ===
"extracted"`), so the PDF claims strictly more than the screen it was frozen from.

**The test that would still pass:** `backend/tests/test_reports.py:308`
`test_a_recognised_passage_carries_its_provenance_line`. It asserts presence only —

```python
    assert "Read by OCR from a scanned page" in text
    assert "0.51" in text
```

— and never `assert "Quoted verbatim from the document" not in text`. Standing rule 13 was
written for exactly this: "a presence-only assertion passes happily while both labels sit on
screen together". Here they sit in one PDF.

**Smallest fix:** branch the label on the answer passage's provenance, as the screen does —
`if any((p.get("text_source") or "extracted") == "recognised" for p in s["passages"] if
p.get("cited"))` renders the OCR label instead — and add the absence assertion to the test above.

---

## 2. CRITICAL — the analysis screen labels every span "quoted verbatim", and provenance is dropped before it can be branched on

**`frontend/src/components/analysis/ClaimTable.tsx:160`**,
**`frontend/src/components/analysis/GapAnalysisCard.tsx:357`**,
**`backend/app/claims.py:215-224`**, **`backend/app/claims.py:1035-1051`**,
**`backend/app/schemas.py:794-800`**

**Invariant:** the verbatim label must branch on `text_source` in EVERY place a quotation is
rendered.

**What is wrong:** Two unconditional verbatim labels on the analysis surface, and the reason
neither can branch is that `claims.Claim` discards `text_source` at the point it reads the
evidence item that carries it.

```tsx
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-signal-400">
        Claim comparison &mdash; quoted verbatim from the documents
      </h3>
```
```tsx
            {baselineIsStated ? "Requirement as stated by the user" : "Baseline, quoted verbatim"}
```

`extract_claims` (`claims.py:423-449`) reads `item.get("exact_span")` off an evidence item that
has `text_source` and `ocr_min_conf` on it (`analysis.to_evidence`, `analysis.py:78-80`) and
constructs a `Claim` with no provenance field at all:

```python
class Claim:
    evidence_id: str
    filename: str
    page_start: int
    section: str | None
    exact_span: str
```

`_row` (`claims.py:1035`) therefore cannot emit one, `GapItemOut`/`ClaimClusterOut` do not
declare one, and the two components above have nothing to test. Provenance is stored, carried to
`chunks`, threaded through retrieval — and dropped one function before the screen that decides
whether a sentence may be called the document's own words. This is audit entry 6's mechanism
reproduced on a different screen.

A third site on the same screen renders a span in the reserved quotation style with no
provenance mark at all: `AnalysisModeScreen.tsx:1122-1124`, `SelectedPassage`, whose
`EvidenceItem` *does* carry `text_source`, `ocr_min_conf` and `ocr_alphabet_violations` and reads
none of them.

**The failure:** any analysis run over a document with recognised pages — 92 recognised chunks
are retrievable per the audit. The Claim comparison panel opens with "quoted verbatim from the
documents" above a blockquote of OCR output, and a gap row prints "BASELINE, QUOTED VERBATIM"
over the recognised text that the whole gap verdict rests on. An engineer comparing "280 um"
against "320 microns" cannot tell that one of them was read off a page image.

**The test that would still pass:** `frontend/src/components/chat/provenance.enumerated.test.tsx`
— the guard written to stop exactly this from recurring. Its sweep is
`/export function (\w+)\(([\s\S]{0,600}?)\)\s*\{/` filtered by `/AnswerPassage/.test(m[2])`, so
it enumerates only components with an `AnswerPassage`-typed prop. `ClaimTable` takes
`ClaimCluster[]`, `GapAnalysisCard` takes `GapAnalysis`, `SelectedPassage` takes `EvidenceItem`
and is not exported — all three are invisible to it, and its `walk(path.resolve(HERE, ".."))`
root is `src/components`, so nothing under `src/views` is scanned either. The file's own
docstring says it catches "anything added later"; that is true only of a later renderer typed
with `AnswerPassage`. **A count without a boundary reads as total** — standing rule 7, applied to
a sweep, which is audit entry 11.

**Smallest fix:** carry `text_source` (and `ocr_min_conf`) onto `Claim`, `_row` and `GapItemOut`;
branch both labels on it; and widen the enumerator to any exported component whose props name
`AnswerPassage | EvidenceItem | ClaimRow | GapItem`, with the root at `src/`.

---

## 3. CRITICAL — a refused recommendation and an absent one are byte-identical on the wire and on screen

**`backend/app/schemas.py:841-853`**, **`frontend/src/views/AnalysisModeScreen.tsx:862-875`**,
**`frontend/src/views/AnalysisModeScreen.tsx:1474-1476`**

**Invariant:** a refusal and an empty result must be distinguishable; a card that renders nothing
and a card that was refused look identical and mean opposite things.

**What is wrong:** `analysis.recommendation()` computes a named reason on both refusal paths
(`analysis.py:1051` and `analysis.py:1065-1068`) and `AnalysisRecommendation` does not declare
the field, so FastAPI's response model drops it before it leaves the process.

```python
class AnalysisRecommendation(BaseModel):
    question: str
    evidence_ledger: list[EvidenceItem]
    recommendation: RecommendationOut | None = Field(
        None, description="null is not an empty recommendation")
    public_market_findings: list[MarketFinding]
    not_implemented_sections: list[str]
```

No `recommendation_refusal`. That the author knows this mechanism is proved by the comment
beside the sibling field in `synthesis.py:1400-1403`: "Not yet declared on
schemas.AnalysisSummary, so the response model drops it at the wire". The client then discards it
a second time — `recSlot`'s adapter never reads it and collapses to the empty slot:

```tsx
            const rec = toRecommendation(d.recommendation, located);
            const findings = rec === null ? [] : onlySamples(d.public_market_findings);
            if (rec === null && findings.length === 0) return null;
```

and `SlotBody` then prints the screen's own guess at a reason:

```tsx
                emptyHint={filteredEmptyHint(
                  "Nothing was produced that carried a citation, so there is nothing to advise on.",
                )}
```

**The failure:** the model declines with `INSUFFICIENT EVIDENCE`, or `_fit` drops every source as
too large for the window, or the transport 503s into `None`. Every one of those arrives on screen
as "No recommendation was generated. Nothing was produced that carried a citation, so there is
nothing to advise on." The sentence is a claim about what happened and it is false in at least
three of the reachable cases: in the window case nothing was ever *produced*, and in the decline
case the model produced a judgement and the screen attributes a citation failure to it. Also note
`synthesis.recommend` returns a bare `None` for six distinct failures (`synthesis.py:1300-1330`)
with no reason attached, which is why `analysis.py:1065` has to guess `REFUSAL_NO_ADVICE` —
"the advisory generation produced no sentence a supplied source supported" — and asserts it over
cases where no generation ran.

**The tests that would still pass:** `backend/tests/test_recommendation_gate.py:238-244`
`test_the_route_returns_null_not_a_sentence_when_the_summary_refused` is the only test that goes
through the route, and it asserts only `assert r.json()["recommendation"] is None` — never that
the reason survived. Every test that *does* assert the reason
(`test_recommendation_gate.py:208-234`, `test_recommendation_from_gaps.py:187-200`) calls
`analysis.recommendation(...)` directly, one layer above where the field is lost. This is the
"check that cannot see the thing it judges" pattern: the assertions are right and the evidence is
about the wrong layer.

**Smallest fix:** add `recommendation_refusal: str | None = None` to `AnalysisRecommendation`,
return the reason from `synthesis.recommend` instead of bare `None`, render it where the summary
refusal is already rendered (`AnalysisModeScreen.tsx:1452-1458`), and add the wire assertion to
the route test.

---

## 4. HIGH — a confidence check that could not be computed renders as "— clear", and a test locks that in

**`backend/app/analysis.py:1016-1022`**, **`backend/app/synthesis.py:1236-1242`**,
**`frontend/src/components/analysis/RecommendationCard.tsx:88-100`**

**Invariant:** unmeasured says unmeasured; `coverage_complete=None` must not read as a pass.

**What is wrong:** `ConfidenceCheck` is `(label, fired: bool)` — a two-state type with no way to
say "not computed" — and two of the seven checks are structurally incapable of firing in this
build, yet both are printed in the checklist as evaluated and clean.

```python
    checks = synthesis.confidence_checks(
        gaps_applicability=gap["gaps"]["applicability"],
        document_statuses=[],
        ...
        # This build computes no coverage object for an analysis, and a
        # missing check must not read as a passing one.
        coverage_complete=None,
```

The comment states the rule and the line below it breaks it:

```python
        ConfidenceCheck(
            "a credible passage was retrieved and not used", coverage_complete is False
        ),
```

`None is False` → `fired=False`. Same for `document_statuses=[]`, which is a hardcoded empty
list, so "a document failed or could not be searched" can never fire either. The renderer turns
`fired=False` into an affirmative statement:

```tsx
                    {c.fired ? "▲ fired" : "— clear"}
```

**The failure:** a run where coverage was never computed and no document status was ever read
shows

> Confidence **medium** — 0 of 7 checks fired
> — clear  a credible passage was retrieved and not used
> — clear  a document failed or could not be searched

"medium" is the strongest word this system may emit, and two of the seven rows it is derived from
are not measurements. `confidence_from` has no third branch ("low" if any fired, else "medium"),
so an entirely unmeasured run is reported as the better of the two words. "0 of 7" is also a
fraction whose denominator counts checks that cannot be computed. The comment recording the
opposite reason is itself a defect of the entry-15 class.

**The test that would still pass — it asserts the defect:** `backend/tests/test_synthesis.py:485`

```python
    assert confidence_checks(**{**CLEAR, "coverage_complete": None})[4].fired is False
```

and `CLEAR` (line 423) carries `"coverage_complete": None`, so
`test_everything_clear_is_medium_and_nothing_else_is` enshrines "medium from an uncomputed
check". Removing the invariant is not detectable because the suite already encodes its absence.
This is standing rule 12: a structure that cannot express its own headline case files that case
under whichever value is least wrong.

**Smallest fix:** give `ConfidenceCheck` a third state (`fired: bool | None`, rendered as "not
computed" and never as "clear"), pass `None` for both uncomputable rows, and make
`confidence_from` return `None` — "not assessed" — rather than "medium" when any check is
uncomputed.

---

## 5. HIGH — the baseline document is counted as a project document that spoke, so a facet only the baseline addresses reads "Met"

**`backend/app/analysis.py:847-869`**

**Invariant:** silence is not compliance. "The document does not mention it" must never render as
met.

**What is wrong:** `others` is "every row that is not the one row I picked as the baseline",
which is used as a proxy for "rows from a non-baseline document". When the baseline document
contributes two rows to a cluster, its second row lands in `others` and satisfies the branch
whose comment says the *project* documents spoke.

```python
        baseline_row = next(
            (r for r in rows
             if document_of.get(r.evidence_id) == baseline_document_id), None
        ) if baseline_document_id else None
        others = [r for r in rows if r is not baseline_row]
```
```python
        elif others:
            # THE PROJECT DOCUMENTS SPOKE. Whatever the label says about HOW
            # they agree, retrieval did not come back empty - so nothing here
            # may claim it did.
            status = STATUS_FOR_LABEL.get(c.label, "insufficient_evidence")
```

**The failure:** the reader nominates doc17 as the baseline and asks about coating thickness.
doc17 states the requirement in two sentences on two pages; no other document mentions it. Both
sentences cluster on the same facet, so `others` is non-empty, `label_cluster` returns
`agreement` (identical dimensions and identifiers), and the row renders

> ✓ MET — Positive matching evidence was found.

with a project-evidence chip that points back at the baseline document's own second passage. The
truth is `possible_gap`: no project document addressed the facet, which is the finding this panel
exists to make. It is inverted, and the caption is a positive claim the row disproves. This is
the same shape as "`ready` derived from a document existing": the status is derived from row
identity rather than from document identity, which usually travels with it.

**Smallest fix:** `others = [r for r in rows if document_of.get(r.evidence_id) !=
baseline_document_id]`, and keep `baseline_row` as the chosen one for display.

---

## 6. HIGH — "addition" maps to "Met · Positive matching evidence was found" when the project row lacks the value

**`backend/app/analysis.py:810-814`**, **`backend/app/claims.py:910`**,
**`frontend/src/components/analysis/GapAnalysisCard.tsx:80-90`**

**Invariant:** silence is not compliance.

**What is wrong:** `label_cluster` returns `addition` precisely when one row carries a
measurement the others lack —

```python
    return ("addition", "One row carries a measurement or identifier the others lack; nothing is contradicted.")
```

— and the status table maps that to `met`:

```python
STATUS_FOR_LABEL: dict[str, str] = {
    "possible_conflict": "conflict",
    "agreement": "met",
    "addition": "met",
```

which the card captions "Positive matching evidence was found." The caption's guard
(`captionRequires: "project_evidence"`, `GapAnalysisCard.tsx:229-236`) tests only that *a* chip
is present, not that the chip's row states the value.

**The failure:** the baseline states "minimum dry film thickness 280 um"; the project document's
row for the same facet carries an identifier and no measurement. The card reads "✓ Met —
Positive matching evidence was found", with a chip that opens a passage saying nothing about
thickness. An absence of the requirement in the project document is rendered as the requirement
being met. The comment at `analysis.py:800-808` argues this is acceptable reuse and then gives
its actual reason — "a broken `Record<GapItemStatus, ...>` in a file another agent is editing
right now". A convenience recorded as a correctness argument is the entry-15 shape.

**Smallest fix:** map `addition` to `insufficient_evidence` when the baseline row carries a
measurement and no non-baseline row does (the comparison could not be made), keeping `met` for
`agreement`; or add the sixth status the comment declined.

---

## 7. HIGH — a Comprehensive summary that dropped five of fourteen documents says nothing about it on the wire

**`backend/app/schemas.py:756-773`**, **`backend/app/synthesis.py:1091-1097`**

**Invariant:** a count must state its boundary; a shortfall named in the engine and not delivered
is silence.

**What is wrong:** `map_reduce` records `documents_summarised` and `documents_refused`, and
`summary_to_api` emits them, and `AnalysisSummary` declares neither — so the response model drops
both. `AnalysisSummary` does declare `refusal` and `dropped_sentences`, which is what makes the
omission look deliberate when it is not.

`map_reduce`'s docstring claims the delivered result is honest about it:

```
    ONE DOCUMENT FAILING IS NOT THE SUMMARY FAILING. ... The result is honest about the shortfall
    - the reader is told which documents are not represented - rather than either hiding it
```

The reader is not told. The field never leaves the process.

**The failure:** a Comprehensive run (limit 24) over fourteen documents where nine map calls
survive and five decline. The screen shows the reduce's prose under "Summary of N passages" and
carries no statement that five documents contributed nothing. A summary presented without its
boundary reads as a summary of the corpus — which is standing rule 7, and audit entry 11 twice
over.

**The test that would still pass:** `backend/tests/test_synthesis_map_reduce.py:265-266` asserts
`summary_to_api(out)["documents_refused"] == [...]` — the engine's dict, not the HTTP response.
No test posts to `/api/analysis/summary` and asserts the field arrives.

**Smallest fix:** declare `documents_summarised: list[str]` and `documents_refused:
list[DocumentRefusal]` on `AnalysisSummary`, render them beside the existing
`DroppedSentences` block, and assert them through `TestClient`.

---

## 8. HIGH — the recommendation route runs a second synthesis, so its refusal can contradict the summary panel beside it

**`backend/app/analysis.py:1009-1011`**, **`backend/app/analysis.py:966-978`**

**Invariant:** a refusal says what actually happened, and one screen may not give two
contradictory answers to one question.

**What is wrong:** `recommendation()` calls `_synthesise` again rather than reusing the
summary route's result, and `advisory_refusal` then makes a claim about "the document layer" from
that second, independent generation.

```python
    evidence, raw = gather(question, scope, limit=limit)
    gap = gaps(question, scope, limit=limit,
               baseline_document_id=baseline_document_id)
    summarised = _synthesise(question, evidence, limit, generate)
```
```python
REFUSAL_NO_DOCUMENT_LAYER = (
    "no recommendation: the document layer produced no cited sentence"
)
```

`settings.temperature = 0.1` (`config.py:143`), so the two generations are not required to agree.
The client mitigates by sequencing (`AnalysisModeScreen.tsx:791-799`, whose comment records the
live defect and says "the proper fix (reuse the summary's findings server-side) is tracked"), but
sequencing removes CPU contention, not divergence.

**The failure:** the summary panel renders three cited sentences; the recommendation section
below it says "no recommendation: the document layer produced no cited sentence (the model
reported the sources do not support a summary)". Both are on one screen, about one question, and
one of them is false. It is also two syntheses of the same evidence on a 15 W CPU-bound 4B model
— the cost the review's own engineering rule flags.

**Smallest fix:** have the recommendation path take the summary's `findings` (or an
already-computed `Summary`) instead of re-synthesising, so the sentence about "the document
layer" describes the layer the reader is looking at.

---

## 9. HIGH — Chat's Tier 2 gate is per-answer, not per-sentence, so an uncited sentence is rendered

**`backend/app/answer.py:660-690`**

**Invariant:** a generated sentence that cannot be cited is DROPPED, never shown. No claim
without resolving evidence.

**What is wrong:** the chat answer path checks only that *at least one* marker in the whole
completion resolves, then ships the completion whole.

```python
    if not valid:
        return {
            ...
            "answer_type": "insufficient_evidence",
```
```python
    return {
        **base,
        "answer_type": "generated",
        "answer": text,
```

`synthesis._cite` (`synthesis.py:540-600`) does the per-sentence work — drops a sentence that
cites nothing, drops one carrying a number no cited span contains, drops one asserting a
compliance the span does not state, and rebuilds the prose from the survivors. None of that
machinery is applied in `answer.py`, and `AnswerCard`'s Tier 2 branch renders `view.answer`
verbatim (`AnswerCard.tsx:729-735`).

**The failure:** the model returns "Coatings must be 0.28 mm thick. [S1] All work is compliant
with the relevant standards." over a source that says "280 um" and asserts no compliance. `valid`
is `[1]`, so the answer is served. On screen the reader gets a converted unit under a resolving
citation and a compliance claim with no citation at all — the two defects `synthesis.py`'s
docstring names as the ones this product exists to prevent, on the screen most people use. Two
gates, two standards, one product.

**Smallest fix:** run the completion through the same sentence gate — extract `_cite`,
`claimed_numbers` and `assertions.unsupported` into a shared module (they were deliberately
duplicated for import hygiene, not for behaviour) and rebuild `text` from the survivors, refusing
when none survives.

---

## 10. HIGH — the clause label suppressed on every other surface is still printed on the analysis screen

**`frontend/src/views/AnalysisModeScreen.tsx:1119`**

**Invariant:** a citation must resolve to a real document and page; a value the codebase cannot
stand behind is not printed.

**What is wrong:** `clauseLabel` returns `null` in every case, deliberately, because
`chunks.section` was measured wrong on 5 of 6 cited passages and 0 of 11 correct on doc16
(`Provenance.tsx:126-166`). Chat stopped printing it, the PDF stopped printing it
(`reports.py:244-256`), `ClaimTable` stopped printing it and says why
(`ClaimTable.tsx:98-113`). `SelectedPassage` still prints it:

```tsx
        {item.section !== null && <span>&sect; {item.section}</span>}
```

**The failure:** the reader clicks a citation chip in the summary and the passage panel opens
with "doc16.pdf p.22 § 6.0 Procedure" — a heading that is on page 15. The audit records that
fabricated clause numbers are zero corpus-wide, which is what makes a stale one dangerous: it is
a real clause from the same document and reads as plausible. Four surfaces now disagree about the
same clause, which the ClaimTable comment argues is worse than none of them naming it.

**Smallest fix:** route this through `clauseLabel(...)` like every other surface, or delete the
span.

---

## 11. HIGH — "quoted directly, no AI rewriting" is printed beside "Provenance unknown"

**`frontend/src/components/chat/Provenance.tsx:112`**, **`frontend/src/components/chat/AnswerCard.tsx:586-598`**

**Invariant:** absence of provenance is not evidence of provenance; a verbatim string may appear
only over text-layer characters.

**What is wrong:** the label branch is a positive predicate on three states, but the detail line
beside it is a negative predicate on one:

```ts
export function provenanceDetail(passage: AnswerPassage): string {
  if (!isRecognised(passage)) return "quoted directly, no AI rewriting";
```

`"quoted directly, no AI rewriting"` is one of the two `VERBATIM_STRINGS` this module exists to
police (`Provenance.tsx:20-23`). `AnswerCard` calls it whenever a passage object is present:

```tsx
          {recognised && p ? (
            <ProvenanceMark passage={p} variant="full" />
          ) : extracted ? (
            <Label tone="quote">Quoted verbatim from the document</Label>
          ) : (
            <Label tone="ocr">Provenance unknown — source not attached</Label>
          )}
          {view.seconds != null && (
            <span className="font-mono text-[11px] text-slateish-500">
              {formatDuration(view.seconds)}
              {" · "}
              {p
                ? provenanceDetail(p)
                : "this answer arrived without its source passage — it cannot be checked"}
```

**The failure:** a replayed transcript whose persisted payload predates the `text_source` field —
`viewFromMessage` reads `m.payload ?? {}` straight out of the messages table with no validation
(`AnswerCard.tsx:64-80`), and `chat.py:367` `json.loads(r["payload"])` does not fill defaults. A
passage object exists with `text_source` undefined, so `recognised` is false and `extracted` is
false. The card renders, on one line:

> PROVENANCE UNKNOWN — SOURCE NOT ATTACHED    1.2s · quoted directly, no AI rewriting

The label says the provenance is unknown and the sentence next to it makes the verbatim claim.

**The test that would still pass:** `provenance.enumerated.test.tsx`'s
`viewWithNoPassage()` sets `passage: null`, which takes the safe `p ? … : …` branch. The failing
case — a passage that *exists* with unknown provenance — is not in any fixture, so the assertion
never reaches it. The file's own comment ("A test whose fixtures exclude the failing case is not a
test of that case") describes its remaining gap.

**Smallest fix:** make `provenanceDetail` a positive predicate too — return the verbatim detail
only for `passage.text_source === "extracted"`, and a "provenance not recorded" line otherwise —
and add a fixture with `text_source` absent.

---

## 12. MEDIUM — the analysis narrowed the corpus to two documents and nothing on the response says so

**`backend/app/analysis.py:1009`**, **`backend/app/analysis.py:670-681`**,
**`backend/app/main.py:777-784`**

**Invariant:** a count must state its boundary. "12 documents" with no boundary reads as total.

**What is wrong:** `gather` computes the narrowing record and every caller throws it away.

```python
    result["analysis_named_documents"] = names
    result["analysis_named_scope_applied"] = narrowed
    result["analysis_per_document_cap"] = cap
    result["analysis_per_document_cap_lifted"] = bool(
        hits and max(shares.values()) > cap)
    result["analysis_document_shares"] = shares
```

with the comment "A narrowing that did not apply is recorded as not having applied rather than
being indistinguishable from one that did". `summary()` and `gaps()` discard it as `_`;
`recommendation()` binds it to `raw` (`analysis.py:1009`) and never reads it — a value resolved
and discarded, which is entry 15's shape. Meanwhile the one boundary the response *does* carry
describes a different filter:

```python
        "documents_in_scope": len(narrowed.allowed_document_ids),
```

that is the classification-narrowed scope, computed in `main._analysis_scope` before
`gather` narrows again by filename.

**The failure:** the reader asks "compare design submittal percentages in doc13.pdf and
doc16.pdf" over a 13-document corpus with no filter set. `narrow_to_named` restricts retrieval to
2 documents; `applied_scope` reports `applied: false, documents_in_scope: 13`. The summary is
presented as an answer over everything the reader can read, and eleven documents were never
searched. Note the narrowing is correct behaviour and well argued — only its invisibility is the
defect.

**Smallest fix:** return the `analysis_*` keys from `summary`/`gaps`/`recommendation`, declare
them on the three response models, and print the boundary line the frontend already has a slot
for.

---

## 13. MEDIUM — "Summary of N passages" counts what the model was shown, and the prose survives citations that do not resolve

**`frontend/src/components/analysis/SummaryCard.tsx:200-203`**,
**`frontend/src/views/AnalysisModeScreen.tsx:410-415`**, **`backend/app/synthesis.py:1385`**

**Invariant:** a count must state its boundary; a citation must resolve to a real document and
page.

**What is wrong, first half:** the field named `summary_cited_evidence_ids` is populated from
`positional_evidence_ids` — every source the model was *shown* —

```python
        "summary_cited_evidence_ids": list(summary.positional_evidence_ids),
```

(the dataclass comment at `synthesis.py:300-305` admits "the name is the frontend's") and the
card counts it as the summary's extent:

```tsx
              Summary of {n} passage{n === 1 ? "" : "s"}
```

A Quick run showing 8 sources of which the surviving prose cited 2 is headed "Summary of 8
passages". `Summary.cited_evidence_ids` — the actual answer — is computed and never serialised.

**What is wrong, second half:** the client's own rule 4 gate is applied to the findings list and
not to the prose:

```ts
export function citedSummary(r: AnalysisSummaryResult): string | null {
  const ids = Array.isArray(r.summary_cited_evidence_ids) ? r.summary_cited_evidence_ids : [];
  if (typeof r.summary !== "string" || r.summary.trim() === "") return null;
  if (ids.length === 0) return null;
  return r.summary;
}
```

`citedFindings` (`AnalysisModeScreen.tsx:226-232`) requires `ids.every((id) => located.has(id))`
and drops the claim otherwise — "It is not rendered with a caveat: the claim would still be on
screen and the reader takes the claim." `citedSummary` only counts. So the same claim can be
dropped from Documented findings for an unresolvable citation and still be on screen as prose, in
the same card.

**Smallest fix:** serialise `cited_evidence_ids` as a separate field and count that; and gate the
prose with the same `located.has` test the findings use.

---

## 14. LOW — two smaller instances of the same family

**a. `backend/app/reports.py:283-289` — "Citation audit passed" over zero markers.**
For `answer_type == "extract"` there are no `[S#]` markers in the answer at all, `missing` is
empty, and the `generated`-only branch does not apply, so the PDF prints

```python
            '<p class="ok">Citation audit passed: every inline [S#] marker '
            'resolves to evidence frozen in this report.</p>'
```

A green audit over an empty population. It is standing rule 14 — a check that can run against
zero inputs must assert it ran against more than zero — and it is what an engineer will read as
positive verification. Fix: say "no inline markers to audit; the answer is a single quoted
passage" on the extract branch.

**b. `frontend/src/views/AnalysisModeScreen.tsx:449-460` — a hardcoded 0 under a comment
promising nulls.** The docstring says "Every count is null rather than 0", and the first field
is `authorized_documents_selected: 0`. `CoverageLedger.tsx:53` renders it unconditionally —
``const segments: string[] = [`${c.authorized_documents_selected} authorized`];`` — under its own
comment "Only the counts that were measured. A null contributes no segment." Not currently on the
live path: `App.tsx:249` mounts `AnalysisModeScreen`, which does not render `CoverageLedger` and
says so at line 54; `AnalysisView` has no importer outside a test comment. Latent, and both
comments are false of the code beside them. Fix: type the field `number | null`, pass `null`, and
make the first segment conditional like the rest.

Also noted, not filed as a finding: `claims.py:439` `page_start=int(item.get("page_start") or 0)`
would render "p.0" in `ClaimTable` for a null page. `EvidenceItem.page_start` is typed `int` on
the schema, so I could not find a path that produces it; the 0 is a defensive default that would
print as a measurement if one ever appeared.

---

# Verified clean

Traced, and the invariant holds. Where it holds, this says what enforces it.

- **The citation gate in synthesis, sentence by sentence.** `synthesis._cite`
  (`synthesis.py:540-600`) drops a sentence that cites no supplied source, one carrying a number
  no cited span contains (`claimed_numbers` / `_numbers`), and one asserting a compliance the span
  does not state (`assertions.unsupported`); each drop is recorded in `dropped_sentences` with a
  reason. `summary.text` is **rebuilt** from the survivors (`synthesis.py:923`), so the reader
  cannot be shown a rejected sentence. `CitedSentence.__post_init__` raises `UncitedClaim` on
  empty `citation_ids`, so an uncited claim is not representable.
- **Invented citations.** `validate_citations` bounds markers to `1..len(sources)`;
  `_strip_invented` removes out-of-range markers from the text and `rejected_citations` counts
  them; `SummaryCard`'s `DeadChip` renders an unresolvable marker struck through and never
  clickable. Same in `answer.py:663-666`.
- **Markers for evidence removed to fit the window.** In all four call sites — `_run_summary`,
  `map_reduce`'s map and reduce, `recommend`, and `answer.py:598` — `_fit`/`fit_passages` runs
  **before** `build_prompt` numbers the sources, so `[S#]` is always positional over the surviving
  set and a marker for a removed source is not constructible. What was removed travels on
  `evidence_removed` and is rendered per source with filename and page
  (`AnswerCard.tsx:769-793`).
- **"high" is structurally unreachable.** `confidence_from` has two branches;
  `Recommendation.__post_init__` raises on anything but `low`/`medium`/`None`;
  `RecommendationOut.confidence` is `Literal["low","medium"] | None`; and
  `confidenceWord` (`AnalysisModeScreen.tsx:172`) maps anything else to `null`. Four independent
  layers, and `test_high_is_unreachable_from_every_combination_of_checks` enumerates all 2^7
  firing patterns. (The *derivation* is the defect in finding 4, not the word's reachability.)
- **`coverage.complete` is never true.** `confidence_checks` raises on `True` as an input
  (`synthesis.py:1225`); `coverage.py` returns `False` or `None` only, on both the
  `not reranked` and the `no uncited credible passage` paths, with a note explaining the null
  rather than a "2 of 2"; `completeness()` discards a `true` arriving over the wire.
- **The summary refusal reaches the screen.** `refusal` is declared on `AnalysisSummary`, read by
  `AnalysisModeScreen.tsx:811`, and rendered above the card at line 1452-1458. The
  three-way refusal split — model declined / model returned nothing usable / model unreachable — is
  decided before the `INSUFFICIENT` check in `_unusable` and covered by
  `test_synthesis_honest_gate.py:329-402`, including `test_the_three_refusals_are_three_different_sentences`.
- **The baseline is never inferred.** `gaps()` sets `applicability = "applicable" if
  baseline_document_id else "not_applicable"` and nothing else writes it;
  `main.analysis_gaps` puts the caller's id through `require_document` (404, not 403); with no
  baseline every non-conflict row is `not_applicable` rather than `insufficient_evidence`
  (`analysis.py:853-862`), and a disagreement keeps `conflict` because it is knowable without an
  authority. A stated requirement is refused loudly rather than silently dropped
  (`AnalysisModeScreen.tsx:903-914`).
- **"Not addressed" is not counted as a gap or as met** in the one branch that decides it:
  `analysis.py:866-869`, where only the baseline is in the cluster, yields `possible_gap` — worded
  as possible — and `gap_evidence_ids` excludes `not_applicable` rows from the advisory footing
  because "a facet nothing could be compared against is not evidence that something is there".
  (Findings 5 and 6 are the two paths where an absence still reaches `met`.)
- **Facets are not named from unit tokens.** `_is_subject_term` (`claims.py:468`) requires a
  letter, so "%", "(%)", "5" and "7.1" cannot name a facet; `subject_terms` strips `dim:` and
  `designator:`; the unit appears only in brackets after the subject. `_facet_phrase` is
  deterministic, its support floor and tie-breaks are stated, and it degrades to a bare word
  rather than inventing a phrase.
- **Nulls render as nothing, in the places I checked.** `reports._fmt` prints "not measured" for
  `None`; `revision`/`approval_status` print "not recorded"; `to_evidence` sets
  `relevance_score_type: None` rather than 0.0 and `highest_scoring` sorts `None` last rather than
  as zero; `hasBaselineSpan`, `noteOf` and `hasFacet` withhold a label rather than print it over
  an empty string; `clauseLabel` returns null and its docstring forbids "unknown"/"N/A"/a dash;
  `OcrConfidence` returns null when `ocr_min_conf` is null; `toClaimRow` keeps an unparseable
  `normalized_value` as null "never 0 - 0 is a real measurement".
- **No percentage without a denominator.** I found no percentage emitted by any of these modules.
  `tallyLine` is counts and status names only, with no total and no ratio;
  `percentage_intent`/`carries_percentage` are predicates about the *documents'* percentages, not
  claims of their own. The one bare fraction is "N of M checks fired", whose denominator is stated
  and whose defect is finding 4.
- **Market rows.** `onlySamples` drops any row not declaring `is_sample === true`, and
  `MarketFinding.is_sample` is `Literal[True]`, so an unlabelled row has no shape on screen.
- **The report is frozen and drift is reported, not resolved.** `render()` reads the snapshot
  only; `verify()` compares live `sha256`, `filename`, `chunk_signature` and `indexed_at` against
  the frozen row and returns `evidence_drift` rather than re-rendering;
  `on_document_deleted` unlinks the file and keeps the record with a `suppressed_reason`. The PDF
  names what it does **not** contain on page 1. Its remaining defect is finding 1 — the label,
  not the freezing.
- **Scope.** Every analysis entry point takes an `AccessScope` and passes it into `search()`;
  `named_document_ids` bounds the filename lookup twice (`id IN (allowed)` in SQL and an
  intersection on the way out) and its `sqlite3.Error` fallback returns `frozenset()`, which can
  only shrink; `_corpus_filenames` is scope-bound so a name the caller cannot see is not a name
  they can ask about.

---

# Not reviewed

- **Anything I would have had to run.** No test was executed, no mutation planted, no PDF
  rendered, no route called. The severities above rest on reading; the claims about what a test
  asserts are checkable from the quoted lines, but I did not watch any test pass or fail.
- **Files outside my assignment**, except where I followed a value into them to confirm a
  finding: `search.py`, `keyword.py`, `lexical.py`, `passages.py`, `chunker.py`, `ocr.py`,
  `context_budget.py` internals (I confirmed only that `fit_passages` is called before the prompt
  is numbered), `market*.py`, `access.py`, `auth.py`, `db.py`, `metrics.py`, `chat.py` beyond the
  payload round-trip.
- **`assertions.py`'s vocabulary.** I confirmed `_cite` calls `assertions.unsupported` and uses
  `assertions.reason` for the drop record; I did not audit which compliance verbs it covers, so I
  cannot say how much of "silence is not compliance" that gate actually catches in generated
  prose.
- **`eval/`.** Not read. Two recorded defects (#14, #22) live there, and this review says nothing
  about whether the harness can see the layers above.
- **`test_recommendation_gate.py`'s `PENDING` bookkeeping.** `analysis.REFUSAL_RESTATEMENT` is
  referenced at lines 257 and 267 and does not exist in `analysis.py`; those two tests are marked
  `@PENDING` (strict xfail), so they fail on `AttributeError` rather than on the assertion. That is
  consistent with the module's stated design, but I did not verify the PENDING count against the
  current tree — audit entry 23 is precisely a stale count in this file's prose.
- **Whether the legacy-payload state in finding 11 exists in this database.** I did not query the
  `messages` table. The finding rests on `viewFromMessage` reading unvalidated persisted JSON and
  on `text_source` being a recent addition; if no such row exists the defect is latent rather than
  live, and the contradiction in the code is real either way.
