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
