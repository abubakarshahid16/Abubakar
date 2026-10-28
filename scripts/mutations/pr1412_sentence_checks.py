"""Order 274.1 (PR 1412): the review reads the standards converter's SENTENCE checks. The hook in `comparison.py`
(danger zone) and the gates of `converter_review.converter_rules` decide which sentence a review compares with an
AI-proven check, so each gets an entry. Ids M1412-01 onwards, phase 1412."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_274_sentence_checks.py"
_TAGS = ("honesty", "o274")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1412-{n}",
        phase=1412,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


_C = APP / "converter_review.py"

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the review no longer asks for the converter's rules (nor the drafts): no sentence is compared through a check",
        APP / "comparison.py",
        "        auto_rules = converter_review.rules_with_drafts(\n"
        "            standard_id, submittal_id, allowed_document_ids\n"
        "        )",
        "        auto_rules = {}",
        "unproven_family",
    ),
    _m(
        "02",
        "the owner's switch is ignored: the converter's rules are given with rule_auto_use_enabled off",
        _C,
        "        or not settings.rule_auto_use_enabled\n",
        "",
        "both_switches",
    ),
    _m(
        "03",
        "a standard outside the reader's scope is given its rules",
        _C,
        "        or standard_document_id not in allowed_document_ids\n    ):\n        return {}\n    entries",
        "    ):\n        return {}\n    entries",
        "standard_in_scope",
    ),
    _m(
        "04",
        "a draft made for another equipment type is read for this review",
        _C,
        "        if rule_roles.same_type(file_type, equipment_type)\n    ]\n    conn = connect()",
        "    ]\n    conn = connect()",
        "another_equipment_type",
    ),
    _m(
        "05",
        "a draft made for another standard is read for this one",
        _C,
        '        if standard_ids.same_standard(e.get("standard"), label):\n',
        "        if True:\n",
        "another_equipment_type",
    ),
    _m(
        "06",
        "a sentence edited since the draft is matched anyway (the first rule of the file stands in for it)",
        _C,
        "        if digest in by_hash:\n            rule = _rule_from(row, digest, *by_hash[digest])\n",
        "        if by_hash:\n            rule = _rule_from(row, digest, *next(iter(by_hash.values())))\n",
        "edited_since_the_draft",
    ),
    _m(
        "07",
        "code does not check the row again against the stored sentence: the file's word stands",
        _C,
        "        limit = ai_requirements.limit_from_draft(draft, sentence)\n",
        "        limit = {\n"
        '            "operator": draft["operator"],\n'
        '            "raw_value": draft["value"],\n'
        '            "raw_unit": draft["unit"],\n'
        '            "value": float(draft["value"]),\n'
        '            "unit": draft["unit"],\n'
        '            "field": name,\n'
        '            "subject": name,\n'
        '            "condition": None,\n'
        "        }\n",
        "refused_by_code",
    ),
    _m(
        "08",
        "the converter's rule wins over an AI clause-check draft for the same sentence",
        _C,
        "        **converter_rules(\n"
        "            standard_document_id,\n"
        "            equipment_type,\n"
        "            allowed_document_ids=allowed_document_ids,\n"
        "        ),\n"
        "        **ai_requirements.auto_use_rules(\n"
        "            standard_document_id, allowed_document_ids=allowed_document_ids\n"
        "        ),\n",
        "        **ai_requirements.auto_use_rules(\n"
        "            standard_document_id, allowed_document_ids=allowed_document_ids\n"
        "        ),\n"
        "        **converter_rules(\n"
        "            standard_document_id,\n"
        "            equipment_type,\n"
        "            allowed_document_ids=allowed_document_ids,\n"
        "        ),\n",
        "draft_for_the_same_sentence_wins",
    ),
    _m(
        "09",
        "the review reads an unproven row of the draft file",
        _C,
        '                e.get("status") == "verified"\n                and (\n',
        '                e.get("status") is not None\n                and (\n',
        "verified_yes_row",
    ),
    _m(
        "10",
        "the review reads a depends row of the draft file",
        _C,
        '                    e.get("applies") == "yes"\n                    # v2 (order 286.1)',
        '                    e.get("applies") in ("yes", "depends")\n                    # v2 (order 286.1)',
        "verified_yes_row",
    ),
    _m(
        "11",
        "a scope written after the limit is read as an unconditional limit by the review",
        _C,
        "    if not standards_converter.limit_closes_sentence(\n"
        "        sentence,\n"
        '        entry.get("quote") or "",\n'
        '        entry.get("limit") or "",\n'
        '        entry.get("unit") or "",\n'
        "    ):\n"
        "        return None\n",
        "",
        "scope_written_after_the_limit",
    ),
)
