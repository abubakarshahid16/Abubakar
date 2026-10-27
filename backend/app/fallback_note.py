"""Say so when Claude was asked for and the local model answered (#555).

`reasoning_provider.get_provider` hands back the local engine whenever
REASONING_PROVIDER=claude cannot be honoured (the provider switch, the two
egress flags or the key). The fallback used to be a log line only, so a stored
engine read "ollama:<model>" like any local answer and nobody could tell a
chosen local run from a downgrade. The provider now carries `fell_back` (plain
words, closed list, never a setting value or a key), and the places that
record which engine answered add it through `engine_label`.

Chat names its own downgrade (`chat_model.downgrade_fields`); both use WORDS.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: Plain words for each closed reason `reasoning_provider.claude_unavailable`
#: gives (its UNAVAILABLE_* codes). Written here, never taken from an exception
#: or a setting: the note is shown to the reader.
WORDS = {
    "PROVIDER_OFF": "the system is not set up to use Claude",
    "EGRESS_OFF": "Claude access is switched off in the settings",
    "KEY_MISSING": "no Claude key is set",
}
OTHER = "Claude could not be used"
NOT_APPROVED = "a document in this review is not approved for the cloud model"


def mark(engine, requested_claude: bool, code: str | None, why: str):
    """`engine` (the local provider `get_provider` is about to return) with
    `fell_back` set when Claude was asked for; the fallback is logged either way."""
    if requested_claude:
        engine.fell_back = WORDS.get(code or "", OTHER)
        log.warning(
            "reasoning provider: claude requested but not available (%s); using ollama",
            why,
        )
    return engine


def engine_label(provider, response) -> str:
    """ "ollama:<model>" as recorded before, plus "(Claude not used: <words>)"
    when `provider` fell back from Claude. A provider without the attribute
    (a test double, the Claude provider) adds nothing."""
    label = f"{response.provider}:{response.model_tag}"
    words = getattr(provider, "fell_back", None)
    return f"{label} (Claude not used: {words})" if words else label


def carry(old, **timeout):
    """A fresh local provider (built with `timeout`) that keeps `old`'s `fell_back` note: a
    replacement must not drop the fact that Claude was asked for."""
    from . import reasoning_provider as rp

    new = rp.OllamaProvider(**timeout)
    new.fell_back = getattr(old, "fell_back", None)
    return new


def or_local(
    provider, engine_setting: str | None, role: str = "reasoning", *, step=None
):
    """The Claude provider for a step whose OWN engine setting says claude when the lane and the
    review's documents allow it (`rp.claude_for_task`), else `provider` (local), marked when the
    step asked for Claude and did not get it (per_task: `get_provider` could not know)."""
    from . import reasoning_provider as rp

    claude = rp.claude_for_task(engine_setting, role, step=step)
    if claude is not None:
        return claude
    if (
        getattr(provider, "fell_back", None)
        or str(engine_setting or "").strip().lower() != rp.CLAUDE
    ):
        return provider
    code, _why = rp.claude_unavailable_for_task(engine_setting)
    provider.fell_back = WORDS.get(code or "", NOT_APPROVED) if code else NOT_APPROVED
    return provider
