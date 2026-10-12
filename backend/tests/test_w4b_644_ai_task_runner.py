"""#644: the AI task runner. A fake provider stands in for the model, so these
run without model weights; what is proved is the RUNNER: strict JSON, one
retry, cache, queue order, pausing, unloading, the model as a setting."""
from __future__ import annotations

import json
import threading

import pytest

from app import access, ai_task_runner as runner, db, model_transport, progress
from app.config import settings
from app.reasoning_provider import Response, ProviderRefused

SCHEMA = {"type": "object", "required": ["quote", "kind"],
          "properties": {"quote": {"type": "string"},
                         "kind": {"type": "string", "enum": ["rule", "note"]}}}
TEXT = "The vessel shall be hydrotested at 1.5 times the design pressure."


def _check(data, text):
    return [] if data["quote"] in text else ["the quote is not in the text"]


SPEC = runner.TaskSpec(name="t_kind", version="v1", instruction="Say what kind of sentence this is.",
                       schema=SCHEMA, check=_check)


class Fake:
    """Replies are consumed in order; a reply that is an exception is raised."""

    def __init__(self, replies, model="qwen3.5:2b"):
        self.requested_model = model
        self.replies = list(replies)
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        text, finish = reply if isinstance(reply, tuple) else (reply, "stop")
        return Response(text=text, provider="ollama", model_tag=self.requested_model, digest="d",
                        finish_reason=finish, prompt_sha256=packet.sha256)


GOOD = json.dumps({"quote": "hydrotested at 1.5 times", "kind": "rule"})


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w4b644.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    runner.TASKS.clear()
    runner.register(SPEC)
    progress.clear()
    yield
    runner.TASKS.clear()


# ----------------------------------------------------------------- one task

def test_a_valid_reply_is_kept_and_the_schema_is_sent_to_the_engine():
    fake = Fake([GOOD])
    result = runner.run_task(SPEC, TEXT, provider=fake)
    assert result.state == runner.STATE_OK and result.data["kind"] == "rule"
    assert fake.packets[0].json_schema == SCHEMA
    assert fake.packets[0].temperature == 0.0


@pytest.mark.parametrize("bad, why", [
    ("", "empty"), ("not json at all", "not JSON"), ("[1, 2]", "not a JSON object"),
    (json.dumps({"quote": "x"}), "required"),
    (json.dumps({"quote": "x", "kind": "poem"}), "allowed"),
    (json.dumps({"quote": "invented words", "kind": "rule"}), "not in the text"),
])
def test_an_invalid_reply_twice_is_could_not_read_never_a_guess(bad, why):
    fake = Fake([bad, bad])
    result = runner.run_task(SPEC, TEXT, provider=fake)
    assert result.state == runner.STATE_COULD_NOT_READ
    assert result.data is None and why in result.reason
    assert len(fake.packets) == runner.MAX_ATTEMPTS == 2


def test_one_retry_names_what_was_wrong_and_can_succeed():
    fake = Fake([json.dumps({"quote": "made up", "kind": "rule"}), GOOD])
    result = runner.run_task(SPEC, TEXT, provider=fake)
    assert result.state == runner.STATE_OK and result.attempts == 2
    assert "rejected: the quote is not in the text" in fake.packets[1].prompt
    assert "rejected" not in fake.packets[0].prompt


def test_a_reply_cut_off_by_the_length_cap_is_not_kept():
    result = runner.run_task(SPEC, TEXT, provider=Fake([(GOOD, "length"), (GOOD, "length")]))
    assert result.state == runner.STATE_COULD_NOT_READ and "cut off" in result.reason


def test_a_late_or_unreachable_model_is_a_named_state_without_a_retry():
    late = Fake([ProviderRefused("ollama: ReadTimeout: x")])
    result = runner.run_task(SPEC, TEXT, provider=late)
    assert result.state == runner.STATE_COULD_NOT_READ and "in time" in result.reason
    down = Fake([ProviderRefused("ollama: ConnectError: secret passage text")])
    result = runner.run_task(SPEC, TEXT, provider=down)
    assert "could not be reached" in result.reason and "secret passage" not in result.reason
    assert len(down.packets) == 1


