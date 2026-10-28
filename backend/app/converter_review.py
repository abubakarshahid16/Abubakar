"""The review reads the standards converter's drafts (orders 270.3, 274.1).

The converter (`standards_converter`) writes one DRAFT per standard, offline, outside the repository. This module is
the READING side, and it is empty unless the owner's switch `standards_converter_dir` names that folder:

  * `reviewed_entries` - the VERIFIED rows whose answer was "yes" (never unproven, no, depends), which
    `rule_roles.reviewed_names` uses as a field mapping for the numeric rules of the standard;
  * `converter_rules` / `rules_with_drafts` - a clause SENTENCE (requirement_type 'statement') the converter proved,
    as a rule in its sentence's own place, on the road of the AI clause-check drafts
    (`ai_requirements.auto_use_rules`, `rule_auto_use_enabled`): `rule_trust` decides what its verdict may say, and
    an unproven family never decides.

Code checks every row again against the sentence stored now. Nothing is written; the draft file is never changed;
nothing here calls a model.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import rule_roles, standards_converter


def reviewed_entries(files: list[Path] | None = None) -> list[tuple[str, dict]]:
    """[(equipment type, entry)] of the VERIFIED rows whose answer was 'yes', from the converter's drafts
    in `settings.standards_converter_dir` (or the given files). Nothing when the setting is empty."""
    from .config import settings

    if files is None:
        folder = (settings.standards_converter_dir or "").strip()
        if not folder or not Path(folder).is_dir():
            return []
        files = sorted(Path(folder).glob("*.json"))
    out: list[tuple[str, dict]] = []
    for f in files:
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            not isinstance(data, dict)
            or data.get("converter") is not True
            or data.get("status") != standards_converter.STATUS
        ):
            continue
        for e in data.get("entries", []):
            if (
                e.get("status") == "verified"
                and e.get("applies") == "yes"
                and e.get("field")
                and e.get("text_sha256")
            ):
                out.append(
                    (
                        data["equipment_type"],
                        {
                            **e,
                            "standard": data.get("standard"),
                            "model": data.get("model"),
                        },
                    )
                )
    return out


def converter_rules(
    standard_document_id: str,
    equipment_type: str | None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, dict]:
    """The standard's SENTENCE rules (requirement_type 'statement') that the converter proved, as rules the
    review may compare with, keyed by the sentence row each stands on - the shape and the road of
    `ai_requirements.auto_use_rules`: the rule takes its sentence's place, same id, so the scope ledger still
    ends every requirement in exactly one state, and `rule_trust.label_finding` decides what its verdict may say
    (an unproven family never decides: NEEDS_ENGINEER_REVIEW with the arithmetic shown). The caller lets a
    draft of `auto_use_rules` for the same sentence win.

    EMPTY unless the owner's switch `rule_auto_use_enabled` is on, `standards_converter_dir` names a folder, the
    standard is in the reader's scope and the review's equipment type is the type the draft was made for. A row
    is used only if it is verified with applies = "yes" (never unproven, no, depends), its sentence still hashes
    the same, its standard is this one, and CODE CHECKS IT AGAIN against the sentence stored now
    (`ai_requirements.limit_from_draft`: the quote is in the sentence, the number and unit are in the quote, the
    operator does not point the other way, a sentence that holds only under a condition is refused). Nothing is
    written; the draft file is never changed."""
    from . import ai_requirements, standard_ids
    from .config import settings
    from .db import connect

    if (
        not equipment_type
        or not settings.rule_auto_use_enabled
        or standard_document_id not in allowed_document_ids
    ):
        return {}
    entries = [
        (file_type, e)
        for file_type, e in reviewed_entries()
        if rule_roles.same_type(file_type, equipment_type)
    ]
    conn = connect()
    doc = conn.execute(
        "SELECT d.filename, c.document_number FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
        (standard_document_id,),
    ).fetchone()
    if not entries or doc is None:
        return {}
    label = doc["document_number"] or doc["filename"]
    rows: dict[str, list[tuple]] = {}
    for file_type, e in entries:
        if standard_ids.same_standard(e.get("standard"), label):
            rows.setdefault(e["text_sha256"], []).append(
                (file_type, _what_it_says(e), e)
            )
    # One sentence, two rows that say different things (the same boilerplate in two drafts): used by neither,
    # whatever the file order (cloud-3 on #1412).
    by_hash = {
        key: (group[0][0], group[0][2])
        for key, group in rows.items()
        if all(g[:2] == group[0][:2] for g in group)
    }
    out: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT id, source_text, requirement_text FROM standard_requirements"
        " WHERE standard_document_id = ? AND requirement_type = ? AND superseded_at IS NULL ORDER BY id",
        (standard_document_id, ai_requirements.STATEMENT),
    ):
        digest = rule_roles.text_hash(row["requirement_text"])
        if digest in by_hash:
            rule = _rule_from(row, digest, *by_hash[digest])
            if rule is not None:
                out[row["id"]] = rule
    return out


def _what_it_says(entry: dict) -> tuple:
    """The parts of a row that decide a comparison: two rows for one sentence agree only if all are equal."""
    return tuple(
        entry.get(k)
        for k in ("field", "applies", "comparator", "limit", "unit", "quote")
    )


def _rule_from(row, digest: str, file_type: str, entry: dict) -> dict | None:
    """One proven row as the review's rule, re-checked by code against the sentence now stored; None when
    the field is not on the type's form or code refuses it."""
    from . import ai_requirements

    _dictionary, roles, _families = rule_roles.form(file_type)
    name = next((n for n, role in roles.items() if role == entry["field"]), None)
    if name is None:
        return None
    draft = {
        "field": name,
        "operator": entry.get("comparator"),
        "value": entry.get("limit"),
        "unit": entry.get("unit") or None,
        "condition": None,
        "quote": entry.get("quote"),
    }
    sentence = row["source_text"] or row["requirement_text"] or ""
    # A scope AFTER the limit ("... 25 bar for services other than sour service") is not caught by
    # `limit_from_draft`, which reads leading conditions (s3, #1412): it must close the sentence.
    if not standards_converter.limit_closes_sentence(
        sentence,
        entry.get("quote") or "",
        entry.get("limit") or "",
        entry.get("unit") or "",
    ):
        return None
    try:
        limit = ai_requirements.limit_from_draft(draft, sentence)
    except ai_requirements.DraftError:
        return None
    return {
        "requirement_type": "numeric_limit",
        **limit,
        # The AI's rule, never confirmed by a person: `rule_trust` labels it.
        "extraction_method": "model",
        "model": entry.get("model"),
        "confirmed_by": None,
        "confirmed_at": None,
        "rule_draft_id": f"converter:{digest[:16]}",
        "quote": entry.get("quote"),
    }


def rules_with_drafts(
    standard_document_id: str,
    submittal_document_id: str,
    allowed_document_ids: frozenset[str],
) -> dict[str, dict]:
    """What a review compares an undecided clause sentence with (the one call `comparison` makes): the AI
    clause-check drafts of `ai_requirements.auto_use_rules`, and where a sentence has no draft the check the
    converter proved for it (`converter_rules`, for the equipment type this sheet was classified as). A draft
    for the same sentence wins. Empty with the owner's switch off."""
    from . import ai_requirements, classification

    equipment_type = (classification.of_document(submittal_document_id) or {}).get(
        "equipment_type"
    )
    return {
        **converter_rules(
            standard_document_id,
            equipment_type,
            allowed_document_ids=allowed_document_ids,
        ),
        **ai_requirements.auto_use_rules(
            standard_document_id, allowed_document_ids=allowed_document_ids
        ),
    }
