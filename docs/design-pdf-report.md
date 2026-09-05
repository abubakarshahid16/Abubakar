# Design — the PDF report

Written against the installed code and the execution plan's section 8. Nothing
here was executed: the venv is a Windows venv and this reading was done from a
Linux shell, so every capability claim below comes from reading
`pymupdf/__init__.py` and extracting strings from `mupdfcpp64.dll`. **The
ten-minute spike exists to settle exactly the claims marked unverified.**

## The renderer: PyMuPDF, already installed, and it can write

`requirements.txt` has `PyMuPDF==1.26.6` (line 9) and `pillow`. **Absent:
reportlab, weasyprint, fontTools, jinja2, cairocffi, pango.** Confirmed against
`.venv/Lib/site-packages`.

PyMuPDF can generate, not only parse — verified by reading the installed source:

| Capability | Where |
|---|---|
| `new_page` | `pymupdf/__init__.py:5908` |
| `save`, `tobytes` | `:6462`, `:7883` |
| `class Story(html, user_css, em, archive)` | `:15843` |
| `insert_htmlbox(page, rect, text, css, archive)` | `:12306` |
| `TextWriter`, `subset_fonts`, `set_metadata` | `:16747`, `:7460`, `:6911` |

`Story` has `write`, `write_with_links`, `write_stabilized_with_links`,
`element_positions`, `add_header_ids`, `add_pdf_links` — a paginating HTML/CSS
layout engine with link and position callbacks, which is what a real table of
contents needs.

So the plan's own step 1 — *"If an existing local PDF library is already
installed and passes a Unicode/table/page-break smoke test, reuse it"* (line
1393) — resolves to PyMuPDF, and the WeasyPrint/ReportLab fallbacks are moot
unless the spike fails.

### The honest comparison

| | Offline install on Windows | Weight | Runtime needs | Licence |
|---|---|---|---|---|
| **PyMuPDF 1.26.6** | Already there. **Zero new wheels on the air-gapped host** | DLLs already paid for by ingestion | Nothing external — fonts are inside the DLL | **AGPL-3.0 / commercial dual** |
| WeasyPrint | Needs Pango/HarfBuzz/GObject/Cairo **native** DLLs via a GTK runtime — an installer, not a wheel. Cannot be `pip download`ed into an air-gap reliably | ~50–100 MB of GTK | GTK stack, system fontconfig | BSD-3, clean |
| ReportLab | Clean wheel, `pip download` works | ~4 MB | Fonts must be vendored as TTF | BSD-3, clean — but **no HTML/CSS flow engine** |
| Headless browser | Excluded by the plan (line 1400), and 150–200 MB of Chromium on a 92%-RAM machine | — | — | — |

**Pick PyMuPDF**, for one reason above the others: it is the only candidate that
costs **zero new air-gap risk**. Every alternative is a pre-freeze install that
can fail on the 48 GB host.

## The licence flag, stated as the plan requires

Plan line 52: *"PyMuPDF is dual-licensed under AGPL/commercial terms; flag it for
owner/legal review rather than assuming commercial redistribution is
permitted."*

**Generating a client deliverable is not the same use as parsing an input.** The
report is an artefact that leaves the tool and lands in a client's hands; under
AGPL that strengthens the argument that the whole application is a covered work
being conveyed. This design therefore adds a second, narrower exposure on top of
the one already recorded.

Contain it structurally:

- One file, `backend/app/report/renderer.py`, exposing `render(snapshot) -> bytes`,
  with **no PyMuPDF import anywhere else in the report package.** If legal says
  no, one file is swapped for a ReportLab implementation against the same
  snapshot and nothing else changes.
- `report_renderer: str = "pymupdf"` in `config.py`, so the swap is a config
  change and a second module rather than a revert — the discipline `auth_mode`
  already uses.
- Record it in `limitations.md`. **Do not ship the report to a client build until
  A37 clears.**

## The freeze the plan asks for cannot honestly happen

Plan line 1391 requires the smoke test on the 48 GB host *"before freezing the
renderer"*. The schedule puts PDF at 06:45–07:45 (line 1930) and the 48 GB host
at 10:30–12:00 (line 1934). **The renderer must be frozen four hours before the
machine that validates it is booted.** That is a contradiction in the plan, not a
judgement call.

What to do:

1. Spike on the 16 GB host and freeze **provisionally**, recording in the commit
   and `CHANGELOG.md` that the freeze is single-host.
