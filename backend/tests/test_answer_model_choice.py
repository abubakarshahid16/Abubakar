"""The local answer model in use (planner's browser check of update 10, 26 Nov 2026): ANSWER_MODEL in .env named the 35B and the
general review's default, Chat and the technical-query drafts would have used it. Now a configured model PROVEN unusable here (too
large, a cloud name, not a model file) is replaced by the code's default, everywhere, and the screens say why. The engine's list is
faked: nothing is loaded and no engine is called. Invented model names only."""

from __future__ import annotations

import inspect

import pytest

from app import answer_model_choice, chat_model, model_transport
from app import reasoning_provider as rp
from app.aim_review import local_model
from app.config import settings

HUGE = "invented-huge:35b"
FITS = "invented-fits:9b"
CODE_DEFAULT = answer_model_choice.code_default()


def _list(*entries):
    return {"models": [dict(e) for e in entries]}


@pytest.fixture(autouse=True)
def fresh():
    answer_model_choice.forget()
    yield
    answer_model_choice.forget()


@pytest.fixture
def engine(monkeypatch):
    calls: list[str] = []
    listed = {
        "models": [
            {"name": HUGE, "size": 24_000_000_000, "digest": "d1"},
            {"name": FITS, "size": 6_000_000_000, "digest": "d2"},
            {
                "name": "invented-stub:9b",
                "size": 400,
                "digest": "d3",
                "remote_host": "https://invented.example",
            },
        ]
    }

    def get_json(path, *, timeout, required=True):
        calls.append(path)
        assert path == "/api/tags"
        return listed

    def no_post(*_a, **_k):
        raise AssertionError("a model was called")

    monkeypatch.setattr(model_transport, "get_json", get_json)
    monkeypatch.setattr(model_transport, "post_json", no_post)
    return calls


def test_a_too_large_answer_model_with_nothing_stored_falls_back_to_the_code_default_everywhere(
    engine, monkeypatch
):
    """Fails on the code before this fix: every one of these named the 35B."""
    from app import review_model_setting

    monkeypatch.setattr(settings, "answer_model", HUGE)
    monkeypatch.setattr(review_model_setting, "default_choice", lambda: None)
    choice = answer_model_choice.resolve()
    assert choice.name == CODE_DEFAULT and choice.fell_back
    assert HUGE in choice.why and answer_model_choice.TOO_LARGE in choice.why
    assert local_model.model_name() == CODE_DEFAULT  # the general review on Local only
    assert (
        rp.OllamaProvider().requested_model == CODE_DEFAULT
    )  # technical-query drafts and every local provider call
    local = next(
        m
        for m in chat_model.available_models()["models"]
        if m["id"] == chat_model.LOCAL
    )
    assert local["model"] == CODE_DEFAULT  # Chat's local model
    assert (
        answer_model_choice.ram_bytes() == answer_model_choice.code_default_ram_bytes()
    )


def test_a_model_that_fits_is_used_as_configured(engine, monkeypatch):
    monkeypatch.setattr(settings, "answer_model", FITS)
    choice = answer_model_choice.resolve()
    assert choice.name == FITS and not choice.fell_back
    assert rp.OllamaProvider().requested_model == FITS
    assert answer_model_choice.ram_bytes() == settings.answer_model_ram_bytes


@pytest.mark.parametrize(
    "configured, reason",
    [
        (
            "invented-stub:9b",
            answer_model_choice.NOT_A_FILE,
        ),  # a remote entry with an ordinary name
        (
            "invented:cloud",
            answer_model_choice.NOT_A_FILE,
        ),  # a cloud name, even unlisted
    ],
)
def test_a_model_that_is_not_a_file_here_falls_back(
    engine, monkeypatch, configured, reason
):
    monkeypatch.setattr(settings, "answer_model", configured)
    choice = answer_model_choice.resolve()
    assert choice.name == CODE_DEFAULT and reason in choice.why


