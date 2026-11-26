"""THE LOCAL ANSWER MODEL IN USE (planner's browser check of update 10, 26 Nov 2026: on live, ANSWER_MODEL in .env named the 35B,
so Local only, Chat and the technical-query drafts would have used a model the owner forbade: "it crashes memory").

ONE RULE for every local call that reads the answer model (the general review's default, Chat's local answers, technical-query
drafts, every `reasoning_provider.OllamaProvider` and Explain): the setting ANSWER_MODEL is used unless it is PROVEN that it
cannot be chosen: a cloud name, an engine entry that is not a model file on this computer, or a file larger than
`local_model.MAX_MODEL_BYTES` (15 GB). Then the code's own default (the 9B) is used instead, and `why` says so in one sentence
for the screens. When the engine's list cannot be read nothing is proven, so the setting stands (a run's own start check,
`local_model.readiness`, still refuses a model that is missing or too large).

No document is read or sent: the engine's own model list (`/api/tags`, loopback), read at most once a minute.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Seconds the engine's model list is reused (a Chat answer or a plan never waits on it twice).
LIST_SECONDS = 60.0
_CACHE: dict[str, tuple[float, dict | None]] = {}

FELL_BACK = "ANSWER_MODEL names {configured}, which cannot be used here ({reason}), so the code's default {default} is used"
TOO_LARGE = "its file is over 15 GB: too large for this computer"
NOT_A_FILE = "it is not a model file on this computer"


@dataclass(frozen=True)
class Choice:
    name: str
    configured: str
    why: str | None = None  # set only when the configured model was replaced

    @property
    def fell_back(self) -> bool:
        return self.why is not None


def code_default() -> str:
    from .config import Settings

    return str(Settings.model_fields["answer_model"].default)


def code_default_ram_bytes() -> int:
    from .config import Settings

    return int(Settings.model_fields["answer_model_ram_bytes"].default)


def forget() -> None:
    """Drop the cached model list (tests; a model pulled or removed)."""
    _CACHE.clear()


def _entry(name: str) -> tuple[bool, dict | None]:
    """(the list was read, the engine's entry for `name` or None)."""
    from . import model_transport

    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached and now - cached[0] < LIST_SECONDS:
        return cached[1] is not None, (cached[1] or {}).get(name)
    try:
        body = model_transport.get_json("/api/tags", timeout=3.0, required=False)
    except Exception as exc:  # noqa: BLE001 - nothing proven; the log says why and the setting stands
        log.info(
            "answer model: the engine's list was not read (%s)", type(exc).__name__
        )
        body = None
    listed = None
    if isinstance(body, dict) and isinstance(body.get("models"), list):
        listed = {
            str(m.get("name") or m.get("model") or ""): m
            for m in body["models"]
            if isinstance(m, dict)
        }
    _CACHE[name] = (now, listed)
    return listed is not None, (listed or {}).get(name)


def _why_not(name: str) -> str | None:
    """Why `name` is PROVEN unusable here, or None (usable, or nothing proven)."""
    from .aim_review import local_model

    if local_model.is_cloud_name(name):
        return NOT_A_FILE
    read, entry = _entry(name)
    if not read or entry is None:
        return None  # not proven: the run's own start check says "not installed" if so
    if not local_model.is_local_file(name, entry):
        return NOT_A_FILE
    if local_model._count(entry.get("size")) > local_model.MAX_MODEL_BYTES:
        return TOO_LARGE
    return None


def resolve() -> Choice:
    """The local answer model every local call uses now (see the module's rule)."""
    from .config import settings

    configured = str(settings.answer_model or "").strip()
    default = code_default()
    if not configured or configured == default:
        return Choice(name=default, configured=configured or default)
    reason = _why_not(configured)
    if reason is None:
        return Choice(name=configured, configured=configured)
    why = FELL_BACK.format(configured=configured, reason=reason, default=default)
    log.warning("answer model: %s", why)
    return Choice(name=default, configured=configured, why=why)


def name() -> str:
    return resolve().name


def ram_bytes() -> int:
    """The resident size the memory warning asks for: the setting's, or the code default's when the model was replaced."""
    from .config import settings

    return (
        code_default_ram_bytes()
        if resolve().fell_back
        else int(settings.answer_model_ram_bytes)
    )