2. Choose PyMuPDF **because** it is the option whose 48 GB result is near-certain
   — the identical wheel is already proven there by ingestion. WeasyPrint is where
   late validation would carry real risk, and it is the one being declined.
3. Add the golden-report render to the 10:30 clean-host checklist as a
   **blocking** item.
4. **Do not write "smoke-tested on both machines before freezing" into the
   acceptance record.** It would be false in ordering even if true in outcome.

## What the report can actually contain today

Section 8.2 lists 18 required items. Measured against what `answer()` returns:

**Exists now** — the question (asked *and* resolved, since retrieval ran on the
resolved one); the answer and its passages; document, page and clause citations;
`text_source`, `ocr_min_conf`, `ocr_alphabet_violations` and the sample; document
filenames and content-hash prefixes; model identifiers; timings and token counts;
the mandated engineer-approval line.

**Cheap to add** — generating user (**null under `auth_mode=disabled`, rendered
as "authentication disabled — no user identity recorded", never a placeholder
name**); analysis mode from the tier; section numbering; the evidence appendix.

**Cannot be produced at all. Do not design for these.**

| Item | Why |
|---|---|
| Document **revision** and **approval status** | Columns do not exist on `documents` (`db.py:15-33`) and nothing extracts them |
| **Coverage ledger** | No such object. `candidates_considered` is a *chunk* count, not per-document coverage |
| **Conflicts, agreements, gaps** | §7.3B is an unbuilt algorithm — no claim typing, no clustering, no baseline selection |
| **Advisory recommendation** | No generator exists |
| **Public-market findings** | No provider, and the machine is offline |
| **`evidence_id` / `also_supported_by`** | Citations are `[S1]` positional indices into a per-request list. There is no evidence-id namespace |
| **`analysis_id`** | No analyses table, no lifecycle |

**So today's report is a single-answer evidence report, not the §7.2 analysis
report, and it must say so on page 1** in a bordered box beside the watermark.

Sections with no data are **omitted with a stub line naming them as not
implemented** — never rendered empty, never rendered with zeros. Unmeasured is
null; nothing is dropped silently. Both rules point the same way: an absent
section must be visible as absent.

## The snapshot

Two tables, additive and idempotent, `PRAGMA table_info` in `_migrate`, no
version table.

`reports` holds: the question and resolved question; nullable FKs to message and
conversation (**`ON DELETE SET NULL` — deleting a conversation must not delete
the record that a report was issued**, the same reasoning `audit_events` uses);
`owner_user_id` **and** a denormalised `owner_username`; `auth_mode`; the frozen
authorization decision (`scope_document_ids`, `scope_unrestricted`);
`snapshot_json` and `snapshot_sha256`; every model and setting identifier;
`config_version`; `renderer`; `template_version`; `stored_path` (**never
serialised to a client**); `report_sha256`.

`report_documents` holds one row per contributing document with **frozen**
filename, full sha256, page count, chunk signature and indexed_at, plus
`revision` and `approval_status` recorded as **NULL and rendered as "not
recorded"** — the columns do not exist and inventing a value would be a false
record.

**`report_documents.document_id` is deliberately NOT a foreign key.** A deleted
document must not erase the record that it was cited.

### What is hashed

- `snapshot_sha256` — SHA-256 of `json.dumps(sort_keys=True, separators=(",",":"),
  ensure_ascii=False)`. Deterministic.
- `report_sha256` — SHA-256 of the PDF bytes. **Not a reproducibility hash:**
  PyMuPDF embeds a producer string and an ID array, so a different build produces
  a different file hash and identical content. **Say that in `limitations.md`**, or
  someone will re-render and treat the difference as corruption.
- `config_version` — first 16 hex of a hash over the sorted subset of settings
  that can change an answer. Computed in `config.py` so the field list lives next
  to the settings and drifts with them.

### How this satisfies A25

The renderer's only input is the snapshot. **It performs no query against
`documents`, `chunks` or `pages`.** Rename a document, re-ingest it, change its
timestamps — regenerating produces byte-comparable body content, and a verify
endpoint reports divergence explicitly as `evidence_drift: [...]` rather than
silently using the new state. Plan line 1433: *"Regenerating an old report must
not silently use newer documents."* The mechanism that enforces *not silently* is
comparing the frozen sha256 against the live one at verify time.

## Fonts and layout

