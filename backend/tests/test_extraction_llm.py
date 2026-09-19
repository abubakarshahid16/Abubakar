"""The no-lying gate: an imagined fact cannot pass, an unstable one drops."""
import json

from app.extraction_llm import accept, extract_page, parse_response
from app.extraction_score import score

PAGE = """8  Set pressure        340 psig (By Contractor, as per Code)
10 Density at relieving temper.   23.55 Kg/m3
44 Cap type   Bolted"""


def fake(facts):
    return lambda prompt: json.dumps({"facts": facts})


GOOD = {"field": "Set pressure", "value": "340", "unit": "psig",
        "quote": "8  Set pressure        340 psig"}
INVENTED = {"field": "Design pressure", "value": "99", "unit": "barg",
            "quote": "Design pressure 99 barg"}
MISQUOTE = {"field": "Density at relieving temper.", "value": "99.9",
            "unit": "Kg/m3",
            "quote": "10 Density at relieving temper.   23.55 Kg/m3"}


def test_a_true_fact_passes_the_gate():
    out = extract_page(PAGE, fake([GOOD]))
    assert [f["field"] for f in out["accepted"]] == ["Set pressure"]


def test_an_invented_fact_cannot_pass():
    out = extract_page(PAGE, fake([GOOD, INVENTED]))
    assert len(out["accepted"]) == 1
    assert out["rejected"][0]["reason"] == "quote_not_on_page"


def test_a_value_not_in_its_own_quote_is_rejected():
    out = extract_page(PAGE, fake([MISQUOTE]))
    assert out["accepted"] == []
    assert out["rejected"][0]["reason"] == "value_not_in_quote"


def test_quotes_survive_whitespace_differences():
    squeezed = {**GOOD, "quote": "8 Set pressure 340 psig"}
    assert extract_page(PAGE, fake([squeezed]))["accepted"]


def test_malformed_model_output_yields_reason_never_guess():
    out = extract_page(PAGE, lambda p: "not json at all")
    assert out == {"accepted": [], "rejected": [],
                   "error": "model_malformed"}


def test_two_runs_must_agree_or_the_fact_drops():
    first = fake([GOOD, {"field": "Cap type", "value": "Bolted",
                         "unit": None, "quote": "44 Cap type   Bolted"}])
    second = fake([GOOD])
    out = extract_page(PAGE, first, second)
    assert [f["field"] for f in out["accepted"]] == ["Set pressure"]
    assert any(r["reason"] == "model_unstable" for r in out["rejected"])


def test_parse_drops_entries_without_field_or_quote():
    facts, err = parse_response(
        json.dumps({"facts": [{"value": "1"}, GOOD]}))
    assert err is None and len(facts) == 1


def test_scorer_counts_hits_misses_and_inventions():
    truth = [{"field": "Set pressure", "value": "340"},
             {"field": "Cap type", "value": "Bolted"}]
    got = [{"field": "SET PRESSURE", "value": "340"},
           {"field": "Ghost", "value": "1"}]
    s = score(got, truth)
    assert s["read_correctly"] == 1 and s["recall"] == 0.5
    assert len(s["extra_or_wrong"]) == 1