def test_text_over_the_word_limit_is_refused_by_name_with_no_model_call(monkeypatch):
    monkeypatch.setattr(settings, "ai_task_max_words", 5)
    fake = Fake([GOOD])
    result = runner.run_task(SPEC, TEXT, provider=fake)
    assert result.state == runner.STATE_COULD_NOT_READ and "words" in result.reason
    assert fake.packets == []
    assert runner.run_task(SPEC, "  ", provider=fake).reason == "there was no text to read"


# ----------------------------------------------------------------- the cache

def test_a_cache_hit_makes_no_model_call_and_a_failure_is_not_cached():
    first = Fake([GOOD])
    assert runner.run_task(SPEC, TEXT, provider=first).cached is False
    second = Fake([])                       # would raise IndexError on any call
    again = runner.run_task(SPEC, TEXT, provider=second)
    assert again.cached is True and again.data == json.loads(GOOD) and second.packets == []
    # A failure is retried next time.
    bad = Fake(["x", "x"])
    runner.run_task(SPEC, "Another sentence entirely here.", provider=bad)
    retry = Fake([GOOD.replace("hydrotested at 1.5 times", "Another sentence")])
    got = runner.run_task(SPEC, "Another sentence entirely here.", provider=retry)
    assert got.state == runner.STATE_OK and len(retry.packets) == 1


def test_the_cache_key_changes_with_the_version_the_model_and_the_text():
    base = runner.cache_key(SPEC, "m1", TEXT)
    assert base != runner.cache_key(SPEC, "m2", TEXT)
    assert base != runner.cache_key(SPEC, "m1", TEXT + " x")
    newer = runner.TaskSpec(**{**SPEC.__dict__, "version": "v2"})
    assert base != runner.cache_key(newer, "m1", TEXT)


# ------------------------------------------------- the model is a setting

def test_two_models_run_the_same_task_through_one_runner(monkeypatch):
    small, big = Fake([GOOD], "qwen3.5:2b"), Fake([GOOD], "qwen3.5:4b")
    a = runner.run_task(SPEC, TEXT, provider=small)
    b = runner.run_task(SPEC, TEXT, provider=big)
    assert (a.model, b.model) == ("qwen3.5:2b", "qwen3.5:4b")
    assert a.cached is False and b.cached is False      # separate cache entries
    assert runner.run_task(SPEC, TEXT, provider=Fake([], "qwen3.5:4b")).cached is True


def test_the_default_model_is_the_setting_not_code(monkeypatch):
    assert settings.ai_task_model == "qwen3.5:2b"
    monkeypatch.setattr(settings, "ai_task_model", "qwen3.5:4b")
    assert runner.make_provider().requested_model == "qwen3.5:4b"
    assert runner.make_provider("bigger:70b").requested_model == "bigger:70b"
    assert runner.make_provider().timeout == settings.ai_task_timeout_s


# ----------------------------------------------------------------- the queue

def _ok(i=0):
    return GOOD.replace("hydrotested at 1.5 times", "vessel")


def test_the_queue_runs_one_job_at_a_time_in_order_and_records_each_result():
    ids = [runner.enqueue("t_kind", f"The vessel number {i} shall hold.", ref=f"r{i}") for i in range(3)]
    fake = Fake([_ok(), "bad", "bad", _ok()])
    summary = runner.run_batch(provider=fake, pause=lambda: None, unload=lambda p: None)
    assert (summary["ran"], summary["ok"], summary["could_not_read"], summary["remaining"]) == (3, 2, 1, 0)
    states = [runner.job(i)["state"] for i in ids]
    assert states == ["done", "could_not_read", "done"]
    assert runner.job(ids[1])["data"] is None and runner.job(ids[1])["reason"]
    assert runner.job(ids[0])["ref"] == "r0"


def test_a_second_concurrent_batch_is_refused():
    runner.enqueue("t_kind", TEXT)
    seen = {}

    def pause_then_try_again():
        seen["second"] = runner.run_batch(provider=Fake([]), pause=lambda: None)
        return "stop here"

    first = runner.run_batch(provider=Fake([]), pause=pause_then_try_again, unload=lambda p: None)
    assert seen["second"]["paused"] == "another batch is already running"
    assert first["paused"] == "stop here" and first["remaining"] == 1


def test_a_paused_batch_leaves_the_jobs_queued_and_says_why():
    job_id = runner.enqueue("t_kind", TEXT)
    fake = Fake([GOOD])
    summary = runner.run_batch(provider=fake, pause=lambda: "pytest is running", unload=lambda p: None)
    assert summary["paused"] == "pytest is running" and summary["ran"] == 0
    assert runner.job(job_id)["state"] == "queued" and fake.packets == []


