# Known limitations register

> Client-facing. Every entry here must be stated plainly at handoff.
> Nothing in this project may be presented as better than what this file says.

## Performance — measured on the production machine

- Answer generation runs on a 15 W mobile CPU with **no GPU acceleration**. This laptop is the production machine; there is no faster environment later.
- A single LLM answer over a full RAG context measured **195 seconds**. This is why the system defaults to a **no-LLM Tier 1 path** that returns the quoted source passage in 1–2 seconds.
- LLM synthesis (Tier 2) remains materially slower than Tier 1 and is an explicit, opt-in action.
- Ingestion is paused during demonstrations; running it concurrently invalidates latency figures.

## Scope not implemented

- **OCR is not implemented.** Scanned pages are detected and flagged, not read. A scanned document will not be searchable.
- **No ANN index** — brute-force vector search. Correct and fast at prototype scale; requires an index before full-corpus use.
- **Perfect table and diagram extraction is not claimed** for every PDF type.
- **Table column pairing is not preserved.** A table chunk keeps its caption, headers and every value in reading order, one cell per line, but the row/column pairing is positional rather than explicit. A reader can see the table; a search engine cannot reliably answer "what is the value at row X, column Y".
  - **Plan, deferred deliberately:** when the real Saudi Aramco documents arrive, run PyMuPDF `page.find_tables()` on *only* the pages already flagged `kind=table`, to recover real rows and cells. Building this before we know what the client's tables look like would be guesswork.
- **Mathematical notation degrades.** PyMuPDF text extraction loses `=` and `+` operators and flattens sub/superscripts, so an equation-dense page becomes prose *about* mathematics with the mathematics missing. Not fixable in text mode, and re-implementing a PDF layout engine is out of scope.
  - **The flag is conservative and NOT exhaustive.** On a 613-page differential-equations textbook only 11 pages were flagged. The signal is weak precisely *because* the equations were already stripped by extraction — a page whose mathematics vanished cleanly leaves little evidence that it ever contained any. Treat `equation_pages` as "the worst offenders", never as "every page whose mathematics degraded". This is deliberately not being tuned further: page images are the mitigation, and Saudi Aramco specifications are prose and tables rather than dense mathematics.
  - **Made visible, not hidden.** Pages are scored for equation density at extraction and flagged `equation_heavy`, the same way `needs_ocr` works. `GET /api/documents/{id}/pages` reports the flag per page and the document record carries an `equation_pages` count, so a degraded page is visible rather than quietly useless.
  - **Mitigated by page images.** `GET /api/documents/{id}/pages/{page}/image` renders the real page to PNG on demand (150 DPI default, cached by content hash). The citation panel shows the actual page beside the quoted text, so whatever the extracted text lost — equations, table column pairing, figures — the reader still sees the truth. This is the durable answer to both degraded equations and flattened tables.
  - A side effect: equation debris is sometimes segmented as `kind="table"`. The quality gate correctly rejects it (fractions extract as `1 / 210 / 250 X dX`), so it is recorded in the exclusion ledger rather than retrieved as a table.
- **A document can finish with nothing searchable.** A fully scanned PDF, or one whose every chunk fails the content-quality gate, reaches the terminal state `no_searchable_content` — never `ready`. The reason is carried on the record (e.g. *"all 3 pages are scanned images with no extractable text; OCR is not implemented"*) and the UI must render it as a warning, not a success. Calling such a document ready would tell an operator it is usable when it can answer nothing.
- **Front matter, contents, index and references pages are excluded from search.** They are classified and stored, with `retrievable=0`, so they can be inspected, but they never compete with body text. A contents line such as "5.3.1 Identity Theft 257" would otherwise outrank the page where the answer actually is.
- **The contents/index detector is positional and will not generalise to the real corpus.** It looks for contents pages in the front 6% of a document and index pages in the back 15%, which is right for books. Saudi Aramco specifications are often multi-part compilations with contents pages part-way through, which this rule would miss.
  - **Durable answer:** the generic content-quality gate, not more positional detectors. The gate rejects a chunk whose text does not read like natural language (alphabetic ratio, symbol ratio, proportion of real words, average word length, longest unbroken run, control characters), and it catches failure modes no structural detector anticipated. Tuned against known-good prose and known-bad symbol-font tables: 0 of 1033 good chunks rejected, 157 of 159 known-bad rejected.
- **Section headings are null when uncertain.** A heading is only accepted from an unambiguous numbered pattern. Roughly 12% of retrievable chunks carry no section. That is deliberate: a wrong heading in a citation is worse than a missing one.
- **No authentication, RBAC, SSO, high availability, disaster recovery, or enterprise key management.**
- **No domain fine-tuning**, and no production accuracy claim.
- **Full corpus not ingested.** ~45 GB free disk does not accommodate ~1.2 M pages.

## Security and governance

- ⚠️ **This is a locally-inferencing system on a networked machine. It is NOT air-gapped.** Client document content never leaves the machine, but the machine has internet access.
- The repository is private but on GitHub **free tier**, where four controls are **unenforceable** and must not be described as enforced:
  - No direct pushes to `main`
  - No force pushes to `main`
  - Required status checks before merge
  - GitHub Advanced Security secret scanning
- Compensating controls are in place: gitleaks in CI **and** as a pre-commit hook, plus a CI guard rejecting client documents. These are verified by deliberate failure tests.
- "No document content leaves the machine" reduces exfiltration exposure. It does **not** remove malicious-PDF, local-account, disk-theft, dependency, or privilege-escalation risk.
- **Saudi Aramco security architecture and data-classification review remains a production gate.**

## Measurement honesty

- No accuracy or throughput figure is claimed without a recorded benchmark in `docs/benchmarks.md`, stating hardware, corpus, version, and sample size.
- Domain accuracy cannot be claimed until the client supplies answerable and unanswerable questions with expected page evidence.
