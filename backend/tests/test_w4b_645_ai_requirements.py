"""#645: AI requirement extraction - the model reads, code checks every field.

A fake model stands in for qwen3.5 (no weights needed). Every test is about
what CODE does with what the model said: a quote not in the passage, a figure
not in its quote, a unit read wrongly (11 psi as 11 %), a standard that is not
the one quoted - each is `could_not_read` with its reason, never kept. Clean
items are kept once, however many overlapping passages repeat them.

Invented text only. Mutations M4301-M4310.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app import access, ai_requirements as air, ai_task_runner as runner, db
from app.config import settings
from app.reasoning_provider import Response


class Fake:
    def __init__(self, replies, model="qwen3.5:2b"):
        self.requested_model = model
        self.replies = list(replies)
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        reply = self.replies.pop(0)
        return Response(text=reply, provider="ollama", model_tag=self.requested_model, digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w4b645.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


PASSAGE = ("6.1 Accumulation shall not exceed 10 % of the design pressure for a single relief "
           "device. 6.2 The test pressure shall be 150 psig. 6.3 Bolting shall comply with "
           "ASTM A193 grade B7. Allowable accumulation, psi (kPa) 10.0 (69)")


def item(**over) -> dict:
    base = {"quote": "Accumulation shall not exceed 10 % of the design pressure",
            "subject": "accumulation", "operator": "<=", "value": "10", "value_to": None,
            "unit": "%", "condition": None, "standard": None}
    return {**base, **over}


def reply(*items) -> str:
    return json.dumps({"requirements": list(items)})


def run(*items, text=PASSAGE):
    return air.extract(text, provider=Fake([reply(*items)]), use_cache=False)


# ------------------------------------------------- what code keeps

def test_a_clean_item_is_kept():
    out = run(item())
    assert [r["value"] for r in out["requirements"]] == ["10"]
    assert out["could_not_read"] == []


def test_the_same_requirement_read_twice_is_kept_once():
    out = run(item(), item())
    assert len(out["requirements"]) == 1 and out["merged"] == 1


# ------------------------------------------------- what code refuses

def test_a_quote_not_in_the_passage_is_not_kept():
    out = run(item(quote="Accumulation shall never exceed 10 % of design pressure"))
    assert out["requirements"] == []
    assert out["could_not_read"] == [{"passage": 0, "reason": air.QUOTE_NOT_IN_SOURCE}]


def test_a_figure_not_in_its_quote_is_not_kept():
    out = run(item(value="12"))
    assert out["could_not_read"][0]["reason"] == air.FIGURE_NOT_IN_QUOTE


def test_psi_read_as_percent_is_not_kept():
    """#653 in the extraction lane: the row says 10.0 psi, the model says 10 %."""
    out = run(item(quote="Allowable accumulation, psi (kPa) 10.0 (69)", value="10.0", unit="%"))
    assert out["requirements"] == []
    assert out["could_not_read"][0]["reason"] == air.UNIT_NOT_IN_QUOTE


def test_gauge_read_as_absolute_is_not_kept():
    out = run(item(quote="The test pressure shall be 150 psig", value="150", unit="psia",
                   operator="="))
    assert out["could_not_read"][0]["reason"] == air.UNIT_NOT_IN_QUOTE


def test_a_correctly_converted_figure_is_kept():
    out = run(item(quote="Allowable accumulation, psi (kPa) 10.0 (69)", value="69", unit="kPa"))
    assert len(out["requirements"]) == 1


def test_a_named_standard_must_be_the_one_quoted():
    good = run(item(quote="Bolting shall comply with ASTM A193 grade B7", value=None, unit=None,
                    operator="none", standard="ASTM A193"))
    assert len(good["requirements"]) == 1
    wrong = run(item(quote="Bolting shall comply with ASTM A193 grade B7", value=None, unit=None,
                     operator="none", standard="ASTM A194"))
    assert wrong["could_not_read"][0]["reason"] == air.STANDARD_NOT_IN_QUOTE
    unread = run(item(quote="Bolting shall comply with ASTM A193 grade B7", value=None, unit=None,
                      operator="none", standard="the bolting rules"))
    assert unread["could_not_read"][0]["reason"] == air.STANDARD_NOT_READ


def test_a_reply_the_runner_cannot_read_is_listed_not_guessed():
    out = air.extract(PASSAGE, provider=Fake(["not json", "still not json"]), use_cache=False)
    assert out["requirements"] == []
    assert out["could_not_read"][0]["reason"].startswith("the reply was not valid")


# ------------------------------------------------- the passages (#644 b)

def test_long_text_is_read_in_passages_under_the_word_limit():
    sentence = "The wall thickness shall be at least 6 mm for every line in this class. "
    passages = air.split_passages(sentence * 60)
    assert len(passages) > 1
    assert all(len(p.split()) <= air.MAX_WORDS for p in passages)
    assert " ".join(passages).split() == (sentence * 60).split()


def test_every_passage_is_a_task_the_runner_accepts():
    long_text = "Each support shall carry 5 kN. " * 120
    passages = air.split_passages(long_text)
    fake = Fake([reply() for _ in passages])
    out = air.extract(long_text, provider=fake, use_cache=False)
    assert out["passages"] == len(passages) == len(fake.packets)
    assert out["could_not_read"] == []


# ------------------------------------------------- the pilot script refuses the live file

def _pilot():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "pilot_ai_requirements.py"
    spec = importlib.util.spec_from_file_location("pilot645", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pilot_refuses_a_live_database_path(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(str(live)).close()
    with pytest.raises(SystemExit, match="refusing"):
        _pilot().refuse_live(live)


def test_the_pilot_scores_value_and_unit_not_the_number_alone():
    pilot = _pilot()
    truth = [{"value": "4", "unit": "psi"}, {"value": "116", "unit": "%"}]
    found = [{"value": "28", "unit": "kPa"},          # 4 psi, converted: true
             {"value": "4", "unit": "%"},             # number right, unit wrong: not true
             {"value": "116", "unit": "%"}]
    s = pilot.score(found, truth)
    assert s == {"true": 2, "found": 3, "true_found": 2, "found_correct": 2}
    # the wrong unit alone does not find the psi item
    s = pilot.score([{"value": "4", "unit": "%"}, {"value": "116", "unit": "%"}], truth)
    assert s == {"true": 2, "found": 2, "true_found": 1, "found_correct": 1}
