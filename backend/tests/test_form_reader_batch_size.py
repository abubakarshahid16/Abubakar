"""The form reader's per-call batch size is a setting (default 8), measured on
the PC: 25 fields per call never finished inside the local model's call limit;
8 did. Fake model only; invented text."""
from __future__ import annotations

import json

import pytest

from app import form_reader_run as fr
from app.config import Settings, settings


def _count_calls(monkeypatch, size: int) -> list[str]:
    monkeypatch.setattr(settings, "form_reader_batch_size", size)
    asked: list[str] = []

    def model(prompt: str) -> str:
        asked.append(prompt)
        return json.dumps({"fields": []})
    subjects = [f"invented field {i}" for i in range(30)]
    printed = "Casing note: 6 in\n" + "\n".join(f"{s}: 1" for s in subjects)  # every label printed
    run = fr.read_document({1: printed}, None, model_call=model, extra_subjects=subjects)
    assert run["form_batch_size"] == size
    return asked


def test_the_default_is_eight():
    assert Settings().form_reader_batch_size == 8


def test_the_setting_decides_how_many_calls_a_page_takes(monkeypatch):
    # 32 fields (the generic 2 + 30): two runs per batch
    assert len(_count_calls(monkeypatch, 8)) == 2 * 4
    assert len(_count_calls(monkeypatch, 25)) == 2 * 2


@pytest.mark.parametrize("bad", [0, -1, 26])
def test_a_size_outside_one_to_twenty_five_is_refused_at_startup(bad):
    with pytest.raises(ValueError, match="FORM_READER_BATCH_SIZE"):
        Settings(form_reader_batch_size=bad)
