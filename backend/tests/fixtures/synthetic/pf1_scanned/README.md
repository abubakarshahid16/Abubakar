# Invented scanned sheet (fix 7 proof)

`pf1-t01-pump.scanned.datasheet.pdf` is the PF1 invented pump datasheet
(`../pf1/pf1-t01-pump.datasheet.pdf`) drawn with the generator's `scanned`
layout (`backend/tools/pf1_set.py`): the same two pages as pixels only, **no
text layer**. It is invented; no client data.

- Standard to review it against: `../pf1/pf1-t01-pump.standard.pdf`.
- Answer key: `pf1-t01-pump.scanned.key.json` (the pump's key, renamed). The
  scanned sheet must catch the same items as the text version once OCR reads it.
- Use: ingest it as a contractor submittal with OCR on and read the page ledger
  (`page_ledger`): every page should be `done` for OCR and `facts`, never
  `not_reached` / `not_run`.
