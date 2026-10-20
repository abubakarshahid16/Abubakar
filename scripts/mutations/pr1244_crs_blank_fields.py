"""#882 (PF2, orders 180 / 180.1 items 3, 4, 8): blank fields no clause asks
about are one CRS row. `crs_mapping.py` is in the danger zone (rule 6).
PR #1244."""

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
        id=f"M1244-{n}",
        phase=1244,
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
        "a blank a clause requires is folded into the one row, hiding its clause",
        _B,
        '        and not f.get("standard_clause")\n',
        "",
        "a_blank_a_clause_requires_keeps_its_own_row",
    ),
    _m(
        "02",
        "the one row is numbered by whichever field leads it, so a re-run renumbers it",
        _M,
        '    return comment_key(*key) if key[0] == "blanks" else _subject_key(f)\n',
        "    return _subject_key(f)\n",
        "the_row_number_does_not_depend_on_which_fields_are_blank",
    ),
    _m(
        "03",
        "two findings of one field are two entries",
        _B,
        "fields.setdefault(_same_field(label),",
        "fields.setdefault(label,",
        "two_findings_of_one_field_are_one_entry",
    ),
    _m(
        "04",
        "the entry keeps the first spelling, a fragment, not the full label",
        _B,
        '        if len(label) > len(entry["label"]):\n',
        "        if False:\n",
        "two_findings_of_one_field_are_one_entry",
    ),
    _m(
        "05",
        "a not-found mandatory field is grouped as a blank",
        _B,
        '        and f"{BLANK_RULE}:" in str(f.get("requirement_source_text") or "")\n',
        "",
        "a_not_found_mandatory_field_is_not_a_blank_row",
    ),
    _m(
        "06",
        "the row's sentence loses its instruction to the contractor",
        _B,
        'HEADLINE = "These fields are left blank; contractor to complete: "',
        'HEADLINE = ""',
        "blank_fields_with_no_clause_are_one_row",
    ),
    _m(
        "07",
        "a breach with no clause is grouped as a blank",
        _B,
        '        and f.get("compliance_status") == "MISSING_INFORMATION"\n',
        "",
        "a_blank_with_a_clause_is_not_grouped",
    ),
)
