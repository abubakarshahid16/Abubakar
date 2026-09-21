# Phase 8 visual record

Captured 2026-09-19 against the real corpus - 274 documents, 45 tables - signed
in as an administrator, since three of the four images are of a screen only an
administrator can open.

Each is a screenshot of the **section element**, not the page. The
Administration page is 33,600px tall once it lists every document, and a
full-page capture of it is unreadable at any size a reader will look at.

| file | what it shows |
|---|---|
| `A-table-list.png` | the Database section as it loads: 45 tables, each with its row count, and the standing note that the screen is read-only |
| `B-users-masked.png` | **the mask on the real column.** `users.password_hash` holds argon2 digests; every value renders as `•••`, the column is still listed and still named, and `masked` marks it in the column strip. `email` and `display_name` beside it are untouched, which is what proves the mask is selective rather than a blank response |
| `C-paging.png` | `rows 26–50 of 274` - the range and the total, never "page 2". `sha256` is shown in full, deliberately: it is a document content digest, not credential material (see the commit, and the test that states the asymmetry with `content_hash`) |
| `D-discipline-canonical.png` | the Standards Library chip showing the canonical spelling with the document's own in the tooltip: `Onshore Structures Standards Committee`, hovering to reveal `the document says "Onshore Structure Standards Committee"` |

## Two things these images are evidence for

**The mask is real, not a UI decoration.** The capture script asserted on the
rendered DOM of the section, not on the picture: `$argon2` appears nowhere in
it, and the mask glyph does. Masking happens in `admin_explorer.read_rows`
before the value reaches the wire, so a browser's network tab shows the same
`•••` the screen does.

**14 chips carry the discipline tooltip**, which is exactly the 14 documents
`disciplines.backfill()` reported as changing display. The database and the UI
arrived at that number independently.

## What is in these images

Filenames of SAES standards, their sha256 digests, internal document ids, and
four user rows - three pre-existing test accounts and the throwaway
administrator created for this capture and deleted afterwards. No password
material: that is the point of `B-users-masked.png`.

None of it is `Engineering Deliverables.pdf`, which CLAUDE.md rule 3 keeps out
of the repository entirely.
