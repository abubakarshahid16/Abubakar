# Backlog — one issue body per known gap

Ready to paste. Each carries the evidence already gathered, so nobody
re-derives it. Several of these exist only in a chat log today, which is the
actual risk this file removes.

Format for every entry: **what is wrong**, **the evidence** (file:line, chunk
id, or a measured number — no claim without one), **why it matters**, and
**what "fixed" looks like** as something observable.

> **Two changes from the brief this file was written against.** The
> stale-embeddings issue is dropped: it was measured at 4,787 → 0 after one
> worker cycle and is closed. And the "21 pages dropped with no reason
> recorded" issue is **not** filed as a defect — see entry 10, which explains
> what it actually turned out to be.

---

## 1. The reachability sweep has never been run

**What is wrong.** We can say how much of a document is *indexed*. We cannot say
how much of it is *retrievable*. Those are different properties and only the
second supports the claim the product makes.

**The evidence.** Coverage is measured: 96.3% of 2,583 pages reach a retrievable
chunk (`docs/benchmarks.md`, and `python eval/coverage.py`). Retrieval quality is
measured on **15 questions**. There are **4,787 retrievable chunks**. Fifteen
questions over 4,787 chunks is a sample of 0.3%, and every one of them was
written by someone who already knew the answer was there.

**Why it matters.** Coverage proves the text is in the index. It says nothing
about whether any question a reader would actually ask brings it back. The gap
between "indexed" and "reachable" is the entire difference between "your
document is searchable" and "you can ask this any question", and only the second
is what anyone wants to hear. Until this is run, "any question" is not a claim
we are entitled to make.

**What fixed looks like.** One auto-generated question per retrievable passage
(~4,787), derived from that passage's own distinctive terms, each asked against
the live index. The reported number is the fraction whose source passage comes
back in the top *k*. Failures grouped by cause — vocabulary mismatch, a chunk
too short to be distinctive, a heading that never made it into the chunk. A
figure in `docs/benchmarks.md` with the corpus stamped by `observed_corpus()`.

---

## 2. book4 has never been scored cold

**What is wrong.** Every retrieval measurement this project has taken is on a
corpus the tuning was done against. There is no unbiased number.

**The evidence.** `eval/questions.json` was written against *"3 documents:
NORSOKM501Rev5.pdf, book1-professionalpractices.pdf,
book2-Differential-Equations.pdf"* — its own `corpus` field says so. book4
(*Chemical Process Dynamics and Controls*, **1,400 pages, 2,268 chunks**) has
never had a question written for it. The `MIN_RERANK_SCORE` floor, the
identifier boost, the conflict penalty and the classifier thresholds were all
tuned while looking at the other three.

**Why it matters.** A model evaluated on its training distribution reports its
best case. Every accuracy figure in this repository is that figure. book4 is the
only document large enough and different enough to give an honest one, and it is
sitting right there unused.

**What fixed looks like.** 15 questions written against book4 by someone reading
book4, with ground truth recorded the same way — page, clause, expected answer
tokens — **before** any run. Scored once, cold, and the number published whatever
it is. If it is materially worse than the NORSOK figures, that is the real
number and the others were optimistic.

---

## 3. Chapter-opener subsection lists are consumed and kept nowhere

**What is wrong.** On a chapter-opening page, the list of subsections is eaten
during chunking and stored in no chunk. The content is neither indexed nor
recorded as excluded — it simply is not there.

**The evidence.** Chunk `0c5c007fcedd:p00453:c01272:ca0c6ad9` does not contain
`12.3`, although raw page 453 of book2 does. Lines **12.1 through 12.8** are
consumed and kept nowhere. The same chunk's `section` reads **"11.5.2
FOURIER-LEGENDRE SERIES"** — a heading from the *previous* chapter, so the chunk
is also mis-attributed.

**Why it matters.** Two failures at once. A reader asking about section 12.3 gets
nothing, because 12.3 is not in the index. And a chunk that *is* returned carries
a citation pointing at the wrong chapter — which is worse than a missing
citation, because it looks right. The project's own rule is that a wrong heading
in a citation is worse than a missing one (`docs/limitations.md`); this is that
rule being broken by a path nobody has looked at.

