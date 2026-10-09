"""One lock for the heavy jobs on a machine (#680).

P1, the changed-test run, the mutation run and the AI task batch each need most
of the machine's memory. Run together they starved each other, and every session
had its own waiter. This is the ONE shared lock file they all take before they
start and release when they end.

The file says WHO holds it: owner, kind (p1, tests, mutation, ai_batch), pid,
host and start time, so a person (or a waiting job) can read who to wait for.
It is a plain file created with O_EXCL, so two jobs cannot both win.

  * STALE after 3 hours (the issue's rule), or at once when the holder's process
    is gone on this machine. A stale lock is taken over; it never blocks for ever.
  * WAITERS leave a small marker file while they wait, so a long job that can
    pause (the AI batch) knows somebody is queued and steps aside.
  * A job that cannot get the lock within its wait (30 minutes by default) is
    told who holds it and exits; it does not hang.
  * `HEAVY_JOB_LOCK=off` disables it (CI); `HEAVY_JOB_LOCK=<path>` moves it.

Standard library only (psutil is used when installed, to see a dead holder), so
scripts outside the backend can import it. No document text is ever written.
"""
from __future__ import annotations

import json
import os
import platform
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

#: A lock older than this is stale (the issue's rule).
STALE_AFTER_SECONDS = 3 * 3600
#: How long a job waits for the lock before giving up and saying who holds it.
DEFAULT_WAIT_SECONDS = 30 * 60
POLL_SECONDS = 5.0
#: The Windows location the owner named; elsewhere the user's temp folder.
WINDOWS_LOCK = Path("D:/project/.heavy-job.lock")
KINDS = ("p1", "tests", "mutation", "ai_batch")


class HeavyJobBusy(RuntimeError):
    """The lock is held by someone else and the wait ran out."""

    def __init__(self, holder: dict | None, waited: float) -> None:
        self.holder = holder
        self.waited = waited
        super().__init__(describe(holder, waited))


def disabled() -> bool:
    return os.environ.get("HEAVY_JOB_LOCK", "").strip().lower() in ("off", "0", "false", "no")


def lock_path() -> Path:
    env = os.environ.get("HEAVY_JOB_LOCK", "").strip()
    if env and not disabled():
        return Path(env)
    if os.name == "nt" and WINDOWS_LOCK.parent.is_dir():
        return WINDOWS_LOCK
    import tempfile
    return Path(tempfile.gettempdir()) / "rag-intelligence-heavy-job.lock"


def _now() -> float:
    return time.time()


def _pid_alive(pid: int) -> bool | None:
    """True/False, or None when it cannot be told."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return bool(psutil.pid_exists(pid))
    except Exception:  # noqa: BLE001 - "cannot tell" is a valid answer
        return None


def read(path: Path | None = None) -> dict | None:
    """The holder's record, or None when nobody holds it (or the file is unreadable)."""
    p = path or lock_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_stale(record: dict | None, now: float | None = None) -> bool:
    """A lock with no readable record, one older than 3 hours, or one whose
    process is gone on THIS machine is stale."""
    if record is None:
        return True
    now = _now() if now is None else now
    started = record.get("started_epoch")
    if not isinstance(started, (int, float)) or now - started > STALE_AFTER_SECONDS:
        return True
    if record.get("host") == platform.node() and isinstance(record.get("pid"), int):
        if _pid_alive(record["pid"]) is False:
            return True
    return False


def describe(record: dict | None, waited: float = 0.0) -> str:
    if record is None:
        return "the heavy-job lock could not be taken"
    age = max(0, int((_now() - float(record.get("started_epoch", _now()))) / 60))
    return (f"{record.get('kind', 'a heavy job')} is running ({record.get('owner', 'unknown owner')}, "
            f"started {age} min ago); waited {int(waited / 60)} min")


class Handle:
    def __init__(self, path: Path, token: str, record: dict) -> None:
        self.path, self.token, self.record = path, token, record
        self.released = False

    def release(self) -> None:
        """Remove the lock only if it is still OURS (a stale takeover by someone
        else must not be undone by our late release)."""
        if self.released:
            return
        self.released = True
        current = read(self.path)
        if current is not None and current.get("token") == self.token:
            try:
                self.path.unlink()
            except OSError:
                pass


