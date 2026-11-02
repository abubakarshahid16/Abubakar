"""The stored answer of every Claude call: the same request is never bought twice.

WHY THIS EXISTS. The first pilot on the Claude lane (2 Nov 2026) left the cache
folder empty and a re-run paid again in full: the old cache lived only inside
`ClaudeProvider`, while the steps that spend the money (the datasheet reader and
the matcher) go through `claude_spend.metered`, which had no cache at all. So this
file is the store, and `claude_spend.answer_on_file` / `keep_answer` are the one
door: every lane that reserves money asks there first.

THE KEY is the request exactly as it would leave (model, messages with images,
system, tools, thinking, effort, max_tokens, temperature), plus the step and a
prompt version. Anything that can change the answer is in it, so a changed model
or prompt is a miss by construction. `stream` is left out: how a reply travels
does not change what it says.

ONLY COMPLETE ANSWERS ARE KEPT: a normal stop, some text, and the caller's validity
check. Never a refusal, a cut-off, an error, an empty reply or a reply that fails its
check. A tool-use turn is not an answer either. Corrupt or unreadable means a miss,
never a crash.

THE FILES HOLD DOCUMENT TEXT (the answers quote it). They live under `data_dir`
with the database, outside git, and nothing from them is ever logged: this module
logs the error type only. Each file names the documents its prompt carried, with
their hashes (`claude_approved.still_holds`), so a document deleted, replaced,
withdrawn or blocked leaves nothing served. Deleting a document also removes its
files (`forget_documents`).

This module opens no socket. `AI_ANSWER_REUSE_ENABLED=false` turns it off, as it
turns off every other stored answer (order 205): nothing read, nothing kept.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from .ai.json_reply import unfenced
from .config import settings

log = logging.getLogger(__name__)

#: The API's stop reasons for an answer the model finished by itself.
COMPLETE_STOPS = frozenset({"end_turn", "stop_sequence"})
#: What the audit says about a call answered from here.
NOT_SENT = "not sent: cache hit"


def is_json(text: str) -> bool:
    """The validity check of the `metered` lane, whose every prompt asks for JSON."""
    try:
        json.loads(unfenced(text.strip()))
    except ValueError:
        return False
    return True


def _root() -> Path:
    """`settings.claude_cache_dir`, but never a folder git could pick up: a path
    inside the repository that is not under `data_dir` falls back to `data_dir`."""
    chosen = Path(settings.claude_cache_dir).resolve()
    data = Path(settings.data_dir).resolve()
    repo = Path(__file__).resolve().parents[2]
    if repo in chosen.parents and data not in chosen.parents:
        return data / "claude_cache"
    return chosen


def key_of(step: str, version: str, body: dict) -> str:
    """Everything that changes the answer. See the module docstring."""
    sent = {k: v for k, v in body.items() if k != "stream"}
    text = json.dumps(
        {"step": step, "version": version, "body": sent},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return _root() / key[:2] / f"{key}.json"


def _text_of(payload: dict) -> str:
    from . import reader_api

    return reader_api.response_text(payload).strip()


def complete(payload) -> bool:
    """A finished answer with text in it, and nothing else."""
    return (
        isinstance(payload, dict)
        and payload.get("stop_reason") in COMPLETE_STOPS
        and bool(_text_of(payload))
    )


def _usable(path: Path, stored, valid) -> bool:
    from . import claude_approved

    if not complete(stored) or not (valid is None or valid(_text_of(stored))):
        return False
    if claude_approved.still_holds(stored.get("documents")):
        return True
    # Deleted, replaced, withdrawn or blocked: its answers are not kept for later.
    path.unlink(missing_ok=True)
    return False


def read(key: str, *, valid=None) -> dict | None:
    """The stored answer, or None. Every failure here is a miss, never a crash."""
    if not settings.ai_answer_reuse_enabled:
        return None
    path = _path(key)
    try:
        if not path.is_file():
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached if _usable(path, cached, valid) else None
    except Exception as exc:  # noqa: BLE001 - corrupt or unreadable: pay again, say the type only
        log.info(
            "claude answer cache: a file could not be used (%s); asking",
            type(exc).__name__,
        )
        return None


def write(key: str, *, step: str, payload, cost_usd: float, valid=None) -> bool:
    """Keep a complete, valid answer. True when it was stored. Best effort: the
    answer is already paid for, and a full disk must not lose it for the caller."""
    from . import claude_approved

    if not settings.ai_answer_reuse_enabled or not complete(payload):
        return False
    if valid is not None and not valid(_text_of(payload)):
        return False
    try:
        # None: nobody declared (possible only with the list not enforced, on a copy).
        documents = claude_approved.carried_hashes()
        if documents is not None and not all(documents.values()):
            return False  # a declared document the library does not hold cannot be followed
        path = _path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = {
            "step": step,
            "model": payload.get("model"),
            "stop_reason": payload.get("stop_reason"),
            "content": payload.get("content"),
            "usage": payload.get("usage"),
            "cost_usd": float(cost_usd or 0.0),
            "documents": documents,
        }
        handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(stored, fh, ensure_ascii=False)
        os.replace(temp, path)
        return True
    except Exception as exc:  # noqa: BLE001 - see the docstring; the type only, never the text
        log.info("claude answer cache: an answer was not kept (%s)", type(exc).__name__)
        return False


def forget_documents(document_ids) -> int:
    """Remove every stored answer whose prompt carried one of these documents.
    Returns how many. Called when a document is deleted: its text must not stay
    behind in here."""
    wanted = {str(d) for d in document_ids if d}
    root = _root()
    removed = 0
    if not wanted or not root.is_dir():
        return 0
    for path in root.glob("*/*.json"):
        try:
            documents = (
                json.loads(path.read_text(encoding="utf-8")).get("documents") or {}
            )
        except (OSError, ValueError, AttributeError):
            # Unreadable, so nobody can say it is innocent of this document.
            documents = wanted
        if wanted & set(documents):
            path.unlink(missing_ok=True)
            removed += 1
    return removed