**What fixed looks like.** Page 453 of book2 produces a chunk containing `12.3`,
and that chunk's `section` names a chapter-12 heading or is null. A test on this
exact page and chunk id. The heading mis-attribution fixed even if the
subsection list is deliberately dropped — those are separable, and the wrong
`section` is the more dangerous half.

---

## 4. Counting and aggregation questions get a vague refusal

**What is wrong.** "How many coating systems are there", "list all the
inspection requirements", "which clauses mention chlorides" — questions whose
answer is a count or a set across many passages — are refused with the generic
insufficient-evidence message.

**The evidence.** `backend/app/intent.py` has no aggregation class. Every
question is routed as if the answer lives in one passage, because for a
single-passage extractive system it does.

**Why it matters.** The refusal is honest but uninformative: it says "no evidence
was found", when the truth is "this system does not answer questions of this
shape". A reader cannot tell the difference between a gap in their document and
a gap in the tool, and will reasonably conclude the former.

**What fixed looks like.** Minimally: an aggregation intent that produces an
honest, *specific* refusal — *"this asks for a count across the document;
answers here come from a single passage"* — which costs no retrieval work and
tells the reader something true. Beyond that, whether to actually answer such
questions is a separate decision that needs its own evidence.

---

## 5. The follow-up resolver borrows on question LENGTH, not topic overlap

**What is wrong.** A short question inherits the previous question's terms
regardless of whether it is about the same subject.

**The evidence.** `backend/app/chat.py` gates borrowing on
`len(_content_words(question)) < 3`. Measured consequence: **"what is hippa
compliance"** — a new topic, and a misspelling — pulled in the carried terms
`11.5`, `11.4`, `question`, `exercise`, `differential`, and `1in`. `1in` is
debris from a typo in an earlier turn.

**Why it matters.** A three-word question about a genuinely new subject is
polluted with the last subject's vocabulary, so retrieval is steered away from
the answer by the mechanism meant to help it. Worse, the reader is not told: the
resolved question is stored, but a wrong answer arrived at through borrowed terms
looks exactly like a wrong answer arrived at honestly.

**What fixed looks like.** Borrowing gated on topic overlap between the new
question and the previous one, not on word count. The measurable check: "what is
hippa compliance" after a differential-equations turn carries **no** terms from
that turn. Existing follow-up tests continue to pass, since genuine follow-ups
do overlap.

---

## 6. The dashboard reports the reranker's name as "reranker"

**What is wrong.** The operations dashboard displays the reranker model as
`reranker`, which is a directory name, not a model.

**The evidence.** `backend/app/metrics.py` reads
`reranker_mod.model_dir().name`, and the directory is
`backend/models/reranker`. The actual model is
`Xenova/ms-marco-MiniLM-L-6-v2` — named in `scripts/fetch_models.py`.

**Why it matters.** Small, but it is the same family as everything in
`docs/status-honesty-audit.md`: a field derived from something adjacent to the
truth rather than from the truth itself. The dashboard exists to let an
operator state what the system is running, and on this row it cannot.

**What fixed looks like.** The dashboard names the model, read from the model's
own config or from the staging manifest rather than from a folder name. An
assertion that the displayed string is not equal to `"reranker"`.

---

## 7. The OCR confidence threshold is unset

**What is wrong.** Per-page and per-chunk OCR confidence is stored, the
exclusion rule `ocr_confidence_below_threshold` exists, and no threshold is
configured — so the rule cannot fire.

**The evidence.** Observed mean confidence on pages that produced sane text ran
**0.92–0.99**; the lowest chunk minimum in the corpus is **0.501**. There is no
labelled ground truth for recognised text in this corpus, because the flagged
pages are book covers and UI screenshots rather than scanned specification
prose (`docs/limitations.md`).

