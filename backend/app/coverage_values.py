"""The footer's one count of values read (#1592 item a), beside the pair of `coverage_pair`:
what the run read from the sheet, and the standard rules tied to a field. Two lanes, stated
apart and never added, each counted once. Words only: the gate and the code do not read it.
Read only. Counts and a checklist's type name only, no document text.
"""

from __future__ import annotations

import sqlite3

from . import coverage_pair as pair
from . import requirement_split, scope_ledger
from .db import connect

#: `comparison.plain_reason` and `_insufficient_reason`: the sentences a run stores about
#: `completeness.fields_answered`; a test holds them to what those functions write.
FOUND_OLD_PLAIN = (
    "Found {answered} of the {required} datasheet value{s} the applicable standards ask"
    " for."
)
FOUND_OLD_TECHNICAL = (
    "{answered:,} of the {required:,} datasheet values the applicable standards'"
    " requirements ask for were found in the fields read from this submittal"
)


def _rules_tied(conn: sqlite3.Connection, run_id: str) -> tuple[int, int]:
    """(rules, rules a field read from the sheet is tied to), EACH RULE ONCE, as the pair
    counts them: `requirement_split.requirement_key`, the rule lane only, a rule that does
    not apply left out. `comparison._required_and_answered` still says what answers a
    rule; it is handed the rule's key, because the stored ids repeat."""
    from .comparison import _required_and_answered

    findings = pair._rows(
        conn,
        "SELECT * FROM review_findings WHERE review_run_id = ?"
        " AND requirement_id IS NOT NULL",
        (run_id,),
    )
    rules = pair._rule_texts(conn, {f["requirement_id"] for f in findings})
    out = requirement_split.DOES_NOT_APPLY
    return _required_and_answered(
        [
            {
                **f,
                "requirement_id": requirement_split.requirement_key(
                    rules[f["requirement_id"]]
                ),
            }
            for f in findings
            if pair._lane(f, rules) == "rule"
            and scope_ledger.group_of(f.get("compliance_status"))[0] != out
        ]
    )


def values_count(
    conn: sqlite3.Connection, run_id: str, outcome: dict | None
) -> dict | None:
    """THE one count behind the footer's "values found" sentence. Two lanes, stated apart
    like the pair's, never added, each counted once:

      checklist  fields read of the fields the equipment type's checklist asks for, each
                 field once (`datasheet_coverage.coverage`). A field read may still defer
                 its value ("by contractor"). None when the run used no checklist.
      rules      `_rules_tied`: the standard rules with a stored row not sent to another
                 document (`rows`), how many a field read from the sheet was tied to
                 (`tied`), and the pair's `applicable` around them.

    The stored `completeness` counts stored ids, so it can repeat a rule and take in one
    that does not apply; it says only whether the run wrote the sentence this replaces.
    The checklist's rows carry no requirement id, so `rules` cannot see a value they read.
    None when the run wrote no such sentence; its stored words then stand."""
    from .comparison import BASIS_REQUIRED_FIELDS

    outcome = outcome or {}
    done = outcome.get("completeness") or {}
    if not done.get("fields_required") or done.get("basis") != BASIS_REQUIRED_FIELDS:
        return None
    split = pair._stated_split(outcome) or {}
    cover = split.get("checklist_coverage")
    named = split.get("checklist") or {}
    applicable = pair._applicable(split or None)
    rows, tied = _rules_tied(conn, run_id)
    return {
        "checklist": None
        if not cover
        else {
            "read": int(cover["read"]),
            "fields": int(cover["fields"]),
            "type": named.get("type"),
        },
        "rules": {
            "tied": tied,
            "rows": rows,
            # a count that does not fit inside what the run states is not printed around it
            "applicable": applicable if (applicable or 0) >= rows else None,
        },
    }


def values_sentence(
    conn: sqlite3.Connection, run_id: str, outcome: dict | None
) -> str | None:
    """The count in words, with its boundary and denominators."""
    count = values_count(conn, run_id, outcome)
    if count is None:
        return None
    rules = count["rules"]
    around = (
        f"Of the {rules['applicable']} standard rules that apply, "
        if rules["applicable"] is not None
        else "Of the standard rules, "
    )
    said = (
        f"{around}{rules['rows']} looked for a field on this sheet and a field was tied"
        f" to {rules['tied']} of them."
        if rules["rows"]
        else f"{around}none looked for a field on this sheet."
    )
    listed = count["checklist"]
    if listed is None:
        return said
    kind = f"{listed['type']} " if listed["type"] else ""
    return (
        f"Read from this datasheet: {listed['read']} of the {listed['fields']} fields the"
        f" {kind}checklist asks for, each field once (a field read may still defer its"
        f" value). {said} The checklist and the rules are counted apart."
    )


def found_words(text: str, outcome: dict | None, run_id: str) -> str:
    """The stored "found" sentence replaced by `values_sentence`. Words only."""
    said = values_sentence(connect(), run_id, outcome)
    if said is None:
        return text
    done = (outcome or {}).get("completeness") or {}
    count = {
        "answered": done.get("fields_answered") or 0,
        "required": done.get("fields_required") or 0,
    }
    plain = FOUND_OLD_PLAIN.format(s="" if count["required"] == 1 else "s", **count)
    technical = FOUND_OLD_TECHNICAL.format(**count)
    return text.replace(plain, said).replace(technical, said.rstrip("."))
