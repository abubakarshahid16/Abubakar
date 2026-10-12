# Vision reader (#193 B4 item 1) - real-layout proof log

Each run below used real submittal copies kept outside git. See `scripts/prove_vision_reader_layouts.py` for how to reproduce.

## Run at 2026-09-28 19:19 UTC

Aggregate numbers only - no document text (CLAUDE.md rules 1 and 3).

| Layout | Page | Page kind | Kept | Proposed | Dropped |
|---|---|---|---|---|---|
| heat_exchanger_datasheet | 5 | datasheet | 43 | 53 | {'unit not on the page beside the value': 8, 'value not beside its label': 1, 'value not on the page': 1} |
| psv_datasheet | 2 | datasheet | 44 | 48 | {'value not on the page': 2, 'empty label or value': 2} |
| pump_datasheet | 2 | datasheet | 40 | 55 | {'label not on the page': 9, 'value not on the page': 3, 'unit not on the page beside the value': 2, 'value not beside its label': 1} |

**3/3 layouts produced at least one proven field. 127 fields kept in total. Dropped by reason: {'unit not on the page beside the value': 10, 'value not beside its label': 2, 'value not on the page': 6, 'empty label or value': 2, 'label not on the page': 9}.**