**Why it matters.** This is deliberately unfinished and should stay unfinished
until it can be measured — any number chosen now would be a guess wearing a
decimal point, and it would silently exclude content. The risk is that the
absence stops being a decision and becomes an oversight. The gate is currently
**open**: everything recognised is indexed and labelled, which is the correct
default under the standing rule that recognised text is labelled, not hidden.

**What fixed looks like.** Scanned specification pages with hand-transcribed
ground truth; the confidence distribution of correct against incorrect
recognitions; a threshold placed where those separate, or a recorded finding
that they do not separate and the gate stays open permanently. Either outcome
is a result.

---

## 8. Four of ten facts change answer with phrasing

**What is wrong.** The same fact asked two ways can produce an answer one way
and a refusal the other.

**The evidence.** 30 phrasing variants over 10 facts: **4 of 10 shift**.
Partly quantisation noise on the rerank scale — one passage scored **-3.281**
alone and **-3.039** in batch, a ±0.5 band, and **within 0.04 of flipping**
across `MIN_RERANK_SCORE`. Documented in `docs/limitations.md` with the
measurement behind it.

**Why it matters.** It is the most likely thing a client notices, because they
will not phrase questions the way the eval set does.

**And it is NOT tunable, which is the important half.** Over 35 queries with
known ground truth, the answer-present and answer-absent populations do not
separate on any shape statistic. A floor low enough to admit every
correct-at-rank-1 query is -8.01 or lower, and that floor admits **3 of 3**
unanswerable questions. Lowering the threshold trades three correct refusals for
three confident wrong answers. Anyone picking this up should read that section
before touching the constant.

**What fixed looks like.** Not a threshold change. Either a retrieval signal
that separates the two populations where the current one does not, or a
documented acceptance that phrasing sensitivity is the cost of never answering
wrongly. The measurable target: more than 4 of 10 facts stable across phrasings
**with refusal accuracy still at 4/4**.

---

## 9. Vocabulary mismatch: the document's words are the only words that work

**What is wrong.** A question using an everyday synonym for a term the document
states formally will not retrieve it.

**The evidence.** *"how much salt is allowed on the surface before painting"*
cites the wrong clause, because the document says **chlorides** and **NaCl** and
never says *salt* (`docs/limitations.md`).

**Why it matters.** The mitigation currently offered is "use the document's own
words", which is reasonable advice for an engineer and useless for anyone else.
It also compounds entry 8: an unlucky synonym and an unlucky phrasing together
are how a correct answer becomes a refusal.

**What fixed looks like.** A curated domain glossary, built from the real
corpus rather than guessed at, with the *salt → chlorides / NaCl* case as its
first test. Deliberately deferred until the Aramco documents arrive — building
it against three books and one specification would be fitting to the wrong
vocabulary.

---

## 10. Prose pages excluded for having no long clause — a question, not a defect

**What is wrong.** Possibly nothing. Filing it so the question is asked with
evidence rather than re-derived.

**The evidence.** 21 pages across the corpus are uncovered because **every chunk
on them** failed the content-quality gate — 17 in book2, 4 in book4. Book2 page
2 carries **1,266 extracted characters** and book2 page 4 carries **1,217**;
both are excluded with the quality flag `no_clause(longest=2<6)`, meaning the
longest clause found is 2 words against a minimum of 6.

**A correction worth recording.** These were nearly filed as *"content dropped
by a code path that does not log why"*, which would have been a defect against
the invariant that nothing is dropped silently. That was wrong: it came from a
query in `eval/coverage.py` that looked only at `scope='page'` exclusions and
missed the chunk-scope rows. **Every one of the 21 has a recorded reason.** The
invariant holds; the count of silently-dropped pages is zero. See
`docs/status-honesty-audit.md` instance 8.

**Why it matters.** The gate is doing what it was tuned to do — 0 of 1,033 good
chunks rejected, 157 of 159 known-bad rejected. But a page with 1,266 characters
of text is a page a reader might expect to search, and "no clause over 2 words"
describes a table of contents, a figure list, *or* a page of short prose. The
question is which of those these 21 are.

