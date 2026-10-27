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
