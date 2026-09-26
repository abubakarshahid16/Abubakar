# Finish-mode status (B6B → B11)

Running record, updated at every stage boundary. **Aggregate numbers only** –
no client text, questions, standard names or pages (CLAUDE.md rules 1 and 3).
The frozen B6 benchmark (72 answerable + 8 unanswerable, AI-authored, NOT
engineer-approved) lives outside git and is used for RELATIVE comparison only.

Categories are never merged: code complete / tested in CI / tested on real
documents / engineer-validated / owner-laptop pending.

## Owner gates still pending (cannot be run in the cloud session)

| Stage | Gate |
|---|---|
| B4 (merged #243) | owner laptop: backup, re-extract datasheets, one live review (nozzle facts present, no revision-block names) |
| B5 (merged #245) | owner laptop: `scripts/b5_on_copy.py` all PASS, then one live review; no approved equipment taxonomy yet |
| B6 (merged #247) | latency on the target laptop |

## B6B – retrieval improvements (branch `feat/b6b-e1-heading-embeddings`)

Frozen baseline: recall@1 0.583, recall@5 0.875, MRR 0.706; reworded
recall@1 0.417 / recall@5 0.778; own-words recall@5 0.972; 9/72 misses; cloud
p95 ≈ 2.45 s.

| Exp | Change | overall r@1 / r@5 / MRR | reworded r@5 | own-words r@5 | p95 | misses | Kept |
|---|---|---|---|---|---|---|---|
| E1 | clause heading in the semantic embedding input (stored text, citations, boundaries unchanged; body never cut for the heading) | 0.597 / **0.917** / 0.725 | **0.861** | 0.972 | 2.47 s | 6 (3 fixed, 0 broken) | yes |

| E2 | E1 + ancestor headings (outermost first) in the embedding input | 0.611 / 0.861 / 0.721 | 0.750 | 0.972 | 2.34 s | 10 (4 broken vs E1) | **no** – long ancestor chains dilute short chunks |
| E3 | E1 + running-header lines stripped when contiguous with the page-edge block (up to 2× the scan window) | 0.653 / 0.875 / 0.745 | 0.778 | 0.972 | 2.35 s | 9 (3 broken vs E1) | **no** – regresses reworded recall@5 |
| E4 | E1 + numbered-paragraph clause anchors in every document | 0.681 / 0.875 / 0.767 | 0.778 | 0.972 | 2.38 s | 9 (3 broken vs E1) | **no** – re-chunks well-structured standards finer |
| **E4b** | E1 + numbered-paragraph anchors only in a document with fewer detected headings than half its prose pages; a top-of-page clause number is never stripped as a running header | **0.653 / 0.903 / 0.755** | **0.833** | 0.972 | **2.44 s** | **7** (2 fixed, 0 broken vs frozen) | **yes** |
| E5 | query expansion / multi-query | – | – | – | – | – | **not run** – needs the local LLM (Ollama), not available in the cloud session; a hand-written synonym list would be corpus tuning. Pending on the owner laptop. |

Control: a full re-ingest with E1 alone reproduces E1 exactly (0.597 / 0.917 / 0.725), so E3/E4 effects are real.
E4b fixes the one standard with broken clause tracking: 25 chunks / 2 clause labels → 73 chunks / 64 labels (citation clause correctness); the other 8 standards chunk exactly as before.

**B6B final (E1 + E4b) vs frozen B6:** recall@1 0.583 → **0.653**, recall@5 0.875 → **0.903**, MRR 0.706 → **0.755**; reworded recall@1 0.417 → **0.500**, recall@5 0.778 → **0.833**; own-words recall@5 0.972 → 0.972 (recall@1 0.750 → 0.806); p95 2.45 s → 2.44 s. Misses 9 → 7, none newly broken.

Remaining 7 misses by root cause: identical boilerplate across standards (1, own words) – needs document scoping (B6C); long multi-clause chunk (1); benchmark label incomplete (1 – the top hit is a correct answer on another page); ambiguous question (1); vocabulary / rewording (2 – query expansion, E5); missing parent-heading context (1 – ancestry, E2, measured harmful).

Tests: `test_b6b_e1_heading_embedding.py` (4), `test_b6b_e4_numbered_paragraphs.py` (5); mutations M797–M803, 7/7.

**B6B merged: PR #248, merge commit `0cef6cd`.** CI green (8/8).

## B6C – question understanding (branch `feat/b6c-question-understanding`)

`app/understanding.py`: a deterministic, structured step between follow-up
resolution and retrieval. Retrieval input only – it never produces an answer
and never reads a prior answer's text (only which document / clause the
previous turn's evidence came from).

| Behaviour | How | Test |
|---|---|---|
| Document named by its designation scopes the search | designation read from the caller's own filenames, separator-insensitive | yes |
| Scope only narrows | named / referenced documents intersected with the permitted set | yes (M805, M807) |
| A name matching several documents | search those, choose none, report | yes (M806) |
| "this standard / that document" | the previous answer's document, else the conversation's; nothing to refer to → reported, not guessed | yes |
| "this requirement / the next / previous clause" | from the previous evidence's clause number; appended to the retrieval query | yes (M808) |
| Same text in several documents | search dedup now records which kept chunk a dropped copy repeats; the answer's source is reported as ambiguous | yes (M809, M811) |
| Fallback | anything not understood leaves the question exactly as typed | yes |

Measured: frozen B6 retrieval unchanged (0.653 / 0.903 / 0.755, same misses,
p95 2.45 s). Real boilerplate questions (2): named standard → answered from
it at the right page 2/2; unscoped → flagged ambiguous 1/2 (the other's top
passage is differently worded, a legitimate clause of another standard).
Tests `test_b6c_understanding.py` (18); mutations M804–M811 8/8.
