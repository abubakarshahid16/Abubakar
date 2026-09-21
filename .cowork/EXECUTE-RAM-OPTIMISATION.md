# EXECUTION ORDER - make local inference fit on this laptop

Authorized by Muhammad Usman, 2026-09-21. For the session with a working shell on
`D:\project\Rag_chatbot`, laptop ABUBAKAR (15.57 GB RAM).

**Goal: find ~4 GB and make it repeatable.** Not a one-time cleanup. The output of this
order is a documented **inference mode** that can be entered before a review run and
before the client demo, and exited afterwards.

## Read first

`.cowork\README-INDEX.md`, `NORTH-STAR.md` (**verify sha256
`3d0505be629a99631e8cbcc0681134c642b7a00ae962a5c9f5ebf9df43499619`**, 9 sections,
checklist at section 8 - **STOP if it differs**), `CURRENT_STATE_AND_BLOCKERS.md`
checkpoint row 30, `LAPTOP-MODEL-UPGRADE-9B.md`.

NORTH-STAR section 2.1 governs the acceptance measure: peak memory for the **complete
running system** - OS, backend, retrieval, embeddings, OCR, model weights, context and
cache - not model file size.

---

# THE TARGET, STATED IN NUMBERS

| | Value |
|---|---|
| Total RAM | 15.57 GB |
| Available, dev stack and browsers stopped (row 30) | **2.70 GB** |
| Page file already in use | 9.55 GB |
| Process working sets still resident | **11.33 GB** |
| `qwen3.5:4b` weights | 3.4 GB |
| `qwen3.5:2b` weights, **never tested** | 2.7 GB |
| **Estimated need for 4b without swapping** | **6 to 7 GB** |
| **Gap to close** | **~4 GB** |

---

# PHASE A - Find out where the 11.33 GB actually is. Measure, do not guess.

**No changes in this phase. Measurement only.**

1. Full process inventory, sorted by working set, **all processes not just 15**:

       Get-Process | Sort-Object WS -Descending |
         Select-Object Name, Id, @{n='WS_GB';e={[math]::Round($_.WS/1GB,3)}},
         @{n='Private_GB';e={[math]::Round($_.PrivateMemorySize64/1GB,3)}} |
         Format-Table -AutoSize

   Report every process above 100 MB.

2. Group them into four buckets and **total each bucket**:
   - **Unavoidable** - Windows kernel, drivers, antivirus mandated by IT policy
   - **This project** - VS Code, Python backend, Node/Vite, Ollama
   - **Discretionary apps** - Claude desktop, ChatGPT, WhatsApp, Chrome, Teams, OneDrive,
     Spotify, anything else
   - **Unknown** - name it and say so rather than assuming

3. Startup inventory. Record what launches at boot:

       Get-CimInstance Win32_StartupCommand |
         Select-Object Name, Command, Location | Format-Table -AutoSize

4. Record page file configuration: current size, whether system-managed, and the drive.

**Report all four before changing anything.** The bucket totals decide whether 4 GB is
findable at all.

---

# PHASE B - Reduce the discretionary baseline

**Only touch the discretionary bucket. Do not disable antivirus, security software, or
anything IT policy requires. Do not change Windows system or security settings.**

For each discretionary app: close it, wait 15 seconds, re-measure available RAM, and
record the delta. **One at a time**, so you know what each is worth. A list of apps
closed with a single total is not useful.

Specific items to measure individually:

- Claude desktop
- ChatGPT desktop
- WhatsApp desktop
- OneDrive (pause sync rather than uninstall)
- Microsoft Teams
- Chrome - **force close, do not graceful close.** Row 30 recorded that a graceful close
  left 16 processes holding 2.01 GB, which would have produced a falsely low baseline

**VS Code is the awkward one.** This shell runs inside it. Measure its working set and
record it. **Do not close it in this phase.** Phase D tests whether the run can be done
from a plain PowerShell window with VS Code closed, which is the honest test.

## Report after Phase B

Available RAM, and a per-app table of what each closure returned.

---

# PHASE C - Reduce the project's own footprint

The backend is part of the load NORTH-STAR counts. Three things to establish:

1. **What does the backend hold at idle?** Start it alone, nothing else, and measure its
   working set. Report the number
2. **Are the embedding and OCR models loaded eagerly or lazily?** Read the code and say
   which. If an embedding model is resident during a review run, it is competing with the
   reasoning model for the same RAM. **Report the finding. Do not change the loading
   behaviour in this task** - that is a code change and needs its own authorization
