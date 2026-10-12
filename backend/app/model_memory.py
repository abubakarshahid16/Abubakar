"""Free the memory the local answer models hold (#666).

Ollama keeps a model resident for `keep_alive` after the last call. A long
window held the memory after every call and blocked both owner PC sessions for
about two hours. This module is the way to give it back on purpose:

  * `loaded_models()`   what Ollama says is resident right now (`/api/ps`).
  * `unload(model)`     one request with keep_alive 0 for that model.
  * `unload_used()`     unload exactly the models THIS process sent work to
                        (`model_transport.models_used`), for a runner such as
                        the P1 run that must leave the machine as it found it.
  * `free_all()`        unload every resident model; the administrator's button.

Every request goes through `model_transport`, the one module that opens the
socket (loopback Ollama), with the keep_alive override set to 0. Nothing here
reads or sends document text: a model name and `keep_alive: 0` only.
"""
from __future__ import annotations

import logging

from . import model_transport

log = logging.getLogger(__name__)

_TIMEOUT = 30.0


def loaded_models() -> list[str] | None:
    """Names of the models Ollama holds in memory, or None when that cannot be
    read (Ollama stopped, or it answered nothing about loaded models)."""
    try:
        running = model_transport.get_json("/api/ps", timeout=_TIMEOUT, required=False)
    except model_transport.ModelHostRefused:
        raise            # a refused host is the operator's to see
    except Exception as exc:  # noqa: BLE001 - a stopped Ollama is a state
        log.warning("loaded models could not be read (%s)", type(exc).__name__)
        return None
    if running is None:
        return None
    return [str(m.get("name") or m.get("model") or "") for m in running.get("models", [])
            if m.get("name") or m.get("model")]


def unload(model: str) -> bool:
    """Ask Ollama to drop `model` now. True when the request was accepted."""
    try:
        with model_transport.keep_alive_override(0):
            model_transport.post_json(
                "/api/generate", {"model": model, "prompt": "", "stream": False},
                timeout=_TIMEOUT)
        return True
    except model_transport.ModelHostRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised into a finish
        log.warning("model %s could not be unloaded (%s)", model, type(exc).__name__)
        return False


def unload_used() -> dict:
    """Unload every model this process used. Never raises for a model that
    would not unload: the report says which."""
    freed, failed = [], []
    for model in model_transport.models_used():
        (freed if unload(model) else failed).append(model)
    return {"unloaded": freed, "failed": failed}


def free_all() -> dict:
    """Unload every resident model. `still_loaded` is read back afterwards, so
    the answer is what Ollama reports, not what was asked."""
    before = loaded_models()
    if before is None:
        return {"freed": [], "still_loaded": [], "reachable": False}
    for model in before:
        unload(model)
    after = loaded_models()
    still = after if after is not None else []
    return {"freed": [m for m in before if m not in still], "still_loaded": still,
            "reachable": True}
