# Chat redesign — change log (owner order 2026-09-26)

Plain-English notes, one per PR. **Paste each into `.cowork/CURRENT_STATE_AND_BLOCKERS.md`
section 16 on the laptop** — that file is local-only (the `.cowork` default-deny
rule in `.gitignore`), so the notes live here in git until copied.
No client text, document numbers or standards text in this file.

## Before (recorded 2026-09-26)

- `main` at `b9a0ce3` (merge of #262).
- Tests (cloud container): backend 3,893 passed / 5 failed (4 OCR tests that
  need OCR models absent here + one intermittent parallel test, both known);
  frontend 736 passed / 2 failed (2 known local-only failures).
- Chat today: nav item "Document Q&A"; a conversations column beside the
  thread; a response-style menu (exact quotation, written explanation, plain
  language). Answers come ONLY from documents: the default is a verbatim
  quotation; "written explanation" goes to the LOCAL model with a 250-token
  cap and sees no conversation (only earlier user questions, for retrieval).
  Greetings and task requests get a fixed guidance card ("Hello. I answer
  questions about your documents…", "I cannot advise you on how to do the
  work…"). No Claude in chat, no streaming, no stop, no web.
- Owner decisions applied (record in CURRENT_STATE if absent): Claude API is
  the chat's reader and reasoner (hardware decision 2026-09-24), local Ollama
  the offline fallback; KJO permits sending submittals and standards text;
  build mode (no evidence packs or review stops inside this order); the repo
  is public, so no client text, document numbers or standards text in PRs,
  issues or logs.

## What the cloud container cannot do (owner, on the laptop)

- Back up the live DB and restart the backend on `main` after each merge,
  recording old/new PID and version — there is no live DB or running server
  here.
- Real Claude calls: no API key in this container. Every Claude path is
  tested with an injected transport; the first real call happens on the
  laptop, under the existing USD caps.
- The ChatGPT / public-Claude side of the benchmark (section 6).

## PR 1 — model lane, caps, memory, answer fields (backend only)

- Chat answers now go through the reasoning provider: **Claude when it is
  configured** (REASONING_PROVIDER=claude + both standards-reader egress flags
  + a key), otherwise the local model. The reader can only *narrow* to local.
- Claude's chat answers may be up to **1,500 tokens** (`CHAT_MAX_OUTPUT_TOKENS`);
  the local model keeps its 250 so its small window still holds the evidence.
  Document answers run at temperature 0.2.
- Every Claude call is checked against the **USD caps before it leaves** and
  logged in the ledger under step `chat`. An over-cap call is refused and the
  reader is told why; nothing is sent.
- **The model now sees the conversation** (last 10 turns / ~3,000 tokens;
  600 on the local model), filtered by the reader's permissions first — a
  turn citing a document they can no longer open is never sent. It is
  labelled "context only, not a source"; old [S#] markers are stripped.
  Retrieval still reads documents only.
- Every answer carries its **grey used-line, numbered sources, steps, and
  which engine wrote it at what cost**. "✓ N of N points found on the page"
  appears only where literally true (verbatim quotations for now).
- New `GET /api/chat/models` for the composer's Model menu.
- Tests: 15 new; 14 new mutations (M912–M925) all detected; 78 existing
  mutations on the touched files all detected.
- Also fixed (found by the full suite): a search word with no similar-length
  word in the vocabulary crashed the spelling-correction step; it now simply
  gets no correction.

## PR 2 — the router, general answers, rewrites (backend only)

- **Every message is routed before anything is searched**: small talk,
  general knowledge, your documents, "either", a rewrite, an action, or
  `/records`. `/quote` asks for the exact wording.
- **"hi" gets a natural reply**; the old "Hello. I answer questions about
  your documents…" and "I cannot advise you…" cards are gone. The about-me
  reply says honestly who answers (Claude, or the local model).
- **General questions are answered from general knowledge**, always labelled
  "General knowledge, not from your documents", never searched, never with a
  document citation.
- **A question about your own material never gets a general answer**: it
  goes to the documents, and if they cannot answer, you are told so. A
  question with no signal tries the documents first and falls back to general
  knowledge only when they are silent — with a note saying so.
- **"In points", "more detail", "simpler", "for an engineer", "shorter"**
  re-render the previous answer without searching again; a document answer
  keeps exactly its sources. "Check against my documents" asks the previous
  question of the documents.
- **On the Claude lane every document claim must quote its page**; a claim
  whose quote is not on the page (or an uncited figure) is removed and
  counted, and the "✓ N of N points found on the page" badge reports it.
- **Compliance questions** end with "This needs an engineer's judgement – the
  passages are evidence, not a verdict". Nothing in chat writes a finding;
  "write that as a comment" returns a draft only.

## PR 3 — streaming, progress steps, Stop (backend only)

- New `POST /api/conversations/{id}/ask/stream` (Server-Sent Events): the
  reader sees the **real steps** ("Searching your documents", "Ranking the
  closest passages", "Reading the best sources", "Writing the answer"), the
  **text as it is written**, then the complete answer — the same one the
  normal route gives.
- On the Claude lane a **document sentence is shown only after its quote is
  found on the page**; an invented claim never appears, not even briefly.
- **Stop really stops**: `POST /api/conversations/{id}/ask/{turn_id}/cancel`
  (or closing the page) shuts the connection to the model within 2 seconds —
  even while it is still reading the prompt. The Claude ledger records what a
  stopped call cost. The turn is saved as "Stopped" with only the sentences
  the reader had already seen. Only the turn's owner can stop it.
- The old non-streaming route still works for older screens and tests.

## PR 4 — the new Chat screen (frontend)

What you can do now:

- **Nav says "Chat"** (hint: "Ask anything, with sources"). The conversations
  column is gone; **recent chats sit in the left navigation** on the Chat
  screen, with a search box once there are more than five. **Delete asks
  first, then offers Undo** for 6 seconds; nothing is deleted until that
  window closes (leaving the page inside it still deletes).
- **First screen**: "What can I help with?", one big box, four starter
  questions and "Continue:" links to your last three chats.
- **Answers stream**: the real steps ("Searching your documents", "Ranking the
  closest passages", "Reading the best sources"), the text as it is written,
  and a **■ Stop** button. Stop tells the server which answer to stop; if the
  server has not named it yet, the connection is closed, which also stops it.
  A stopped answer is kept as "Stopped" with what you had seen.
- **Each answer** has the grey line saying what was used and how long it took,
  the **"✓ N of N points found on the page"** badge where that is true, and
  **"How I got this ▾"** with the steps.
- **Written answers from documents** read as plain text ("Partly." / points /
  "What I'd do:") with small superscript source numbers. A number opens **one
  preview card**: document, number, page, clause, the passage with the exact
  words the answer stood on highlighted, and **Open page** for the page image.
  "Written by the model — not the document's words" stays on every one.
- **General knowledge** says "General knowledge, not from your documents" and
  shows no source numbers at all, even if the model wrote one. **Rewrite as:**
  Points / More detail / Shorter / For an engineer / Check against my documents.
- **Actions**: Copy · Try again · Exact wording (asks `/quote` of the same
  question) · Save as report (then "Saved to CRS & Reports · Open"). Suggested
  next questions under document answers.
- **"Write that as a comment"** shows a **Draft comment** card marked "Needs an
  engineer", editable, with Copy. It is not added anywhere.
- **Composer**: Enter sends, Shift+Enter adds a line, the 500-character limit
  is counted as you near it and an over-long question cannot be sent; **Model:**
  Claude / Local model (Claude greyed out, with the reason, when it is not
  set up). **+** opens workflow-record search and "Add a document".
- **Honest footer**: "AI can be wrong. Open a source to check the page it came
  from." plus, with Claude, "your question and the passages it needs are sent
  to it"; with the local model, "nothing you type leaves this machine". The
  sidebar's privacy line now says the same.

Moved, not removed: exact quotation (now **Exact wording** and `/quote`),
Save as report (now in the action row; see the note after PR 6), the evidence page
viewer (**Open page**), OCR labels, verdict and scope notices, removed-citation
and dropped-evidence notices, two-part answers, "read as a follow-up" terms,
workflow-record search (**+** menu and `/records`), withheld turns, delete.

Not in this PR (each needs backend work first, so no button is shown for it
yet): "Was this right? Yes/No" and "Add to comment sheet" (PR 5), "@ a
document" and "Change" on the Talking-about pill (PR 5, document scope),
"Web on" (PR 6).

One behaviour change, on purpose: **one answer is written at a time.** While
an answer (or an Explain) is being written, Ask waits and Stop is offered;
the old screen let a second question run and then had to drop the late
answer so it could not land under the wrong question.

## PR 5 — Was this right?, Add to comment sheet, @ a document

What you can do now:

- **Was this right? Yes / No** under every answer. It is your own (other
  readers never see it), you can change your mind, and it is stored on this
  machine only. If it could not be saved, the screen says so and puts the
  button back.
- **Add to comment sheet** on a drafted comment ("Write that as a comment").
  What is filed is the text in front of you, edited or not. It becomes a
  finding on the **submittal** the answer drew on (a standard is never
  chosen when the submittal is there), in that submittal's latest review
  run, and it prints on that run's comment sheet as **your row, "filed from
  chat"** — never "AI Review". It is recorded as confirmed by you, so
  re-running the review does not erase it.
  - If the document has no review run yet, the comment is kept in its
    findings and the screen says it is on no comment sheet until a review is
    run.
  - A draft that names no document you can read shows no button, and says
    why.
- **Undo** for 5 minutes, only for the person who filed it, and only while
  nobody has changed the finding. After that, change it on the review. A
  withdrawal removes it from the sheet; the record that it was filed and
  withdrawn stays.
- **@ a document**: pick one or more documents; the next answers come only
  from those (the header shows "Answering from: …" with **Change**). This
  can only narrow what you may already read. Nothing picked means all your
  documents.

Database: two new tables (`chat_feedback`, `chat_filed_comments`) and one
new nullable column (`review_findings.origin`), all added automatically on
start. **Back up the live DB before restarting on this version.**

## PR 6 — web search in chat (off by default)

- A **Web on/off** switch in the chat box. It is greyed out, with the reason,
  unless the system allows it: `CHAT_WEB_ENABLED=true` **and** the market
  lane's two egress flags (`MARKET_LIVE_ENABLED`, `MARKET_ALLOW_PUBLIC_EGRESS`)
  in `backend/.env`. All three are off by default; any one off means nothing
  is sent.
- With Web on, a question about the web ("is there a newer edition of ISO
  12944 online?") gets a **consent card** first: the exact phrase that would
  be sent, **Search once** and **Cancel**. Nothing leaves before you press
  Search once.
- The phrase is built on the server from **your one question only**, through
  the same whitelist the market screen uses: file names, quoted text and
  unrecognised words are removed; nothing from your documents or the earlier
  conversation is ever in it. Pressing the button sends no text at all.
- Every web query is recorded in the audit log with the phrase that left.
- The answer lists what the web returned with **site, date and link**, marked
  **"web · unverified"**, and says your contract baseline is the edition it
  names whatever a website says. Web results never become a document source
  or a finding.
- A search runs once per consent. If every provider failed (rate limit,
  network), you can try again.

## After PR 6 — two owner decisions, before PR 7

- **Privacy fix:** a document's file name typed with spaces, hyphens,
  underscores or dots (any mix, with or without the extension, any case) is
  now removed from every outbound web or market search phrase. The one
  exception: a file named only after a published standard (e.g.
  `NORSOK-M-501.pdf`) keeps the standard's public name searchable. Honesty
  audit entry 67.
- **"Save as report"** is the answer action's name again (it was "Save as PDF"
  in PR 4). After saving it says **"Saved to CRS & Reports · Open"**, and Open
  takes you to that screen.

## PR 7 — browser test and the benchmark kit

- **End-to-end test in a real browser** (`frontend/tests/e2e/chat-redesign.spec.ts`,
  `playwright.chat.config.ts`): a question streaming in with its points-found
  badge and source preview; Stop; a general answer and a rewrite; a draft
  comment filed and undone; a web question cancelled with nothing sent;
  deleting a recent chat and undoing it. The API is mocked with sample data,
  so it needs no backend, model or document, and it now runs in CI.
- **Benchmark kit** (`scripts/chat_benchmark.py`, guide in
  `docs/chat-benchmark-guide.md`): runs your 30 questions through this chat
  on the laptop and writes `.cowork/CHAT-BENCHMARK-2026-09.md` with columns
  to paste ChatGPT's and Claude.ai's answers and score all three. Questions
  and answers stay in `.cowork/` (git-ignored); the script refuses otherwise.
  **Not run yet** — it needs the live documents and your Claude key, which
  only the laptop has.
