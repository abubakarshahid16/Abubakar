# .cowork INDEX - navigation only

Last updated 2026-09-21 (transport column added). This file is a signpost. It has **no authority of its own** and
**cannot override `NORTH-STAR.md`**. Where this index and a canonical file disagree, the
canonical file wins and this index is wrong and must be corrected.

---

## 1. Canonical project memory - FIVE files, in authority order.
## Read all five before every task.

All five live in `D:\project\Rag_chatbot\.cowork\`. Where two disagree, the lower number
wins.

**NOT ALL FIVE ARRIVE BY `git clone`.** Instruction 6 in section 0 of
`RAG-INTELLIGENCE-POC-EXECUTION.md` keeps client document names and hashes, extracted
text, prompts and answers out of Git, and two canonical files carry such content. They
travel by **direct copy** from the source machine into `.cowork\`. On a fresh clone
their absence means **not yet copied**, not missing or deleted - rule 4 below still
applies: STOP and ask for the copy, do not substitute anything.

| # | File | Transport | Authority |
|---|---|---|---|
| 1 | `NORTH-STAR.md` | **clone** | **Highest policy authority.** 9 sections, checklist at section 8 |
| 2 | `CURRENT_STATE_AND_BLOCKERS.md` | **direct copy** (client document references, a document hash, DB row ids) | **Live verified project status.** Bug register, checkpoint log. Facts, not rules |
| 3 | `AI_SUBMITTAL_REVIEW_SYSTEM_AUDIT_AND_NORTH_STAR_V3.md` | **direct copy** (names a client submittal) | **Detailed design. Binding only after owner approval and hash pinning** in NORTH-STAR section 9. Cut line at section 19.1. Not yet approved |
| 4 | `CLIENT_FEEDBACK_REQUIREMENTS_ADDENDUM.md` | **clone** | **Latest client-requested expansion. A requested specification, NOT proof that those features are implemented.** Extends, does not replace, 1 to 3. As of 2026-09-21 its HAZOP, letters and FEED/simulation sections have no implementation at all - see `ADDENDUM-GAP-ANALYSIS.md` |
| 5 | `README-INDEX.md` | **clone** | This file. **Navigation only. Cannot override any file above** |

### Verify NORTH-STAR before using it

    certutil -hashfile D:\project\Rag_chatbot\.cowork\NORTH-STAR.md SHA256

Expected: `3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`

If the hash differs, **STOP**. Visual check: the correct file has **9** numbered
sections, starts with "## 1. Product mission", and its checklist is **section 8**. A file
with 6 sections and a checklist at section 5 is a superseded draft that was once on disk
by mistake and caused a full session to run on the wrong rules.

---

## 2. Supporting audit documents

Read these when the task concerns **testing, honesty, requirements extraction or
standards retrieval**. Not otherwise.

| File | Why it matters |
|---|---|
| `D:\project\Rag_chatbot\docs\status-honesty-audit.md` | Its numbered rules are cited and enforced in practice. Rule 5 stopped a deletion when the archive was incomplete. Rule 16 stopped a failing gate being tuned green |
| `D:\project\Rag_chatbot\docs\ZERO_REQUIREMENTS_CAUSE.md` | Prior investigation into zero-requirement outcomes. Bears on standards retrieval and on B9 |

---

## 3. Working files - NOT governing documents

These record work done or instruct work to be done. They are evidence and instructions,
not policy. **Do not treat any of them as a rule.** If one contradicts a canonical file,
the canonical file wins.

| File | Transport | What it is |
|---|---|---|
| `EXECUTE-NEXT.md` | direct copy | Execution order: B2 test, Gates 2 and 4, commit, Phase 0.5 |
| `EXECUTE-PHASE-0.5.md` | direct copy | Earlier execution order for the Phase 0.5 gates |
| `PHASE-0.5-PREPARATION.md` | direct copy | Prepared specification for the nine Phase 0.5 steps |
| `PHASE-0.5-GATE-RESULTS.md` | direct copy | Gates 1, 3 and 5 as executed, with evidence |
| `STEP-2-M03-CAUSE-AND-ORDER.md` | direct copy | The B19 finding: fact extraction is unwired |
| `ADDENDUM-GAP-ANALYSIS.md` | direct copy (names a client submittal) | Addendum mapped against what exists, with the proposed grouping |
| `PROMPT-PHASE-0.md` | direct copy | Instruction of record for Phase 0. Cited by CURRENT_STATE section 11.1 |
| `PROMPT-crs-client-fields.md` | **clone** | Only written record of the client's four CRS field requests |
| `EXECUTE-B24-B23.md`, `EXECUTE-COMMIT-B24-B23.md` | **clone** | Orders for the B24 condition gate and B23 quote validation, and their commit |
| `EXECUTE-GITHUB-TRANSFER.md` | **clone** | Order for the GitHub transfer and the direct-copy data move |
| `EXECUTE-RAM-OPTIMISATION.md`, `RAM-OPTIMISATION.md` | **clone** | RAM optimisation order, and its record (stopped after Phase A) |
| `LAPTOP-MODEL-UPGRADE-9B.md` | **clone** | Record of the 9B upgrade attempt, stopped at the RAM gate |
| `B24-B23-PREFLIGHT.md` | direct copy (names a client submittal) | Preflight for B24/B23 |
| Every other file in this folder, and both artifact folders | direct copy | Orders, diagnostics and benchmark records that quote prompts, model output or client documents |

**How the split is enforced.** The repository `.gitignore` ignores `.cowork/*` and
re-allows only the ten **clone** files above, by name. A new file here is therefore
ignored until someone decides it is safe, rather than committed until someone notices.
Moving a file to **clone** means editing both this table and that allow-list, in one
change.

---

## 4. Standing rules

1. **Read the five canonical files before every task.** They are the project memory. Do
   not rely on chat context. If context is lost, reload the decisions from these files.
2. **Do not create duplicate copies** of any canonical file, in `docs\` or anywhere else.
   Two copies of a governing file means two answers, and the wrong one will be read.
3. **Do not substitute a similarly named file.** A file with a similar name is not the
   file.
4. **If a canonical file is missing, STOP and report it.** Do not proceed, do not
   improvise, do not use the nearest match.
5. **This index is navigation only.** It cannot override `NORTH-STAR.md` or any other
   canonical file.
6. **Do not modify production code, the database or git history** without the owner's
   explicit authorization for that specific change. This restates the owner's standing
   orders and NORTH-STAR's safety rules; it does not create authority here.

---

## 5. Adding a file to this folder

A new governing rule goes **into** `NORTH-STAR.md`. Working notes and evidence go **into**
`CURRENT_STATE_AND_BLOCKERS.md`. Neither gets its own new file.

If a new working file is genuinely needed, add it to section 3 of this index in the same
change, and say which category it belongs to. A file in this folder that is not listed
here is unclassified, and an unclassified file will eventually be mistaken for a rule.

## PHASE 0.5 EVIDENCE - added 2026-09-21. Transport: direct copy (never in Git)

- `PHASE-0.5-RUN-RECORD.md` - the run record for the Phase 0.5 slice. The slice
  **FAILED**: the only configuration that produced a deliverable returned
  NON_COMPLIANT where NEEDS_ENGINEER_REVIEW was required and recorded in advance.
- `phase-0.5-artifacts/` - the frozen packet and machine-readable records: prompt,
  three manifests with their pre-run hashes, three run records, the model output and
  the thinking channel. Every artifact is labelled "Owner-reviewed architecture
  proof; not engineer-labelled accuracy evidence."
