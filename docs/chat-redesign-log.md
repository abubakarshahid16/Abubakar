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
  question) · Save as PDF. Suggested next questions under document answers.
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
Save as report (now **Save as PDF** in the action row), the evidence page
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
