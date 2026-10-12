# Gold-lite answer keys (#829)

A gold-lite key holds review verdicts on the real, owner-approved datasheets that
a **named session read and no engineer has confirmed** (key source `gold_lite`,
see `../README.md`). It gives a regression signal between merges; it does not
prove a verdict is right.

**Nothing from the documents is in this folder.** The keys, the exported findings
and the hand-check workbooks are built from client documents, so they stay on the
owner's PC (`D:\project\gold-lite-<date>\key-v<N>\`). Only ids and counts are
committed here:

| file | what it holds |
|---|---|
| `v0.counts.json` | per datasheet: the run id, the document id, findings by status, how many verdict rows became key items, the local answer file's SHA-256 checksum, how many workbook rows wait for an engineer |

## v0 (12 Oct 2026)

| datasheet (document id) | findings | verdict rows | key items | workbook rows for the engineer |
|---|---|---|---|---|
| doc_d30f4c63d481 | 243 | 94 | **94 met** | 151 |
| doc_da3fcc0aaacc | 4,232 | 0 | 0 (no verdicts in the run) | 151 |
| doc_2ec2934f8d3f | 4,787 | 2 | **0** (both left out, see the counts file) | 32 |

Engineer cells filled: **0 of 334**. Until an engineer fills the workbooks, no
item here is confirmed.

## Scoring a run against a key (on the owner's PC)

```powershell
python scripts\review_score.py export --db COPY.sqlite --run RUN_ID --out run.findings.json
python scripts\review_score.py score  --key D:\project\gold-lite-2026-10-12\key-v0\gold-lite-psv.key.json --findings run.findings.json
```

A `met` item that is no longer COMPLIANT lowers the precision line; a `met` item
called NON_COMPLIANT is a wrong flag. Every report says the key is not
engineer-confirmed.
