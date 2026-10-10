"""The datasheet review playbook as a data file (W5b-04, #528).

`reference/datasheet_playbook.json` holds the checks that used to be literals
in code: the derivation rules (`rule_eval.KNOWN_RULES`: which datasheet fields
a "design pressure from operating pressure" rule reads) and the closed
categorical families (`field_links`: the flange classes, radiography levels
and which fields answer each family). Engineers edit the file; the code reads
it. The self-checks were already data (`datasheet_checks.json`), and so were
the field aliases (`field_synonyms.json`).

A file that is missing, not JSON or the wrong shape RAISES
`DatasheetPlaybookError` naming the file and the problem when the module is
imported. The review then does not start; it never runs with an empty
playbook and reports nothing (a silent pass).
"""
from __future__ import annotations

import json
from pathlib import Path

FORMAT = "datasheet-playbook/1"
PATH = Path(__file__).resolve().parent / "reference" / "datasheet_playbook.json"


class DatasheetPlaybookError(ValueError):
    """The datasheet playbook file cannot be used; the message says why."""


def _words(value, where: str) -> list[str]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(v, str) and v.strip() for v in value)):
        raise DatasheetPlaybookError(f"{where} must be a non-empty list of words")
    return [v.strip().lower() for v in value]


def parse(data: object, where: str = "datasheet playbook") -> dict:
    """The validated playbook: {derivation_rules, flange_classes,
    radiography_levels, family_fields}. Anything else raises."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise DatasheetPlaybookError(f"{where}: must be a JSON object with format {FORMAT!r}")
    rules = data.get("derivation_rules")
    if not isinstance(rules, list) or not rules:
        raise DatasheetPlaybookError(f"{where}: derivation_rules must be a non-empty list")
    derivation = []
    for i, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict) or not str(rule.get("output") or "").strip():
            raise DatasheetPlaybookError(f"{where}: derivation rule {i} has no output")
        derivation.append({
            "output": rule["output"].strip().lower(),
            "input_names": _words(rule.get("input_names"), f"{where}: derivation rule {i} input_names"),
            "requirement_words": tuple(_words(rule.get("requirement_words"),
                                              f"{where}: derivation rule {i} requirement_words")),
        })
    cat = data.get("categorical")
    if not isinstance(cat, dict):
        raise DatasheetPlaybookError(f"{where}: categorical must be an object")
    classes = cat.get("flange_classes")
    if (not isinstance(classes, list) or not classes
            or not all(isinstance(c, int) and not isinstance(c, bool) and c > 0 for c in classes)):
        raise DatasheetPlaybookError(f"{where}: flange_classes must be a non-empty list of positive whole numbers")
    levels = cat.get("radiography_levels")
    if (not isinstance(levels, dict) or not levels
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in levels.values())):
        raise DatasheetPlaybookError(f"{where}: radiography_levels must map words to whole numbers")
    families = cat.get("family_fields")
    if not isinstance(families, dict) or not families:
        raise DatasheetPlaybookError(f"{where}: family_fields must be a non-empty object")
    return {
        "derivation_rules": tuple(derivation),
        "flange_classes": tuple(sorted(classes)),
        "radiography_levels": {str(k).lower(): v for k, v in levels.items()},
        "family_fields": {str(k): frozenset(_words(v, f"{where}: family_fields.{k}"))
                          for k, v in families.items()},
    }


def load(path: str | Path | None = None) -> dict:
    """Read and validate the playbook file. Missing or unreadable: raises."""
    target = Path(path) if path is not None else PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DatasheetPlaybookError(f"{target.name}: the datasheet playbook file is missing") from exc
    except (OSError, ValueError) as exc:
        raise DatasheetPlaybookError(f"{target.name}: cannot be read as JSON ({type(exc).__name__})") from exc
    return parse(data, target.name)


#: Read once, when the review modules are imported.
PLAYBOOK = load()
