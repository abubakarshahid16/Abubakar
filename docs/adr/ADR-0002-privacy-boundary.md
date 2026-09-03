# ADR-0002 — Privacy boundary: local inference on a networked machine

- **Status:** Accepted
- **Date:** 2026-09-04
- **Corrects:** the air-gap assumption throughout EXECUTION.md

## Context

- The execution plan assumed an air-gapped machine and specified offline installer packaging, USB/checksum staging, an air-gap install rehearsal, and disconnecting the network for the demo.
- **That assumption is wrong.** The machine has internet access.

## Decision

The rule is **not** "no network". The rule is **client document content never leaves this machine**.

**Allowed**
- Model weight downloads, pip, npm, GitHub, CI, reading documentation
- Any network use that does not carry document content

**Forbidden**
- Sending document text, chunks, questions, or answers to any external service
- Hosted inference APIs
- Cloud OCR
- Cloud or hosted vector databases

**Therefore:** all inference — embedding and generation — runs locally.

## Enforcement

- After model download completes, set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` so no library can transmit document content.
- Services bind to `127.0.0.1` only.
- No remote fonts, icons, analytics, images or scripts in the UI.
- Retrieved document text is treated as untrusted data and is never sent anywhere.

## Removed from scope as a consequence

- Offline installer packaging
- USB and checksum staging
- The air-gap install rehearsal
- Disconnecting the network for the demo
- **OPS-001 shrinks to a normal install guide.**

## Consequences

- This is a **locally-inferencing system on a networked machine**. It is **not** an air-gapped system.
- **The client must never be told otherwise.** Describing this as air-gapped would be a false security claim.
- "No internet" would have reduced exfiltration exposure but never removed malicious-PDF, local-account, disk-theft, dependency, or privilege risks. Those remain, and remain out of prototype scope.
