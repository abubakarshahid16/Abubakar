"""Where a sentence does NOT end.

Engineering text is full of full stops that are not sentence ends: "P-No. 1
materials", "para. 7.1", "Fig. 3", "approx. 5 mm", "e.g. the". Every place that
cut text at ". " cut there too, so a quoted line stopped at "P-No." and the next
one began "1 materials is not permitted" (seen on the owner's screen
2026-10-01/02, in two different answers).

`NOT_AN_ABBREVIATION` is a run of negative look-behinds to place right after a
`(?<=[.!?])` look-behind: the split is skipped when the full stop belongs to one
of these abbreviations. Skipping only ever MERGES two pieces, so a miss costs a
longer sentence, never a cut-off quote.

The chunker has its own splitter (`chunker._SENTENCE_SPLIT`) and is not changed
here: it decides where STORED chunks begin, so changing it needs a re-process of
the library (owner's decision, chunker v9).
"""
from __future__ import annotations

#: Written out by hand on purpose: a short, reviewable list, not a vocabulary.
_ABBREVIATIONS = (
    "No", "NO", "Nos", "para", "paras", "Para", "Sec", "Secs", "Fig", "Figs",
    "Cl", "Eq", "Ref", "Refs", "Tbl", "Vol", "Art", "Dwg", "approx", "Approx",
    "Min", "Max", "vs", "Vs",
)

NOT_AN_ABBREVIATION = (
    "".join(rf"(?<!\b{a}\.)" for a in _ABBREVIATIONS)
    + r"(?<!\be\.g\.)(?<!\bi\.e\.)"
)
