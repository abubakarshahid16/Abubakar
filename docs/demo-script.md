# Demo script — RAG Intelligence System

Twelve minutes. Same machine, same order, rehearsed twice with no edits between
runs. Every number below was measured today; where a feature is not built the
script says so rather than talking around it.

**Before you start:** Ollama running (`ollama list` shows `qwen3.5:4b`), backend
on 8000, frontend on 5173, ingestion paused, notifications off, network cable
out if you want to make the offline point physically.

If section 7 is in the run, also: `python scripts/seed_access.py --verify-only`
prints **`0 problem(s)`**. A seeded-but-useless user does not fail — it signs
in and shows an empty corpus, on stage.

---

## 0. The one sentence — 30 s

> "This reads your engineering documents and answers questions with the page
> and clause cited. Everything runs on this laptop. Nothing you upload, ask, or
> receive ever leaves it."

Point at the footer: *Nothing you type leaves this machine.*

## 1. Documents — 1 min

Open **Documents.** Twelve files, 3,717 pages: a coating specification, three
textbooks, a DOE report, four NIST/CISA security standards, three USACE civil
manuals.

> "The 1,400-page process-control textbook was searchable eleven seconds after
> upload. Full indexing took a couple of minutes in the background — you can ask
> questions while that happens."

Click one document. Show the exclusion note: *N pages excluded — table of
contents, references.* Nothing is dropped without a written reason.

## 2. The quoted answer — 2 min

**Chat. New conversation.**

> How is a stripe coat applied and to what?

~2 seconds. Label: **QUOTED VERBATIM FROM THE DOCUMENT.**

> "That's NORSOK M-501, clause 7.3, page 10. Not a summary — the document's own
> words. The label matters: this system never dresses generated text up as a
> quotation."

**Click the citation.** The page image opens with the sentence outlined.

> "That's the actual page. You can check it against what was quoted."

## 3. The refusal — THE MOMENT — 1 min

**New conversation.**

> What vibration limits does API 610 specify for centrifugal pumps?

> "API 610 is a real pump standard. An engineer here would reasonably ask. Watch."

It refuses: *API 610 does not appear anywhere in the indexed documents. Nothing
was made up to fill the gap.* And it shows what it considered.

> "It named the missing term. Most systems you've seen would have produced a
> confident paragraph. This one won't answer what the documents don't say —
> and for a specification, a wrong number delivered confidently is worse than
> no number."

Pause here. This is the demo.

## 4. The scanned document — 1.5 min

**New conversation.**

> What carbon capture technology does this project use and what did it cost per tonne?

> "This DOE report is 89 scanned pages. No text layer at all — a photograph of
> every page. The system read it with OCR."

Point at the label: **READ BY OCR FROM A SCANNED PAGE — not the document's own
text — check it against the page below.** Confidence 0.50.

> "It tells you the text came from OCR, not from the document, and how
> confident it is. Click through and the real page is there to check."

*If asked why the answer gives a target ($40/tonne) rather than a result:* "Good
catch — that passage states the programme goal. The measured result, $39.73, is
on page 68. Retrieval landed on a neighbouring passage. That's a known class of
behaviour and it's in our test set."

**Known risk in this question, and it is the only one in the script.** *"what
did it cost per tonne"* is user vocabulary, not the report's. Retrieval is
measured as solid when a question borrows the document's words and brittle when
it does not — 6 of 10 facts cite the same page across all three phrasings
(`docs/limitations.md`, *Known false refusals — phrasing sensitivity*). This
question is kept as written because the neighbouring-passage answer is the
honest thing to show; if you want the result rather than the target, ask it in
the report's own words: **"what is the measured cost of CO2 captured per tonne"**.

## 5. Conversation — 1 min

Same conversation, **do not start a new one.**

> and the minimum?

> "A follow-up. It carried the subject from the previous question. This morning
> that mechanism was wrong 36% of the time — it borrowed words from unrelated
> earlier questions. We measured it across 122 conversation orders, fixed it,
> and it is now 100%."

## 6. Dashboard — 1 min

Open **Dashboard.**

> "What's searchable, what was excluded and why, memory, latency. Where
> something hasn't been measured it says *not measured yet* — never a zero."

## 7. Role-based access — 1.5 min *(if stage 1 landed)*