def test_a_list_read_that_times_out_uses_the_code_default_and_is_kept_only_for_a_moment(
    monkeypatch,
):
    """Review of update 11, N3 and R2-2: fail closed. While the engine's list cannot be read nothing is proven usable, so the 9B
    is used, never the configured model (on live that was the 35B). A hung engine costs its timeout once: the failure is kept
    `FAILED_SECONDS`, still meaning the 9B, and the list is asked again after it."""
    asked: list[str] = []
    clock = [1000.0]

    def timed_out(path, *, timeout, required=True):
        asked.append(path)
        raise TimeoutError("invented")

    monkeypatch.setattr(model_transport, "get_json", timed_out)
    monkeypatch.setattr(answer_model_choice.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(settings, "answer_model", HUGE)
    choice = answer_model_choice.resolve()
    assert choice.name == CODE_DEFAULT and answer_model_choice.LIST_UNREAD in choice.why
    assert (
        rp.OllamaProvider().requested_model == CODE_DEFAULT
    )  # the kept failure still means the 9B
    assert len(asked) == 1  # a hung engine is asked once, not on every call
    clock[0] += answer_model_choice.FAILED_SECONDS + 1
    assert (
        answer_model_choice.name() == CODE_DEFAULT and len(asked) == 2
    )  # asked again after the moment


def test_a_configured_model_the_engine_does_not_list_is_not_used(engine, monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "invented-missing:9b")
    choice = answer_model_choice.resolve()
    assert (
        choice.name == CODE_DEFAULT and answer_model_choice.NOT_INSTALLED in choice.why
    )


def test_every_other_reader_names_the_model_in_use(engine, monkeypatch):
    """Review of update 11, N5: the run outcome, the AI task fallback, the old local reviewer's model A and the answer labels
    read the model in use, never the configured one."""
    from app import agent_review_local, ai_task_runner, aim_review_jobs

    monkeypatch.setattr(settings, "answer_model", HUGE)
    monkeypatch.setattr(settings, "agent_review_local_model_a", "")
    assert agent_review_local.models_from_settings()[0] == CODE_DEFAULT
    source = inspect.getsource(aim_review_jobs) + inspect.getsource(ai_task_runner)
    assert "settings.answer_model" not in source.replace("settings.answer_model_", "")


def test_the_code_default_never_asks_the_engine_and_the_list_is_read_once_a_minute(
    engine, monkeypatch
):
    monkeypatch.setattr(settings, "answer_model", CODE_DEFAULT)
    assert answer_model_choice.name() == CODE_DEFAULT and engine == []
    monkeypatch.setattr(settings, "answer_model", HUGE)
    for _ in range(5):
        answer_model_choice.name()
    assert engine == ["/api/tags"]


def test_the_administrators_saved_default_still_wins(engine, monkeypatch):
    from app import review_model_setting

    monkeypatch.setattr(settings, "answer_model", HUGE)
    monkeypatch.setattr(review_model_setting, "default_choice", lambda: FITS)
    assert local_model.model_name() == FITS


def test_the_ai_steps_warning_names_the_model_that_would_really_run_never_the_35b(
    engine, monkeypatch
):
    """Planner note 26 Nov 2026 15:15, item 7: with ANSWER_MODEL naming the 35B and the small AI-steps model missing, the
    dashboard warning names the model the steps would really run on (the 9B), never the 35B."""
    from app import ai_task_runner

    def listed(path, *, timeout, required=True):
        return {
            "models": [
                {"name": HUGE, "size": 24_000_000_000, "digest": "d1"},
                {"name": CODE_DEFAULT, "size": 6_000_000_000, "digest": "d2"},
            ]
        }

    monkeypatch.setattr(model_transport, "get_json", listed)
    monkeypatch.setattr(settings, "answer_model", HUGE)
    monkeypatch.setattr(settings, "ai_task_model", "invented-small:2b")
    ai_task_runner._tags_cache.clear()
    (warning,) = ai_task_runner.warnings()
    assert CODE_DEFAULT in warning["message"] and HUGE not in warning["message"]


def test_a_stored_scope_reading_counts_from_the_model_in_use_or_the_configured_one_unless_proven_unusable(
    engine, monkeypatch
):
    """Review of update 11, R2-4: `rule_part_scope` asks `answer_model_choice.trusted_reader`, not the configured ANSWER_MODEL
    alone. The model in use counts; the configured model counts unless it is PROVEN unusable (too large here: the 35B's stored
    readings do not set scope); an engine that cannot be asked proves nothing, so stored readings keep counting."""
    import inspect

    from app import rule_part_scope

    source = inspect.getsource(rule_part_scope)
    assert (
        "settings.answer_model" not in source and "trusted_reader(model[0])" in source
    )
    monkeypatch.setattr(
        settings, "answer_model", HUGE
    )  # listed by `engine`, 24 GB: proven too large
    assert answer_model_choice.trusted_reader(CODE_DEFAULT) is True  # the model in use
    assert answer_model_choice.trusted_reader(HUGE) is False
    assert answer_model_choice.trusted_reader("invented-other:1b") is False
    monkeypatch.setattr(settings, "answer_model", FITS)
    assert answer_model_choice.trusted_reader(FITS) is True

    def down(*_a, **_k):
        raise ConnectionError("invented")

    answer_model_choice.forget()
    monkeypatch.setattr(model_transport, "get_json", down)
    monkeypatch.setattr(settings, "answer_model", "invented-reader:4b")
    assert (
        answer_model_choice.trusted_reader("invented-reader:4b") is True
    )  # nothing proven: its stored readings stand
