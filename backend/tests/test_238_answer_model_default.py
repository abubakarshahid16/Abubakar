"""Order 238.2: the 35B model is the default answer model; a machine without it is told plainly.

The defaults are read from the field definitions, not from `settings`, so a developer's own
`backend/.env` (which may pin another model) cannot change what is being tested.
"""

from __future__ import annotations

import pytest

from app import answer_model_notice, metrics
from app.config import Settings, settings
from tests.test_metrics_host_telemetry import (  # noqa: F401
    _metrics,
    corpus_and_identities,
    temp_storage,
)

THE_35B = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL"


def test_the_default_answer_model_is_the_35b():
    assert Settings.model_fields["answer_model"].default == THE_35B


def test_the_default_small_task_model_stays_small():
    """Order 238: the 2B model keeps the small tasks unless a run proves the 35B is needed."""
    assert Settings.model_fields["ai_task_model"].default == "qwen3.5:2b"


def test_the_memory_the_default_asks_for_is_about_24_gb():
    need = Settings.model_fields["answer_model_ram_bytes"].default
    assert 22_000_000_000 < need <= 26_000_000_000


def _models(**more):
    return {
        "embed_model": "e5-small",
        "embed_model_present": True,
        "reranker_model": "reranker",
        "reranker_present": True,
        "answer_model": settings.answer_model,
        "answer_model_reachable": True,
        "answer_model_installed": True,
        "answer_model_loaded": False,
        "ollama_error": None,
        **more,
    }


def test_an_engine_without_the_model_gets_a_warning_that_names_the_model_and_the_fallback():
    [warning] = answer_model_notice.warnings(
        _models(answer_model_installed=False), host=True
    )
    assert warning["code"] == "answer_model_not_installed"
    assert warning["severity"] == "warning"
    assert settings.answer_model in warning["message"]
    assert f"ollama pull {settings.answer_model}" in warning["message"]
    assert answer_model_notice.EARLIER_DEFAULT in warning["message"]
    assert "Quoted answers are unaffected" in warning["message"]


def test_someone_who_is_not_the_operator_gets_the_consequence_and_the_remedy_without_the_name():
    [warning] = answer_model_notice.warnings(
        _models(answer_model_installed=False), host=False
    )
    assert settings.answer_model not in warning["message"]
    assert "cannot run" in warning["message"] and "administrator" in warning["message"]


@pytest.mark.parametrize(
    "info",
    [
        _models(),  # installed
        _models(
            answer_model_reachable=False, answer_model_installed=False
        ),  # engine down
    ],
)
def test_an_installed_model_or_an_unreachable_engine_adds_no_warning(info):
    assert answer_model_notice.warnings(info, host=True) == []


def test_the_dashboard_payload_carries_it_and_only_the_operator_sees_the_model_name(
    corpus_and_identities,  # noqa: F811
    monkeypatch,
):
    """Through the real endpoint: the warning is in `warnings` for both callers."""
    monkeypatch.setattr(
        metrics, "models", lambda: _models(answer_model_installed=False)
    )
    client, _, _ = corpus_and_identities
    admin = [
        w
        for w in _metrics(client, "admin_user")["warnings"]
        if w["code"] == "answer_model_not_installed"
    ]
    engineer = [
        w
        for w in _metrics(client, "engineer")["warnings"]
        if w["code"] == "answer_model_not_installed"
    ]
    assert len(admin) == 1 and len(engineer) == 1
    assert settings.answer_model in admin[0]["message"]
    assert settings.answer_model not in engineer[0]["message"]
