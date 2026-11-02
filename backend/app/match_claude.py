"""The matcher's question through the ONE Claude lane (R32, 2026-10-11; MATCH_ENGINE=claude).

Only when `reasoning_provider.claude_unavailable_for_task` says Claude may be used, through
`reader_transport.transport()` wrapped in `claude_spend.metered` (USD caps before the call,
every call in the ledger). Moved out of `comparison`, which decides what the answer means.
"""

from __future__ import annotations

import dataclasses

from . import errors
from .config import settings

MATCH_STEP = "requirement-matcher"


def ask_claude_for_a_pair(
    prompt: str, nth: int = 0, candidates: list[dict] | None = None
) -> tuple[str | None, str | None]:
    """`(text, None)` or `(None, reason)`; never raises. #456: the cap is the route
    table's; a reply it cut off is `model_truncated`, never parsed. `nth` and `candidates`
    are the stored-answer rules of the local path: each ask of the stability check has its
    own answer, kept only when it passes `comparison._checked_choice`."""
    from . import claude_spend, comparison, reader_api, reader_transport
    from .ai import output_limits
    from .reasoning_provider import claude_unavailable_for_task

    def keep_if(text: str) -> bool:
        choice = comparison._json_object_in(text)
        return comparison._checked_choice(choice, candidates or [])[1] is None

    # #501: the matcher's own engine setting, under the provider switch.
    try:
        if claude_unavailable_for_task(settings.match_engine)[0] is not None:
            return None, comparison.MODEL_UNAVAILABLE
        transport = reader_transport.transport()
        if transport is None:
            return None, comparison.MODEL_UNAVAILABLE
        cfg = dataclasses.replace(
            reader_api.ReaderSettings.from_env(),
            model=settings.claude_reasoning_model,
            timeout_seconds=float(settings.match_timeout_seconds),
        )
        call = output_limits.model_call_for(
            claude_spend.metered(
                transport,
                MATCH_STEP,
                unbilled=reader_transport.unbilled,
                version=f"{comparison.MATCH_PROMPT_VERSION}#{nth}",
                keep_if=keep_if if candidates is not None else None,
            ),
            output_limits.ROUTE_MATCH,
            cfg=cfg,
        )
        return call(prompt), None
    except (claude_spend.StopRun, claude_spend.BudgetExceeded):
        return None, comparison.MODEL_BUDGET
    except (output_limits.Truncated, output_limits.Unreadable) as exc:
        truncated = exc.state == output_limits.TRUNCATED
        return (
            None,
            comparison.MODEL_TRUNCATED if truncated else comparison.MODEL_MALFORMED,
        )
    except Exception as exc:  # noqa: BLE001 - refused, timed out, or answered wrongly
        return errors.fell_back(
            "comparison: the Claude pair-choice call failed; the pair stays unchosen",
            exc,
            (None, comparison.MODEL_UNAVAILABLE),
        )
