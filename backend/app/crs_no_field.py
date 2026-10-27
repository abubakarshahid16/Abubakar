"""A library requirement no field on the sheet answers is ONE engineer line per
standard, never a contractor row (order 245).

With the 35B model reading every page and API 610 in the library, a pump datasheet's comment
sheet grew from 50 to 226 rows: 184 were API 610 clauses with no value read for
them ("no field read from the submittal answers this requirement"), each a
"missing information" row the contractor would be asked to answer. A requirement
paired with a field the sheet carries (a value, or a blank the sheet marks
itself), or one that names a datasheet field the sheet lacks, is still a row. One without any field is the standard's sentence, not a
reading of the sheet: it is counted per standard in the review notes (the
internal copy only) with every reference listed, and printed on no row of the
contractor's copy. The same rule decides the file and the screen
(`crs_mapping._bucket_of`). Pure functions over findings.
"""

from __future__ import annotations

from functools import lru_cache

NOTE_NO_FIELD_ANSWERS = (
    "No field on the sheet answers these requirements - engineer to check"
)

#: Findings that are not a library standard's requirement (they keep their own
#: rows). The same four values `crs_mapping` names `_DATASHEET_ORIGIN`,
#: `_AI_ORIGIN`, `_WEB_ORIGIN` and "chat"; a test pins them together.
OTHER_ORIGINS = (
    "datasheet_check",
    "ai_engineering_check",
    "web_standard_check",
    "chat",
)
_MISSING = "MISSING_INFORMATION"


def has_field(finding: dict) -> bool:
    """The finding is tied to something the sheet carries: a stored value (or the
    blank the sheet marks) or a datasheet page."""
    return bool(finding.get("fact_id") or finding.get("contractor_page"))


@lru_cache(maxsize=1)
def _rules() -> dict:
    from . import datasheet_checks

    return datasheet_checks.load_rules()


@lru_cache(maxsize=1)
def _known_spellings() -> frozenset[str]:
    """Every spelling of a field the system knows, folded: the printed names of the checklist
    data's roles and the spellings of `field_synonyms.json`."""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    rules = _rules()
    out: set[str] = set()
    for role, body in rules["roles"].items():
        out.add(normalise_field_name(role.replace("_", " ")))
        out.update(normalise_field_name(s) for s in body.get("printed_as", []))
    for group, spellings in datasheet_checks._synonyms().items():
        out.add(normalise_field_name(group))
        out.update(normalise_field_name(s) for s in spellings)
    return frozenset(out)


def is_known_field(label: str) -> bool:
    """True when `label` is a field the system knows: it reads as a role of the checklist data
    (`datasheet_checks.role_of`) or is one of the known spellings. Any other clean noun phrase
    is a sentence's subject, not a field a contractor can be asked for."""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    name = normalise_field_name(label)
    if not name:
        return False
    if name in _known_spellings():
        return True
    return datasheet_checks.role_of(name, _rules()) is not None


def names_a_field(finding: dict, field_label) -> bool:
    """The requirement names a KNOWN field (order 245c): the contractor is asked for it."""
    label = field_label(finding)
    return bool(label) and is_known_field(label)


def bucket_of_missing(
    finding: dict, blank_bucket: str, not_found_bucket: str
) -> str | None:
    """The bucket of a library requirement the review found MISSING_INFORMATION:
    `blank_bucket` when a field is paired; `not_found_bucket` when the requirement
    names a datasheet field the sheet does not carry (`_field_label` says so: the
    contractor is asked for that field); otherwise None - no field behind it, no
    row, counted by `notes`."""
    from .crs_mapping import _field_label  # lazy: crs_mapping imports this module

    if has_field(finding):
        return blank_bucket
    if (
        finding.get("origin") in OTHER_ORIGINS
    ):  # defence in depth: they never reach here
        return not_found_bucket
    return not_found_bucket if names_a_field(finding, _field_label) else None


def answered_by_no_field(finding: dict, field_label) -> bool:
    """A library requirement with MISSING_INFORMATION and no field behind it:
    nothing paired and no field named."""
    return (
        finding.get("compliance_status") == _MISSING
        and finding.get("origin") not in OTHER_ORIGINS
        and not finding.get("crs_skip")
        and not has_field(finding)
        and not names_a_field(finding, field_label)
    )


def notes(findings: list[dict]) -> list[dict]:
    """One note per standard: how many of this run's requirements have no field on
    the sheet, and every reference (the internal copy lists them all)."""
    from .crs_mapping import _field_label, _rejected, _standard_reference

    by_standard: dict[str, list[str]] = {}
    for f in findings:
        if _rejected(f) or not answered_by_no_field(f, _field_label):
            continue
        name = str(f.get("standard_name") or f.get("standard_document_id") or "")
        by_standard.setdefault(name, []).append(
            _standard_reference(f) or f"finding {f.get('id')}"
        )
    out = []
    for name in sorted(by_standard):
        refs = list(dict.fromkeys(r for r in by_standard[name] if r))
        count = len(by_standard[name])
        out.append(
            {
                "note": NOTE_NO_FIELD_ANSWERS,
                "standard": name,
                "count": count,
                "detail": (
                    f"{count} of this run's requirements from {name or 'this standard'} "
                    "have no matching field on this datasheet and no value was read for "
                    "them. They are not comments for the contractor: find the field, "
                    "or decide that the requirement does not apply"
                    + (f". References: {'; '.join(refs)}." if refs else ".")
                ),
            }
        )
    return out
