"""Which review method the ONE Review button runs, and the fixed sentences of the general review (owner's ONE ORDER, 18 Nov 2026).

THE ONE WAY BACK is `REVIEW_OLD_ENGINE_ENABLED` (`settings.review_old_engine_enabled`, default False):
  False -> the button runs the general review (`app.aim_review`, job stage `aim_review`); the old engine (rule check + old AI
           reviewer) queues nothing and its screens are hidden.
  True  -> everything is exactly as before the general review; it is not offered.

Every piece reads the switch and the knobs ONLY through this module. It opens no lane: the general review runs on Claude only when
the AI reviewer's lane is open as today (`AGENT_REVIEW_ENABLED`, the provider, both egress flags, a key), decided elsewhere.
Each sentence below has ONE home: this file (a grep test says so).
"""

from __future__ import annotations

from .config import settings

GENERAL = "general"
EARLIER = "earlier"

#: Every sheet of the general review's file, the page header and each row carry these words.
AI_MARK = "AI, to be checked"
#: Local only: the general review needs Claude; nothing is sent and nothing is reviewed.
LOCAL_NOT_AVAILABLE = (
    "The general review needs Claude. It does not run on the local model yet, so with Local only nothing is "
    "sent and nothing is reviewed. Choose Automatic or Claude to review this paper."
)
#: The contractor copy of a general review is refused (409) with these words.
NO_CONTRACTOR_COPY_WORDS = "No contractor copy yet: this review is not signed off. This file is for the team: AI, to be checked."
#: The rule-check part of the plan while the general review is on.
OLD_ENGINE_OFF_WORDS = "the earlier rule check is switched off"
#: The label of a review made by the old engine, in history and on the page.
EARLIER_VERSION = "Earlier version"

#: The per-run cap of CLAUDE.md rule 1; the run's own meter is never set above it.
RUN_CAP_USD = 15.0


def answered_check_on() -> bool:
    """True: the general review runs the whole-paper check (S4b) after the judge (`AIM_ANSWERED_CHECK_ENABLED`, default off)."""
    return bool(settings.aim_answered_check_enabled)


def old_engine_on() -> bool:
    """True: the old engine runs as before and the general review is not offered."""
    return bool(settings.review_old_engine_enabled)


def general_on() -> bool:
    """True: the Review button runs the general review (the production default)."""
    return not old_engine_on()


def method() -> str:
    """ "general" or "earlier"."""
    return GENERAL if general_on() else EARLIER


def max_usd() -> float:
    """The general review run's own meter in USD. A value above the rule-1 run cap (or not above 0) is refused."""
    value = float(settings.general_review_max_usd_per_run)
    if not 0 < value <= RUN_CAP_USD:
        raise ValueError(
            f"general_review_max_usd_per_run must be above 0 and at most {RUN_CAP_USD}"
        )
    return value


def lead_model() -> str:
    """The model of the identify, select, checklist and judge steps."""
    return str(settings.general_review_lead_model)


def strong_model() -> str:
    """The model of the attack on a new checklist."""
    return str(settings.general_review_strong_model)
