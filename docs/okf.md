# OKF: the project's knowledge format (version 1)

Issue #513, the first step of R29 (#833). Code: `backend/app/okf.py`. Tests: `backend/tests/test_513_okf.py`.

## What it is

One **concept** per file. A concept is one of four things:

| Kind | One per | Example id |
|---|---|---|
| `standard` | standard held in the library | `okf:standard:<document id>` |
| `clause` | clause of a standard that a stored requirement was read from | `okf:clause:<document id>:<clause>` |
| `requirement` | active stored requirement | `okf:requirement:<requirement id>` |
| `equipment_type` | equipment type a stored requirement names | `okf:equipment_type:<name>` |

Each file is Markdown with a small frontmatter block. The frontmatter is one `key: JSON` per line, keys sorted; the body is the requirement's own words (empty for the other kinds).

```
---
content_sha256: "..."
facts: {"requirement_id": "...", "requirement_type": "numeric_limit", "confirmed": false}
id: "okf:requirement:..."
kind: "requirement"
links: [{"rel": "in_clause", "to": "okf:clause:...", "cite": {"document_id": "...", "page": 12, "chunk_id": "..."}}]
okf: 1
source: {"document_id": "...", "page": 12, "chunk_id": "..."}
state: "ok"
title: "<document number> <clause>"
---

<the requirement's words>
```

## The rule of the format

**No link without a resolving citation.**

A link says one of three things, always from the more specific concept to the more general one:

| Relation | From | To |
|---|---|---|
| `part_of` | clause | standard |
| `in_clause` | requirement | clause |
| `applies_to` | requirement | equipment type |

Every link carries a citation: a document, a page and a stored chunk. The citation **resolves** when:

1. the chunk exists;
2. it belongs to that document (a chunk of another document would open something real and wrong);
3. the page is one the chunk spans;
4. the words are there: for a sentence, the stored quote is in the chunk's text; for a reading from a table, the **row label and the value** are both in the chunk's text. (A table reading's stored sentence is composed by the extractor and stands nowhere on the page, so it cannot be the proof.) Whitespace and case are folded; nothing else.

## A concept whose source does not resolve

It is still written, with `state: "citation_unresolved"`, the closed reason in `unresolved`, and **no links**. It is counted in the build report. It is never dropped silently and never linked on trust.

Reasons: `no_chunk_recorded`, `chunk_not_found`, `chunk_of_another_document`, `page_outside_the_chunk`, `quote_not_in_the_chunk`, `table_cell_not_in_the_chunk`.

## Where it comes from, and where it goes

- **Built from stored facts only** (`okf.build`): the documents, classification, chunks and requirements tables. No model is called and no socket is opened.
- **Access is the caller's**: a standard the caller may not read gives no concept and is named in the report (`not_readable`); one the library does not hold is named too (`not_held`).
- **Files are local**: `okf.write` puts them under `<data folder>/okf/v1/<kind>/` and refuses any other place. They hold document text, so they never enter git, an issue or CI. Reports are counts and ids only.
- `okf.problems(concepts)` lists everything that breaks the rule; `okf.write` refuses a set with any.
- `okf.parse` reads a file back to the same concept; a file that is not OKF is an error, not an empty concept.

## Measured on the current library (12 Oct 2026, read-only on a backup; counts only)

The 26 standards applied to the three approved datasheets:

| | Count |
|---|---|
| Standards | 26 |
| Clauses | 1,637 |
| Requirements | 7,965 |
| Requirements whose citation resolves | 7,391 (92.8%) |
| Not resolved: a table cell not in its cited chunk | 527 |
| Not resolved: a quote not in its cited chunk | 47 |
| Resolved requirements with no clause recorded | 797 |
| Equipment types named by a requirement | 0 |
| Build time | about 1 second |

What the numbers say: 574 stored requirements point at a chunk that does not show their words. They are listed by the build, not hidden; most are table values (527 of 996 table readings). No stored requirement of these standards names an equipment type yet, so that kind is empty on real data.

## Not in version 1

Named so they are not forgotten: concepts for a datasheet, a revision and a finding; cross-reference links between standards (R8, #772); engineer approval and versions of the map (#833). Each concept already carries `content_sha256`, which is what a version will be made of. The graph (#514), its queries (#515) and the "no uncited answer" check (#516) are built on these files.
