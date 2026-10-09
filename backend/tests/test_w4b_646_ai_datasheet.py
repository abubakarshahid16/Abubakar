"""#646: AI datasheet reading - the model LOCATES each field, code READS its value.

A fake model stands in for any model (no weights; #683). Code checks the
label and the value are on the page as whole words, reads the figure and unit
from the verified value text, keeps text values as text, and merges repeats.

Invented datasheet only. Mutations M4515-M4519.
"""
from __future__ import annotations

import json

import pytest

from app import access, ai_datasheet, db
from app.config import settings
from app.reasoning_provider import Response


class Fake:
    def __init__(self, *replies, model="test-model"):
        self.requested_model = model
        self.replies = [json.dumps({"fields": list(r)}) for r in replies]

    def reason(self, packet):
        return Response(text=self.replies.pop(0), provider="ollama", model_tag=self.requested_model,
                        digest="d", finish_reason="stop", prompt_sha256=packet.sha256)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ds.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


PAGE = ("RELIEF VALVE DATA SHEET  Tag: PSV-0001  Set pressure 10 barg (1000 kPag)  "
        "Over pressure % 10  Design temperature 120 °C  Body material By Contractor  "
        "Bellows Yes")


def read(*fields):
    return ai_datasheet.read_page(PAGE, page=2, provider=Fake(list(fields)), use_cache=False)


def f(label, value):
    return {"label": label, "value_text": value}


def test_a_located_value_is_read_by_code_with_its_unit():
    out = read(f("Set pressure", "10 barg (1000 kPag)"), f("Design temperature", "120 °C"))
    got = [(x["label"], [(g["value"], g["unit"]) for g in x["figures"]], x["page"]) for x in out["fields"]]
    assert got == [("Set pressure", [("10", "barg")], 2),          # one quantity, not two
                   ("Design temperature", [("120", "c")], 2)]
    assert out["could_not_read"] == []


def test_a_text_value_stays_text_never_a_number():
    out = read(f("Body material", "By Contractor"), f("Bellows", "Yes"))
    assert [(x["value_text"], x["figures"]) for x in out["fields"]] == [
        ("By Contractor", []), ("Yes", [])]


def test_a_value_not_on_the_page_is_not_kept():
    out = read(f("Set pressure", "12 barg"))
    assert out["fields"] == []
    assert out["could_not_read"] == [{"passage": 0, "reason": ai_datasheet.VALUE_NOT_ON_PAGE}]


def test_a_label_not_on_the_page_is_not_kept():
    out = read(f("Cold differential test pressure", "10 barg"))
    assert out["could_not_read"][0]["reason"] == ai_datasheet.LABEL_NOT_ON_PAGE


def test_part_of_a_word_is_not_on_the_page():
    """"10 bar" inside "10 barg" would lose the gauge marking."""
    out = read(f("Set pressure", "10 bar"))
    assert out["fields"] == []
    assert out["could_not_read"][0]["reason"] == ai_datasheet.VALUE_NOT_ON_PAGE


def test_the_same_field_read_twice_is_kept_once():
    out = read(f("Over pressure %", "10"), f("Over pressure %", "10"))
    assert len(out["fields"]) == 1
