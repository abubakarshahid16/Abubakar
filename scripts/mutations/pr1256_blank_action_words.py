"""#882 item 4: a blank field's CRS row asks in a full sentence. `crs_mapping.py`
and `crs_blank_fields.py` are danger-zone modules (rule 6). PR #1256."""

from __future__ import annotations

from ._base import APP, Mutation

_B = APP / "crs_blank_fields.py"
_M = APP / "crs_mapping.py"
_T = "tests/test_882_crs_blank_fields.py"
_TAGS = ("honesty",)


def _m(
    n: str, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1256-{n}",
        phase=1256,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a blank field's row asks with a bare label again",
        _M,
        "            return crs_blank_fields.provide_words(finding, field)\n",
        '            return f"Contractor to provide {what}."\n',
        "asks_in_a_full_sentence",
    ),
    _m(
        "02",
        "a field that states a value is called blank",
        _B,
        '    if field and finding.get("crs_is_blank"):\n',
        "    if field:\n",
        "keeps_the_plain_request",
    ),
    _m(
        "03",
        "a blank field with no name is quoted as an empty field",
        _B,
        '    if field and finding.get("crs_is_blank"):\n',
        '    if finding.get("crs_is_blank"):\n',
        "never_quotes_an_empty_field",
    ),
)
