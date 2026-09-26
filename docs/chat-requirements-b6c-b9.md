# Chat requirements, recorded for B6C and B9

**Status: RECORDED, NOT IMPLEMENTED.** Owner instruction, 2026-09-25: follow the
master order; finish the B4 and B5 acceptance gates first; implement these when
B6C and B9 are reached. Nothing here is built yet, and nothing here may be
reported as built until its acceptance test (section 5) has run against the live
chat.

**Mapping caveat.** The master order text that defines B6C and B9 is not in this
repository. The split below follows `docs/architecture-call-graph.md` section 7
(B6 = chunks, embeddings, retrieval; B9/B9A = conversation). The owner should
confirm or move any row before implementation starts.

## 1. The chat call path today (read from code, 2026-09-25)

| Step | Where | What it does |
|---|---|---|
| Route | `main.py` `POST /api/conversations/{id}/ask` | Scope from `access.current_scope`; body `question`, `tier` (`extract` / `generated`), `explain_of`, `progress_id` |
| Follow-up | `chat.resolve_followup`, `FOLLOWUP_WINDOW = 3` | Up to 3 prior **user questions** only; prior answers never reach retrieval or the prompt; the rewritten query is not stored |
| Retrieval | `search.search` | FTS5 BM25 + cosine over `vectorcache`, scope mask **before** top-k, RRF, identifier boost, cross-encoder rerank; 30 candidates, 16 reranked |
| Tier 1 | `answer.answer`, `tier="extract"` | One verbatim passage, no model |
| Tier 2 | `answer.answer`, `tier="generated"` | Local Ollama writes a cited answer; `validate_citations`, `strip_half_citation`; floor `MIN_RERANK_SCORE=-3.0` |
| Refusal | `answer_type="insufficient_evidence"` | "The documents do not answer this" |
| UI | `ChatView.tsx` | Default style **Exact quotation**; Evidence panel; Explain upgrades Tier 1 to Tier 2 |

What it cannot do today: count or list across a whole document (top-k only);
compare two documents side by side; answer a general question (refused as
insufficient evidence); use the Claude lane (`answer.py` never calls
`reasoning_provider`); research the web; carry the previous ANSWER into a
follow-up ("that pump").

## 2. B6C — evidence methods (retrieval side)

| # | Requirement | Method, not a special case |
|---|---|---|
| C1 | Document questions answer from the selected document or the permitted library, with page and clause citations | Existing permission-filtered retrieval; scope mask stays before top-k |
| C2 | Whole-document tasks (count, list, summarise, analyse across all relevant pages) are never answered from the top few hits | Full-document or database operation over the caller's permitted pages / facts / requirements; the count is computed by code, never by the model |
| C3 | Comparisons (datasheet, drawing or contract vs standards): agreements, differences, missing evidence, cited on BOTH sides | Retrieve per side; pair through the review pipeline's evidence services, not a chat-only copy |
| C4 | No compliance verdict unless the review validation gate permits it | Chat reads verdicts from the review pipeline; it never computes Compliant / Non-compliant / an approval code itself |
| C5 | Incomplete reading or retrieval says exactly what was not checked | Page ledger (B3) and retrieval coverage: pages unread, documents outside scope, candidates cut by top-k |
| C6 | Response style never changes the facts or the document scope | Evidence is selected BEFORE the style is applied; the same evidence set feeds both styles |

## 3. B9 — conversation (answer side)

| # | Requirement |
|---|---|
| N1 | Default is a concise written answer. Exact quotation stays a user-selected option |
| N2 | Source passages, document previews and retrieval scores sit in an expandable Evidence area, not in the answer body |
| N3 | General discussion answers conversationally with the selected model, **labelled general knowledge** when no document supports it |
| N4 | Mixed questions separate "What our documents say" (cited) from "General background" (labelled) |
| N5 | Follow-ups resolve "that pump", "compare it", "the next clause" from conversation history, including the entity the previous answer established; the resolved query is stored and shown |
| N6 | Internet research only through the authorised research path, on request, previewed per query (CLAUDE.md rule 1); web text labelled separately from the local standards library |
| N7 | The model may explain or compare verified evidence; it may not invent counts, clauses, citations or pass/fail results. A sentence that cannot be cited is dropped or moved to the labelled general-knowledge part |
| N8 | Claude use, if selected, goes only through `reader_transport` and the `claude_spend` caps (USD 5 per step, USD 20 total) |
| N9 | Permissions, evidence rules and review safeguards stay as they are; classification only narrows |

## 4. Not allowed

- A growing list of hard-coded answers or question patterns. The Recycle Brine
  Pumps question is a regression test, not a case to special-case.
- A chat-side compliance verdict or review code.
- Any count, clause number or citation produced by the model rather than by code.

## 5. Acceptance — live chat, not unit tests alone

Run in the running UI on the owner's machine (real documents, real models),
with previously unseen questions of each type. Record for each: the answer
text, sources, response time, the model used, and what was not checked.

| Type | Example shape (final wording chosen fresh at test time) |
|---|---|
| Standard clause | "What does clause X of standard Y require?" |
| Datasheet summary | "Summarise the Recycle Brine Pumps datasheet" (**regression**) |
| Exhaustive count | "How many nozzles are listed on the vessel datasheet?" |
| Two-document comparison | "Compare the pump datasheet's design pressure with the applicable standard" |
| Drawing question | A question about a drawing's title block or a note |
| General engineering | "What is NPSH and why does it matter?" |
| Mixed | "What does our standard say about seal flush plans, and what are they generally?" |
| Follow-ups | "that pump", "compare it", "what about the next clause" |

Tests must fail on a fluent but unsupported answer: an automated check that
every claim sentence resolves to a cited page, that every count equals the
code-computed count, and that general-knowledge text is labelled.

## 6. Demo-only fixes allowed before B6C / B9

Each is identified separately, tested, and does **not** mark B6C or B9 done.

| Fix | Status |
|---|---|
| Frontend blinking: a single failed health poll unmounted the whole screen; idle chat showed a fake "Working" panel (honesty audit entry 56) | Done 2026-09-25, frontend only |
| Candidate: default response style to Written explanation (N1) | Not done - owner decision; Tier 2 takes 20-50 s on the demo laptop |
