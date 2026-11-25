# Word (.docx) as a first-class input (W5b-01, #525)

A `.docx` goes through the same pipeline as a PDF: upload, extract, chunk, index, search, citations, requirements, reviews. It is read with its structure kept.

| Piece | Where |
|---|---|
| Setting (ON by default) | `DOCX_INPUT_ENABLED` (`settings.docx_input_enabled`). OFF: a `.docx` is refused unless `DATASHEET_OFFICE_INPUT` is on |
| Reader | `backend/app/docx_reader.py` (heading levels from the style chain, list numbers computed from `numbering.xml`, tables as rows and cells, page and section breaks, headers/footers, tracked changes, comments, table of contents). No new dependency; same hostile-file limits as `datasheet_inputs` |
| Chunks | `backend/app/docx_chunks.py`: a chunk never crosses a heading; tables are cut only on row boundaries with the header row repeated; same sizes and `chunker.Block` shape as a PDF chunk |
| Citation | `chunks.locator`, for example `1 > 1.1 > para 3` or `1 > 1.1 > Flange ratings > table 1`. Shown instead of a page number (a Word file has no fixed pages). `documents.pagination = 'flow'` marks the document |
| Kept beside the body, never in it | chunk kinds `header_footer`, `tracked_change`, `comment`, `toc`: stored and inspectable (`/chunks?retrievable=all`), never retrievable |
| Tracked changes | deleted text is never body text (a `tracked_change` chunk records it); inserted text is current text and the chunk's locator says `(contains a tracked change)` |
| Not read, said in the log (counts only) | pictures and text boxes, footnote and endnote bodies, list number formats it does not know |

Refused with a clear message (`unsupported_office`): PowerPoint (.pptx), OpenDocument, and old Office files (.doc, .xls, .ppt). An Excel workbook (.xlsx) is still stored and not indexed (a CRS template).

Datasheet FIELDS (the review's fact extraction) are read from a Word file's tables only with `DATASHEET_OFFICE_INPUT` on; without it the page ledger says the fields were not read, and the text is searchable.

Not done yet: footnotes and endnotes, text boxes, pictures, a page count in the document list for Word files, the standards-table reader for a Word standard.
