"""The measured score of a paper KIND, shown beside a general review (order 14, piece G).

Owner's rule (18 Nov 2026): a kind below 7 of 10 still goes live if it beats the old engine, with its real score shown on the
screen as "below target". This module only READS `reference/general_review_measured.json` (filled from the score files by the
lead) and words it. No model, no network, no database, no number made up here.

Honesty: a kind with no measured number says "has not been measured yet", never a score; the score is always stated with its
denominator ("of 10"); a number that is not a real score between 0 and the denominator counts as not measured; a missing kind
renders as nothing (None). The verdict compares two numbers in code; no AI opinion is involved.
"""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TABLE_PATH = Path(__file__).parent / "reference" / "general_review_measured.json"

AT_OR_ABOVE = "at or above target"
BELOW = "below target"
NOT_MEASURED = "not measured"
VERDICTS = (AT_OR_ABOVE, BELOW, NOT_MEASURED)

#: The owner's limit on false alarms: at most 1 wrong comment in 10 (a strict reader's KEEP / WEAK / WRONG read of the real sheet).
FALSE_ALARM_TARGET_PERCENT = 10


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        data = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.info("measured scores not read (%s)", type(exc).__name__)
        return {}
    return data if isinstance(data, dict) else {}


def _word(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _number(value: Any, top: float) -> float | None:
    """A real score only: a number (not a bool) from 0 to `top`; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= top else None


def _row(kind: str, equipment_type: str) -> tuple[dict | None, str]:
    """(the row, how it was found): "exact" an equipment-type row of that name, "family" the row named by the LAST WORD of the type
    ("centrifugal pump" -> the "pump" row; the taxonomy names a type by its family), "kind" the kind's own row, "" no row.

    An equipment type with its own measured number wins; a family row is used only when it holds a number; a type with neither
    falls back to the kind's row. The sentence says which row it used whenever it was not the exact one (a guess is shown as one)."""
    kinds = _table().get("kinds")
    if not isinstance(kinds, dict):
        return None, ""
    base = next(
        (v for k, v in kinds.items() if _word(k) == kind and isinstance(v, dict)), None
    )
    if base is None:
        return None, ""
    types = base.get("equipment_types")
    if equipment_type and isinstance(types, dict):
        family = equipment_type.rsplit(" ", 1)[-1]
        for how, wanted in (("exact", equipment_type), ("family", family)):
            for name, row in types.items():
                if (
                    _word(name) == wanted
                    and isinstance(row, dict)
                    and row.get("found_mean") is not None
                ):
                    return row, how
    return base, "kind"


def _fmt(number: float) -> str:
    """One decimal, NEVER rounded up (6.96 -> "6.9"): a score is never shown above what was measured."""
    return f"{math.floor(round(number * 10, 6)) / 10:.1f}"


def _count(value: Any) -> int | None:
    """A whole number (not a bool) of 0 or more, else None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def false_alarm(row: dict | None) -> dict | None:
    """The share of comments a strict reader judged wrong, from the row's `false_alarm_wrong` and `false_alarm_of`, or None.

    Set only when BOTH counts are real whole numbers with `of` above 0 and `wrong` not above `of`: a percentage is never made up
    without its "N of M". The percentage is rounded UP to a whole number (a wrong share is never shown lower than measured)."""
    wrong, of = (
        _count((row or {}).get("false_alarm_wrong")),
        _count((row or {}).get("false_alarm_of")),
    )
    if wrong is None or not of or wrong > of:
        return None
    percent = math.ceil(round(wrong * 100 / of, 6))
    return {
        "wrong": wrong,
        "of": of,
        "percent": percent,
        "target_percent": FALSE_ALARM_TARGET_PERCENT,
        "within_target": wrong * 100 <= FALSE_ALARM_TARGET_PERCENT * of,
        "sentence": f"A strict reader judged {wrong} of {of} comments wrong across those test copies ({percent}%; target {FALSE_ALARM_TARGET_PERCENT}% or less).",
    }


def _copies_words(row: dict | None) -> str:
    """ "2 planted test copies" when the row says how many, else "planted test copies": the score is of test copies, never of this paper."""
    n = _count((row or {}).get("copies"))
    return (
        f"{n} planted test cop{'y' if n == 1 else 'ies'}"
        if n
        else "planted test copies"
    )


def _when_words(row: dict | None) -> str:
    """ " (measured 18 Nov 2026, version 71152b91)" from the row's own date and code head, so an old number says it is old."""
    on, head = (
        str((row or {}).get("measured_on") or "").strip(),
        str((row or {}).get("code_head") or "").strip(),
    )
    if not on and not head:
        return ""
    return (
        " ("
        + ", ".join(
            x
            for x in (f"measured {on}" if on else "", f"version {head}" if head else "")
            if x
        )
        + ")"
    )


def round_note() -> str | None:
    """The table's own line about the latest round ("Update 6 round cut short: 3 of 5 kinds measured."), or None. Each kind states its own
    date and version; this line says the newest round did not reach every kind, so an older number beside a newer one is not a mistake."""
    note = str(_table().get("round_note") or "").strip().rstrip(".")
    return f"{note[0].upper()}{note[1:]}." if note else None


def _not_measured(label: str, target) -> dict:
    return {
        "kind_label": label,
        "found": None,
        "target": target,
        "verdict": NOT_MEASURED,
        "sentence": "This kind has not been measured on test copies yet.",
    }


def for_run(identity: dict | None) -> dict | None:
    """What a run's page and file say about the measured score of its kind, or None when the run names no kind."""
    if not isinstance(identity, dict):
        return None
    # a paper not placed by its kind: "not yet scored for this kind" (L3)
    from . import document_groups

    if (unscored := document_groups.not_scored(identity)) is not None:
        return unscored
    kind = _word(identity.get("kind"))
    if not kind:
        return None
    equipment_type = _word(identity.get("equipment_type"))
    row, how = _row(kind, equipment_type)
    label = _word((row or {}).get("label")) or kind
    top = _number(_table().get("out_of"), 1000)
    target = _number(_table().get("target"), top) if top else None
    if (
        not top or not target
    ):  # a denominator or target missing or 0: not measured, never a silent default
        return _not_measured(label, target or None)
    found = _number((row or {}).get("found_mean"), top)
    if found is None:
        return _not_measured(label, target)
    verdict = AT_OR_ABOVE if found >= target else BELOW
    sentence = (
        f"Measured on {_copies_words(row)} of this kind{_when_words(row)}: {_fmt(found)} of {_fmt(top).rstrip('0').rstrip('.')} "
        f"mistakes found (target {_fmt(target).rstrip('0').rstrip('.')}): {verdict}."
    )
    old = _number((row or {}).get("old_engine_mean"), top)
    if old is not None:
        sentence += f" The earlier version found {_fmt(old)} of {_fmt(top).rstrip('0').rstrip('.')}."
    if equipment_type and how in ("family", "kind"):
        used = f"{label}" if how == "family" else f"the {label} row for every type"
        sentence += (
            f" Row used: {used}; this paper's equipment type is {equipment_type}"
            + (", which has no number of its own." if how == "kind" else ".")
        )
    wrong = false_alarm(row)
    if wrong is not None:
        sentence += " " + wrong["sentence"]
    note = round_note()
    if note:
        sentence += " " + note
    return {
        "kind_label": label,
        "found": found,
        "target": target,
        "verdict": verdict,
        "sentence": sentence,
        "false_alarm": wrong,
    }


def for_local_run(identity: dict | None, models: list[str]) -> dict:
    """What a run made on the LOCAL model says in place of its kind's score: the measured scores are of Claude reviews, so they do
    not apply; `aim_review_gate.LOCAL_NOT_SCORED` until local runs are scored (planner 25 Nov 2026 22:35). `models`: the model names
    the local engine itself reported in the run's calls (never the setting); none recorded is said so."""
    from . import aim_review_gate, document_groups

    kind = _word((identity or {}).get("kind"))
    named = ", ".join(models) if models else "its name was not recorded"
    return {
        "kind_label": kind or None,
        "found": None,
        "target": None,
        "verdict": NOT_MEASURED,
        "sentence": (
            f"Reviewed on the local model on this computer ({named}): {aim_review_gate.LOCAL_NOT_SCORED}. "
            "The scores of this kind were measured on Claude reviews and do not apply to it."
        )
        + "".join(
            " " + x["sentence"] for x in [document_groups.not_scored(identity)] if x
        ),
    }
