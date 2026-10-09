"""The AI task runner (#644): small strict model tasks, run from a queue.

"AI reads, code checks" (owner decision 2026-10-08). A task is a short piece of
source text (about 300 words), one instruction, and a JSON schema. The model
reads; this module and the task's own `check` decide whether what it said can
be kept. Nothing here ever turns a failure into a guess:

  * INVALID, LATE OR EMPTY reply  -> state `could_not_read`, with the reason.
    The data is None. There is no default value and no "best effort" parse.
  * THE SCHEMA is sent in Ollama's `format` field (the engine enforces it), is
    checked again in code (`reasoning_provider.schema_errors`), and the task's
    own `check(data, source_text)` runs on top (for example "every quote is on
    the page"). A reply failing any of the three gets ONE retry that names what
    was wrong; a second failure is `could_not_read`.
  * A CACHE HIT makes no model call. The key is the task, its version, the
    model, the schema and the exact input, so a changed prompt version or a
    different model never reuses an old answer. Only `ok` results are cached,
    so a failure is retried next time.
  * THE MODEL IS A SETTING (`settings.ai_task_model`, qwen3.5:2b by default,
    qwen3.5:4b or a larger local model by changing the value). The same tasks
    run through the same runner with any model.

Gentle on the machine: ONE job at a time (`run_batch` refuses a second
concurrent batch); the model stays loaded between the tasks of one batch
(`keep_alive` "10m") and is unloaded at the end (0); the batch PAUSES, leaving
the queue untouched, while a chat answer is being produced (the user comes
first), while the test suite or the P1 run is going, or while less than
`ai_task_min_free_ram_gb` of memory is free.

Privacy: the only socket is `model_transport` (loopback Ollama), through
`reasoning_provider.OllamaProvider`. This module opens none, logs no source
text, and the queue and the cache live in the local database.

Nothing calls this from the review pipeline yet: it is the runner, not a
feature. A task is added by registering a `TaskSpec`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from . import heavy_lock, model_transport, progress
from .config import settings
from .db import connect
from .reasoning_provider import OllamaProvider, Packet, ProviderRefused, schema_errors

_log = logging.getLogger(__name__)

STATE_OK = "ok"
STATE_COULD_NOT_READ = "could_not_read"

#: Queue states. `queued` -> `running` -> `done` | `could_not_read`.
Q_QUEUED = "queued"
Q_RUNNING = "running"
Q_DONE = "done"
Q_COULD_NOT_READ = "could_not_read"

#: Attempts per task: the first, and ONE retry after an invalid reply.
MAX_ATTEMPTS = 2

#: A running job older than this (seconds) belongs to a dead process.
STALE_RUNNING_S = 15 * 60

#: Command-line fragments of the heavy jobs the queue steps aside for.
HEAVY_PROCESS_MARKERS = ("pytest", "run_p1.py")


@dataclass(frozen=True)
class TaskSpec:
    """One kind of task. Built by code; the model only ever fills the schema."""

    name: str
    #: Part of the cache key: change it when the instruction or schema changes.
    version: str
    instruction: str
    schema: dict
    #: Code check on the parsed reply and the source text. Returns a list of
    #: problems; an empty list means the reply can be kept.
    check: Callable[[dict, str], list[str]] | None = None
    num_predict: int = 400

    def prompt(self, text: str) -> str:
        return (f"{self.instruction.strip()}\n\nANSWER with one JSON object that matches the "
                f"schema and nothing else.\n\nTEXT:\n{text}\n")


@dataclass(frozen=True)
class TaskResult:
    task: str
    state: str
    #: The parsed reply when `state` is `ok`; always None otherwise.
    data: dict | None
    #: Why it could not be read (plain words); None when `ok`.
    reason: str | None
    model: str
    cached: bool = False
    attempts: int = 0


TASKS: dict[str, TaskSpec] = {}


def register(spec: TaskSpec) -> TaskSpec:
    TASKS[spec.name] = spec
    return spec


# ------------------------------------------------------------------ the schema

def ensure_schema() -> None:
    conn = connect()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ai_task_cache (
                key TEXT PRIMARY KEY, task TEXT NOT NULL, version TEXT NOT NULL,
                model TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_task_queue (
                id TEXT PRIMARY KEY, task TEXT NOT NULL, input_text TEXT NOT NULL,
                ref TEXT, state TEXT NOT NULL, result_json TEXT, reason TEXT,
                model TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_ai_task_queue_state
                ON ai_task_queue (state, created_at);
        """)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ one task

