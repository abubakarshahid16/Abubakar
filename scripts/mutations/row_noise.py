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

    # ---- B4 defects, 2026-09-25 (tests/test_b4_defects.py)
    Mutation(
        id="M719", phase=65, description="B4d: an identifier's bare number is stored as a measurement",
        path=APP / "row_noise.py",
        anchor="    if _IDENTIFIER_LABEL.search(label) and _BARE_INTEGER.match(value):\n        return IDENTIFIER_NUMBER\n",
        replacement="",
        target="tests/test_b4_defects.py", keyword="identifier_number_is_noise or drops_the_title_block",
        tags=("honesty",),
    ),
    Mutation(
        id="M720", phase=65, description="B4d: an identifier label with a tag value is dropped as noise",
        path=APP / "row_noise.py",
        anchor="    if _IDENTIFIER_LABEL.search(label) and _BARE_INTEGER.match(value):\n",
        replacement="    if _IDENTIFIER_LABEL.search(label):\n",
        target="tests/test_b4_defects.py", keyword="count_or_a_quantity_is_not_noise",
    ),
    Mutation(
        id="M721", phase=65, description="B4d: job / P.O. / requisition labels are not title block",
        path=APP / "row_noise.py",
        anchor='    r"job\\s*no\\.?|p\\.?\\s*o\\.?\\s*no\\.?|requisition\\s*no\\.?|"\n',
        replacement="",
        target="tests/test_b4_defects.py", keyword="identifier_number_is_noise",
    ),
    Mutation(
        id="M722", phase=65, description="B4d: the noise filter runs only with the geometry flag on",
        path=APP / "datasheets.py",
        anchor="                noise = (row_noise.noise_reason(label, value)\n                         if not blank else None)\n",
        replacement="                noise = (row_noise.noise_reason(label, value)\n                         if settings.geometry_reader_enabled and not blank else None)\n",
        target="tests/test_b4_defects.py", keyword="default_path_drops_the_title_block",
    ),
)