**Precondition, and check it before the client is in the room:**

```bash
python scripts/seed_access.py --verify-only
```

It must print **`0 problem(s)`**. Anything else means a user or a discipline is
seeded but useless, and that state does not fail — it signs in successfully and
shows an empty corpus, which in front of a client looks exactly like broken
search. If it does not print zero, skip this section.

**Sign out. Sign in as the Civil Engineering user.** Open Documents.

> "Three documents — the civil manuals. The security standards don't exist for
> this user. Not hidden — absent. Ask about zero trust:"

> What are the logical components of a zero trust architecture?

Refuses. *Does not appear anywhere in the indexed documents.*

> "Same question, different discipline, different world. The permission check
> runs inside the database query, not after — a document you may not see cannot
> even take up a slot in the results."

Sign out, sign in as the IT user, ask again. Answered from NIST SP 800-207.

**If asked how the disciplines are set up**, the four are Civil Engineering,
Mechanical, Chemical-Process and IT, and `admin` is not a fifth:

> "Admin is a capability, not a discipline. An administrator also works
> somewhere — our IT administrator is IT *and* admin. If admin were a fifth
> discipline they'd have to choose between running the system and seeing their
> own team's documents."

*If stage 1 did not land:* skip this section. Do not describe RBAC as working.

## 8. The report — 1 min *(if stage 2 landed)*

On any answer, **Generate report.** Download. Open the PDF.

> "Question, answer, every passage with page and clause, the OCR provenance,
> the model identifiers. And this box on page one —"

Point at the *not implemented* box.

> "— lists what this report does not contain. Coverage ledger, gap analysis,
> recommendation. We'd rather the report says what it lacks than let you
> discover it."

*If stage 2 did not land:* skip. Do not show an HTML fallback as "the PDF".

## 9. What is not built — say it yourself — 1 min

> "Three things on the roadmap are not in this build, and I'll name them
> rather than let you find out:
>
> **Multi-document AI summarisation.** Designed and costed. On this CPU a
> fifteen-document synthesis is ten to twenty minutes per question. We surface
> the evidence directly instead — faster and, for a specification, more useful
> than a paraphrase.
>
> **Gap analysis.** It needs a baseline you nominate — the document the others
> are checked against. The UI for that is built; the comparison engine is next.
>
> **Live market research.** This machine is offline by design. What you'd see
> is a labelled sample, and it is labelled SAMPLE on every row."

## 10. Close — 30 s

> "Twelve documents, five hundred and ninety-one automated tests, and a
> published record of every measurement we got wrong and how we caught it.
> The system tells you when it's quoting, when it's reading a scan, when it's
> unsure, and when it doesn't know. That last one is the feature."

---

## If something breaks

| Symptom | Do |
|---|---|
| Answer takes >10 s | "The model is loading — first call after idle pays a 24-second load." Wait |
| Explain button hangs | Ollama not running. Skip Tier 2; the quotation is the answer |
| Login fails | `AUTH_MODE=disabled`, restart backend, skip section 7 |
| Signed in but no documents | The user has no discipline. `--verify-only` would have said so. Skip section 7 — do not debug it live |
| Wrong page cited | Click through to the page image. "This is why we show the source" |
| Anything else | `git checkout v1.0.0-prototype`, restart. That is what the tag is for |

## Questions you will get

**"Can it summarise across all documents?"** — Section 9. Ten to twenty minutes
per question on this hardware. Not a demo feature; a roadmap item with a
measured cost.

**"How accurate is it?"** — Twelve of twelve on retrieval, eleven of eleven on
citation, zero false refusals, on a question set written independently of the
retrieval code. And a 25-question adversarial set designed to break it, which
we haven't finished running — so the honest answer is "very good on what we've
measured, and we're still measuring."

**"Does it hallucinate?"** — The quoted tier cannot; it has no model. The
generated tier cites every sentence and rejects any citation the model invents.
Refusal is preferred to a guess, and that is tested.

**"Does our data leave the machine?"** — No. Loopback only, no external calls
at query time, and a CI check that fails the build if document content appears
in a commit.

**"Can we run it on our own server?"** — Yes. Fresh-clone tested today: install,
run models script, start. About 4 GB including the language model.
