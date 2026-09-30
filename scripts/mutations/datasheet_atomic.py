"""Mutations for "one value, one fact" in backend/app/claude_datasheet.py
(2026-09-30, M1800, M1802-M1805, M1807 and M1808; the range guard M1801 was dead code and was removed). Target: backend/tests/test_datasheet_atomic.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_datasheet_atomic.py"
_CD = APP / "claude_datasheet.py"
_TAG = ("datasheet_atomic",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1800", phase=1800,
             description="a quantity followed by words is no longer trimmed",
             path=_CD,
             anchor="    if not re.match(r\"\\s*[,;(]|\\s+[A-Za-z]\", rest):\n        return None\n",
             replacement="    return None\n",
             target=_T, keyword="words_as_a_qualifier", tags=_TAG),
    Mutation(id="M1802", phase=1802,
             description="a value with an unknown unit is split anyway",
             path=_CD,
             anchor="    if unit and not _unit_recognised(unit):\n        return None\n    if unit and not gap",
             replacement="    if unit and not gap",
             target=_T, keyword="never_split", tags=_TAG),
    Mutation(id="M1803", phase=1803,
             description="two conditions are no longer two facts",
             path=_CD,
             anchor="        if len(pieces) < 2:\n            pieces = [value]\n",
             replacement="        pieces = [value]\n",
             target=_T, keyword="two_conditions or keeps_the_quote", tags=_TAG),
    Mutation(id="M1804", phase=1804,
             description="a note reference becomes a qualifier",
             path=_CD,
             anchor="            if qualifier and re.match(r\"(?:note|see|ref)\\b\", qualifier, re.IGNORECASE):\n                qualifier = None  # a note reference is not a condition\n",
             replacement="",
             target=_T, keyword="note_reference", tags=_TAG),
    Mutation(id="M1805", phase=1805,
             description="the gate no longer trims values before checking them",
             path=_CD,
             anchor="    for p in atomise(proposals):\n",
             replacement="    for p in proposals:\n",
             target=_T, keyword="keeps_the_quote", tags=_TAG),
    Mutation(id="M1807", phase=1807,
             description="the model's qualifier is dropped at parse",
             path=_CD,
             anchor="            **({\"qualifier\": str(p[\"qualifier\"]).strip()}\n               if p.get(\"qualifier\") not in (None, \"\") else {}),\n",
             replacement="",
             target=_T, keyword="parse_keeps", tags=_TAG),
    Mutation(id="M1808", phase=1808,
             description="a number glued to a one-letter unit (316L SS) is split as a quantity",
             path=_CD,
             anchor="    if unit and not gap and len(unit) == 1:\n        return None  # \"316L SS\" is a steel grade, not 316 litres with a note\n",
             replacement="",
             target=_T, keyword="steel_grade", tags=_TAG),
)
