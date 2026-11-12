"""Is Claude refusing every call right now? (owner, 12 Nov 2026: the account hit its usage limit; "No, local only".)

Read from the spend ledger the app already keeps (`claude_spend`, read only): the most recent call that settled or was released
decides. A release or a failure whose closed word names an account-level rejection (`HTTPStatusError:http_400` with no credit,
`http_402`, `http_403`, `http_429`) within the last day, with no successful call after it, is a STANDING refusal. The engine choice
"Automatic" then plans the review on this computer with one plain sentence (`review_engine`), never a failed review. Nothing is sent,
no key is read, no file is written; counts and closed words only. An unreadable ledger is not a refusal (the lane's own checks
still refuse a call that cannot be made).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)

WORDS = "Claude is not available now, so this review runs on this computer"
WINDOW = timedelta(hours=24)
_REFUSAL = re.compile(r"HTTPStatusError:http_(?:400|402|403|429)\b")


def _when(line: dict) -> datetime | None:
    try:
        got = datetime.fromisoformat(str(line.get("at")))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=UTC)


def standing(now: datetime | None = None) -> bool:
    """True when the newest outcome in the last day is an account-level refusal and no call has succeeded since."""
    from . import claude_spend

    now = now or datetime.now(UTC)
    try:
        lines = claude_spend._raw_lines()
    except (OSError, ValueError) as exc:
        log.warning("claude refusal state: ledger unreadable (%s)", type(exc).__name__)
        return False
    for line in reversed(lines):
        at = _when(line)
        if at is None or now - at > WINDOW:
            continue
        word = str(line.get("reason") or line.get("finish_reason") or "")
        if _REFUSAL.search(word):
            return True
        if (
            line.get("settles")
            and not word.startswith("failed")
            and not line.get("cached")
        ):
            return False  # a call went through after any refusal: Claude answers
    return False
