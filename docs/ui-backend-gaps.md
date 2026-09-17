# UI/backend evidence-field inventory

Phase 0 inventory recorded 2026-09-17. “Hidden” means the backend already
returns the value in the relevant response but the named UI surface does not
show it. It does not mean the field should automatically be exposed; raw
retrieval values need careful, non-judgemental presentation.

## Chat answer and evidence panel

| Field | Returned | Current display | Gap / decision |
| --- | --- | --- | --- |
| document, filename, page range, section, exact passage | Yes | Answer source rows and `EvidencePanel` | Visible. Verbatim extracted text remains visually separate from generated prose. |
| `text_source` | Yes | `ProvenanceMark`; extracted text gets the verbatim label, recognised text gets the OCR label | Visible and correctly prevents OCR text being called verbatim. |
| `ocr_min_conf` | Yes for recognised text | `OcrConfidence` in the evidence citation | Visible without an invented pass/fail threshold. |
| `ocr_alphabet_violations`, `ocr_alphabet_sample` | Yes | `ProvenanceMark`/detail names the count and offending characters | Visible for recognised passages. |
| `score` | Yes | Not shown | Hidden. If exposed later, place under Retrieval details with its scale and no “strong/weak” label. |
| `identifier_hits` | Yes | Not shown | Hidden. Useful only as diagnostic/retrieval detail. |
| `evidence_removed` | Yes | Amber disclosure in `AnswerCard`: count, filename/page, dropped vs shortened, omitted character count | Already visible. Do not rebuild. Screenshot: `ui-redesign/evidence-removed-chat.png`. |
| server header `X-Answer-Located` | Yes on boxed-page response | Discarded by `fetchImageObjectUrl`; UI says “answer outlined” whenever a pre-request highlight exists | **Gap.** Return the header through the image hook and show the explicit unlocated state when it is `0`. Do not draw a client-side box. |
| raw `rrf`, `boost`, `rerank_score`, `bm25`, `cosine`, keyword/dense rank | Present in backend search records, not in the answer-passage contract | Not shown | Not a missing widget: those values are not delivered on this response. If Phase 3 requires them, extend the answer API contract and tests first. |

## Analysis summary and selected evidence

| Field | Returned | Current display | Gap / decision |
| --- | --- | --- | --- |
| `dropped_sentences[].sentence` and `.reason` | Yes | Collapsed `DroppedSentences` details directly after `SummaryCard`; count remains honest when text is absent | Already visible. Do not rebuild. Controlled presentation screenshot: `ui-redesign/dropped-sentences-analysis-controlled.png`. |
| `evidence_removed` | Yes | Parsed by the response contract but not rendered in the Analysis summary result | **Gap.** Reuse the existing AnswerCard wording/pattern near the summary; do not create a second data model. |
| evidence filename, page, section, exact span | Yes | `SelectedPassage` | Visible. |
| evidence `text_source` | Yes | Finding/summary components preserve source kind, but `SelectedPassage` itself does not label extracted vs recognised | **Gap.** Reuse `ProvenanceMark` in the selected source. |
| `ocr_min_conf`, `ocr_alphabet_violations` | Yes | Not shown in `SelectedPassage` | **Gap.** Reuse existing OCR disclosure; no threshold or verdict. |
| `relevance_score`, `relevance_score_type` | Yes | Not shown | Hidden intentionally for now. Any later retrieval-details view must name the rerank scale and avoid cross-scale comparisons. |
| assertion flags | No standalone response field | Unsupported compliance/approval/obligation wording is removed and represented through `dropped_sentences.reason` | No duplicate flag panel can be built from current data. If a future design needs flags separate from removals, add a typed API field and tests first. |

## Gap analysis

`GapAnalysisCard` does **not** receive `dropped_sentences` or
`evidence_removed`; the gaps response contract does not contain them. The card
already has a different honesty mechanism: it counts structurally empty result
rows and states how many were withheld. That is not the same event and must not
be relabelled as model evidence removal.

| Field | Returned by gaps route | Current display | Gap / decision |
| --- | --- | --- | --- |
| baseline and applicability | Yes | Baseline header / nominate-baseline state | Visible. |
| gap status, facet, rows, citations | Yes | Status/tally and item rows | Visible; nulls are not guessed. |
| empty-row withheld count | Derived from response rows | Plain disclosure below the rendered rows | Visible. |
| `dropped_sentences` | No | None | Do not invent or duplicate. |
| `evidence_removed` | No | None | Do not invent or duplicate. |

## Reports

The generated PDF already includes `evidence_removed` when present and records
OCR provenance/alphabet warnings. The Reports list itself is an index and does
not expand those details until the file is opened. Phase 0 verified the actual
PDF download path; it did not claim that every evidence-field variant is
present in the current report sample.

## Phase 3 implications

1. Improve visibility and wording around the two existing removal disclosures;
   do not create replacement components or another removal record.
2. Carry `X-Answer-Located` through the authenticated image fetch before
   claiming a server-drawn box was found.
3. Reuse the existing provenance primitives in Analysis selected evidence.
4. Put retrieval diagnostics behind an expandable detail area only after the
   relevant values and scale labels exist on that endpoint.
5. Keep `GapAnalysisCard`’s empty-row disclosure separate from synthesis
   removals.