def _record(kind: str, owner: str | None) -> tuple[str, dict]:
    token = uuid.uuid4().hex
    now = _now()
    return token, {
        "token": token, "kind": kind,
        "owner": owner or os.environ.get("HEAVY_JOB_OWNER") or f"pid {os.getpid()}",
        "pid": os.getpid(), "host": platform.node(),
        "started_epoch": now,
        "started_at": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def try_acquire(kind: str, owner: str | None = None, path: Path | None = None) -> Handle | None:
    """One attempt. A stale lock is removed first. None when someone else holds it."""
    if disabled():
        return Handle(Path(os.devnull), "off", {"kind": kind})
    p = path or lock_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for _ in range(2):
        token, record = _record(kind, owner)
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if is_stale(read(p)):
                try:
                    p.unlink()
                except OSError:
                    return None
                continue
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        return Handle(p, token, record)
    return None


def _waiter_dir(path: Path) -> Path:
    return path.parent


def _waiter_prefix(path: Path) -> str:
    return path.name + ".wait."


def waiters(path: Path | None = None) -> list[dict]:
    """Jobs currently waiting for the lock (live markers only)."""
    if disabled():
        return []
    p = path or lock_path()
    out = []
    try:
        names = list(_waiter_dir(p).glob(_waiter_prefix(p) + "*"))
    except OSError:
        return out
    for f in names:
        rec = read(f)
        if is_stale(rec):
            try:
                f.unlink()
            except OSError:
                pass
            continue
        out.append(rec)
    return out


def acquire(kind: str, owner: str | None = None, wait_seconds: float = DEFAULT_WAIT_SECONDS,
            poll_seconds: float = POLL_SECONDS, path: Path | None = None,
            say=print, sleep=time.sleep) -> Handle:
    """Take the lock, waiting up to `wait_seconds`. Raises HeavyJobBusy, naming
    the holder, when the wait runs out."""
    handle = try_acquire(kind, owner, path)
    if handle is not None:
        return handle
    p = path or lock_path()
    token, record = _record(kind, owner)
    marker = p.parent / (_waiter_prefix(p) + token)
    try:
        marker.write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        marker = None
    started = _now()
    told = False
    try:
        while True:
            holder = read(p)
            waited = _now() - started
            if not told:
                say(f"waiting for the heavy-job lock: {describe(holder, waited)}")
                told = True
            if waited >= wait_seconds:
                raise HeavyJobBusy(holder, waited)
            sleep(min(poll_seconds, max(0.0, wait_seconds - waited)))
            handle = try_acquire(kind, owner, p)
            if handle is not None:
                return handle
    finally:
        if marker is not None:
            try:
                marker.unlink()
            except OSError:
                pass


@contextmanager
def held(kind: str, owner: str | None = None, wait_seconds: float = DEFAULT_WAIT_SECONDS, **kw):
    handle = acquire(kind, owner, wait_seconds, **kw)
    try:
        yield handle
    finally:
        handle.release()


def wait_seconds_from_env() -> float:
    """`HEAVY_JOB_WAIT_MINUTES` (default 30)."""
    try:
        return max(0.0, float(os.environ["HEAVY_JOB_WAIT_MINUTES"]) * 60)
    except (KeyError, ValueError):
        return DEFAULT_WAIT_SECONDS


#: Exit code of a script that gave up waiting (EX_TEMPFAIL).
EXIT_BUSY = 75


def run_locked(kind: str, fn, owner: str | None = None, say=print) -> int:
    """Run `fn()` (returns an exit code) while holding the lock. If the lock
    cannot be had within the wait, say who holds it and return EXIT_BUSY
    instead of hanging. The lock is released on any exit, Ctrl+C included."""
    try:
        with held(kind, owner, wait_seconds_from_env(), say=say):
            return fn()
    except HeavyJobBusy as exc:
        say(f"BUSY: gave up waiting. {exc}")
        say("Nothing was run. Try again when that job finishes, or remove a lock you know is dead.")
        return EXIT_BUSY