def cache_key(spec: TaskSpec, model: str, text: str) -> str:
    material = "\x00".join([spec.name, spec.version, model,
                            json.dumps(spec.schema, sort_keys=True), text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    row = connect().execute("SELECT result_json FROM ai_task_cache WHERE key = ?",
                            (key,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def _cache_put(key: str, spec: TaskSpec, model: str, data: dict) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO ai_task_cache (key, task, version, model, result_json,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (key, spec.name, spec.version, model, json.dumps(data, sort_keys=True), _now()))


def make_provider(model: str | None = None) -> OllamaProvider:
    return OllamaProvider(model or settings.ai_task_model,
                          timeout=float(settings.ai_task_timeout_s))


def _failed(spec: TaskSpec, model: str, reason: str, attempts: int = 0) -> TaskResult:
    return TaskResult(spec.name, STATE_COULD_NOT_READ, None, reason, model, False, attempts)


def run_task(spec: TaskSpec, text: str, *, provider=None, use_cache: bool = True) -> TaskResult:
    """Run one task. Never raises for a model problem; never guesses."""
    ensure_schema()
    provider = provider or make_provider()
    model = getattr(provider, "requested_model", None) or settings.ai_task_model
    text = (text or "").strip()
    if not text:
        return _failed(spec, model, "there was no text to read")
    words = len(text.split())
    if words > settings.ai_task_max_words:
        return _failed(spec, model, f"the text is {words} words; a task reads at most "
                                    f"{settings.ai_task_max_words}. Split it into passages.")
    key = cache_key(spec, model, text)
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return TaskResult(spec.name, STATE_OK, hit, None, model, True, 0)

    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = spec.prompt(text)
        if problems:
            prompt += ("\nYour previous answer was rejected: " + "; ".join(problems[:5])
                       + ". Answer again with only valid JSON that fixes this.\n")
        packet = Packet(prompt=prompt, num_ctx=2048, num_predict=spec.num_predict,
                        json_schema=spec.schema, step=f"ai_task:{spec.name}",
                        prompt_version=spec.version)
        try:
            response = provider.reason(packet)
        except ProviderRefused as exc:
            # A refusal, a timeout, an unreachable host: not an invalid reply,
            # so no retry here. The name of the failure is the reason.
            late = "timeout" in str(exc).lower()
            return _failed(spec, model, "the model did not answer in time" if late
                           else f"the model could not be reached ({_kind(exc)})", attempt)
        problems = _reply_problems(spec, response, text)
        if not problems:
            data = json.loads(response.text)
            if use_cache:
                _cache_put(key, spec, model, data)
            return TaskResult(spec.name, STATE_OK, data, None, model, False, attempt)
    return _failed(spec, model, "the reply was not valid: " + "; ".join(problems[:3]),
                   MAX_ATTEMPTS)


def _kind(exc: BaseException) -> str:
    # The type only. The message can carry a prompt fragment, which is
    # document text and must not reach a log or a stored reason.
    return type(exc.__cause__ or exc).__name__


def _reply_problems(spec: TaskSpec, response, text: str) -> list[str]:
    """Everything wrong with a reply: empty, cut off, not JSON, off schema, or
    failing the task's own code check. Empty list = keep it."""
    if not (response.text or "").strip():
        return ["the reply was empty"]
    if response.finish_reason == "length":
        return ["the reply was cut off before it ended"]
    try:
        data = json.loads(response.text)
    except ValueError:
        return ["the reply was not JSON"]
    if not isinstance(data, dict):
        return ["the reply was not a JSON object"]
    errors = list(getattr(response, "schema_errors", None) or schema_errors(response.text, spec.schema))
    if errors:
        return [str(e) for e in errors]
    if spec.check is not None:
        return [str(p) for p in spec.check(data, text)]
    return []


# ------------------------------------------------------------------ the queue

def enqueue(task: str, text: str, *, ref: str | None = None) -> str:
    if task not in TASKS:
        raise KeyError(f"unknown AI task {task!r}; register it first")
    ensure_schema()
    job_id = uuid.uuid4().hex
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO ai_task_queue (id, task, input_text, ref, state, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, task, text, ref, Q_QUEUED, now, now))
    return job_id


def job(job_id: str) -> dict | None:
    ensure_schema()
    row = connect().execute(
        "SELECT id, task, ref, state, result_json, reason, model, attempts, updated_at"
        " FROM ai_task_queue WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["data"] = json.loads(out.pop("result_json")) if out.get("result_json") else None
    return out


def counts() -> dict[str, int]:
    ensure_schema()
    rows = connect().execute("SELECT state, COUNT(*) AS n FROM ai_task_queue GROUP BY state")
    return {r["state"]: r["n"] for r in rows}


def _recover_stale() -> None:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - STALE_RUNNING_S))
    conn = connect()
    with conn:
        conn.execute("UPDATE ai_task_queue SET state = ?, updated_at = ? WHERE state = ?"
                     " AND updated_at < ?", (Q_QUEUED, _now(), Q_RUNNING, cutoff))


def _claim_next() -> dict | None:
    conn = connect()
    with conn:
        row = conn.execute("SELECT id, task, input_text FROM ai_task_queue WHERE state = ?"
                           " ORDER BY created_at, rowid LIMIT 1", (Q_QUEUED,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE ai_task_queue SET state = ?, updated_at = ? WHERE id = ?",
                     (Q_RUNNING, _now(), row["id"]))
    return dict(row)


def _finish(job_id: str, result: TaskResult) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE ai_task_queue SET state = ?, result_json = ?, reason = ?, model = ?,"
            " attempts = ?, updated_at = ? WHERE id = ?",
            (Q_DONE if result.state == STATE_OK else Q_COULD_NOT_READ,
             json.dumps(result.data, sort_keys=True) if result.data is not None else None,
             result.reason, result.model, result.attempts, _now(), job_id))


# ------------------------------------------------------------------ the gate

def heavy_work_running() -> str | None:
    """Name of a test run or P1 run on this machine (other than this process),
    or None. Read from the process list: nothing to wire into those jobs."""
    import os

    import psutil
    me = os.getpid()
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            if proc.info["pid"] == me:
                continue
            line = " ".join(proc.info.get("cmdline") or ())
            for marker in HEAVY_PROCESS_MARKERS:
                if marker in line:
                    return marker.replace(".py", "")
    except psutil.Error as exc:
        _log.warning("the process list could not be read (%s); heavy work is assumed absent",
                     type(exc).__name__)
    return None


def free_ram_bytes() -> int:
    import psutil
    return int(psutil.virtual_memory().available)


def pause_reason(*, chat_active: int | None = None, heavy: str | None = "probe",
                 free_ram: int | None = None) -> str | None:
    """Why the queue must wait right now, or None. The user comes first."""
    active = progress.active_count() if chat_active is None else chat_active
    if active:
        return "a chat answer is being produced"
    heavy_name = heavy_work_running() if heavy == "probe" else heavy
    if heavy_name:
        return f"{heavy_name} is running"
    queued = heavy_lock.waiters()
    if queued:
        # Another heavy job (P1, a test run) is queued for the machine; a batch
        # that can pause steps aside rather than make it wait (#680).
        return f"{queued[0].get('kind', 'a heavy job')} is waiting for the machine"
    free = free_ram_bytes() if free_ram is None else free_ram
    floor = settings.ai_task_min_free_ram_gb * 1_000_000_000
    if free < floor:
        return (f"only {free / 1e9:.1f} GB of memory is free "
                f"(needs {settings.ai_task_min_free_ram_gb:g} GB)")
    return None


# ------------------------------------------------------------------ the batch

_batch_lock = threading.Lock()


def _unload(provider) -> None:
    """Free the model's memory: a request with keep_alive 0."""
    model = getattr(provider, "requested_model", None) or settings.ai_task_model
    try:
        with model_transport.keep_alive_override(0):
            model_transport.post_json("/api/generate", {"model": model, "prompt": "", "stream": False},
                                      timeout=30.0)
    except Exception as exc:  # noqa: BLE001 - unloading is a courtesy, never a failure of the batch
        _log.warning("the AI task model could not be unloaded (%s)", type(exc).__name__)


def run_batch(*, provider=None, limit: int | None = None, pause=None, unload=None) -> dict:
    """Run queued tasks ONE AT A TIME until the queue is empty, `limit` tasks
    have run, or the machine needs to be left alone.

    Returns {"ran", "ok", "could_not_read", "cached", "paused", "remaining"};
    `paused` is the plain reason the batch stopped early, else None. A paused
    queue loses nothing: its jobs stay `queued`.
    """
    ensure_schema()
    pause = pause or pause_reason
    if not _batch_lock.acquire(blocking=False):
        return {"ran": 0, "ok": 0, "could_not_read": 0, "cached": 0,
                "paused": "another batch is already running", "remaining": counts().get(Q_QUEUED, 0)}
    summary = {"ran": 0, "ok": 0, "could_not_read": 0, "cached": 0, "paused": None}
    provider = provider or make_provider()
    # The shared heavy-job lock (#680): a batch is a heavy job like P1 and the
    # test run, so it takes the same lock, and does not start while one is held.
    lock = heavy_lock.try_acquire("ai_batch", owner="ai task batch")
    if lock is None:
        _batch_lock.release()
        return {**summary, "paused": f"{heavy_lock.describe(heavy_lock.read())}",
                "remaining": counts().get(Q_QUEUED, 0)}
    called_model = False
    try:
        _recover_stale()
        with model_transport.keep_alive_override(settings.ai_task_batch_keep_alive):
            while limit is None or summary["ran"] < limit:
                reason = pause()
                if reason:
                    summary["paused"] = reason
                    break
                claimed = _claim_next()
                if claimed is None:
                    break
                spec = TASKS.get(claimed["task"])
                if spec is None:
                    result = TaskResult(claimed["task"], STATE_COULD_NOT_READ, None,
                                        "this kind of task is not registered",
                                        getattr(provider, "requested_model", ""), False, 0)
                else:
                    result = run_task(spec, claimed["input_text"], provider=provider)
                _finish(claimed["id"], result)
                summary["ran"] += 1
                summary["cached"] += 1 if result.cached else 0
                called_model = called_model or (not result.cached and result.attempts > 0)
                summary["ok" if result.state == STATE_OK else "could_not_read"] += 1
    finally:
        lock.release()
        _batch_lock.release()
        if called_model:
            (unload or _unload)(provider)
    summary["remaining"] = counts().get(Q_QUEUED, 0)
    return summary
