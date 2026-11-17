"""FTU-17: a "does not apply" stands only with its reason and its PROOF (owner's decision on the first-time-user test of live update 17).

The proof is two facts, each FOUND BY CODE: the rule's condition (words code found in the rule book) and the paper's fact (words code
found on the paper), with the reason, stored by code under `NOT_APPLICABLE_PROOF`. Without it, the reader's own "not applicable" is a
question for the engineer (`agent_review_wording.classify` and `read_time`). The AI review's context check runs before a Fail only and
stores no such proof, so today every reader's "not applicable" is a question. Pure: no model, no network."""

from __future__ import annotations

from collections.abc import Mapping

NOT_APPLICABLE_PROOF = "not_applicable_proof"
NOT_APPLICABLE_WHY = "the rule does not apply to this paper"
UNPROVEN_WHY = (
    "the AI reader judged the rule not applicable to this paper, but code holds no proof of it (the rule's condition and the "
    "paper's fact, each found by code); the engineer checks whether it applies"
)
ACTION = "Engineer to check whether the rule applies to this paper: the AI reader judged it does not, without proof."

#: Owner's decision on PR #1872: these lines are NOT the main questions. They are their own short section, grouped, each ticked to
#: confirm (one engineer decision per line, who and when; "Confirm all" is the same tick on each; a tick can be undone), counted apart,
#: never on the contractor copy. Until ticked a line is still to decide.
TITLE = "AI thinks these do not apply, tick to confirm"
SHEET = "AI thinks does not apply"
CONFIRMED = "Does not apply (confirmed by the engineer)"
OPEN = "Not confirmed yet"
TILE = "na_to_confirm"


def count_line(n: int, confirmed: int) -> str:
    """The ONE count sentence of the group (sheet 1 of the team file, the group's sheet, the page): N, K confirmed, M open."""
    return f"{n} points the AI thinks do not apply, to confirm: {confirmed} confirmed, {n - confirmed} open."


def proof(line: Mapping) -> dict | None:
    """The proof a "does not apply" carries: its reason, the rule's condition and the paper's fact, with code's own finding of each
    (`condition_found`, `paper_found` exactly True); None when any part is missing or was not found by code."""
    got = line.get(NOT_APPLICABLE_PROOF)
    if not isinstance(got, Mapping):
        return None
    words = {
        k: " ".join(str(got.get(k) or "").split())
        for k in ("reason", "condition", "paper_fact")
    }
    if (
        not all(words.values())
        or got.get("condition_found") is not True
        or got.get("paper_found") is not True
    ):
        return None
    return {
        **words,
        "condition_page": got.get("condition_page"),
        "paper_page": got.get("paper_page"),
    }


def reason(found: Mapping | None) -> str:
    """The reason a not-applicable line carries: the proof's own reason, or that there is no proof."""
    return f"{NOT_APPLICABLE_WHY}: {found['reason']}" if found else UNPROVEN_WHY
