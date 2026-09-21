# Laptop model upgrade — STOPPED AT THE STEP 1 GATE

> Owner-reviewed model evaluation; not a Phase 0.5 result and not engineer-labelled
> accuracy evidence.

Executed 2026-09-21 by Claude Code in VS Code on laptop ABUBAKAR under
`.cowork/EXECUTE-LAPTOP-MODEL-UPGRADE.md`. NORTH-STAR sha256 verified with
`certutil` as `3d0505be…9619`, 9 sections, checklist at section 8.

**No model was pulled. No benchmark was run.** The Step 1 gate stopped it, which is
the gate working as designed.

---

## The missing number, now measured

The order's premise was right: every RAM figure on record was taken with the full
development stack running, and **nobody had measured this laptop clean**. Here it is.

### The five numbers, clean machine, `ollama ps` confirming no model loaded

| # | Measurement | Value |
|---|---|---|
| 1 | total physical RAM | **15.57 GB** |
| 2 | **available RAM** | **2.70 GB** ← the gate number |
| 3 | page file / swap in use | **9.55 GB** |
| 4 | committed | **25.03 GB** of a 49.58 GB commit limit |
| 5 | sum of all process working sets | **11.33 GB** |

Free disk on the Ollama models drive (`C:`, models at `C:\Users\abuba\.ollama\models`):
**112.6 GB free** of 380 GB. The disk gate would have passed comfortably; it was never
reached.

### How it got there

| State | Available RAM | Page file |
|---|---|---|
| As found — backend, Vite, Chrome (23 procs, 2.9 GB), Edge (11, 0.67 GB), VS Code, Claude/ChatGPT/WhatsApp desktop | **0.88 GB** | 10.54 GB |
| Backend + frontend stopped, browsers sent a close request | 1.81 GB | 9.35 GB |
| Chrome force-closed (16 processes survived the graceful close, holding 2.01 GB) | 3.27 GB | 9.48 GB |
| Settled, final measurement | **2.70 GB** | 9.55 GB |

Stopping the entire development stack and both browsers recovered **about 1.8–2.4 GB**.
The machine still holds **11.33 GB** in process working sets with nothing of this
project running.

### What holds the memory when the project is stopped

`claude` 0.55 + 0.26 GB · VS Code 0.40 + 0.31 + 0.26 + 0.24 GB · `msedgewebview2`
0.31 GB · `chrome` 0.33 GB (2 processes survive a force-close) · `explorer` 0.25 GB ·
`ChatGPT` 0.25 GB · `WhatsApp.Root` 0.24 GB · `MsMpEng` (Defender) 0.22 GB.

VS Code was **left running deliberately** — this shell runs inside it, so it cannot be
stopped from here. ChatGPT and WhatsApp desktop were left running: they are not
browsers and the order did not name them.

---

## The gate

| Available RAM, clean | Decision | Applies? |
|---|---|---|
| 10 GB or more | `qwen3.5:9b` viable, proceed | no |
| 7 to 10 GB | marginal, proceed and record swapping | no |
| **Under 7 GB** | **STOP and report** | **YES — 2.70 GB** |

**2.70 GB against a 7 GB floor, and a 6.6 GB model.** Not marginal — short by a
factor of about 2.6. The order's own wording for this row is the correct conclusion:

> *"A 6.6 GB model will thrash. The problem is the machine's baseline load, not the
> model, and that is a different fix."*

Steps 2 through 7 were therefore not executed: no `ollama pull`, no benchmark
manifest, no L1, no L2. `qwen3.5:2b` and `qwen3.5:4b` are both still present and
untouched, confirmed by `ollama list` after the stop.

## What this adds to the record

The existing Phase 0.5 and diagnostic RAM figures were read as *the 4b model nearly
exhausting the machine*. This measurement reframes them: **the model was never the
load.** With every part of this project stopped, the laptop has 2.70 GB free and 9.55
GB of page file already committed. `qwen3.5:4b` (3.4 GB) does not fit in 2.70 GB
either — which is why every previous run swapped, and why it swapped before the model
was even the largest thing in memory.

That makes the hardware conclusion in `DIAGNOSTIC-OUTPUT-FORMAT.md` stronger and more
specific than it was: the constraint is not "a 4b model is at this machine's ceiling",
it is **this machine has no usable headroom for local inference of any size while it
is being used as a development and communications workstation**.

## What was NOT concluded

Nothing about whether `qwen3.5:9b` reasons better. That question is untested and
remains open — it was not answered, and this document must not be cited as having
answered it. Phase 0.5 remains failed and stopped.

## Two routes, for the owner — neither begun

1. **Reduce the baseline, then re-run this order unchanged.** Closing VS Code, the
   Claude and ChatGPT desktop apps, WhatsApp and Chrome, and running the benchmark
   from a plain terminal, would plausibly clear the 7 GB gate — the working sets above
   suggest roughly 3–4 GB is recoverable beyond what was recovered here. This costs
   nothing but a session where the laptop does one job. It is the cheapest way to get
   the 9b answer on existing hardware.
2. **Treat it as the server evidence.** If the laptop must keep running its normal
   workload, then it is not a local-inference host at any model size, and this is the
   measured argument for the separate machine — with the number 2.70 GB rather than an
   estimate.

Route 1 is the smaller step and answers the model question; route 2 answers the
deployment question. They are not exclusive.

## Confirmation

Backend and frontend were **restarted** and verified: both ports up in ~4.5 s,
`GET /api/health` → **HTTP 200** `{"ok":true,"embed_model_present":true,
"answer_model_present":true,...}`, `GET :5173/` → **HTTP 200**. Browsers were closed
and not reopened; Chrome will restore its tabs on next launch.

No model pulled. No model deleted. Production configuration unchanged —
`ANSWER_MODEL` still `qwen3.5:4b`, and no switch was made or proposed in code. No
code, no database, no schema, no commit, no push. No cloud API and no Claude call.
The Phase 0.5 manifest, prompt, expectation and run record, and the output-format
diagnostic record, were not modified.
