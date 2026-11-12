"""The Claude lane's STANDING refusal: the account has no credit, or its usage limit is reached (U5).

When every call would be refused, the review page must not promise Claude. The spend ledger already records each refused call as a
closed word (`claude_spend.failure_word`: `...:no_credit`, `...:usage_limit`); this module reads the newest one back. Counts and a
closed word only: never an API message, a prompt or a key. Read only; it calls nothing and writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

NO_CREDIT = "no_credit"
NO_CREDIT_WORDS = (
    "the Claude account has no credit (the owner tops it up in the Anthropic console)"
)
USAGE_LIMIT = "usage_limit"
USAGE_LIMIT_WORDS = "the Claude account's usage limit is reached"
#: How long a standing refusal is believed without a newer call: a limit may reset, and a screen that says "not available" stops the
#: calls that would show it has.
STANDING_REFUSAL_HOURS = 3


def mentions_limit(error: dict) -> bool:
    """True when the API's error body says the usage limit was reached. Only TESTED, never stored (the message is free text)."""
    return "usage limit" in str(error.get("message") or "").lower()


def _word(why: str) -> str | None:
    for word in (NO_CREDIT, USAGE_LIMIT):
        if why.endswith(":" + word):
            return word
    return None


def standing_refusal(now: datetime | None = None) -> dict | None:
    """The NEWEST ledger entry that records a refusal for no credit or a reached usage limit, when no call has gone through since and it is
    not older than `STANDING_REFUSAL_HOURS`; else None (nothing is known: not "available"). `{"cause", "words", "at"}`."""
    from . import claude_spend

    now = now or datetime.now(UTC)
    found: dict | None = None
    for e in claude_spend._raw_lines():
        why = str(e.get("finish_reason") or e.get("reason") or "")
        word = _word(why)
        if word and (e.get("releases") or e.get("settles") or "finish_reason" in e):
            words = NO_CREDIT_WORDS if word == NO_CREDIT else USAGE_LIMIT_WORDS
            found = {"cause": word, "at": str(e.get("at") or ""), "words": words}
        elif _went_through(e, why):
            found = None
    if found is None:
        return None
    try:
        at = datetime.fromisoformat(found["at"])
    except ValueError:
        return None
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    age = (now - at).total_seconds()
    return found if age <= STANDING_REFUSAL_HOURS * 3600 else None


def _went_through(entry: dict, why: str) -> bool:
    """A settled call that carried tokens: the lane works."""
    return bool(
        "finish_reason" in entry
        and not why.startswith(("failed:", "unbilled:"))
        and not entry.get("corrupt")
        and not entry.get("cached")
        and entry.get("input_tokens")
    )
