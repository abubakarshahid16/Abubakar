# Standards retrieval audit

Audit date: 2026-09-20. Database: `backend/data/rag_intelligence.sqlite`. API: live `127.0.0.1:8000`, authenticated with a valid server-issued bearer token. No production code, database, or configuration was changed.

## Executive result

The pipeline is structurally populated for all 272 `COMPANY_STANDARD` documents, but it does not pass the retrieval acceptance bar. Only 20 standards have any `standard_requirements`; 640 extracted pages have no searchable chunk; and the required table queries retrieve a containing chunk but do not resolve the requested row/value with a reliable table citation. SAES-A-105 is present and its key prose clauses are reachable, but the final retrieval metadata exposes chunk page ranges/section headings rather than the requested clause-level citation.

## 1. Corpus chain counts

| Check | Exact result |
|---|---:|
| COMPANY_STANDARD documents | 272 |
| Standards with zero extracted pages | 0 |
| Standards with zero chunks | 0 |
| Standards missing FTS rows | 0 |
| Standards missing vectors | 0 |
| Standards with zero `standard_requirements` | 252 |
| Requirements with missing `chunk_id`, page, clause, or `source_text` | 2 rows (both missing `clause`; both in `doc_e3b6199f392d`) |
| Pages producing no searchable chunk | 640 |
| Documents in non-terminal/failed processing state | 0 (`ready`: 272) |
| Jobs in non-terminal/failed state | 0 (`done`: 277 jobs for these documents) |

The 640-page count is page-level coverage: a page is counted when no `retrievable=1` chunk spans it. It includes expected front matter/contents pages, but also demonstrates that the current chain cannot assert page reachability from document/chunk counts alone.

## 2. Revisions, duplicates, and citations

There were no duplicate SHA-256 document bodies and no duplicate populated `document_number` values among COMPANY_STANDARD classifications. There were also no rows with `superseded_by` set. This means the current database contains no recorded supersession chain to resolve; it does not prove that the corpus has no duplicate/revised standards, because most standard classifications have no document number or revision metadata.

Requirements resolve through `standard_requirements.standard_document_id -> standard_requirements.chunk_id -> chunks(document_id,page_start,page_end,text)`. The two malformed requirements retain a chunk and page but lose clause context, so citation resolution is incomplete. For SAES-A-105, the document has no `standard_requirements` rows; its citations therefore come from chunk section/page metadata, not the requirements layer.

## 3. Live SAES-A-105 retrieval

Document: `doc_a835c3a15e04`, `SAES-A-105.pdf`.

The API was called at `/api/search` with `mode=keyword` and `mode=hybrid`; dense-only was run through the product's `search.dense_search` primitive against the same live vector store and access scope. Ranks below are top-five ranks for each mode. Scores are mode-native: keyword/hybrid `score` is the API/reranker score; dense is cosine.

### Prose queries

| Query | FTS-only top result | Dense-only top result | Hybrid top result | Correct? |
|---|---|---|---|---|
| Pressure relief valve maximum permitted noise | rank 1, `a835c3a15e04:p00009:c00022:f3701ce4`, p9–10, section 5.3.1; score 2.091223 | rank 1, same chunk, cosine 0.878808 | rank 1, same chunk, score 2.317886 | Retrieval yes; clause 5.3.3 is inside text, but API section/page citation is not clause-exact. The source text contains `Pressure relief valves ... 115dB (A)`. |
| Engineering controls reduce equipment noise | rank 1, `a835c3a15e04:p00008:c00017:ea5e6176`, p8, section 5.1.3; score 9.444638 | rank 1, `a835c3a15e04:p00008:c00017:ea5e6176`, cosine 0.853791 | rank 1, same chunk, score 9.444638 | Yes: clause 5.1.3, page 8, `<90 dB(A)`. |
| Equipment Noise Data Sheet Form 7305-ENG | rank 1, `a835c3a15e04:p00009:c00022:f3701ce4`, p9–10, section 5.3.1; score 8.797010 | rank 1, same chunk, cosine 0.894136 | rank 1, same chunk, score 8.799001 | Page 9 is retrieved, but FTS rank 2 also returns a references/contents chunk on p4–5. The result is not a page-9-only citation. |

The pressure-relief result is a chunk containing clauses 5.3.1–5.3.3 and exceptions. The expected fact is present, but the retriever does not emit `clause=5.3.3`; it emits a section beginning `5.3.1` and a p9–10 range. That is a citation-context failure under the requested standard.

### Table queries and cross-table pairing

