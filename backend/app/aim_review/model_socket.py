"""THE MODEL SOCKET of the general review (owner via the planner, 25 Nov 2026 22:40: "a model option in the app", one interface,
not a second hard-wired class).

ONE INTERFACE: the ask() contract `engine.ClaudeModel` has (step, model, system, cached paper block, prompt, carried documents,
answer size -> the step's JSON answer, or `StepFailed` with a code). The method never knows which adapter answered. THE ADAPTERS:

  * "claude": `engine.ClaudeModel`, the one approved Claude lane (`reader_transport`, `claude_spend`), as before;
  * "local": `local_model.LocalModel`, the local engine through `model_transport` only (Local only; nothing leaves this computer,
    USD 0);
  * "openai_compatible": a SLOT ONLY. The owner has not approved any other vendor for document text (#1584), so it has no network
    code and no socket of its own: every call is refused with `NOT_APPROVED`, before anything is built or sent.

THE GUARDS (`selectable`): a model is offered only when (a) its vendor is approved for document text (today Claude and local),
(b) the money meter has its price (Claude in `claude_spend`; local is 0), and (c) its measured score for the paper's kind is shown,
or the screen and the file say "not yet scored" (`aim_review_local_view`). Local only keeps barring every Claude step for the whole
run (`review_engine.barring`); the socket opens no lane. No document text is read, logged or kept here.
"""

from __future__ import annotations

from dataclasses import dataclass

CLAUDE, LOCAL, OPENAI_COMPATIBLE = "claude", "local", "openai_compatible"

NOT_APPROVED = (
    "not approved by the owner: no document text may go to this vendor (#1584)"
)


@dataclass(frozen=True)
class Adapter:
    key: str
    #: the owner approved this vendor for document text
    approved: bool
    #: the money meter has its price (local: 0)
    priced: bool
    words: str


ADAPTERS = {
    CLAUDE: Adapter(
        CLAUDE,
        True,
        True,
        "Claude: approved for document text (#1584), priced by the spend meter",
    ),
    LOCAL: Adapter(
        LOCAL, True, True, "the local model: nothing leaves this computer, USD 0"
    ),
    OPENAI_COMPATIBLE: Adapter(OPENAI_COMPATIBLE, False, False, NOT_APPROVED),
}


def selectable(key: str) -> tuple[bool, str]:
    """(may this adapter be chosen, the plain words why). Unknown adapters are never chosen."""
    adapter = ADAPTERS.get(str(key or "").strip().lower())
    if adapter is None:
        return False, "no such review model"
    if not adapter.approved:
        return False, adapter.words
    if not adapter.priced:
        return False, "the money meter has no price for this model"
    return True, adapter.words


class OpenAICompatibleModel:
    """The slot for an OpenAI-compatible endpoint. Refuses every call: no network code, no socket, nothing built or sent."""

    dry = False
    engine = OPENAI_COMPATIBLE

    def __init__(self, meter=None) -> None:
        from .engine import Meter

        self.meter = meter or Meter(cap=0.0)

    def ask(self, *, step: str, **_kw):
        from .engine import StepFailed

        raise StepFailed(f"{step}: stop not_approved ({NOT_APPROVED})")


def model_for_run(key: str, *, paper_tokens: int | None = None):
    """The model object of a run on adapter `key`. A local run gets its window sized to the paper (`budget.for_paper`: the whole
    paper fits; never cut). Raises ValueError for an adapter that may not be chosen."""
    ok, words = selectable(key)
    if not ok:
        if key == OPENAI_COMPATIBLE:
            return OpenAICompatibleModel()  # refuses every call with its words
        raise ValueError(words)
    if key == CLAUDE:
        from .engine import ClaudeModel

        return ClaudeModel()
    from .budget import LOCAL as BASE
    from .budget import for_paper
    from .local_model import LocalModel

    return LocalModel(budget=for_paper(paper_tokens) if paper_tokens else BASE)
