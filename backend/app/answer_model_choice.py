"""THE LOCAL ANSWER MODEL IN USE (planner's browser check of update 10, 26 Nov 2026: on live, ANSWER_MODEL in .env named the 35B,
so Local only, Chat and the technical-query drafts would have used a model the owner forbade: "it crashes memory").

ONE RULE for every local call that reads the answer model (the general review's default, Chat's local answers, technical-query
drafts, every `reasoning_provider.OllamaProvider` and Explain): the setting ANSWER_MODEL is used only when the engine's own
list shows it is a model file on this computer of at most `local_model.MAX_MODEL_BYTES` (15 GB). A cloud name, an entry that is
not a model file, a missing model, a file too large, or a list that cannot be read: the code's own default (the 9B) is used
instead, and `why` says so in one sentence for the screens (fail closed, review of update 11, N3).

No document is read or sent: the engine's own model list (`/api/tags`, loopback), read at most once a minute.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Seconds the engine's model list is reused (a Chat answer or a plan never waits on it twice). ONLY A LIST THAT WAS READ is
#: kept (review of update 11, N3): a failed read is asked again next time, never remembered.
LIST_SECONDS = 60.0
_LIST: dict[str, tuple[float, dict]] = {}
_SAID: dict[str, str] = {}

FELL_BACK = "ANSWER_MODEL names {configured}, which cannot be used here ({reason}), so the code's default {default} is used"
TOO_LARGE = "its file is over 15 GB: too large for this computer"
NOT_A_FILE = "it is not a model file on this computer"
NOT_INSTALLED = "it is not installed on this computer"
#: FAIL CLOSED (review of update 11, N3): while the engine's list cannot be read nothing is proven usable, so the code's default
#: is used, never the configured model (on live that was the 35B).
LIST_UNREAD = "the engine's model list could not be read"


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
    """Drop the kept model list (tests; a model pulled or removed)."""
    _LIST.clear()


def _listed(body) -> dict | None:
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        return None
    return {
        str(m.get("name") or m.get("model") or ""): m
        for m in body["models"]
        if isinstance(m, dict)
    }


def share_list(body) -> None:
    """Keep a model list another caller already read (the dashboard's probe), so one probe asks the engine once (#626)."""
    listed = _listed(body)
    if listed is not None:
        _LIST["list"] = (time.monotonic(), listed)


def _list() -> dict | None:
    """The engine's model list, read at most once a minute; None when it cannot be read (not kept: asked again next time)."""
    from . import model_transport

    kept = _LIST.get("list")
    if kept and time.monotonic() - kept[0] < LIST_SECONDS:
        return kept[1]
    try:
        body = model_transport.get_json("/api/tags", timeout=3.0, required=False)
    except Exception as exc:  # noqa: BLE001 - unread: the code's default is used and the log says why
        log.info(
            "answer model: the engine's list was not read (%s)", type(exc).__name__
        )
        return None
    share_list(body)
    return _listed(body)


def _why_not(name: str) -> str | None:
    """Why `name` may not be used now, or None when it is a usable model file here. An unread list is a reason (fail closed)."""
    from .aim_review import local_model

    if local_model.is_cloud_name(name):
        return NOT_A_FILE
    listed = _list()
    if listed is None:
        return LIST_UNREAD
    entry = listed.get(name)
    if entry is None:
        return NOT_INSTALLED
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
    if _SAID.get("why") != why:  # said once in the log, not on every call
        _SAID["why"] = why
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
