# CLAUDE.md: RAG Intelligence System

Read this first, every session. The current order is `~/project/mirror/proof/order14/STANDING-ORDER.md` (on the owner's Mac).
Where this file and the standing order disagree, the standing order wins, EXCEPT the binding privacy and safety rules below:
they change only with the owner's written approval on #692 and #1584. The earlier, longer text of this file is kept for history
only, not as an instruction, in `docs/claude-md-old.md`. Lessons learned: `REVIEW.md`; read it before a review or a push.

## The goal
The app reviews any contractor document against the standards we hold and writes a comment sheet a senior engineer of the
client would sign. The owner is not a coder: write to the owner in plain everyday words. Product name everywhere: RAG
Intelligence System.

## How a review works (the only design)
1. Read every page. A page counts as read only if text or a picture reading came back.
2. The AI names the paper (kind, equipment or subject) and picks standards by subject and equipment tag, never by shared words.
3. It writes the checklist from those standards; a second model attacks it. A checklist is saved and reused for the same type.
4. Each item is judged by opening its clause and the paper. Numbers are compared by code, not by the AI.
5. Every comment carries standard, clause, page and quote, and the label "AI, to be checked" until an engineer signs.
6. Where no standard is held: engineering knowledge, labelled. A value left to the vendor is a Question, never Pass or Fail.

## Done and release
Done = live in the app and scored: the planted-mistake score and a KEEP / WEAK / WRONG read of the real exported sheet
(`~/project/mirror/proof/order14/BUILD/DONE-MEANS.md`). Passing tests alone is not done; built on a branch is not done.
Release to the contractor needs two more things that are not connected yet: an engineer's sign-off of the sheet, and the
contractor copy issued only after that sign-off. Until then every file is the team copy, "AI, to be checked".

## Binding privacy and safety rules (word for word from the earlier CLAUDE.md, rules 1 to 5)

1. **Privacy is the product.** No document text, filename, page reference or
   anything derived from a document may leave the machine - with ONE
   owner-approved lanes: the **Claude API**, only through
   `reader_transport.py`, only under the budget of **per review run USD 5 per step, except the AI clause
   review step USD 10, and at most USD 15 for one whole review run; USD 25 per
   standard, USD 100 per day and USD 500 for November** (owner, #1584, 2 Nov
   2026; the USD 500 ends on 30 Nov unless the owner says otherwise; enforced in `claude_spend`), and with **no
   document text in logs, GitHub issues, PRs or CI**. **The standards
   converter's Claude lane is open (owner, 3 Nov 2026, #1584; it was off from
   28 Oct, order 277); its caps are those above.** The standards converter
   (order 270.3) sends STANDARDS text only, of the SAES, ISO, API, ASME and NACE
   families (owner, 3 Nov 2026, #1584), and never a datasheet, procedure or CRS. Every other
   outbound path for document content stays forbidden. Standing approval (owner decision of
   12 Nov 2026 afternoon, recorded on #1584): with
   `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED=true` the paper under review and the rule books of the rules the AI
   reviewer asks join the approved list automatically. The AUTOMATIC routes are exactly these four: (1) a file uploaded as a contractor submittal or a specification, or given either role later, is approved when it is uploaded or when the role is set, unless the code's own kind decision reads it as a contract (a contract is never approved by an automatic route); (2) the paper a review is started on is approved when the review starts, if its role is none, contractor submittal or specification and it is not a contract; (3) a rule book (a document classed as a standard) that the AI reviewer asks rules from is approved just before it asks, if the paper qualifies and the book is inside the access of the user who started the review; (4) a rule book that a review cites, or that governs its equipment type, is approved when the review starts or records it. The citation route approves rule books only; a cited specification goes out only if it is already on the list through its role. Any other document a review cites (a contract, a supporting document, a drawing, another datasheet, a procedure) is not approved automatically: the review shows "not sent: this document is not a rule book; the owner approves it". A specification on the approved list may be sent to Claude when it is the paper under review. When another paper's review cites it, it goes out only when it was on the list shown before the start (`review_shown`: the run's stored list; owner decision of 12 Nov 2026, #1584). `GET /api/reviews/plan` lists every document a Claude review of the paper may send (`documents.leaving`: the paper, the held rule books it cites or that govern its type, cited specifications on the approved list, chosen project papers; each with title, kind and why; what will not go, with the reason; a book the caller may not read is counted, never named), and `POST /api/reviews/start` with `shown_document_ids` stores that list with the run (and with the AI run that follows its rule check): a run with a stored list sends ONLY the documents it names, paper, rule books and specifications alike, and says "not sent" for the rest. Every start the screens offer shows the list first (one pre-start step; the "Start AI review" button included) and goes through `POST /api/reviews/start` with that list ("Review all" runs Local only). `POST /api/reviews/start` without `shown_document_ids` is refused ("the list of documents was not shown") whenever text would leave, and served for Local only or a start where nothing leaves; the older one-click `POST /api/reviews/run` and `POST /api/reviews/agent-run` are refused with "start from the review page: it shows what will be sent" while the Claude lane is open with an engine set to Claude, and served otherwise (nothing can leave). `tests/test_d1_every_review_start.py` enumerates every caller of the two review job-queue functions (by module, alias or bare imported name) and fails on a raw job insert with a review stage outside those two modules, so a new way to queue a review fails it until it is listed with its guard. A rule book that the scope step finds only during a review is not on the list shown: it is not sent, the result counts it ("N more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them.") and the next plan lists the books the paper's last completed review applied by scope. A held book does not stop the AI reviewer: it drops that book's rules before any request is built and goes on with the listed books; the rule check's Claude steps run on the local model for that review and say so. At send time a document that is a contract by role or by the code's kind decision is refused on every route except chat (whose per-request consent is its own lane), including "cited by another review", unless the run's consent record (below) covers it or the owner's older per-upload yes for that file is recorded (`contract_yes`). BESIDES THE AUTOMATIC ROUTES, a review started with an explicit choice of Claude (not Automatic) sends exactly the documents listed on the screen before the start, of any kind (a contract, a specification, a procedure, a supporting document, a cited document on the list), and records that start (who, when, run, engine, each document's kind, role and file hash; `review_claude_consent`; ids only, no title, no text; owner decision of 12 Nov 2026, #1584: "button is enough"). Automatic never sends a contract or an unscored kind to Claude by itself. A document not on the run's list is not sent, and a run queued without a stored list (a script or a retry path) sends a contract only if the owner's older per-upload yes is recorded for it, and no cited specification. The client's register stays blocked on every route even if it is listed (name and checksum block, `claude_blocked_hashes.json`, any file the owner marks), and so do the money caps. Nothing else is approved automatically: no library-wide approval, and chat uses its own per-request consent. The register is blocked by its file name
   (built in, any case, spacing, extension or copy suffix) and by checksum when the file is held. The name block is by file name: a register renamed before it was uploaded is recognised only by its checksum when that file is held, and accented or look-alike letters in a name are not matched. the block list
   (`claude_blocked_hashes.json`) also holds the files, by name or checksum, that the owner marks; the switch needs no
   block file, but a block file that cannot be read turns it off; the switch is off by default. ONE REVIEW BUTTON (owner decision of 12 Nov 2026, #1584 comment 6820183348): Automatic (default), Claude or Local only, resolved in ONE place (`review_engine.decide`), shown before the start (`GET /api/reviews/plan`: engine, whether text leaves, cost as an upper bound, what will not run). The choice only narrows or selects among lanes the installed switches already open; it never opens one. Local only is a run-wide bar (`review_engine.barring`, read by `reasoning_provider._lane_unavailable`, `claude_approved.refusal` and `agent_claude.gate_open`): nothing is sent; the AI review needs Claude, so it does not run. A specification (role SPECIFICATION) joins the approved list like a contractor submittal; a contract paper never joins by itself and Automatic never sends it: only the explicit choice of Claude sends it (the older per-upload yes, `contract_yes`, still counts at send time); the block list wins. A kind not scored against an answer key (`agent_review_gate.SCORED_KINDS`) is not sent by Automatic; an explicit choice of Claude sends it as a draft, internal copy only (an explicit choice is not gated by `REVIEW_UNSCORED_KINDS_FOR_CLAUDE_ENABLED`). In chat, the user may choose Claude and explicitly
   select the documents for that request; that selection is per-request consent
   for only those files. Local sends no file content to Claude; Claude without
   explicit document selection can answer general questions but gets no document
   content from the library or prior document-bearing chat history.
   Other Claude workflows retain the owner-approved document list. The ONLINE SEARCH FOR RULE BOOKS WE DO NOT HOLD (owner,
   17 Nov 2026, #1584 comment 6930244442; `standards_web_search.py`, `STANDARDS_WEB_SEARCH_ENABLED`, off by default) sends
   only a public standard's name taken from the app's own tables of public standards (never the paper's words), through
   `reader_transport.py` under the same caps; a stored answer is reused for 90 days and says when it was searched.
   TECHNICAL QUERIES (owner, 25 Nov 2026, #1584 comment 7170031292: "Yes, approve both"): (1) the Gmail client may
   connect to Google with the `gmail.readonly` scope only, behind the feature's own switch (off by default), for a mailbox
   label an admin activated; mail comes in, nothing goes out by it; (2) an answer draft may send the contract documents
   the engineer chooses for that one query, and the query's own text, to Claude through `reader_transport.py` under the
   `claude_spend` caps (per-request consent for those files only, its own lane, not chat's); sending mail stays off
   (`gmail.send` is not asked for) until the owner writes "sending approved".
   TQ EVIDENCE SEARCH COVERS HELD STANDARDS TOO (owner, 26 Nov 2026, #1584: "Technical query evidence search must
   include company standards and the standards we hold, as well as contract documents. Show which source each passage
   comes from."): the evidence search (local only, nothing sent) now searches the held standards the caller may read
   (a company standard by role, or an unroled public standard; never a contract or a submittal) together with the
   readable contracts, and a form's own cited standard is looked up by name first. Every passage shown names its
   source (contract document / company standard / standard, an unroled public one / document, with its title or number).
   THE CLAUDE DRAFT LANE NOW ALSO SENDS STANDARD TEXT (owner, 26 Nov 2026 23:00 PKT, in session chat: "Yes. Claude may
   read standards passages to write a query reply, same as it does for reviews."): a draft may now also send the held
   standard passages the evidence search above surfaces for this query (a company standard by role, or an unroled
   public standard; never a contract, a submittal or the client's register), scoped exactly as that evidence search is
   (the caller may read it) -- in addition to the contract documents the engineer already chooses for that query. Same
   lane, same `reader_transport.py`, same `claude_spend` caps, same per-request consent record for the files sent. A
   standard the caller may not read is still refused, counted never named, same as everywhere else in this file.
   THE RULE APPROVAL LANE (owner, 25 Nov 2026, #1584 comment 7169525003; `rule_second_approval.py`,
   `scripts/run_rule_second.py`): the second-model rule approval step and its blind sample judge send rule-book text of
   the SAES, ISO, API, ASME and NACE families only, through `standards_lane` and `reader_transport.py` under the
   `claude_spend` caps; nothing else uses this lane; the first batch is 2,000 rules, and its error rate is reported before
   the rest is run.
   PAGE PICTURES IN A REVIEW (owner, 26 Nov 2026 14:59 PKT, #1584 comment 7188761254, "Yes, allow it"): during a review,
   the picture of a page may go to Claude only when that page belongs to a paper this review may already send as text (the
   paper under review on the approved list; the held rule books on the run's stored list, `review_shown`), with the same
   refusals, consent records (`review_claude_consent`, `contract_yes`) and register block as text, only through
   `reader_transport.py` under the `claude_spend` caps, behind its own switch (off by default; on only after a scored run
   of a planted copy whose mistake shows only on a drawing or sketch page, and the five scored kinds not down); the plan
   screen lists the pages whose pictures leave.
   FIGURES OF RULE BOOKS (owner, 26 Nov 2026, #1584 comment 7189065710, "Yes, allow it"): page pictures of the figure pages
   of HELD rule books of the SAES, ISO, API, ASME and NACE families only may go to Claude to read their figures as rules,
   through `standards_lane` (its figure-reading user) and `reader_transport.py` under the `claude_spend` caps; never a
   datasheet, procedure, contract, CRS, submittal or the register; each rule read is marked "from a figure, page N", goes
   to a file first, and joins the library only after a judged sample whose error rate is reported to the owner.
   CHAT DATABASE TOOLS (owner, 25 Nov 2026, #1584 comment 7171320073: "Yes, allow it"): Chat in Claude mode may call
   the database tools (`chat_db_tools.py`: documents by kind or role, a paper's latest review with its counts and top
   comments with page, the open items of a technical query) and the records answers (`chat_records.py`: signed
   reviews, a paper's review, documents listed by kind, queries waiting), ALL behind one switch,
   `CHAT_DATABASE_TOOLS_ENABLED`, **off by default** (reverted 26 Nov 2026: update 14's fresh review found three gaps -
   the block-list check did not cover a cross-referenced OTHER paper's name/value written into a comment by
   `tag_cross.py`; `chat_records.py` answers carried no document id, so nothing was ever withheld from a later turn;
   and `chat.py` routed a question into `chat_records` even when the caller had documents selected, so a selected
   paper could be bypassed for a library-wide answer. `chat_records.kind_of` now checks the switch FIRST, before any
   records answer including "list the <kind>", so with the switch off none of this is reachable - proven by
   `test_u14_chat_records.py`'s switch-off test. Update 15 closes all three gaps for when the switch is on (block list
   on every document a comment names, document ids carried so withholding works, no short-cut once a paper is
   selected) and corrects `chat_records.py`'s docstring to match; turning the default on still waits for a fresh
   review of that work). Their answers go to Claude only through `reader_transport.py` under the `claude_spend` caps,
   must hold only documents the caller may read (one outside the caller's grants is counted, never named), must never
   name or give the client's register or any blocked file, and must never carry document text; each call is logged
   with ids only; Local only and the local Chat engine send nothing. With the switch off, none of this runs; these
   are the rule for
   when it is turned on, not yet a proven property of the code in that state.
   The market search sends only the human-typed
   phrase, previewed and approved per query. Only six modules may open a
   socket, each behind a gate (the two Gmail modules, `gmail_auth.py` and `gmail_client.py`, read-only behind
   `TECHNICAL_QUERIES_ENABLED`, off by default: owner, 25 Nov 2026, #1584 comment 7170031292; the other four below):
   `market_transport.py` (market lane, off by default), `model_transport.py`
   (local Ollama only — `ollama_url` validated by `config.check_model_url`),
   `reader_transport.py` (Claude API: the reasoning provider and the reader;
   off unless `REASONING_PROVIDER=claude` (or `=per_task`, and then only for a
   step whose OWN engine setting says claude: `DATASHEET_AI_READER`,
   `MATCH_ENGINE`, `VISION_READER_ENGINE`, `CRS_AI_WORDING_ENGINE`,
   `REVIEW_AI_CHECK_ENGINE`, `AI_CLAUSE_REVIEW_ENGINE`, `AI_DIVISION_SCOPE_ENGINE`,
   `AI_ENGINEERING_REVIEW_PASS_ENGINE` and, for the AI reviewer (rule review and
   general review) alone, `AGENT_REVIEW_ENGINE`, and for the chat alone `CHAT_MODEL_ENGINE`, and for technical-query drafts alone `TECHNICAL_QUERY_DRAFT_ENGINE` (owner, 25 Nov 2026, #1584)
   (the picker offers Claude under per_task only when it says claude; the reader still
   chooses per request) - owner decision 2026-10-12, #501; two steps with no setting of their own follow another
   step's: in a Claude-lane review run `clause_check_proposal` follows `AI_CLAUSE_REVIEW_ENGINE` and field naming
   (`b4-naming2`) follows `MATCH_ENGINE`; `requirement_value_question` stays local - owner decision of 17 Nov 2026,
   recorded on #1584;
   AI reviewer 12 Nov 2026; under per_task a normal review whose own engine
   settings are all local runs exactly as under ollama, no local-engine bar; owner
   decision of 12 Nov 2026, recorded on #1584 (comment 6806441133, item 5), to be
   confirmed there by the owner; no new outbound path) AND both `STANDARDS_READER_*` egress
   flags AND a key - owner decision 2026-09-25, USD caps in `claude_spend`,
   which the three `claude_api` review routes reach via `claude_spend.metered`) and the datasheet AI reader (`datasheet_ai`, with `DATASHEET_AI_READER=claude`) reaches the same way and
   `notifications.py` (SMTP, off by default; in the socket-containment test
   since #196). Known gap: the
   `claude_api` review routes check the two egress flags but not
   `REASONING_PROVIDER` (audit 2026-09-25 finding 1). Call graph:
   `docs/architecture-call-graph.md`.
2. **Never** commit `backend/.env`. Never print, log, paste or commit a secret.
   Never put a token in a URL. Keys live only in `backend/.env`.
3. **The client's register PDF (`Engineering Deliverables.pdf`) is confidential.**
   It may live in the local DB. It never enters git, is never copied into the
   repo, and no test depends on it.
4. **Honesty invariants, enforced in code:** no claim without a resolving
   citation; null renders as nothing (never 0); confidence is never "high";
   every count states its boundary (whose documents); "not mentioned" is never
   "compliant"; a guess is shown as a guess until a human confirms it; samples
   are labelled samples; no percentage without a denominator.
5. **Classification is NOT access control.** `document_classification` says what
   a document is about; the grant tables say who may read it. A filter may only
   NARROW what a caller may already read — intersection, never union.

## Completeness is a hard rule (owner, 15 Nov 2026)

"Completeness is now a hard rule, like "0 wrong".
1. After every review, code compares three counts: points on the page, lines in the database, rows in each CRS file. If they differ, the download is refused and the page says what is missing.
2. Every CRS file states on its first sheet: "N points reviewed, N in this file".
3. No text is ever cut without a visible mark and the full text beside it.
4. After every live update you download the CRS for the valve and the pump and count the rows yourself, before you say "live"."

How it is built: `backend/app/crs_completeness.py` is the one home of the comparison (it runs after every review ends, the result is stored with the run, and it runs again at every download: a difference answers 409 with a plain sentence naming the missing points). The contractor file holds fewer rows by design, so it states "N points reviewed, M in this file, K not issued: <reasons with counts>" and code checks M + K = N. `scripts/crs_count_check.py <run>` prints the counts and exits 1 on any difference. The general review's file has its own home,
`backend/app/aim_review_completeness.py` (page = database = rows on "All points", comments = rows on "Comments"; same 409).

## Other safety (never skipped)
- A verified backup before any live data change, restore on failure. The live database is read-only for helpers; only the
  server writes it.
- No document text or client identifier in code, tests, commits, PRs, branch names or briefs. Use invented values.
- All PDF work goes through pdf_guard (the PDF reader is not thread-safe). One large local model at a time on the Mac.
- A failed AI step is shown in the run and on the sheet, and never makes a comment more confident.
- Nobody deletes. Unneeded files are moved to a `_to_delete` folder. Nobody switches branches in the live checkout.

## Speed
- Per change: tests of the touched files only. Full suite and the full GitHub checks once, before a live update.
- One review round, by a different model in a fresh session, for the PR that goes live.
- One PR per live update. No new switch except a way-back switch. General fixes only, never for one sheet or one wording.

## Facts
- Backend: Python 3.12 FastAPI, port 8000 (`python run.py`). Frontend: React, port 5173. Database: SQLite (WAL: copy all
  three files) in backend/data. Local models: Ollama. Verify the model from the run record, not from the config.
