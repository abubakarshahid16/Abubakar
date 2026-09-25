"""Mutations of `backend/app/row_noise.py` (#193 plan B4 item 3)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b4_quality.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M645", phase=64,
        description="B4 noise: the row-number ruler is kept as a field",
        path=APP / "row_noise.py",
        anchor="    if _RULER.match(label):\n        return RULER\n",
        replacement="",
        target=_T, keyword="each_noise_rule",
    ),
    Mutation(
        id="M646", phase=64,
        description="B4 noise: the revision table is kept as fields",
        path=APP / "row_noise.py",
        anchor="    if _REVISION.search(label) or _REVISION.search(value) and len(value.split()) >= 2:\n",
        replacement="    if False:\n",
        target=_T, keyword="each_noise_rule",
    ),
    Mutation(
        id="M647", phase=64,
        description="B4 noise: a note or clause reference is kept as a value",
        path=APP / "row_noise.py",
        anchor="    if _NOTE_REF.match(value) or _CLAUSE_REF.match(value):\n",
        replacement="    if False:\n",
        target=_T, keyword="each_noise_rule",
    ),
    Mutation(
        id="M648", phase=64,
        description="B4 noise: a decimal number reads as a clause reference (real values dropped)",
        path=APP / "row_noise.py",
        anchor=r'_CLAUSE_REF = re.compile(r"^(\(\d+(\.\d+)+[a-z]?\)|\d+(\.\d+){2,}[a-z]?)$", re.IGNORECASE)' + "\n",
        replacement=r'_CLAUSE_REF = re.compile(r"^\(?\d+(\.\d+)+[a-z]?\)?$", re.IGNORECASE)' + "\n",
        target=_T, keyword="real_fields_are_not_noise",
        tags=("honesty",),
    ),
)
