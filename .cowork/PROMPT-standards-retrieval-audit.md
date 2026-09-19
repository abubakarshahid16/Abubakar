# Standards retrieval audit. AUDIT ONLY. No production changes.

Do not change code. Audit the REAL standards retrieval pipeline in
D:\project\Rag_chatbot using the current database and the authenticated
API. A recreated search proves nothing about the shipped one.

For every COMPANY_STANDARD, trace:

  original PDF -> extracted pages -> chunks -> chunks_fts -> chunk_vectors
  -> standard_requirements -> resolving document/page/clause citation

## Report exact counts, every one with its denominator

1. Total COMPANY_STANDARD documents.
2. Standards with zero extracted pages.
3. Standards with zero chunks.
4. Standards missing FTS rows.
5. Standards missing vectors.
6. Standards with zero standard_requirements.
7. Requirements with missing chunk_id, page, clause or source_text.
8. Pages that produced no searchable chunk.
9. Standards stuck in non-terminal or failed processing states.
10. Duplicate and superseded revisions.

## Then test SAES-A-105 through the REAL API/retriever

Expected answers, from reading the PDF:

- "Pressure relief valve maximum permitted noise" -> clause 5.3.3, page 9, 115 dB(A)
- "Engineering controls reduce equipment noise"   -> clause 5.1.3, page 8, 90 dB(A)
- "Equipment Noise Data Sheet Form 7305-ENG"      -> page 9
- "NC-30 sound pressure at 125 Hz"                -> Table 2, page 12, 48 dB
- "16-hour permissible exposure"                  -> Table 3, page 13, 85 dB(A)
- "Category A night community limit"              -> Table 4, page 13, 40 dB

Run each query three ways, separately: (a) FTS only, (b) dense/vector only,
(c) the final hybrid retrieval. For every result report document ID, chunk
ID, page, clause, rank, score, source text, and whether the answer is
correct.

Check that a table value is never paired with a header or row label from a
different table. Page 13 holds three tables.

## The two specific things to settle

1. NORMALIZATION. The PDF extracts the value as "115dB (A)", with no space.
   Test BOTH "115 dB" and "115db" and report which retrieve clause 5.3.3.
   I read `backend/app/keyword.py` and found no unit or spacing
   normalization anywhere in it, so my expectation is that the two queries
   behave differently. Confirm or refute that against the running system.

2. CONTENTS PAGES AND RUNNING HEADERS. Verify they cannot outrank a real
   clause. Query "5.3.3" and report whether the contents page and the
   clause page both return, and in what order.

Do not claim success from document or chunk counts. A standard passes only
when the expected fact is retrievable WITH the correct page and clause.

Write the results to `docs/STANDARDS_RETRIEVAL_AUDIT.md`. Record failures
and recommended fixes. Make no production changes until the audit is
reviewed.

## RETRACTED, 2026-09-20

The section that stood here told you the PSV 115 dB sentence reads "shall
not exceed" and that the ChatGPT finding about it was false. That was
WRONG. I took the wording from an illustrative comment in
`requirements_3b.parse_exceptions`, not from the PDF.

The audit read the real source text. It says:

    Pressure relief valves, which MAY NOT exceed 115dB (A)

"may not" is not in `_MANDATORY_HERE`. The extractor cannot see that
sentence. SAES-A-105 has zero `standard_requirements` rows, which is
consistent with exactly that.

The original finding was right and my correction was wrong. Treat the
"may not" gap as confirmed and demonstrated on a real clause, not as a
theoretical hole waiting for a count.
