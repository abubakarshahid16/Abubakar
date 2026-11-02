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

THE FILES HOLD DOCUMENT TEXT (the answers quote it). They live only inside `data_dir`
and git-ignored: any other folder means no cache, with the reason stated
(`refused_folder`). Outside git, and nothing from them is ever logged: this module
logs the error type only. Each file names the documents its prompt carried, with
their hashes (`claude_approved.still_holds`), so a document deleted, replaced,
withdrawn or blocked leaves nothing served. Deleting a document also removes its
files (`forget_documents`).

This module opens no socket. `AI_ANSWER_REUSE_ENABLED=false` turns it off, as it
turns off every other stored answer (order 205): nothing read, nothing kept.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .ai.json_reply import unfenced
from .config import settings

log = logging.getLogger(__name__)

#: The API's stop reasons for an answer the model finished by itself.
COMPLETE_STOPS = frozenset({"end_turn", "stop_sequence"})
#: What the audit says about a call answered from here.
NOT_SENT = "not sent: cache hit"
_SAID: set[str] = set()


def is_json(text: str) -> bool:
    """The validity check of the `metered` lane, whose every prompt asks for JSON."""
    try:
        json.loads(unfenced(text.strip()))
    except ValueError:
        return False
    return True


def _root() -> Path:
    """`settings.claude_cache_dir`, or `<data_dir>/claude_cache` when it is not set."""
    if settings.claude_cache_dir:
        return Path(settings.claude_cache_dir).resolve()
    return Path(settings.data_dir).resolve() / "claude_cache"


@functools.lru_cache(maxsize=8)
def _ignored_by_git(repo: Path, folder: Path) -> bool:
    """What git itself says. No answer from git is a no: the files hold document text."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", str(folder / "x.json")],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def refused_folder() -> str | None:
    """Why the configured folder may not hold the answers, or None. It must be inside
    the data folder, and git-ignored if that is inside the repository. Never the path:
    this reason is printed in the audit."""
    folder, data = _root(), Path(settings.data_dir).resolve()
    repo = Path(__file__).resolve().parents[2]
    if folder in (repo, *repo.parents) or data in (repo, *repo.parents):
        return "the cache folder or data folder is the repository root or above it"
    if data != folder and data not in folder.parents:
        return "the cache folder is outside the data folder"
    in_repo = repo in folder.parents and (repo / ".git").exists()
    if in_repo and not _ignored_by_git(repo, folder):
        return "the cache folder is inside the repository and git does not ignore it"
    return None


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


def _refused_now() -> bool:
    """The refusal, stated in the log once per reason (it holds no path and no text)."""
    why = refused_folder()
    if why and why not in _SAID:
        _SAID.add(why)
        log.warning("claude answer cache is off: %s", why)
    return why is not None


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
    if not settings.ai_answer_reuse_enabled or _refused_now():
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

    if not settings.ai_answer_reuse_enabled or not complete(payload) or _refused_now():
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
        Path(temp).replace(path)
        return True
    except Exception as exc:  # noqa: BLE001 - see the docstring; the type only, never the text
        log.info("claude answer cache: an answer was not kept (%s)", type(exc).__name__)
        return False


def forget_documents(document_ids) -> int:
    """Remove every stored answer whose prompt carried one of these documents.
    Returns how many. Called when a document is deleted: its text must not stay
    behind in here."""
    wanted = {str(d) for d in document_ids if d}
    root = (
        _root()
    )  # asked even when refused now: what is there still goes with its document
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


def report(entries: list[dict], *, run_id: str | None = None) -> dict:
    """Hits, misses and the USD the hits saved, on the ledger lines of one review run, or
    on the whole ledger with no run named. A miss is a call that went out and was charged."""
    hits = misses = 0
    saved = 0.0
    by_step: dict[str, int] = {}
    for entry in entries:
        if run_id is not None and entry.get("run") != run_id:
            continue
        if entry.get("cached"):
            hits += 1
            saved += float(entry.get("saved_usd") or 0.0)
            by_step[str(entry.get("step"))] = by_step.get(str(entry.get("step")), 0) + 1
        elif entry.get("settles"):
            misses += 1
    whose = (
        "this review run"
        if run_id is not None
        else "the whole spend ledger, every run and chat"
    )
    return {
        "hits": hits,
        "misses": misses,
        "saved_usd": round(saved, 6),
        "hits_by_step": by_step,
        "cache_off": refused_folder(),
        "boundary": f"Claude calls of {whose}; the USD is the list-price estimate of "
        "what each stored answer first cost",
    }