def test_an_unregistered_task_in_the_queue_is_could_not_read_not_a_crash():
    job_id = runner.enqueue("t_kind", TEXT)
    runner.TASKS.clear()
    runner.run_batch(provider=Fake([]), pause=lambda: None, unload=lambda p: None)
    assert runner.job(job_id)["state"] == "could_not_read"
    with pytest.raises(KeyError):
        runner.enqueue("never_registered", TEXT)


def test_a_job_left_running_by_a_dead_process_is_picked_up_again():
    job_id = runner.enqueue("t_kind", TEXT)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE ai_task_queue SET state = 'running', updated_at = '2020-01-01T00:00:00Z'")
    runner.run_batch(provider=Fake([GOOD]), pause=lambda: None, unload=lambda p: None)
    assert runner.job(job_id)["state"] == "done"


# ----------------------------------------------- the gate: the user comes first

def test_the_gate_yields_to_chat_then_heavy_work_then_low_memory(monkeypatch):
    plenty = 8_000_000_000
    assert runner.pause_reason(chat_active=0, heavy=None, free_ram=plenty) is None
    assert "chat" in runner.pause_reason(chat_active=1, heavy="pytest", free_ram=0)
    assert runner.pause_reason(chat_active=0, heavy="run_p1", free_ram=0) == "run_p1 is running"
    low = runner.pause_reason(chat_active=0, heavy=None, free_ram=1_000_000_000)
    assert "1.0 GB of memory is free" in low and "1.5 GB" in low
    assert runner.pause_reason(chat_active=0, heavy=None, free_ram=1_500_000_000) is None


def test_a_chat_request_in_progress_counts_as_active():
    assert progress.active_count() == 0
    progress.start("req-1")
    assert progress.active_count() == 1
    assert "chat" in runner.pause_reason(heavy=None, free_ram=8_000_000_000)
    progress.finish("req-1")
    assert progress.active_count() == 0


def test_heavy_work_is_found_in_the_process_list(monkeypatch):
    import psutil

    class P:
        def __init__(self, pid, cmd):
            self.info = {"pid": pid, "cmdline": cmd}

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([
        P(1, ["python", "run.py"]), P(2, ["python", "-m", "pytest", "tests"])]))
    assert runner.heavy_work_running() == "pytest"
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([
        P(3, ["python", "eval/p1/run_p1.py"])]))
    assert runner.heavy_work_running() == "run_p1"
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([P(4, ["python", "run.py"])]))
    assert runner.heavy_work_running() is None


# ----------------------------------------------- keep_alive: 10m in the batch, 0 at the end

def test_the_model_stays_loaded_during_a_batch_and_is_unloaded_at_the_end(monkeypatch):
    sent = []
    monkeypatch.setattr(model_transport, "post_json",
                        lambda path, body, timeout: sent.append(model_transport.with_runner_options(body)) or {})
    runner.enqueue("t_kind", TEXT)

    class Provider(Fake):
        def reason(self, packet):
            sent.append(model_transport.with_runner_options({"model": "m", "prompt": "p"}))
            return super().reason(packet)

    runner.run_batch(provider=Provider([GOOD]), pause=lambda: None)
    assert [b["keep_alive"] for b in sent] == ["10m", 0]
    assert sent[1]["model"] == "qwen3.5:2b" and sent[1]["prompt"] == ""
    # Outside a batch every other call keeps the setting.
    assert model_transport.with_runner_options({})["keep_alive"] == settings.ollama_keep_alive


def test_the_keep_alive_override_is_per_thread():
    seen = {}
    with model_transport.keep_alive_override("10m"):
        thread = threading.Thread(
            target=lambda: seen.update(other=model_transport.with_runner_options({})["keep_alive"]))
        thread.start()
        thread.join()
        assert model_transport.with_runner_options({})["keep_alive"] == "10m"
    assert seen["other"] == settings.ollama_keep_alive


def test_nothing_is_unloaded_when_no_model_call_was_made():
    runner.run_task(SPEC, TEXT, provider=Fake([GOOD]))        # cached now
    runner.enqueue("t_kind", TEXT)
    unloaded = []
    runner.run_batch(provider=Fake([]), pause=lambda: None, unload=lambda p: unloaded.append(p))
    assert unloaded == []
