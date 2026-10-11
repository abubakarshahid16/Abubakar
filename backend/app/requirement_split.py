"""Every requirement in a run's scope is in ONE of three honest groups (#678).

  * CHECKED: the review compared it (met, not met, or needs an engineer).
  * APPLIES BUT NOT CHECKED: it applies to this submittal, and the review could
    not check it (a standards-table value with no field to answer it, text that
    could not be read reliably). Each has its reason.
  * DOES NOT APPLY: it is about other equipment than this submittal. Each has
    its reason.

"6364 of 6891 (92%) were not compared" mixed the last two, and counted stored
duplicates. An engineer cannot act on one blended number. Now:

  * a requirement counts ONCE: the same standard and the same requirement text
    is one requirement, however many stored rows repeat it (#669, #673);
  * a requirement in two groups (a repeat that was checked in one row and
    skipped in another) counts in the strongest: checked, then applies-but-not-
    checked, then does-not-apply;
  * the approval rule and the unchecked share use ONLY "applies but not
    checked", out of the requirements that apply (checked + not checked);
    requirements that do not apply are shown but never count against a run;
  * a count with no stored reason says "no reason recorded", never a guess.

Pure functions over dicts. No database, no network.
"""
from __future__ import annotations

from collections import Counter

from . import table_gate

CHECKED = "checked"
APPLIES_NOT_CHECKED = "applies_not_checked"
DOES_NOT_APPLY = "does_not_apply"
#: #746: NOT USED - the equipment type's review checklist governs this
#: requirement's standard, so the review checked the checklist item instead of
#: the library rule one by one. Shown with its count; never in the unchecked
#: share or the approval rule (planner decision on #746).
NOT_USED = "not_used"
_ORDER = (CHECKED, APPLIES_NOT_CHECKED, DOES_NOT_APPLY, NOT_USED)

NO_REASON = "no reason recorded"

#: Reason codes the gates store, in plain words. A code not listed here is
#: shown as "no reason recorded" rather than guessed at.
REASON_TEXT = {
    "row_label_not_on_sheet": "neither the row label nor the column name matches a field on this submittal",
    "column_not_on_sheet": "the column name matches no field on this submittal",
    "other_row_matched": "another row of the same table matched, so the column was not used for this row",
    "no_label": "the table value has no row label or column name to match",
    "text_quality": "its text could not be read reliably",
}


def requirement_key(requirement: dict) -> str:
    """Standard + normalised requirement text. A requirement with no text is
    keyed by its id (or object), so two different unreadable rows never merge."""
    words = " ".join(table_gate.tokens(requirement.get("requirement_text")))
    if not words:
        return f"id:{requirement.get('id') or id(requirement)}"
    return f"{requirement.get('standard_document_id') or ''}\x00{words}"


def reason_words(code: str | None, detail: str | None = None) -> str:
    """The sentence for a stored reason. `detail` is a reason the gate wrote in
    words (does-not-apply: "about relief valves, this submittal is a pump")."""
    if detail and detail.strip():
        return detail.strip().rstrip(".")
    return REASON_TEXT.get(code or "", NO_REASON)


def build(checked: list[dict], not_checked: list[dict], not_applied: list[dict],
          not_used: list[dict] | None = None) -> dict:
    """`checked`: requirement dicts. `not_checked` / `not_applied`: items
    {"requirement": dict, "code": str|None, "detail": str|None}.

    Returns the counts, the reasons behind each of the two groups that have
    one, how many stored repeats were ignored, and the share of the
    requirements that apply that were not checked (None when none apply)."""
    placed: dict[str, tuple[str, str]] = {}
    seen_rows = 0

    def put(group: str, key: str, reason: str) -> None:
        nonlocal seen_rows
        seen_rows += 1
        current = placed.get(key)
        if current is None or _ORDER.index(group) < _ORDER.index(current[0]):
            placed[key] = (group, reason)

    for r in checked:
        put(CHECKED, requirement_key(r), "")
    for item in not_checked:
        put(APPLIES_NOT_CHECKED, requirement_key(item["requirement"]),
            reason_words(item.get("code"), item.get("detail")))
    for item in not_applied:
        put(DOES_NOT_APPLY, requirement_key(item["requirement"]),
            reason_words(item.get("code"), item.get("detail")))
    for item in not_used or []:
        put(NOT_USED, requirement_key(item["requirement"]),
            reason_words(item.get("code"), item.get("detail")))

    counts = Counter(group for group, _ in placed.values())
    reasons: dict[str, Counter] = {APPLIES_NOT_CHECKED: Counter(), DOES_NOT_APPLY: Counter()}
    for group, reason in placed.values():
        if group in reasons:
            reasons[group][reason] += 1

    def listed(group: str) -> list[dict]:
        return [{"reason": text, "count": n}
                for text, n in sorted(reasons[group].items(), key=lambda kv: (-kv[1], kv[0]))]

    n_checked, n_not, n_na = counts[CHECKED], counts[APPLIES_NOT_CHECKED], counts[DOES_NOT_APPLY]
    n_unused = counts[NOT_USED]
    applies = n_checked + n_not
    return {
        "checked": n_checked,
        "applies_not_checked": n_not,
        "does_not_apply": n_na,
        "not_used": n_unused,
        "total": n_checked + n_not + n_na + n_unused,
        "applies_not_checked_reasons": listed(APPLIES_NOT_CHECKED),
        "does_not_apply_reasons": listed(DOES_NOT_APPLY),
        "repeats_ignored": seen_rows - len(placed),
        "unchecked_share": (n_not / applies) if applies else None,
    }


def from_counts(counts: dict | None) -> dict | None:
    """A split for a run stored BEFORE this existed: only its three counts are
    known, so each group's reason is "no reason recorded" and nothing is
    guessed. None when the run has no counts at all."""
    if not counts:
        return None
    n_checked = int(counts.get("checked") or 0)
    n_not = int(counts.get("not_compared") or 0)
    n_na = int(counts.get("not_applied") or 0)
    applies = n_checked + n_not
    return {
        "checked": n_checked, "applies_not_checked": n_not, "does_not_apply": n_na,
        "total": n_checked + n_not + n_na,
        "applies_not_checked_reasons": [{"reason": NO_REASON, "count": n_not}] if n_not else [],
        "does_not_apply_reasons": [{"reason": NO_REASON, "count": n_na}] if n_na else [],
        "repeats_ignored": None,
        "unchecked_share": (n_not / applies) if applies else None,
    }
