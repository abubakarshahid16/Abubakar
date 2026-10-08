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
- The phrase is built on the server, through the same whitelist the market
  screen uses: file names, quoted text and unrecognised words are removed;
  nothing from your documents or the earlier conversation is ever in it.
  Pressing the button sends no text at all. (Corrected 2026-09-30: on the
  Claude-first path the phrase is built from the query Claude asked the
  `web_search` tool for, not from your question - and "Search once" used to
  rebuild a different phrase from your question. The consent now stores the
  exact phrase shown and "Search once" sends exactly it; see "Audit fixes
  2026-09-30" below.)
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

## PR 8 — Claude-first: Claude answers with tools, not a router (backend + Fix 1)

- **When Model = Claude and Claude is available, the router+gate+template
  pipeline is bypassed for a document/either/general turn**
  (`backend/app/chat_claude_first.py`, wired from `chat.ask`). Every such
  message goes to Claude with a system prompt and five tools
  (`search_documents`, `read_document`, `get_datasheet_fields`,
  `list_cited_standards`, `look_at_page`, plus `web_search` when the Web
  switch and the market flags are on) instead of one pre-built prompt.
  Claude decides which tools it needs, in a loop capped at
  `chat_tool_max_calls` (default 6) - the next call over the cap offers no
  tools, forcing a final answer rather than looping forever.
- **Fixes "hi" gets a template and "tell me about this document" refuses**:
  small talk is now Claude's own natural reply (no tools, no citation);
  an overview question calls `read_document` for real and is answered from
  it, never routed through the single-passage search gate that used to
  refuse it.
- **Every safety guarantee is reused, not reinvented.** Tool permission
  scoping (`chat_tools._readable`) is the same intersection-never-union rule
  as everywhere else; document citations run through the SAME
  `answer.verify_claims` the old pipeline already used, against the SAME
  numbered-source format, so an invented quote is stripped and counted
  exactly as before. The budget check (`claude_spend.ensure_affordable`)
  runs before every call in the loop because it lives inside
  `ClaudeProvider.reason`/`.stream`, not in the new code - this module
  cannot bypass it. Stop cancels the loop within 2 s because every call is
  streamed (`ClaudeProvider.stream`, never `.reason`) with the same `cancel`
  event the existing pipeline uses; a document sentence streams through the
  SAME sentence gate (`chat_stream`), verified as it arrives.
- **Web stays consent-first even as a tool call**: calling `web_search`
  never searches - it raises `ConsentRequired`, which ends the turn as the
  ordinary `chat_web.consent` turn ("Search once?"), so a tool call cannot
  bypass the sanitiser or the one-shot audit trail.
- **`look_at_page` (vision)**: renders a page image (reusing
  `vision_reader.render`) and hands it back inside the tool result, capped
  at `chat_vision_max_pages_per_answer` (default 4) pages per answer. A fact
  read from a page that also has extractable text is cited and verified the
  ordinary way; a fact from a page with NO text layer is labelled
  "read from image - check the page" instead of being silently dropped.
- **Extended thinking**: enabled only for a question shaped like it needs
  real reasoning (comparison, compliance, multi-document, overview -
  `chat_claude_first._is_complex`), with a configurable budget
  (`chat_thinking_budget_tokens`, default 2000). Shown as
  "· Thought for N s" appended to the grey line; thinking tokens are
  ordinary output tokens to `claude_spend`, so no separate budget plumbing
  was needed.
- **`chat_max_output_tokens` raised 1500 → 4000**: a tool-use answer that
  reads a document and a standard needs more room than a single-passage
  extract did.
- **Fix 1 — greeting example chips** (`intent.example_questions`,
  `AssistantAnswer.tsx`, `AnswerNonDocument.tsx`): now built from the
  document's TITLE, never its filename with `.pdf` in front of a reader;
  skips generic headings (Chapter N, Scope, General, Table of Contents,
  ...); prefers a contractor submittal and recent uploads; capped at 3, plus
  one fixed general example ("Explain what a hydrotest is") that names no
  document. Rendered as clickable chips (`SuggestionChips`, reused - no new
  frontend component), not a static bullet list.
- **Scope kept deliberately narrow**: only the DOCUMENT/EITHER/GENERAL
  routes go through Claude-first. Web-consent, rewrite, action and records
  stay on the existing router path unchanged - Claude already sees recent
  conversation as context, so "put that in points" naturally still works
  without needing the REWRITE route's special handling, but that path was
  not touched or re-tested in this PR to keep it reviewable.
- **A pre-existing defect found, not fixed here**: `answer.verify_claims`'s
  sentence splitter (`_SEGMENT`) breaks on ANY ". " it finds, including one
  INSIDE an open citation bracket - a quote like `"...system no. 1 shall..."`
  splits mid-quote and neither half verifies. Pre-dates this PR (shared,
  already-tested code); worked around in this PR's own tests by avoiding
  such quotes; recorded here rather than silently routed around forever.

## Audit fixes 2026-09-30 (chat layer)

Found by the chat audit; each has a failing-without-fix test in
`backend/tests/test_chat_audit_fixes.py` and a mutation in
`scripts/mutations/audit_chat.py` (M1520-M1538).

- **A turn derived from a document turn keeps its documents** (privacy).
  "In points" or "write that as a comment" after a *stopped* document answer
  went down the general path, was labelled "General knowledge", and was
  stored with no document ids - so after a grant was revoked the reworded
  copy was still shown on reopen. Now a rewrite/action stores the previous
  turn's document ids (`derived_document_ids`, read by
  `chat.referenced_document_ids`), a stopped answer's passages are reused
  like a finished one's, and document-derived text with no passages is never
  reworded as general knowledge (the reader is told to check against the
  documents instead).
- **Claude-first history is on the user side, never in the system prompt.**
  Past answers quote document text; they now travel in the first user
  message inside `<prior_conversation>` ... `</prior_conversation>`, marked
  untrusted in the fixed system prompt, with any delimiter inside the history
  neutralised - the same side the old pipeline has always used.
- **"Search once" sends exactly the approved phrase.** The consent turn stores
  the phrase it showed (`web_phrase`); the search sends that phrase, after
  checking it still comes back unchanged from the whitelist against the
  caller's current file names (otherwise 409, nothing sent). A phrase the
  whitelist would change is never offered. The consent is claimed by one
  conditional UPDATE before anything is sent, so two quick clicks cannot both
  send; a search every provider refused releases the claim.
- **Claude's tools are narrowed to the conversation's document** (or the
  request's selected one) - intersection only; @-picked documents still win.
  "Check against my documents" now honours the @-picked documents too.
- **Follow-up conflict rule for identifiers and values.** A newly named
  identifier replaces a carried one of the same family ("and API 610?" after
  API 682 no longer carries API 682; ASME B31.3 replaces B31.1; clause 5.3.4
  replaces 5.3.2). "150#"/"600 lb" count as a class designator, and a
  question naming its own number does not borrow the earlier one.
- **"thanks, that's all", "ok thanks", "thanks, bye" are small talk**, not
  questions: never searched, never context for the next question.
- **A malformed tool input** (`document_ids: [["x"]]`, `pages: ["a"]`, an
  input that is not an object) is returned to Claude as a tool error; the
  loop also turns a `TypeError`/`ValueError`/`KeyError` from a tool into a
  tool error rather than leaving the question unanswered.
- **The done answer holds every round's text (the chosen rule).** Text
  Claude writes before a tool call is streamed to the reader through the
  sentence gate; the finished answer is now all rounds' text joined in order
  and verified as one, so the preview and the stored answer agree.
