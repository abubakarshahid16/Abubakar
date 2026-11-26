"""The local answer model in use (planner's browser check of update 10, 26 Nov 2026): ANSWER_MODEL in .env named the 35B and the
general review's default, Chat and the technical-query drafts would have used it. Now a configured model PROVEN unusable here (too
large, a cloud name, not a model file) is replaced by the code's default, everywhere, and the screens say why. The engine's list is
faked: nothing is loaded and no engine is called. Invented model names only."""

from __future__ import annotations

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


def test_when_the_engine_cannot_be_asked_nothing_is_proven_and_the_setting_stands(
    monkeypatch,
):
    def down(*_a, **_k):
        raise ConnectionError("invented")

    monkeypatch.setattr(model_transport, "get_json", down)
    monkeypatch.setattr(settings, "answer_model", HUGE)
    assert (
        answer_model_choice.resolve().name == HUGE
    )  # the run's own start check still refuses it


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
