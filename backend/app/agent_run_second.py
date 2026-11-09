"""Second opinion and fatal-stop words of the agent proof test runner (#1690, part of #805).

Split out of `agent_run` (file size ratchet). The second opinion is the LOCAL model (`agent_local`, a different family from
the Claude lead); nothing here can reach Claude. A model name that is missing, 'unknown' or of the same family as the lead
fails closed: GREEN and RED become YELLOW.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from . import agent_trace, heavy_lock

UNKNOWN = "unknown"


def _known(models: Iterable[str]) -> set[str] | None:
    """The reported model names, or None when there are none or any is missing/'unknown' (fails closed)."""
    names = {str(m) for m in models if m}
    return names if names and UNKNOWN not in names else None


_VERSION_TAIL = re.compile(r"(?:-\d{8}|-latest|@[\w.\-]+)$")


def model_family(name: str) -> str:
    """The model name without a trailing -YYYYMMDD, -latest or @version: the same family is the same model."""
    return _VERSION_TAIL.sub("", name.strip().lower())


def models_differ(lead_models: Iterable[str], opinion_model: Any) -> bool:
    """True only when BOTH sides reported a model name and the names differ. A missing name fails closed."""
    lead = _known(lead_models)
    other = _known([opinion_model] if isinstance(opinion_model, str) else [])
    if not (lead and other):
        return False
    return not ({model_family(m) for m in lead} & {model_family(m) for m in other})


def ask_second_opinion(opinion: Any, finding: dict, trace: Any) -> dict:
    """{'agree': True|False|None, 'model': name or 'unknown'} from `opinion.second_opinion(finding, evidence)`.

    The real one is `ClaudeProvider.second_opinion` (a different model, the shared meter); built once per run."""
    evidence = {k: finding.get(k) for k in ("doc_quote", "clause_quote")}
    try:
        reply = opinion.second_opinion(
            {k: finding.get(k) for k in ("item", "color")}, evidence
        )
    except Exception as exc:
        if getattr(exc, "fatal", False):
            raise
        # recorded: counted as 'no answer' in RESULTS
        return {"agree": None, "model": UNKNOWN}
    if not isinstance(reply, dict):
        return {"agree": None, "model": UNKNOWN}
    cost = reply.get("usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
        trace.add_spend(float(cost))
    agree = reply.get("agree")
    model = reply.get("model")
    return {
        "agree": agree if isinstance(agree, bool) else None,
        "model": model if isinstance(model, str) and model.strip() else UNKNOWN,
    }


def apply_second_opinion(
    finding: dict, agree: bool | None, ran: bool, same_model: bool = False
) -> dict:
    """GREEN and RED stay only on agreement. Disagreement, no answer, or a model that is the same or unknown -> YELLOW."""
    out = dict(finding)
    if finding.get("color") not in ("GREEN", "RED"):
        return out
    if not ran:
        out["second_opinion"] = "not run"
        return out
    if agree is True and not same_model:
        out["second_opinion"] = "agreed"
        return out
    why = (
        "second opinion model is the same or unknown"
        if same_model
        else "second opinion disagreed"
        if agree is False
        else "no second opinion"
    )
    out.update(
        color="YELLOW",
        second_opinion="disagreed" if agree is False else "no answer",
        reason=agent_trace.words(f"{why}; first verdict {finding.get('color')}"),
        action=finding.get("action") or "ask the engineer",
    )
    return out


class LocalOpinion:
    """The LOCAL second opinion (`agent_local.LocalSecondOpinion`, a different model family from the Claude lead).

    Takes the shared heavy-job lock around each call (not when the lead already holds it: `held_already`) and unloads
    the model at the end (#666). Nothing here can reach Claude."""

    def __init__(self, inner: Any, *, held_already: bool = False) -> None:
        self.inner, self.held_already = inner, held_already

    def second_opinion(self, finding: dict, evidence: dict) -> dict:
        if self.held_already:
            return self.inner.second_opinion(finding, evidence)
        try:
            with heavy_lock.held(
                "agent-review", "run_agent_review", heavy_lock.wait_seconds_from_env()
            ):
                return self.inner.second_opinion(finding, evidence)
        except heavy_lock.HeavyJobBusy as exc:
            exc.fatal = True  # the run stops, resumable; the item is not made YELLOW
            raise

    def unload(self) -> None:
        for name in ("unload", "close"):
            fn = getattr(self.inner, name, None)
            if callable(fn):
                fn()
                return


def fatal_problem(exc: BaseException) -> str:
    """The PROBLEM words of a fatal stop: from its code only, never a message."""
    if isinstance(exc, heavy_lock.HeavyJobBusy):
        return "heavy lock busy"
    code = str(getattr(exc, "code", "") or "")
    if "document" in code:
        return "documents not declared"
    if type(exc).__name__ == "AgentGateClosed":
        return "gate closed"
    if code == "test_cap":
        return "budget stop: run cap reached: owner decides whether to raise it"
    return "budget stop: step cap reached: owner decides whether to raise it"


def wrap_opinion(
    second_opinion: Any, provider: Any, local: bool
) -> LocalOpinion | None:
    """The locked, unloading wrapper of the second opinion, or None. The lead can never be its own second opinion."""
    if second_opinion is None:
        return None
    if second_opinion is provider:
        raise ValueError("the second opinion must be a different model, not the lead")
    return LocalOpinion(second_opinion, held_already=local)
