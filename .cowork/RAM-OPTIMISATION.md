# RAM optimisation — STOPPED after Phase A

> Owner-reviewed memory optimisation and model evaluation; not a Phase 0.5 result and
> not engineer-labelled accuracy evidence.

Executed 2026-09-21 by Claude Code in VS Code on laptop ABUBAKAR under
`.cowork/EXECUTE-RAM-OPTIMISATION.md`. NORTH-STAR sha256 verified with `certutil` as
`3d0505be…9619`, 9 sections, checklist at section 8.

## Status

| Phase | Status |
|---|---|
| **A** — measure where the memory is | **COMPLETE** |
| **B** — reduce the discretionary baseline | **NOT STARTED** |
| C — reduce the project's own footprint | NOT STARTED |
| D — test what now fits | NOT STARTED |
| E — write the inference-mode procedure | NOT STARTED |
| F — record | NOT STARTED (this file records Phase A and the stop only) |

**Stopped on the owner's instruction after Phase A was approved and before any
Phase B action.** No app was closed by this task. No model was loaded. No run
happened. The deliverable of this order — `INFERENCE-MODE.md` — does **not** exist,
and nothing here should be read as having produced it.

### A note on apps that closed without this task closing them

At Phase A, Loom, ChatGPT Classic, ChatGPT and Teams were all running. When the stop
was recorded, all four were **no longer running**. **This task did not close them** —
the announced Phase B never executed a single tool call before the stop. They were
closed by something outside this session between the two measurements. Recorded so the
difference in available RAM below is not mistaken for Phase B progress.

| Measured at | Available RAM | Loom | ChatGPT Classic | ChatGPT | Teams | WhatsApp | Claude desktop |
|---|---|---|---|---|---|---|---|
| Phase A | **3.30 GB** | running | running | running | running | running | running, 1.563 GB |
| at the stop | **3.73 GB** | gone | gone | gone | gone | running, 0.336 GB | running, **2.12 GB** |

The 0.43 GB difference is therefore **not** a measured per-app delta and must not be
used as one. Phase B's whole point — one app at a time, so each closure has its own
number — was not carried out. Note also that Claude desktop **grew** by 0.56 GB over
the same interval.

---

## Phase A findings

### A2 — the four bucket totals

| Bucket | Processes | Working set |
|---|---|---|
| **Discretionary** | 79 | **4.823 GB** |
| Unavoidable — Windows, drivers, Defender | 156 | 2.511 GB |
| This project — VS Code, Python, Node, Ollama, shells | 57 | 2.507 GB |
| Unknown — named below | 72 | 0.551 GB |
| **Total** | **362** | **10.39 GB** |

Available RAM at measurement: **3.30 GB**, of 15.57 GB total. Chrome was already closed
from the previous task; open, it had been another **2.9 GB** (row 30).

**The ~4 GB target is findable: the discretionary bucket alone is 4.823 GB.** Whether
closing it actually returns that much as *available* RAM is exactly what Phase B was
designed to measure, and it was not measured. Working set closed is not the same as
available RAM gained.

### A1 — discretionary, itemised

| App | Processes | Working set |
|---|---|---|
| `claude.exe` (Claude desktop) | 11 | **1.563 GB** |
| `msedgewebview2.exe`, attributed below | 28 | **1.255 GB** |
| `ChatGPT.exe` | 11 | **0.887 GB** |
| `Loom.exe` | 12 | 0.252 GB |
| `WhatsApp.Root.exe` | 1 | 0.244 GB |
| `ChatGPT Classic.exe` | 5 | 0.182 GB |
| `Taskmgr.exe` | 1 | 0.138 GB |
| `ms-teams.exe` | 3 | 0.103 GB |
| SnippingTool, LenovoVantageService, M365Copilot, TeamViewer | 7 | 0.199 GB |

#### A correction made during Phase A: who owns the WebView2 processes

The 35 `msedgewebview2` processes were first assumed to belong to Claude and ChatGPT.
**They do not** — Claude and ChatGPT run under their own process names. Attributed by
walking each process's parent chain:

| Parent application | WebView2 processes | Working set |
|---|---|---|
| Microsoft Teams | 9 | 0.514 GB |
| WhatsApp | 7 | 0.445 GB |
| Windows Search (`SearchHost`) | 7 | 0.269 GB — **unavoidable**, bucketed there |
| TeamViewer | 6 | 0.221 GB |
| M365 Copilot | 6 | 0.040 GB |

So Teams really costs **~0.62 GB** (0.103 + 0.514) and WhatsApp **~0.69 GB**
(0.244 + 0.445) — three to four times their headline process figure.

### Unknown bucket, named rather than assumed

`Secure System` 0.062 · `backgroundTaskHost` 0.041 · `MicrosoftStartFeedProvider`
0.032 · `tailscaled` 0.030 · `WidgetBoard` 0.026 · `DAX3API` 0.020 ·
`CrossDeviceService` 0.020 · `AnyDesk` 0.018 · `tailscale-ipn` 0.018 ·
`MpDefenderCoreService` 0.015 · Realtek audio 0.014 · `FnHotkeyUtility` 0.013 · Wacom
tablet service 0.012 · four `codex-*` helpers 0.036 · remainder small.

**Left alone on the owner's instruction:** `AnyDesk`, `TeamViewer` and Tailscale
(`tailscaled`, `tailscale-ipn`) — remote access and VPN, likely IT-managed. All still
running and untouched at the stop.

### A3 — startup inventory, 8 entries

AnyDesk · Loom · Microsoft Edge auto-launch · **Ollama** · Realtek audio service ·
SecurityHealth · Tailscale · Teams.

Five of the eight are discretionary and return on every boot, so any closure is lost at
the next restart. That is why the order asks for a repeatable inference mode rather
than a one-off cleanup — and why Phase E's procedure matters more than Phase B's
numbers.

### A4 — page file

**System-managed** (`AutomaticManagedPagefile: True`), `C:\pagefile.sys`, allocated
base **34.02 GB**, current use **9.30 GB**, **peak use 22.31 GB**. The machine has at
some point had 22 GB paged out. Not resized — the order forbids it.

---

## What remains open

The question this order exists to answer — **does any local model run on this laptop
without swapping?** — is **unanswered**. `qwen3.5:2b` (2.7 GB, installed) has still
never been tested once.

To resume, re-run the order from **Phase B**, not Phase A: the Phase A inventory
above is valid as a starting point, but the RAM state has moved since (four apps now
closed, Claude desktop grown), so Phase B should re-take its own baseline before the
first closure.

## Confirmation

No app closed by this task. No Windows system or security setting changed. Nothing
uninstalled. No model downloaded or loaded. `ANSWER_MODEL` unchanged. No code,
database, commit or push. Phase 0.5 and diagnostic records untouched.
