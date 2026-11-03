"""ai_senior_review entry point (Part of #805, step 3): off by default, nothing runs, the figure door is the code's."""

from app import ai_senior_review as asr
from app.config import settings


def test_the_switch_is_off_by_default():
    assert settings.ai_senior_review_enabled is False


def test_off_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "ai_senior_review_enabled", False)
    assert asr.run_for_job("run-1", None) == {"state": asr.OFF}


def test_on_before_the_reader_exists_says_so(monkeypatch):
    monkeypatch.setattr(settings, "ai_senior_review_enabled", True)
    assert asr.run_for_job("run-1", None) == {"state": asr.NOT_BUILT}


def test_a_figure_is_decided_by_figure_compare_only():
    result = asr.figure_verdict("15 bar", "not more than 10 bar")
    assert result is not None and result.verdict is False
