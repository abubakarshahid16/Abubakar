# scripts/

Command-line tools. Most are used by CI, the mutation harness or `CLAUDE.md`
(`check_mutation_anchors.py`, `mutation_check.py`, `test_changed.py`,
`review_score.py`, `fetch_models.py`...). A few are **one-off checks run by
hand on the owner's PC** against a COPY of the live database, never the live
file (`live_guard`). They are referenced from no other file, which is why they are
listed here: they are tools, not dead code (#661).

| script | what it is for |
|---|---|
| `b4_before_after.py` | the B4 acceptance: extraction counts before and after, on two disposable copies |
| `backfill_standard_metadata.py` | fill document number and revision of every standard from its own cover pages; `--live` goes through `live_guard` (backup and restore drill first) |
| `bench_vector_store.py` | dense-stage benchmark of the vector-store backends, on synthetic data only |
| `verify_crs_numbers_on_real_runs.py` | check permanent CRS comment numbers on a diagnostic copy of the real runs |
| `verify_geometry_ocr_guard_on_real_docs.py` | read-only sanity check of the geometry reader's OCR guard on real documents |

`vulture_whitelist.py` lists the names the dead-code check in CI must not report
(see the comment beside each).
