"""The invented scanned pump sheet really has no text layer and the same key (fix 7 proof)."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent / "fixtures" / "synthetic"
SCANNED = HERE / "pf1_scanned"
TEXT = HERE / "pf1"


def test_the_scanned_sheet_has_no_text_layer_and_the_same_pages_as_the_text_one():
    scanned = pymupdf.open(SCANNED / "pf1-t01-pump.scanned.datasheet.pdf")
    text = pymupdf.open(TEXT / "pf1-t01-pump.datasheet.pdf")
    assert len(scanned) == len(text) == 2
    assert all(not page.get_text().strip() for page in scanned)
    assert all(page.get_images() for page in scanned)  # the pages are pictures
    assert any(page.get_text().strip() for page in text)  # and the original is not


def test_the_scanned_key_is_the_text_versions_key_under_its_own_name():
    scanned = json.loads((SCANNED / "pf1-t01-pump.scanned.key.json").read_text())
    text = json.loads((TEXT / "pf1-t01-pump.key.json").read_text())
    assert scanned["name"] == "pf1-t01-pump-scanned"
    assert scanned["items"] == text["items"]
    assert scanned["source"] == "invented"