**What fixed looks like.** Look at the 21 pages. Either they are correctly
excluded — in which case record that and close this, and the exclusion viewer's
wording is confirmed adequate — or some are real content, in which case the gate
needs a case it currently rejects. Pages to start with: book2 `[2, 4, 569, 570,
573, 576, 577, 580, 581, 582, 585, 586, 591, 593, 595, 611, 612]` and book4
`[31, 681, 854, 1069]`.

> **CORRECTION — the routing idea in this entry was measured and does not
> work.** An earlier version proposed routing chunks the table detector
> recognises to a structural gate instead of `longest_clause`. Measured across
> all 5,204 chunks: that change would admit **6** chunks, **all of them
> contents pages** — the one category documented as outranking real answers —
> while putting **100** currently-retrievable table chunks under a stricter
> test most would fail for having no caption or header. 16:1 against.
>
> And it would not reach these 21 pages at all. `looks_like_table()` returns
> true on the PAGE text and false on every CHUNK on it (`lines=1`): chunking
> collapses the newlines the detector depends on, so the structure is gone
> before any gate sees it. If these pages are ever worth recovering the
> mechanism is upstream, in chunking, not in the quality gate.

---

## Already documented — link, do not duplicate

Two known limits are fully written up with their evidence and their reasoning in
`docs/limitations.md`, and should be read there rather than restated here:

- **Table column pairing is not preserved.** A table chunk keeps its caption,
  headers and every value in reading order, but row/column pairing is positional
  rather than explicit. The deferred plan — `page.find_tables()` on pages already
  flagged `kind=table`, once the real documents arrive — is recorded with it.
- **Mathematical notation degrades.** PyMuPDF drops `=` and `+` and flattens
  sub/superscripts. The `equation_heavy` flag is explicitly **conservative and
  not exhaustive**: only 11 pages were flagged on a 613-page differential
  equations textbook, because a page whose mathematics vanished cleanly leaves
  little evidence it ever had any. Page images are the mitigation.

---

## 11. "what about system 2" does not work, with carrying or without

**What is wrong.** The canonical example that justifies term-carrying existing
at all — asking about one designator, then asking "what about system 2" — does
not return an answer about system 2 in either mode.

**The evidence.** Measured over 8 constructed genuine follow-ups. With the
prior turn *"what is the MDFT for coating system no. 1"*:

```
follow-up : "what about system 2"
carried   : ['mdft', 'coating']          <- topic words only, NO designator
result    : extract, and it does not mention system 2
alone     : insufficient_evidence
```

The same for *"and system 9"*. The conflict rule in `resolve_followup`
(`chat.py`, `if word in have_designator_words: continue`) is working as
designed — the new question already says "system 2", so "system 1" is
correctly NOT carried. But the topic words that *are* carried (`mdft`,
`coating`) are not enough to retrieve the right clause, and retrieval returns
a system-1 passage anyway.

**Why it matters.** This is the example everyone reaches for when explaining
why the feature exists. Of 8 genuine follow-ups measured, carrying **helped 2,
hurt 0, and was neutral in 6** — and both "what about system N" cases are in
the neutral group, meaning they fail with or without it. The feature is
load-bearing on a narrower set of questions than it appears.

**What fixed looks like.** *"what about system 2"* after a system-1 question
returns a passage citing coating system no. 2. The measurable check is the
existing 8-case probe: HELPED rises from 2 and HURT stays at 0.

---

## 12. CLOSED — "system 9 carried from no prior question" was a measurement error

Recorded so nobody re-derives it. The 200-ordering sweep appeared to show
`system 9` carried into q14 when no prior turn contained it, which would have
been a phantom-term bug.

It was not. q3 is *"what is the MDFT and number of coats for coating system
**no. 9**"*, and `find_designators` normalises that to `system 9`. The
attribution code in the sweep searched prior questions for the literal
substring `system 9`, which does not appear, so it reported "(no prior question
contains this term)". The carry was correct; the reporting was not.

Two lessons worth keeping: the attribution should compare NORMALISED
designators rather than raw substrings, and an earlier version of this
investigation compounded the error by hand-typing q3 as "system no. 1" and
reasoning from the typo. Read the question set, do not retype it.
