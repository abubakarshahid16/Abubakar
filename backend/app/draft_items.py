"""Part of #805: a DRAFT checklist item (`"status": "draft (engineer to approve)"`) never decides.

It is read only with `draft_process_items_enabled`. A value not stated is the contractor's gap, as for every
presence check ("Not stated. ... Contractor to provide ..."); a stated value gives no verdict and no stored row;
an item with a `choice` answer stated "yes" is a QUERY for the engineer (sour service: NACE MR0175 / ISO 15156
for materials), never a decision; yes and no together, or neither, is the engineer's to read. Local only: no model,
no network, no database. The statuses are the datasheet checks' own words (one home: `datasheet_checks`).
"""

from __future__ import annotations

from .config import settings

#: The words a draft item's text carries.
MARK = "draft item, engineer to approve"
#: Its stated value gives no verdict (CLAUDE.md rule 4). Not a row: `datasheet_checks.store` writes none.
STATED_NO_VERDICT = "STATED_NO_VERDICT"
_MISSING = "MISSING_INFORMATION"
_PASS = "COMPLIANT"
_QUERY = "NEEDS_ENGINEER_REVIEW"


def is_draft(item: dict) -> bool:
    return str(item.get("status") or "").lower().startswith("draft")


def read(items: list[dict]) -> list[dict]:
    """The items a checklist reads: a draft item only with its switch on."""
    if settings.draft_process_items_enabled:
        return items
    return [item for item in items if not is_draft(item)]


def without_stated(results: list[dict]) -> list[dict]:
    """The results that become rows: a draft item's stated value gives none."""
    return [x for x in results if x["status"] != STATED_NO_VERDICT]


def _fold(text) -> str:
    return " ".join(str(text or "").lower().replace(":", " ").replace("-", " ").split())


def _says(value: str, choices: list[str]) -> tuple[bool, str]:
    """Whether the stated value contains one of the choice words as whole words, and the value with
    those words taken out (so "non sour" is a no, not a no AND a yes for "sour")."""
    folded = f" {_fold(value)} "
    found = False
    for word in sorted(choices, key=len, reverse=True):
        needle = f" {_fold(word)} "
        while needle in folded:
            found = True
            folded = folded.replace(needle, " ", 1)
    return found, folded


def hold(result: dict, item: dict) -> dict:
    """One checklist result of a draft item, held as above. Other items, and a draft item's other
    statuses (an engineer's question, does not apply), are kept as they are."""
    if not is_draft(item):
        return result
    answer = item.get("answer") or {}
    out = {**result, "draft": True, "item_status": item["status"]}
    to_confirm = "; clause to confirm" if item.get("clause_to_confirm") else ""
    out["text"] = f"{result['text']} [{MARK}{to_confirm}]"
    detail = result["detail"]
    if result["status"] == _MISSING:
        out["detail"] = (
            "Not stated. "
            + detail
            + ("" if "provide" in detail else " Contractor to provide the value.")
        )
    elif result["status"] == _PASS:
        no_verdict = f"{detail} Draft item: stated, no verdict."
        if answer.get("kind") != "choice":
            out["status"], out["detail"] = STATED_NO_VERDICT, no_verdict
            return out
        no, rest = _says(str(result.get("value") or ""), answer["no"])
        yes, _ = _says(rest, answer["yes"])
        if yes and not no:
            out["status"] = _QUERY
            out["detail"] = f"{detail} Query for materials: {answer['query_if_yes']}"
        elif no and not yes:
            out["status"], out["detail"] = STATED_NO_VERDICT, no_verdict
        else:
            out["status"] = _QUERY
            both = " or ".join(answer["choices"][:2])
            out["detail"] = f"{detail} It is not clearly {both}: engineer to read it."
    return out
