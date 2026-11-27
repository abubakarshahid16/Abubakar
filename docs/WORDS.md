# WORDS: one name per thing, one verb per action

Owner, 27 Nov 2026 10:57 PKT: "The look is good. Why can the TEXT not be written as well as possible, so anyone understands it easily,
like a world-class app?" This page is the one word list for every screen. Where `docs/ui-glossary.md` disagrees, this page wins
(its "Everyday words" table still holds for the system's insides). Builder A keeps it; any builder may propose a change.

## How a sentence on a screen is written

1. One idea per sentence. 15 words or fewer. Everyday words.
2. If the person must do something, start with what to do: "Add the code ABC once under More."
3. Say what happened in plain words, never how the system works inside.
4. An error says three things: what went wrong, what is safe, what to do next.
   "The AI could not read the attached file. Your question is safe. Please type it below."
5. Never show: model file names, setting codes, database words, or the words in "Never on a screen" below.
6. Left exactly as they are: quotes from documents, document names and numbers, standard numbers, the reply's own text.

## One name per thing

| Thing | Say | Old words it replaces |
| --- | --- | --- |
| A technical query or a CFC | **query** (the page title stays "Technical Queries and CFCs") | TQ/CFC item, request, ticket |
| What the contractor asks | **question**; its numbered parts are **question 1, question 2** | ask, request, request item, item, the form's own question section |
| The text sent back to the contractor | **reply** | draft, answer, response, proposed response |
| A quoted part of a document that a reply rests on | **source** | passage, evidence, citation, part of a page (in query screens) |
| A file in the library | **document** | file, paper, upload, attachment (in the library) |
| A file sent with an email | **attached file** | attachment |
| An email | **email** | mail, message (in a sentence) |
| The firm that sends the query or the submittal | **contractor** | vendor (unless the document says vendor), supplier |
| The person using the app | **you** | the user, the engineer (when it means "you") |
| Another person who checks work | **engineer** | user, checker, verifier |
| The person allowed to approve a reply or sign a review | **reviewer** | approver, qualified reviewer, super user |
| The AI on this computer | **the AI** (or "the AI on this computer" when it matters where it ran) | the local model, the local drafting model, qwen..., model names |
| Claude | **Claude** | the reasoning provider, the Claude lane |
| A rule book (SAES, API, ISO ...) | **standard** | rule book, held standard, standards library entry |
| A point on a review's comment sheet | **comment** | finding, issue, defect, line |
| The comment sheet file | **comment sheet** (first time on a page: "comment sheet (CRS)") | CRS file, CRS export |
| A document's version | **revision** | edition (unless the standard says edition), version |
| A person's job in the app | **role** | permission, grant, capability |
| A list of who a query goes to | **who it goes to** | routing, routing rule, assignment rule |

## One verb per action

| Action | Say | What it means (one line on the screen, where it helps) |
| --- | --- | --- |
| Record that you checked something | **Confirm** | "Confirm means you checked it. Nothing is sent." |
| Mark a reply ready to send | **Approve** | "Approve means the reply is ready to send. The app does not send it." |
| Ask for changes | **Send back** | "Send back with a note. The reply is written again." |
| Use a source, or not | **Keep** / **Reject** | |
| Search the documents again | **Find the sources again** | |
| Have the AI write the reply again | **Write the reply again** | |
| Start a review of a document, whether or not it was reviewed before | **New review** (the list row, the opened review's header and the New review card) | Review this paper again, Review again, Start review (as a row's button) |
| Write it yourself | **Write the reply yourself** | |
| Open a file or a page | **Open** | |
| Save a file to your computer | **Download** | |
| Add something new | **Add** | |
| Stop a running task | **Stop** | |

## Never on a screen (outside the folded technical details)

attachment, metadata, extraction, extract (as a verb about files), recognition, mitigation, "carries the code", "fills itself",
"the form's own question section", passage, evidence (say "source"), provenance, supersession, verified (say "kept" or "checked"),
proposed (say "suggested"), "found by the system", model file names, setting codes.
Plus every word in `docs/ui-glossary.md` "Everyday words" (engine, ingestion, chunk, job, queue, worker, ...).

## The check

`frontend/src/everydayWords.test.ts` fails when a screen sentence uses an internal word. Pages already rewritten to this list are
named in its `WORDS_DONE` list: there the "Never on a screen" words above are also refused, and a screen sentence over 25 words
fails (document quotes, names and numbers are not screen sentences).
