"""#680: one shared lock for the heavy jobs (P1, test run, mutation run, AI batch).

Mutations: M4401-M4414, `python scripts/mutation_check.py --only M4401 ...`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import access, ai_task_runner as runner, db, heavy_lock, progress
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def lock(tmp_path, monkeypatch):
    """A real lock file in a temp folder, with the lock switched ON (the suite
    pins it off so no test can touch the machine's real lock)."""
    path = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(path))
    return path


def _age(path: Path, seconds: float) -> None:
    rec = json.loads(path.read_text())
    rec["started_epoch"] -= seconds
    path.write_text(json.dumps(rec))


# ------------------------------------------------------------ take and release

def test_the_lock_says_who_holds_it_and_release_removes_it(lock):
    h = heavy_lock.try_acquire("p1", owner="session 2")
    rec = json.loads(lock.read_text())
    assert (rec["kind"], rec["owner"]) == ("p1", "session 2")
    assert rec["pid"] and rec["started_at"].endswith("Z")
    h.release()
    assert not lock.exists()


def test_a_second_job_cannot_take_a_held_lock(lock):
    first = heavy_lock.try_acquire("p1")
    assert heavy_lock.try_acquire("tests") is None
    assert json.loads(lock.read_text())["kind"] == "p1"
    first.release()
    assert heavy_lock.try_acquire("tests") is not None


def test_a_late_release_does_not_remove_someone_elses_lock(lock):
    old = heavy_lock.try_acquire("p1")
    _age(lock, heavy_lock.STALE_AFTER_SECONDS + 60)
    new = heavy_lock.try_acquire("tests")
    assert new is not None
    old.release()
    assert json.loads(lock.read_text())["kind"] == "tests"
    new.release()


# ----------------------------------------------------------------- staleness

def test_a_lock_older_than_three_hours_is_stale_and_taken_over(lock):
    heavy_lock.try_acquire("p1")
    _age(lock, 3 * 3600 + 5)
    taken = heavy_lock.try_acquire("tests")
    assert taken is not None and json.loads(lock.read_text())["kind"] == "tests"


def test_a_lock_just_under_three_hours_still_holds(lock):
    heavy_lock.try_acquire("p1")
    _age(lock, 3 * 3600 - 60)
    assert heavy_lock.try_acquire("tests") is None


def test_a_lock_whose_process_is_gone_is_stale_at_once(lock):
    done = subprocess.run([sys.executable, "-c", "import os;print(os.getpid())"],
                          capture_output=True, text=True)
    dead_pid = int(done.stdout)
    rec = {"token": "x", "kind": "p1", "owner": "gone", "pid": dead_pid,
           "host": heavy_lock.socket.gethostname(), "started_epoch": time.time()}
    lock.write_text(json.dumps(rec))
    assert heavy_lock.try_acquire("tests") is not None


def test_an_unreadable_lock_file_does_not_block_for_ever(lock):
    lock.write_text("not json")
    assert heavy_lock.try_acquire("tests") is not None


# -------------------------------------------------------------------- waiting

def test_a_waiting_job_gets_the_lock_when_the_holder_finishes(lock):
    holder = heavy_lock.try_acquire("p1")
    calls = []

    def fake_sleep(_s):
        calls.append(1)
        holder.release()

    got = heavy_lock.acquire("tests", wait_seconds=60, poll_seconds=1, sleep=fake_sleep, say=lambda m: None)
    assert json.loads(lock.read_text())["kind"] == "tests" and len(calls) == 1
    got.release()


def test_a_job_that_waits_too_long_is_told_who_holds_the_lock(lock, monkeypatch):
    heavy_lock.try_acquire("p1", owner="session 2")
    clock = {"t": time.time()}
    monkeypatch.setattr(heavy_lock, "_now", lambda: clock["t"])

    def advance(s):
        clock["t"] += s

    said = []
    with pytest.raises(heavy_lock.HeavyJobBusy) as busy:
        heavy_lock.acquire("tests", wait_seconds=30 * 60, poll_seconds=300, sleep=advance, say=said.append)
    assert "p1 is running" in str(busy.value) and "session 2" in str(busy.value)
    assert busy.value.waited >= 30 * 60
    assert said and "waiting for the heavy-job lock" in said[0]


def test_the_default_wait_is_thirty_minutes():
    assert heavy_lock.DEFAULT_WAIT_SECONDS == 30 * 60


def test_a_waiter_is_visible_while_it_waits_and_gone_after(lock):
    heavy_lock.try_acquire("p1")
    seen = {}

    def peek(_s):
        seen["during"] = [w["kind"] for w in heavy_lock.waiters()]
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        heavy_lock.acquire("tests", wait_seconds=60, poll_seconds=1, sleep=peek, say=lambda m: None)
    assert seen["during"] == ["tests"]
    assert heavy_lock.waiters() == []


def test_run_locked_gives_up_with_a_code_and_never_runs_the_job(lock, monkeypatch):
    heavy_lock.try_acquire("p1", owner="session 2")
    monkeypatch.setenv("HEAVY_JOB_WAIT_MINUTES", "0")
    ran = []
    said = []
    rc = heavy_lock.run_locked("tests", lambda: ran.append(1) or 0, say=said.append)
    assert rc == heavy_lock.EXIT_BUSY == 75 and ran == []
    assert any("session 2" in m for m in said)


