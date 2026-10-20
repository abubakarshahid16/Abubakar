"""Order 161 C: a CRS row cites the paragraph the standard's own numbering names.
`comparison.py` and `crs_mapping.py` are in the danger zone (rule 6). PR #1218:
ids M1218-01 onwards, phase 1218."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_161c_paragraph_ids.py"
_P = APP / "paragraph_ids.py"
_TAGS = ("honesty", "161c")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1218-01",
        phase=1218,
        description="the CRS never cites the paragraph, only 'not identified'",
        path=APP / "crs_mapping.py",
        anchor='        clause = finding.get("paragraph_id")\n',
        replacement="        clause = None\n",
        target=_T,
        keyword="cites_the_paragraph",
        tags=_TAGS,
    ),
    Mutation(
        id="M1218-02",
        phase=1218,
        description="the paragraph is not looked up when the CRS context is attached",
        path=APP / "comparison.py",
        anchor="    paragraph_ids.attach(findings)  # order 161 C: the paragraph the standard's own text names\n",
        replacement="    pass\n",
        target=_T,
        keyword="wired",
        tags=_TAGS,
    ),
    Mutation(
        id="M1218-03",
        phase=1218,
        description="a numbering is guessed from too few or mixed headings",
        path=_P,
        anchor="    if len(found) >= MIN_HEADINGS and len(found) / total >= MIN_SHARE:\n",
        replacement="    if found:\n",
        target=_T,
        keyword="unsure",
        tags=_TAGS,
    ),
    Mutation(
        id="M1218-04",
        phase=1218,
        description="the sub-paragraph in force is not appended",
        path=_P,
        anchor="        return ident + _sub_marks(text, at, position)\n",
        replacement="        return ident\n",
        target=_T,
        keyword="own_numbering",
        tags=_TAGS,
    ),
    Mutation(
        id="M1218-05",
        phase=1218,
        description="every standard is read in the dotted shape, whatever its own",
        path=_P,
        anchor="    pattern = SHAPES[shape]\n",
        replacement='    pattern = SHAPES["dotted"]\n',
        target=_T,
        keyword="own_numbering",
        tags=_TAGS,
    ),
    Mutation(
        id="M1218-06",
        phase=1218,
        description="a finding whose clause is already a paragraph id also gets a paragraph",
        path=_P,
        anchor='        and (f.get("clause_identified") is False or not f.get("standard_clause"))\n',
        replacement="        and True\n",
        target=_T,
        keyword="real_clause",
        tags=_TAGS,
    ),
)
