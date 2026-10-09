"""#645: AI requirement extraction - the model reads, code checks every field.

A fake model stands in for qwen3.5 (no weights needed). Every test is about
what CODE does with what the model said. The model LOCATES a requirement (its
quote); code checks the quote is in the passage, then READS the figures and
the standards from it. The model's own value, unit and standard fields are
hints: when they disagree with code, code wins and the item is flagged.
Items are kept once, however many overlapping passages repeat them.

Invented text only. Mutations M4301-M4314.
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

def figs(out) -> list[list[tuple]]:
    return [[(f["value"], f["unit"], f["operator"]) for f in r["figures"]]
            for r in out["requirements"]]


def test_a_clean_item_is_kept_with_the_figure_code_read():
    out = run(item())
    assert figs(out) == [[("10", "%", "<=")]]
    assert out["requirements"][0]["flags"] == []
    assert out["could_not_read"] == []


def test_the_same_requirement_read_twice_is_kept_once():
    out = run(item(), item())
    assert len(out["requirements"]) == 1 and out["merged"] == 1


# ------------------------------------------------- AI locates, code reads (owner, #645)

MIN_PASSAGE = "7.2 The overlap on sound laminate shall be minimum 50 mm in every repair."


def test_a_quote_whose_model_value_is_null_still_gives_its_figure():
    """THE DIAGNOSED DEFECT: the model found the sentence and left value and
    unit null, so nothing could be scored. Code reads it from the quote."""
    out = run(item(quote="The overlap on sound laminate shall be minimum 50 mm",
                   value=None, unit=None, operator="range"), text=MIN_PASSAGE)
    assert figs(out) == [[("50", "mm", ">=")]]
    assert out["requirements"][0]["flags"] == []


def test_a_model_value_that_disagrees_loses_to_code_and_is_flagged():
    out = run(item(quote="The overlap on sound laminate shall be minimum 50 mm",
                   value="30", unit="mm", operator=">="), text=MIN_PASSAGE)
    assert figs(out) == [[("50", "mm", ">=")]]
    assert out["requirements"][0]["flags"] == [air.MODEL_VALUE_DISAGREED]


def test_a_bracketed_conversion_is_one_quantity_not_two():
    passage = "4.1 The inlet pressure shall not exceed 16 psi (110 kPa) at any time."
    out = run(item(quote="The inlet pressure shall not exceed 16 psi (110 kPa)",
                   value=None, unit=None), text=passage)
    assert figs(out) == [[("16", "psi", "<=")]]


def test_a_quote_with_two_figures_keeps_both_and_a_range_keeps_both_ends():
    passage = "3.1 The film shall be 25-30 microns thick and cure for at least 7 days."
    out = run(item(quote="The film shall be 25-30 microns thick and cure for at least 7 days",
                   value=None, unit=None), text=passage)
    assert [(v, u) for v, u, _ in figs(out)[0]] == [("25", "microns"), ("30", "microns"),
                                                     ("7", "days")]


def test_a_quote_with_no_figure_stays_a_figure_less_requirement():
    out = run(item(quote="Bolting shall comply with ASTM A193 grade B7", value=None, unit=None,
                   operator="none"))
    assert figs(out) == [[]]


def test_psi_read_as_percent_is_read_as_psi_and_flagged():
    """#653 in the extraction lane: the row says 10.0 psi, the model says 10 %.
    Code reads psi from the quote; the model's percent is flagged."""
    out = run(item(quote="Allowable accumulation, psi (kPa) 10.0 (69)", value="10.0", unit="%"))
    assert figs(out) == [[("10", "psi", None)]]
    assert out["requirements"][0]["flags"] == [air.MODEL_VALUE_DISAGREED]


def test_gauge_read_as_absolute_is_flagged():
    out = run(item(quote="The test pressure shall be 150 psig", value="150", unit="psia",
                   operator="="))
    assert figs(out) == [[("150", "psig", None)]]
    assert out["requirements"][0]["flags"] == [air.MODEL_VALUE_DISAGREED]


def test_a_correctly_converted_model_value_agrees():
    out = run(item(quote="Allowable accumulation, psi (kPa) 10.0 (69)", value="69", unit="kPa"))
    assert out["requirements"][0]["flags"] == []


# ------------------------------------------------- what code refuses

def test_a_quote_not_in_the_passage_is_not_kept():
    out = run(item(quote="Accumulation shall never exceed 10 % of design pressure"))
    assert out["requirements"] == []
    assert out["could_not_read"] == [{"passage": 0, "reason": air.QUOTE_NOT_IN_SOURCE}]


# ------------------------------------------------- standards: code reads, the model hints

BOLTING = "Bolting shall comply with ASTM A193 grade B7"


def test_the_standard_is_read_from_the_quote():
    out = run(item(quote=BOLTING, value=None, unit=None, operator="none", standard="ASTM A193"))
    assert out["requirements"][0]["standards"] == ["ASTM A193"]
    assert out["requirements"][0]["flags"] == []


def test_a_word_for_nothing_in_the_standard_field_is_no_hint():
    """THE DIAGNOSED DEFECT: the string "None" in the standard field rejected
    real requirements (a whole FCAW clause was lost in the pilot)."""
    for nothing in ("None", "null", "N/A", ""):
        out = run(item(standard=nothing))
        assert len(out["requirements"]) == 1, nothing
        assert out["requirements"][0]["flags"] == []


def test_a_standard_the_quote_does_not_cite_is_flagged_not_dropped():
    for named in ("ASTM A194", "a standard drawing"):
        out = run(item(quote=BOLTING, value=None, unit=None, operator="none", standard=named))
        assert len(out["requirements"]) == 1, named
        assert out["requirements"][0]["flags"] == [air.MODEL_STANDARD_DISAGREED], named


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
    def found(*pairs):   # items as extract() returns them: the figures CODE read
        return [{"figures": [{"value": v, "unit": u}]} for v, u in pairs]

    s = pilot.score(found(("28", "kPa"),     # 4 psi, converted: true
                          ("4", "%"),        # number right, unit wrong: not true
                          ("116", "%")), truth)
    assert s == {"true": 2, "found": 3, "true_found": 2, "found_correct": 2}
    # the wrong unit alone does not find the psi item
    s = pilot.score(found(("4", "%"), ("116", "%")), truth)
    assert s == {"true": 2, "found": 2, "true_found": 1, "found_correct": 1}
    # the model's own value fields are never scored, only code's figures
    s = pilot.score([{"value": "4", "unit": "psi", "figures": []}], truth)
    assert s["found"] == 0