def test_run_locked_releases_on_error_and_on_ctrl_c(lock):
    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        heavy_lock.run_locked("tests", boom)
    assert not lock.exists()

    def stop():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        heavy_lock.run_locked("tests", stop)
    assert not lock.exists()


def test_run_locked_holds_the_lock_while_the_job_runs(lock):
    seen = {}
    heavy_lock.run_locked("mutation", lambda: seen.update(rec=json.loads(lock.read_text())) or 0)
    assert seen["rec"]["kind"] == "mutation" and not lock.exists()


def test_the_lock_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAVY_JOB_LOCK", "off")
    assert heavy_lock.try_acquire("p1") is not None
    assert heavy_lock.try_acquire("tests") is not None
    assert heavy_lock.waiters() == []


# ------------------------------------------------- the real scripts take it

def _hold(lock) -> None:
    heavy_lock.try_acquire("ai_batch", owner="another session")


@pytest.mark.parametrize("script, args", [
    ("eval/p1/run_p1.py", []),
    ("scripts/test_changed.py", ["--base", "HEAD"]),
    ("scripts/mutation_check.py", ["--only", "M1350"]),
])
def test_each_heavy_script_waits_for_the_lock_and_gives_up_with_75(lock, script, args):
    _hold(lock)
    env = {**__import__("os").environ, "HEAVY_JOB_LOCK": str(lock), "HEAVY_JOB_WAIT_MINUTES": "0"}
    done = subprocess.run([sys.executable, str(REPO / script), *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 75, done.stdout + done.stderr
    assert "another session" in done.stdout


# ---------------------------------------------------------------- AI batch

@pytest.fixture
def ai_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w8680.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    runner.TASKS.clear()
    progress.clear()
    yield
    runner.TASKS.clear()


def _spec():
    return runner.TaskSpec(name="t_lock", version="v1", instruction="x",
                           schema={"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
                           check=lambda d, t: [])


class _Fake:
    requested_model = "m"

    def __init__(self, on_call=None):
        self.on_call = on_call

    def reason(self, packet):
        from app.reasoning_provider import Response
        if self.on_call:
            self.on_call()
        return Response(text='{"a": "b"}', provider="ollama", model_tag="m", digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


def test_an_ai_batch_does_not_start_while_another_heavy_job_holds_the_lock(lock, ai_storage):
    runner.register(_spec())
    runner.enqueue("t_lock", "text")
    heavy_lock.try_acquire("p1", owner="session 2")
    fake = _Fake(on_call=lambda: pytest.fail("the model was called under a held lock"))
    summary = runner.run_batch(provider=fake, pause=lambda: None, unload=lambda p: None)
    assert summary["ran"] == 0 and "p1 is running" in summary["paused"]
    assert summary["remaining"] == 1


def test_an_ai_batch_holds_the_lock_while_it_runs_and_frees_it_after(lock, ai_storage):
    runner.register(_spec())
    runner.enqueue("t_lock", "text")
    seen = {}
    fake = _Fake(on_call=lambda: seen.update(rec=json.loads(lock.read_text())))
    summary = runner.run_batch(provider=fake, pause=lambda: None, unload=lambda p: None)
    assert summary["ran"] == 1
    assert seen["rec"]["kind"] == "ai_batch"
    assert not lock.exists()


def test_an_ai_batch_frees_the_lock_even_when_it_fails(lock, ai_storage):
    runner.register(_spec())
    runner.enqueue("t_lock", "text")

    def boom():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner.run_batch(provider=_Fake(on_call=boom), pause=lambda: None, unload=lambda p: None)
    assert not lock.exists()


def test_an_ai_batch_steps_aside_when_a_heavy_job_is_waiting(lock, ai_storage):
    marker = lock.parent / (lock.name + ".wait.abc")
    marker.write_text(json.dumps({"kind": "p1", "started_epoch": time.time(),
                                  "host": "elsewhere", "pid": 1}))
    reason = runner.pause_reason(chat_active=0, heavy=None, free_ram=64 * 10**9)
    assert reason == "p1 is waiting for the machine"


# ------------------------------------------------------- mutation selection

def test_changed_mode_selects_only_mutations_of_changed_files():
    import mutation_check
    from mutations._base import Mutation

    def mk(i, rel, target):
        return Mutation(id=i, phase=1, description="d", path=REPO / rel, anchor="a",
                        replacement="b", target=target)

    ms = [mk("A", "backend/app/one.py", "tests/test_one.py"),
          mk("B", "backend/app/two.py", "tests/test_two.py"),
          mk("C", "backend/app/three.py", "tests/test_three.py")]
    chosen = mutation_check.select_changed(ms, ["backend/app/one.py", "backend/tests/test_three.py"])
    assert [m.id for m in chosen] == ["A", "C"]
    assert mutation_check.select_changed(ms, ["README.md"]) == []


# ---------------------------------------------------------------- the docs

def test_claude_md_documents_the_lock_and_the_batching_rules():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert ".heavy-job.lock" in text
    assert "HEAVY_JOB_LOCK" in text
    assert "once per merge round" in text.lower()
    assert "--changed" in text
