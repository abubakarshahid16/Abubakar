"""The AI reviewer has its own engine setting (`agent_review_engine`), and a normal review is not barred
under per_task when every one of its own engine settings is local (owner, 12 Nov 2026). Invented values; no socket."""

from __future__ import annotations

import pytest

from app import agent_review_gate, agent_review_kind, local_engine_bar
from app import reasoning_provider as rp
from app.config import settings
from tests.test_agent_review_job import run_job, start, world  # noqa: F401 - fixture


@pytest.fixture
def open_lane(monkeypatch):
    """Both egress flags and a key present; every engine local; env flags cleared so settings decide."""
    for name in (
        "REASONING_PROVIDER",
        "AGENT_REVIEW_ENGINE",
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "agent_review_engine", "ollama")
    for name in local_engine_bar.REVIEW_ENGINE_SETTINGS:
        monkeypatch.setattr(settings, name, "ollama")
    return monkeypatch


def _barred_during_job() -> bool:
    """What `review_jobs` does: wrap the job, ask whether the bar is up inside it."""
    return local_engine_bar.barring_local_engine(local_engine_bar.active)()


def test_a_per_task_review_with_every_engine_local_is_not_barred(open_lane):  # (a)
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    assert local_engine_bar.is_claude_lane_run() is False
    assert _barred_during_job() is False


@pytest.mark.parametrize("name", local_engine_bar.REVIEW_ENGINE_SETTINGS)
def test_a_per_task_review_with_one_engine_on_claude_is_barred(open_lane, name):  # (b)
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    open_lane.setattr(settings, name, "claude")
    assert local_engine_bar.is_claude_lane_run() is True
    assert _barred_during_job() is True


def test_a_per_task_review_with_a_claude_engine_but_a_closed_lane_is_not_barred(
    open_lane,
):
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    open_lane.setattr(settings, "match_engine", "claude")
    open_lane.setattr(settings, "standards_reader_enabled", False)
    assert local_engine_bar.is_claude_lane_run() is False


def test_the_reviewers_own_engine_does_not_bar_a_normal_review(open_lane):
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    open_lane.setattr(settings, "agent_review_engine", "claude")
    assert local_engine_bar.is_claude_lane_run() is False


def test_under_claude_a_review_is_barred_as_before(open_lane):  # (c)
    open_lane.setattr(settings, "reasoning_provider", "claude")
    assert local_engine_bar.is_claude_lane_run() is True
    assert _barred_during_job() is True


@pytest.mark.parametrize("own", ["ollama", "claude", ""])
def test_under_ollama_the_reviewer_gate_is_closed_whatever_its_engine_says(
    open_lane, own
):  # (d)
    open_lane.setattr(settings, "reasoning_provider", "ollama")
    open_lane.setattr(settings, "agent_review_engine", own)
    assert agent_review_gate.claude_lane_open() is False
    assert local_engine_bar.is_claude_lane_run() is False


def test_under_per_task_with_the_reviewer_engine_on_claude_the_gate_is_open(
    open_lane,
):  # (e)
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    open_lane.setattr(settings, "agent_review_engine", "claude")
    from app import agent_claude

    assert agent_claude.gate_open() is True
    assert agent_review_gate.claude_lane_open() is True


def test_under_per_task_with_the_reviewer_engine_on_ollama_the_gate_is_closed(
    open_lane,
):  # (f)
    open_lane.setattr(settings, "reasoning_provider", "per_task")
    open_lane.setattr(
        settings, "match_engine", "claude"
    )  # another step's engine does not open it
    from app import agent_claude

    assert agent_claude.gate_open() is False
    assert agent_review_gate.claude_lane_open() is False
    assert rp.claude_unavailable_for_task("ollama")[0] == rp.UNAVAILABLE_TASK_LOCAL


