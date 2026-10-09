"""#633: the condition gate's NOT_APPLICABLE on absence; the scope record's failed source. Ids M6701-M6707."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w3_633_condition_absence.py"
_C = APP / "conditions.py"
_S = APP / "scope_records.py"
_TAG = ("w3", "honesty")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6701, "an unrecognised value excuses the clause again", _C,
       "        other = next((t for t in table if t not in terms and _contains_term(value, t)), None)\n",
       "        other = value or None\n", "unrecognised_material or other_kinds"),
    _m(6702, "a named other value is not proof", _C,
       "        if other is not None:\n            return _result(\n                NOT_SATISFIED,",
       "        if False:\n            return _result(\n                NOT_SATISFIED,",
       "different_recognised or named_other_service"),
    _m(6703, "the proving fact is not the one that names the other value", _C,
       "                _evidence_of(named))\n    return _result(\n        UNKNOWN, shape, condition,\n        f\"{len(stated)} field(s) state a value, but none",
       "                _evidence_of(stated[0]))\n    return _result(\n        UNKNOWN, shape, condition,\n        f\"{len(stated)} field(s) state a value, but none",
       "named_other_service"),
    _m(6704, "a failed search source is only logged", _S,
       "        if failures is not None:\n            failures.append(f\"hybrid-search: {type(exc).__name__}\")\n", "",
       "failed_search_source or source_failed"),
    _m(6705, "read_scope does not pass the failures on", _S,
       "    return record_from(document_id, passages, responses, lexicon=lexicon, seed=seed,\n"
       "                       sources_failed=failures)",
       "    return record_from(document_id, passages, responses, lexicon=lexicon, seed=seed)",
       "source_failed"),
    _m(6706, "the stored record does not carry the failed source", _S,
       "    if count and failed:\n        record = {**record, \"sources_failed\": failed}\n", "",
       "carries_the_failed_source"),
    _m(6707, "the error text is recorded instead of its type", _S,
       "            failures.append(f\"hybrid-search: {type(exc).__name__}\")",
       "            failures.append(f\"hybrid-search: {type(exc).__name__}: {exc}\")",
       "failed_search_source or source_failed"),
)
