"""A value printed under a % label with a fraction-sized number is not decided (#1512).

"0.30 %" on a percent card (overpressure at most 21 % of the set pressure,
built-up back pressure at most 10 %) may be 0.30 % or the fraction 0.30 = 30 %.
Read as 0.30 % it passes a limit that 30 % fails: a possible wrong approval. The
number and the label disagree in kind, so the engineer decides.

Local only: no model, no socket.
"""

from __future__ import annotations

from . import claims
from .config import settings


def doubt(fact: dict, rule: dict | None = None, is_percent: bool = True) -> str | None:
    """Why `fact` (printed as a percent) cannot be decided, or None. Off by
    default (PERCENT_KIND_CHECK_ENABLED). `rule` None means any percent use; a
    rule counts only when it is a percent rule (stated as a percent, a
    percentage of a role, or in %)."""
    if not (settings.percent_kind_check_enabled and is_percent):
        return None
    if rule is not None and not (
        rule.get("stated_as_percent")
        or rule.get("percent_of_role")
        or (rule.get("unit") or "").strip() == "%"
    ):
        return None
    number = claims.parse_value(str(fact.get("raw_value")))
    if number is None or not 0 < abs(number) <= 1:
        return None
    printed = str(fact.get("raw_value")).strip()
    return (
        f"the sheet prints {printed} with a % label - a fraction or a percent? "
        f"engineer to confirm"
    )