def test_an_injected_env_is_obeyed_exactly_for_the_reviewer_gate():
    from app import agent_claude

    per_task = {"REASONING_PROVIDER": "per_task"}
    assert agent_claude.gate_open(per_task) is False
    assert agent_claude.gate_open({**per_task, "AGENT_REVIEW_ENGINE": "claude"}) is True
    assert (
        agent_claude.gate_open(
            {"REASONING_PROVIDER": "ollama", "AGENT_REVIEW_ENGINE": "claude"}
        )
        is False
    )


# ---- the bar is decided PER JOB: the AI reviewer's real job function --------------------------------------------------


def _watch_bar(monkeypatch):
    """Record, from inside the real agent job, whether the bar is up and whether a local-engine step is refused."""
    seen = {}

    def decide(*_a, **_k):
        seen["active"] = local_engine_bar.active()
        seen["refused"] = local_engine_bar.refuses("probe-local-step")
        seen["stated"] = [r["step"] for r in local_engine_bar.stated()]
        from tests.test_agent_review_job import reading

        return reading()

    monkeypatch.setattr(agent_review_kind, "decide", decide)
    return seen


def _lane(monkeypatch, provider, own):
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    monkeypatch.setattr(settings, "agent_review_engine", own)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in local_engine_bar.REVIEW_ENGINE_SETTINGS:
        monkeypatch.setattr(settings, name, "ollama")


def test_the_real_agent_job_is_barred_when_its_own_gate_is_open_and_every_other_engine_is_local(
    world,  # noqa: F811
    monkeypatch,
):
    seen = _watch_bar(monkeypatch)
    _lane(monkeypatch, "per_task", "claude")
    _run_id, job_id = start()
    run_job(job_id)
    assert seen["active"] is True and seen["refused"] is True
    assert "probe-local-step" in seen["stated"]


def test_the_real_agent_job_is_not_barred_when_its_own_gate_is_closed(
    world,  # noqa: F811
    monkeypatch,
):
    seen = _watch_bar(monkeypatch)
    _lane(monkeypatch, "per_task", "ollama")
    _run_id, job_id = start()
    run_job(job_id)
    assert seen["active"] is False and seen["refused"] is False


def test_the_real_agent_job_under_ollama_is_not_barred_whatever_its_setting_says(
    world,  # noqa: F811
    monkeypatch,
):
    seen = _watch_bar(monkeypatch)
    _lane(monkeypatch, "ollama", "claude")
    _run_id, job_id = start()
    run_job(job_id)
    assert seen["active"] is False


def test_every_engine_setting_given_to_the_lane_gate_is_in_the_one_list():
    """A new per-step engine setting passed to `claude_for_task` / `claude_unavailable_for_task` must be in
    `REVIEW_ENGINE_SETTINGS`, or a review that uses it would run unbarred. Scans the source."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    call = re.compile(
        r"(?:claude_for_task|claude_unavailable_for_task)\(\s*([^,)]+(?:\([^)]*\))?)"
    )
    names, helpers = set(), set()
    for path in app.rglob("*.py"):
        if path.name == "reasoning_provider.py":
            continue
        for arg in call.findall(path.read_text()):
            m = re.fullmatch(r"(?:settings\.)([a-z_]+)", arg.strip())
            if m:
                names.add(m.group(1))
            else:
                helpers.add((path.name, arg.strip()))
    # a helper such as `engine_setting()` / `_engine()` / `opinion_engine()` reads one setting: resolve by its body
    for fname, arg in helpers:
        helper = arg.rstrip("()").split(".")[-1]
        if not helper or not helper.isidentifier():
            continue
        for path in app.rglob("*.py"):
            m = re.search(
                rf"def {helper}\(\)[^\n]*:\n(?:\s+\"\"\".*?\"\"\"\n)?\s+return[^\n]*?settings\.([a-z_]+)",
                path.read_text(),
                re.S,
            )
            if m:
                names.add(m.group(1))
    names.discard(
        "agent_review_engine"
    )  # the AI reviewer's own job, decided separately per job
    assert names, "the scan found nothing: the test is vacuous"
    assert names <= set(local_engine_bar.REVIEW_ENGINE_SETTINGS), sorted(
        names - set(local_engine_bar.REVIEW_ENGINE_SETTINGS)
    )