| Query | FTS-only | Dense-only | Hybrid | Table safety result |
|---|---|---|---|---|
| NC-30 sound pressure at 125 Hz | rank 1 `...p00012:c00031:aca1eafe`, p12, section 5.5.2, score 4.837294 | rank 1 same chunk, cosine 0.871293 | rank 1 same chunk, score 4.796177 | The chunk contains Table 1 and the beginning of Table 2, but not an isolated row/value pair. It does not prove `NC-30 -> 48 dB`; row/column alignment is not represented. **Fail.** |
| 16-hour permissible exposure | rank 1 `...p00013:c00033:9bc7f562`, p13, section 5.5.2, score 1.287476 | rank 1 same chunk, cosine 0.842542 | rank 1 same chunk, score 1.185859 | The source text contains Table 3 and the sequence `16 85`, but the API has no table-row citation. **Retrieval yes; structured table citation fail.** |
| Category A night community limit | rank 1 `...p00011:c00029:0648aad5`, p11, section 5.5, score -1.370499 | rank 1 `...p00003:c00004:f6572cbb`, p3–4, score/cosine 0.854421 | rank 1 `...p00011:c00029:0648aad5`, score -1.267973 | The expected Table 4 is on p13 in chunk `...p00013:c00033:9bc7f562`; it is not top-1 in any mode. Dense top-1 is a contents/addition chunk. **Fail.** |

The underlying p13 extracted text does contain the relevant unambiguous sequences: Table 3 `16 85`, and Table 4 row `A 50 45 40` after the Night column. The failure is retrieval/citation structure, not absence from the PDF extraction.

### `115 dB` normalization

Both queries retrieved the same correct clause-containing chunk at rank 1 in FTS and hybrid:

`doc_a835c3a15e04`, chunk `a835c3a15e04:p00009:c00022:f3701ce4`, p9–10, source text includes `Pressure relief valves, which may not exceed 115dB (A)`.

For `115 dB`, FTS rank 1 score was `0.722314`, hybrid rank 1 score `0.937076`; dense top-5 placed the clause chunk rank 3 (cosine `0.817785`). For `115db`, FTS rank 1 score was `-0.408124`, hybrid rank 1 score `-0.784148`; dense placed it rank 4 (cosine `0.809531`). Therefore current normalization makes both forms retrieve clause 5.3.3 content, but the unspaced form is materially weaker and hybrid relies on dense/other candidates more heavily. It is not evidence of robust numeric-unit normalization.

## 4. Contents/header/footer contamination

Repeating `Saudi Aramco: Company General Use`, `Page n of 14`, and contents/addition text remain inside extracted chunks. The strongest concrete failure is `Category A night community limit`: dense rank 1 is `a835c3a15e04:p00003:c00004:f6572cbb` (p3–4), a contents/addition chunk mentioning “Table 4”, while the actual Table 4 data is on p13. The `7305-ENG` query also returns a references chunk on p4–5 at FTS rank 2. Thus repeating headers/contents cannot be considered safely suppressed from outranking or competing with real clauses.

## 5. Recommended fixes (no production changes made)

1. Make the requirements stage complete for COMPANY_STANDARD documents or explicitly report standards as untraceable until clause/page/source rows exist. 252/272 currently have zero requirements.
2. Store clause identifiers and table identity/row/column mappings on chunks or requirements; page ranges plus a section prefix cannot safely resolve `5.3.3`, `Table 2`, `Table 3`, or `Table 4` facts.
3. Split table extraction into row-aware records, preserving header-to-column association. Add an acceptance test that rejects a result unless the requested table, row key, column key, and value are co-located in the same structured evidence record.
4. Remove or heavily down-rank contents, revision-history, and repeated header/footer text before FTS/vector indexing; retain it only as non-searchable provenance.
5. Add page reachability gates: 640 uncovered pages should be classified as intentional non-searchable pages or reprocessed; do not call a standard healthy solely because it has chunks, FTS rows, and vectors.
6. Populate document number/revision/effective date and supersession links. The current zero supersession rows and absent document numbers make duplicate/revision auditing inconclusive.
7. Add live API regression tests for all eight queries, including `115 dB` and `115db`, and assert document, chunk, exact page, clause/table identity, and value—not merely that a containing chunk appears in top-k.

## Acceptance decision

**FAIL.** SAES-A-105 prose reachability is partly good, and both spellings of `115 dB` reach the right chunk, but the standards pipeline does not currently provide complete requirements traceability or safe table row/column citation. The corpus-wide uncovered-page and zero-requirement counts independently prevent a passing standards retrieval claim.
