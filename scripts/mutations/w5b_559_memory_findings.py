"""#559: findings from the model's memory of a standard are their own class. Ids M6101-M6107."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_559_memory_findings.py"
_A = APP / "ai_engineering_check.py"
_C = APP / "crs_mapping.py"
_TAG = ("w5b", "honesty")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6101, "an item on a standard not held is stored like any other draft", _A,
       "        unverified = from_memory(item, held)\n", "        unverified = False\n",
       "potential_unverified or draft_row or keeps_the_label"),
    _m(6102, "the model's confidence survives on a memory finding", _A,
       '            "confidence": "low" if unverified else item["confidence"],',
       '            "confidence": item["confidence"],', "potential_unverified"),
    _m(6103, "every named standard counts as from memory, held or not", _A,
       "    return bool(str(item.get(\"relates_to\") or \"\").strip()) and not _held_names(item, held)",
       "    return bool(str(item.get(\"relates_to\") or \"\").strip())", "held_standard"),
    _m(6104, "an item naming no standard is put in the memory class", _A,
       "    return bool(str(item.get(\"relates_to\") or \"\").strip()) and not _held_names(item, held)",
       "    return not _held_names(item, held)", "naming_no_standard or part_of_a_held_name"),
    _m(6105, "the CRS drops the label", _C,
       "            if _ai_unverified(f) and not f.get(\"engineer_comment\"):", "            if False:",
       "draft_row or keeps_the_label"),
    _m(6106, "the label is dropped once an engineer confirms", _C,
       "                text = f\"{UNVERIFIED_LABEL}. {text}\"",
       "                text = text if f.get(\"confirmed_by\") else f\"{UNVERIFIED_LABEL}. {text}\"",
       "keeps_the_label"),
    _m(6107, "the label is forced onto an engineer's own wording", _C,
       "            if _ai_unverified(f) and not f.get(\"engineer_comment\"):",
       "            if _ai_unverified(f):", "own_wording"),
)