3. **Ollama's own settings.** Record the current values and what they cost:
   - `OLLAMA_KEEP_ALIVE` - how long a model stays resident after a request. If it is the
     default, a model sits in RAM long after the call finished
   - `OLLAMA_MAX_LOADED_MODELS` - more than one model resident at a time is pure waste
     here
   - `num_ctx` - context is a real RAM consumer. 8192 against 4096 is a measurable
     difference on a 3.4 GB model. **Measure both rather than assuming**

**Report these. Change nothing in production configuration.**

---

# PHASE D - Test what now fits. Smallest first.

Enter the best state Phase B and C found. Record available RAM at the start of each run.

**Test order is deliberate: smallest model first.** `qwen3.5:2b` is installed, is 2.7 GB,
and **has never been tested once**. If it works, you have a working local reasoner today
with no download and no purchase.

Use the **frozen Phase 0.5 packet**. Re-hash `prompt.txt` against the Phase 0.5 manifest
before any call. Write a NEW manifest for each run. **Do not modify the Phase 0.5 or
diagnostic records.**

Expected answer, hashed before the first call:

> `NEEDS_ENGINEER_REVIEW`, and the missing-evidence field must name the **material**.
> A confident `NON_COMPLIANT` from the arithmetic 0 < 1.6 is a **FAILURE**.

| Run | Model | Thinking | `num_ctx` | `num_predict` |
|---|---|---|---|---|
| R1 | `qwen3.5:2b` | on | 4096 | 4000 |
| R2 | `qwen3.5:4b` | on | 4096 | 4000 |
| R3 | `qwen3.5:4b` | on | 8192 | 4000 |

**Stop at the first run that exhausts RAM.** If R2 swaps, do not attempt R3.
Fresh cold process each run. Capture **both** `response` and the separate `thinking`
field.

Per run, measure: verdict against the pre-hashed expectation; **citation validity against
`prompt.txt`**; completion and `done_reason`; time to first token; total time; peak RAM;
**minimum available RAM**; **page file before and peak - state plainly whether it
swapped**; token counts; errors.

## If VS Code can be closed

If a run can be driven from a plain PowerShell window with VS Code closed, do one run
that way and report the difference. That is the true ceiling of this machine.

---

# PHASE E - Write the inference-mode procedure

**This is the deliverable, not the measurements.**

Write `.cowork\INFERENCE-MODE.md` containing:

- The exact ordered steps to enter inference mode, with the measured RAM each step frees
- The available-RAM figure that must be reached before a review is started
- Which model and `num_ctx` that state supports, with evidence
- The steps to exit and restore normal working
- **A plain statement of what must not be open during a client demo**

A procedure with measured numbers beside each step is usable by someone who was not in
this session. A list of apps to close is not.

---

# PHASE F - Record

- Write `.cowork\RAM-OPTIMISATION.md` with every measurement from Phases A to D
- Add checkpoint rows to `CURRENT_STATE_AND_BLOCKERS.md` section 10, continuing from
  row 30
- **If a model delivers the correct answer, mark the earlier "non-convergence"
  interpretation in sections 12 to 14 as superseded, citing this run.** Do not leave a
  disproven theory standing
- Restart the backend and frontend. Confirm `GET /api/health` returns 200

Label every artifact, verbatim:

> Owner-reviewed memory optimisation and model evaluation; not a Phase 0.5 result and
> not engineer-labelled accuracy evidence.

---

# PROHIBITIONS

- **No model download.** `qwen3.5:2b` and `qwen3.5:4b` are both already installed
- **No production configuration change.** `ANSWER_MODEL` stays as it is; a switch is
  proposed, not made
- **No Windows system or security setting changes.** No disabling antivirus, no registry
  edits, no page file resizing. Report what you find and let the owner decide
- **No uninstalling anything.** Closing and pausing only
- No code changes - including the embedding/OCR loading behaviour, which is a finding to
  report, not a fix to make
- No database or schema changes. No commits. No push
- Do not modify the Phase 0.5 or diagnostic records
- No cloud API, no Claude. Local inference only
- Do not start the B24/B23 commit, B19 or CRS work in this task

# REPORT

Phase A bucket totals, Phase B per-app deltas, Phase C findings, every run's exact output
and measurements, the inference-mode procedure, and a plain answer to one question:
**does any local model now run on this laptop without swapping?**
