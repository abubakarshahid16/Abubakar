"""Order 14: the PRODUCTION default runs the general review; the old engine is the one way back (`REVIEW_OLD_ENGINE_ENABLED`).

The test session pins the old engine ON (`env_isolation.TEST_PINS`: it still ships as the way back, so its tests keep testing it);
these tests read a fresh `Settings()` built from a clean environment, which is what production gets without a `.env` line.
"""

from __future__ import annotations

import pytest

from app import aim_review_gate
from app.config import Settings, settings
from tests import env_isolation


def test_the_production_default_is_the_general_review(monkeypatch):
    for name in (
        "REVIEW_OLD_ENGINE_ENABLED",
        "GENERAL_REVIEW_MAX_USD_PER_RUN",
        "GENERAL_REVIEW_LEAD_MODEL",
        "GENERAL_REVIEW_STRONG_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    clean = Settings()
    assert clean.review_old_engine_enabled is False
    assert clean.general_review_max_usd_per_run == 5.0
    assert clean.general_review_lead_model == "claude-sonnet-5-5"
    assert clean.general_review_strong_model == "claude-opus-5-5"
    monkeypatch.setattr(
        settings, "review_old_engine_enabled", clean.review_old_engine_enabled
    )
    assert aim_review_gate.method() == "general"
    assert aim_review_gate.general_on() and not aim_review_gate.old_engine_on()


def test_the_test_session_keeps_the_old_engine_on():
    assert env_isolation.TEST_PINS["review_old_engine_enabled"] is True
    assert settings.review_old_engine_enabled is True
    assert aim_review_gate.method() == "earlier"
    assert aim_review_gate.old_engine_on() and not aim_review_gate.general_on()


def test_the_way_back_reads_the_environment(monkeypatch):
    monkeypatch.setenv("REVIEW_OLD_ENGINE_ENABLED", "true")
    assert Settings().review_old_engine_enabled is True


@pytest.mark.parametrize("bad", ["15.01", "0", "-1"])
def test_the_run_meter_is_refused_above_the_run_cap_or_at_zero(monkeypatch, bad):
    monkeypatch.setenv("GENERAL_REVIEW_MAX_USD_PER_RUN", bad)
    with pytest.raises(ValueError):
        Settings()


def test_max_usd_refuses_a_value_set_past_validation(monkeypatch):
    monkeypatch.setattr(settings, "general_review_max_usd_per_run", 15.0)
    assert aim_review_gate.max_usd() == 15.0
    monkeypatch.setattr(settings, "general_review_max_usd_per_run", 20.0)
    with pytest.raises(ValueError):
        aim_review_gate.max_usd()


def test_the_models_come_from_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "general_review_lead_model", "invented-lead")
    monkeypatch.setattr(settings, "general_review_strong_model", "invented-strong")
    assert aim_review_gate.lead_model() == "invented-lead"
    assert aim_review_gate.strong_model() == "invented-strong"


def test_the_sentences_say_what_the_contract_says():
    assert aim_review_gate.AI_MARK == "AI, to be checked"
    assert aim_review_gate.AI_MARK in aim_review_gate.NO_CONTRACTOR_COPY_WORDS
    assert (
        "nothing is sent and nothing is reviewed" in aim_review_gate.LOCAL_NOT_AVAILABLE
    )
    assert aim_review_gate.EARLIER_VERSION == "Earlier version"
    assert (
        aim_review_gate.OLD_ENGINE_OFF_WORDS == "the earlier rule check is switched off"
    )
