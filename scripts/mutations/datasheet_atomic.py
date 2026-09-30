"""Mutations for "one value, one fact" in backend/app/claude_datasheet.py
(2026-09-30, M1800 and M1802-M1807; the range guard M1801 was dead code and was removed). Target: backend/tests/test_datasheet_atomic.py.
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
             anchor="    if unit and not _unit_recognised(unit):\n        return None\n    if not re.match",
             replacement="    if not re.match",
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
    Mutation(id="M1806", phase=1806,
             description="the second reading uses the same prompt again",
             path=_CD,
             anchor="again(build_prompt(page_text, page_no, known_fields, \"b\"))",
             replacement="again(prompt)",
             target=_T, keyword="bottom_up or differ_only or differ_only_in_order", tags=_TAG),
    Mutation(id="M1807", phase=1807,
             description="the model's qualifier is dropped at parse",
             path=_CD,
             anchor="            **({\"qualifier\": str(p[\"qualifier\"]).strip()}\n               if p.get(\"qualifier\") not in (None, \"\") else {}),\n",
             replacement="",
             target=_T, keyword="parse_keeps", tags=_TAG),
)