**Free from `Story`:** pagination and reflow; `<table>` with `thead` repeating
across page breaks (**this is the single highest-value item in the spike — verify
it, do not assume it**); long-URL wrapping via CSS; a real TOC with real page
numbers via `write_stabilized_with_links` and `element_positions`; font embedding
via `subset_fonts()`.

**Needs work, ~20 lines each:** repeating header/footer and page numbers (furniture
is not part of the flow — draw per page after it completes); the
`PROTOTYPE — NOT FOR CONSTRUCTION` watermark (rotated, grey, **overlay** so it
cannot be hidden behind body content, using the same `Shape` machinery
`pageimage.py:115-120` already uses); non-clipping tables (`table-layout: fixed`
plus `overflow-wrap: anywhere`, because a 64-char hash or an OCR-garbled run will
overflow a narrow cell); section numbering, generated in Python so it is testable
without opening the PDF.

### Arabic — good news, and one rule it forces

`mupdfcpp64.dll` **embeds NotoNaskhArabic-Regular** — confirmed by string
extraction — under **SIL OFL 1.1**, so it is embeddable and redistributable with
no font to vendor and none to fetch. HarfBuzz is compiled in (`mupdf.py:2604`,
`:9229`) and the bidi algorithm is present (`FZ_BIDI_LTR/RTL/NEUTRAL` at
`:1998-2002`).

**But those pieces are wired into the HTML layout engine — the `Story` path —
and are not in the simple text APIs.** `TextWriter.append` takes
`right_to_left=0`, and `insert_textbox`'s RTL handling is `clean_rtl`
(`:16824-16849`), whose own docstring says it *reverts the sequence of Latin text
parts* — it reverses character order and **performs no Arabic contextual shaping
or joining at all.** Rendering Arabic through `insert_textbox` produces isolated,
unjoined, visually wrong Arabic **that still looks like Arabic to a non-reader.**
That is the worst possible failure mode.

**Rule: body content goes through `Story` only.** `insert_textbox` and
`TextWriter` are permitted for ASCII furniture — page numbers, watermark — and
nowhere else. Enforce it with a test that greps the report module for
`insert_textbox` outside `_draw_furniture`.

**State the limitation now, not after discovery:** Arabic rendering is
**unverified on either host**. The spike must render the Arabic golden fixture and
have it read by someone who reads Arabic — **glyphs appearing is not evidence of
correct joining or correct bidi order.** If it fails, Arabic becomes a stated
limitation and Arabic spans render as a labelled unshaped block with a warning,
never as normal body text.

Upstream and unfixable here: `config.py:69` sets `ocr_expected_script = "latin"`,
and whether the client corpus contains Arabic is recorded as an **open client
question**. An Arabic scanned page today produces text flagged as
alphabet-violating. The report must render that flag, not paper over it.

## Where the file goes

**Content-addressed**, like documents and like the page-image cache:
`data_dir / "reports" / sha[:2] / f"{sha}.pdf"`.

The filename therefore carries **no question text, no document name, no
username**. A report about *"chloride limits, spec 12-SAMSS-007"* must not name
itself that on disk — a filename is metadata that leaks past every access check
into backup indexes, `Referer` headers and browser history.

Download name is the server-assigned id: `nabaa-report-rpt_xxx.pdf`. Never the
question.

`Cache-Control: private, no-store` — **not** the `max-age=86400` page images use.
A page image is a fragment; a report is the whole assembled evidence with quoted
client text in it, and it must not sit in a shared HTTP cache.

### Access control

A report **is** client document content — it quotes it. So the check is **owner
AND still authorized for every cited document**, not owner alone. Owner-alone is
the `list_conversations` defect already recorded in `design-access-holes.md`;
re-introducing it in a new route on the same day the old one is fixed would be
the same mistake twice.

**Revocation:** if a cited document leaves the reader's scope, the report becomes
unreadable **immediately and completely** — not partially redacted, because the
evidence is interleaved through the prose and there is no honest partial view.
**404, not 403** — a 403 confirms the report exists and which documents it cites,
which is itself the leak. The listing shows a `suppressed_count` so a user can see
*that* something is hidden without seeing *what*.

**Document deletion** must unlink the PDF and set `stored_path = NULL` with a
`suppressed_reason`, and must **not** delete the `reports` row — that would erase
the record that a report was issued.

## Latency and memory

