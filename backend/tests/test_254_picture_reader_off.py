"""Order 254 F2 (253.2): a page both text readers read with no field is READ when the
picture reader is switched off by the owner's settings.

On the owner's M-03 run page 1 was "not counted as read: the picture reader could not be
asked", and 25 findings went to the engineer as UNREAD_PAGES. The picture reader only runs on
Claude; with `REASONING_PROVIDER=ollama` (or per_task with a local vision step) it is OFF BY
CHOICE, and the ledger said "unavailable" as if it had been wanted and failed. Now the ledger
says "switched off in the settings" for that cause and counts the page as read; a lane that was
wanted but closed (egress flags, no key), a spent page budget and a page with no text layer stay
unread. Invented text only; the model is a fake callable (no network, no Ollama).
"""

from __future__ import annotations

import pytest

from app import datasheets, page_ledger, vision_reader
from app.config import settings
from tests.test_datasheet_ai import (  # noqa: F401 - the autouse temp_storage
    FakeModel,
    _ingest,
    _use,
    temp_storage,
)

PROSE = [
    "The contractor confirms that all equipment will be supplied in accordance with",
    "the project specification and delivered to site in good condition after the",
    "factory acceptance test has been witnessed by the purchaser representative",
    "and all outstanding comments on the earlier submission have been closed out.",
]
ROWS = [("Design pressure", "23.5 barg"), ("Design temperature", "120 C")]


def _pdf(path) -> str:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for line in PROSE:
        page.insert_text((44, y), line, fontsize=10)
        y += 22
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(ROWS, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(
            pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7
        )
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _read(tmp_path, monkeypatch, **settings_over):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    for key, value in settings_over.items():
        monkeypatch.setattr(settings, key, value)
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    return doc, page_ledger.coverage(doc), page_ledger.rows(doc)[0]


def test_a_page_both_text_readers_read_is_read_when_the_picture_reader_is_off_by_choice(
    tmp_path, monkeypatch
):
    _doc, cov, row = _read(tmp_path, monkeypatch, reasoning_provider="ollama")
    assert "switched off in the settings" in row["vision_reason"]
    assert "unavailable" not in row["vision_reason"]
    assert cov["pages_not_read_into_fields"] == []
    assert cov["pages_read_no_field"] == [1]


def test_a_local_vision_step_under_per_task_is_off_by_choice_too(tmp_path, monkeypatch):
    _doc, cov, row = _read(
        tmp_path,
        monkeypatch,
        reasoning_provider="per_task",
        vision_reader_engine="ollama",
    )
    assert "switched off in the settings" in row["vision_reason"]
    assert cov["pages_not_read_into_fields"] == []


def test_a_picture_reader_that_was_wanted_but_is_closed_leaves_the_page_unread(
    tmp_path, monkeypatch
):
    # REASONING_PROVIDER=claude but the two egress flags are off: the owner meant it to run
    _, cov, row = _read(tmp_path, monkeypatch, reasoning_provider="claude")
    assert "unavailable" in row["vision_reason"]
    assert "switched off" not in row["vision_reason"]
    assert cov["pages_not_read_into_fields"] == [1]
    assert cov["pages_read_no_field"] == []


def test_a_spent_page_budget_leaves_the_page_unread(tmp_path, monkeypatch):
    _doc, cov, row = _read(
        tmp_path,
        monkeypatch,
        reasoning_provider="ollama",
        vision_max_pages_per_document=0,
    )
    assert "budget is spent" in row["vision_reason"]
    assert cov["pages_not_read_into_fields"] == [1]


def test_with_the_ai_reader_off_the_page_stays_unread_even_when_the_picture_reader_is_off(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = page_ledger.coverage(doc)
    assert cov["pages_not_read_into_fields"] == [1]
    assert cov["pages_read_no_field"] == []


@pytest.mark.parametrize(
    ("provider", "engine", "off"),
    [
        ("ollama", "claude", True),
        ("per_task", "ollama", True),
        (
            "per_task",
            "claude",
            False,
        ),  # egress flags are off by default: wanted but closed
        ("claude", "claude", False),
    ],
)
def test_switched_off_names_only_the_owners_own_settings(
    monkeypatch, provider, engine, off
):
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    monkeypatch.setattr(settings, "vision_reader_engine", engine)
    assert vision_reader.switched_off() is off
