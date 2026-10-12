"""#680 "one lock for the heavy jobs": each entry deletes one part;
backend/tests/test_w8_680_heavy_lock.py must notice."""
from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_w8_680_heavy_lock.py"
_TAG = ("w8_680", "heavy_lock")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


H = APP / "heavy_lock.py"
MUTATIONS: tuple[Mutation, ...] = (
    _m(4401, "a lock never goes stale by age", H,
       "    if not isinstance(started, (int, float)) or now - started > STALE_AFTER_SECONDS:\n",
       "    if not isinstance(started, (int, float)):\n", "three_hours"),
    _m(4402, "the stale limit is not three hours", H,
       "STALE_AFTER_SECONDS = 3 * 3600\n", "STALE_AFTER_SECONDS = 10 * 3600\n", "three_hours"),
    _m(4403, "a lock whose process is gone still blocks", H,
       '        if _pid_alive(record["pid"]) is False:\n', "        if False:\n", "process_is_gone"),
    _m(4404, "two jobs can both create the lock", H,
       "os.O_CREAT | os.O_EXCL | os.O_WRONLY", "os.O_CREAT | os.O_WRONLY", "cannot_take_a_held_lock"),
    _m(4405, "a late release removes someone else's lock", H,
       '        if current is not None and current.get("token") == self.token:\n',
       "        if current is not None:\n", "late_release"),
    _m(4406, "the default wait is not thirty minutes", H,
       "DEFAULT_WAIT_SECONDS = 30 * 60\n", "DEFAULT_WAIT_SECONDS = 5 * 60\n", "thirty_minutes"),
    _m(4407, "a waiter's marker is left behind", H,
       "        if marker is not None:\n            try:\n                marker.unlink()",
       "        if False:\n            try:\n                marker.unlink()", "waiter"),
    _m(4408, "the busy message does not name the holder's job", H,
       "    return (f\"{record.get('kind', 'a heavy job')} is running",
       "    return (f\"a heavy job is running", "who_holds"),
    _m(4409, "a job that gave up waiting crashes instead of exiting 75", H,
       "    except HeavyJobBusy as exc:\n        say(f\"BUSY", "    except ZeroDivisionError as exc:\n        say(f\"BUSY",
       "gives_up"),
    _m(4410, "the lock is not released after the job", H,
       "    finally:\n        handle.release()\n", "    finally:\n        pass\n", "releases"),
    _m(4411, "P1 does not take the lock", REPO / "eval" / "p1" / "run_p1.py",
       'raise SystemExit(heavy_lock.run_locked("p1", main))', "raise SystemExit(main())", "each_heavy_script"),
    _m(4412, "the changed-test run does not take the lock", REPO / "scripts" / "test_changed.py",
       'return heavy_lock.run_locked("tests", run_all)', "return run_all()", "each_heavy_script"),
    _m(4413, "the mutation run does not take the lock", REPO / "scripts" / "mutation_check.py",
       'return heavy_lock.run_locked("mutation", lambda: _run_selected(selected))',
       "return _run_selected(selected)", "each_heavy_script"),
    _m(4414, "an AI batch takes no lock", APP / "ai_task_runner.py",
       'lock = heavy_lock.try_acquire("ai_batch", owner="ai task batch")',
       'lock = heavy_lock.Handle(heavy_lock.Path(heavy_lock.os.devnull), "off", {})', "ai_batch"),
    _m(4415, "an AI batch ignores a heavy job waiting for the machine", APP / "ai_task_runner.py",
       "    queued = heavy_lock.waiters()\n", "    queued = []\n", "steps_aside"),
    _m(4416, "--changed selects every mutation", REPO / "scripts" / "mutation_check.py",
       "        if mutated in files or files & tests:\n", "        if True:\n", "changed_mode"),
    _m(4417, "CLAUDE.md no longer says P1 runs once per merge round", REPO / "CLAUDE.md",
       "P1 on the PC runs ONCE per merge round", "P1 on the PC runs per PR", "documents"),
)