Expectations, **labelled as expectations and claimable only once measured**:
snapshot assembly 5–30 ms; layout and write for 10–20 pages 150–600 ms;
`subset_fonts()` 50–300 ms; furniture 2–5 ms per page; **total expected
sub-second, budget 3 s**; peak RSS delta 30–150 MB.

`limitations.md` is explicit that no figure is claimed without a recorded
benchmark, and that latency is only comparable within a session — absolute
latency moved 1,434–4,291 ms on an unchanged corpus, correlating with free RAM at
**r = 0.977**.

**Contention.** `config.py:76` records 14.7 GB of 16 GB in use at demo time.
Report rendering is the **third** claimant after ingestion and generation.

- **Render from the snapshot, never re-run the model.** No LLM call in the report
  path at all — which also satisfies the plan's "the LLM must not emit HTML/CSS".
- **PyMuPDF is not thread-safe** (plan line 789), and FastAPI runs sync routes in
  a threadpool, so a report render and a `page_image` render **can land on two
  threads simultaneously today**. Guard the report render with a module-level
  lock, and treat "does `page_image` need the same lock" as a separate
  pre-existing question this feature is surfacing, not creating.
- **Do not embed page images.** Twenty 150-dpi PNGs is a 40 MB PDF and a memory
  spike on a 92%-RAM machine. Cite page numbers; the reader has the viewer.

## Tests

**The golden fixture:** 20 document rows, an evidence table spanning ≥3 pages,
three recognised passages with alphabet violations, a 180-character unbroken URL,
a 64-char hash in a table cell, and a mixed Arabic/English passage.

**Assert on semantics read back through PyMuPDF, never on bytes.** Byte
assertions break on every point release; the library is already the parser.

- Page count within a **tolerance band**, not an exact number — an exact number
  is a test that fails on an upgrade for no defect.
- All 20 filenames and 20 hash prefixes present exactly once in concatenated
  `get_text()`. Layout-independent.
- Table header repeat count equals the number of pages the table spans, derived
  from which pages hold data rows — asserts the behaviour, not a page index.
- **Nothing clipped:** every text block's bbox inside `page.rect` plus tolerance,
  and the 180-char URL recoverable in full from normalised text. This is the test
  that catches `table-layout` regressions.
- Watermark and `Page N of M` on every page.
- TOC targets resolve to pages whose text contains the corresponding heading —
  catches a two-pass TOC off by one.
- **Arabic glyphs are not `.notdef`** and come from a font named Naskh/Arabic.
  **The docstring must say what this does not prove:** glyph coverage, not
  joining, not bidi order. A green tick must not imply Arabic is correct.

Plus: A25 (snapshot survives metadata change); evidence drift reported not
silently used; unmeasured fields `is None` rather than falsy; `config_version`
changes with a measured setting and not with `port`; **no remote fetch during
render** (monkeypatch `socket` and `httpx` to raise — cheap, strong, exactly right
for an air-gapped target); HTML escaping of document text; `stored_path` never
serialised; other-user report is **404**.

## The smallest honest version — ~75 minutes

| Minutes | Work |
|---|---|
| 0–10 | **The spike.** A 40-row table, a 180-char URL, a 64-char hash cell, an Arabic+English paragraph. Look at it. Does `thead` repeat, does the URL wrap, is the Arabic joined. Record verbatim in `CHANGELOG.md`. **If Arabic fails it becomes a limitation in the same ten minutes** rather than a discovery at 11:00 on the demo host |
| 10–25 | Schema, snapshot builder, hashes |
| 25–50 | `renderer.py` — one `render(snapshot) -> bytes` |
| 50–65 | Four routes, all scoped, plus three hand-added TypeScript interfaces |
| 65–75 | A25, and the two `limitations.md` entries |

### What it does not claim

Not the §7.2 analysis report — no coverage ledger, gap analysis, conflicts,
recommendation, confidence, market findings, `analysis_id` or evidence-id
namespace. **The PDF names each as not implemented on its own face.**

No revision or approval status — those columns do not exist.

No generating user under the default mode.

**No latency or memory figure** until measured in a comparable session with free
RAM recorded.

**Arabic is not claimed correct** until a human who reads Arabic has seen the
golden fixture on the target.

**Not "frozen after a two-host smoke test"** — frozen after one, because the
plan's schedule put the second host after the freeze.

**Not cleared for client distribution.** PyMuPDF now generates a deliverable
rather than only parsing an input, and the licence gate is open.
