"""Which review method the ONE Review button runs, and the fixed sentences of the general review (owner's ONE ORDER, 18 Nov 2026).

THE ONE WAY BACK is `REVIEW_OLD_ENGINE_ENABLED` (`settings.review_old_engine_enabled`, default False):
  False -> the button runs the general review (`app.aim_review`, job stage `aim_review`); the old engine (rule check + old AI
           reviewer) queues nothing and its screens are hidden.
  True  -> everything is exactly as before the general review; it is not offered.

Every piece reads the switch and the knobs ONLY through this module. It opens no lane: the general review runs on Claude only when
the AI reviewer's lane is open as today (`AGENT_REVIEW_ENABLED`, the provider, both egress flags, a key), decided elsewhere. With
Local only it runs on the local model (`aim_review.local_model`), barred from Claude for the whole run.
Each sentence below has ONE home: this file (a grep test says so).
"""

from __future__ import annotations

from .config import settings

GENERAL = "general"
EARLIER = "earlier"

#: Every sheet of the general review's file, the page header and each row carry these words.
AI_MARK = "AI, to be checked"
#: Local only while the AI review itself is switched off on this install: nothing is sent and nothing is reviewed.
LOCAL_NOT_AVAILABLE = "The AI review is switched off on this install, so with Local only nothing is sent and nothing is reviewed."
#: LOCAL ONLY RUNS THE GENERAL REVIEW ON THE LOCAL MODEL (planner 25 Nov 2026 22:35, the owner: "if we do not have the Claude API,
#: use the local model until then"): the same steps, code checks and labels, on the installed local model; nothing leaves this
#: computer, USD 0. Its quality is not measured yet, so the page and the file say so until a score of local runs exists.
LOCAL_RUN_WHY = (
    "it runs on this computer on the local model: nothing leaves this computer, USD 0"
)
LOCAL_PLAN_WORDS = (
    "The general review runs on the local model on this computer. Nothing leaves this computer and nothing is paid. "
    "It is slower than Claude (a large paper can take hours) and its quality is not measured yet: local model, not yet scored."
)
#: Local only while the local route is switched off (GENERAL_REVIEW_LOCAL_ENABLED, the way back): refused before the start.
LOCAL_SWITCHED_OFF = (
    "The local model is switched off for the general review on this install, so with Local only nothing is sent and nothing "
    "is reviewed."
)
#: The one line the plan and the sheet show for the local model: its measured time and score (on the
#: 9B qwen3.5:9b-q4_K_M, lead-4 26 Nov 2026: valve copy A 32.5 minutes, 2 of 10 planted mistakes found; contract copy A 5 of 10 with
#: the lead's reading). Change it with the next measured score.
LOCAL_TEST_NOTE = "Local model (9B): about 33 minutes; found 2 of 10 planted datasheet mistakes and 5 of 10 contract mistakes in our test."
#: The score line of a review made on the local model (page and file), in place of the kind's score measured on Claude.
LOCAL_NOT_SCORED = "local model, not yet scored"
#: A model with no measured score of the general review (the Review model section of the Administration page).
NOT_YET_SCORED = "not yet scored"
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


def local_on() -> bool:
    """True: Local only runs the general review on the local model (the way back, GENERAL_REVIEW_LOCAL_ENABLED, is on)."""
    return bool(getattr(settings, "general_review_local_enabled", True))


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


#: A review that STOPPED because the Claude account itself cannot answer says so in plain words, at the top of its page and in its file:
#: never as a generic failure (the stop codes are `agent_claude.ACCOUNT_STOPS`).
NO_CREDIT_WORDS = "The AI account has no credit left, so the Claude steps cannot run. Choose Local only, or ask the owner to add credit."
USAGE_LIMIT_WORDS = "The AI account's usage limit is reached, so the Claude steps cannot run until it resets. Choose Local only, or ask the owner to raise the limit."
ACCOUNT_WORDS = {
    "account_no_credit": NO_CREDIT_WORDS,
    "account_usage_limit": USAGE_LIMIT_WORDS,
}


def account_words(stop_reason) -> str | None:
    """The plain sentence for a stop reason that names an account refusal ("aim_judge: stop account_no_credit"), else None."""
    said = str(stop_reason or "")
    return next((words for code, words in ACCOUNT_WORDS.items() if code in said), None)
