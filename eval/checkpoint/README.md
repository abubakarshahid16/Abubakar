# Checkpoint: the procedure-type document (#533, extends #468)

`procedure.json` is ONE invented HAZOP procedure and its answer key. `scripts/checkpoint_procedure.py` uploads it, extracts, chunks and reviews it against the `hazop_procedure` playbook in a temporary data directory (never the live database), then records per element the expected state, the review's state and pass/fail, with the sample's boundary.

```
python scripts/checkpoint_procedure.py --out checkpoint-procedure.json
```

| exit | meaning |
|---|---|
| 0 | every element as the key expects |
| 1 | at least one element differs, or the document was not read in full (`incomplete`, never a pass) |
| 2 | not run: the key is missing, unreadable or malformed, or its playbook is not available |

Planted on purpose: H07 (risk ranking) and H11 (revalidation) are left out, H02 has no scribe. A review that calls every element present scores 8 of 11 and fails.

Boundary: 1 invented procedure, the playbook as shipped (a DRAFT, clause numbers unchecked), one invented stand-in for IEC 61882 in the library, keyword index only. It is not the realistic sample of #468; that checkpoint runs on the PC.
