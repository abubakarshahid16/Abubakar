"""Order 242.1: cuts to the AI reader's reply length, each behind a switch.

Off by default (the reader exactly as before). On, each cut changes only what
the model is ASKED or how a dense page is split; the gates (quote on the page,
value and label in it, two runs agree) are the same. A fake model stands in for
the engine; invented pages only.
"""

from __future__ import annotations

import json

import pytest

from app import (
    claude_datasheet,
    datasheet_ai,
    form_reader,
    form_reader_fields,
    form_reader_run,
    reader_speed,
)
from app.config import settings

PAGE = "Design pressure  10 barg\nDesign temperature  120 C\n"


@pytest.fixture
def cuts(monkeypatch):
    def set_cuts(value: str):
        monkeypatch.setattr(settings, "datasheet_reader_speed", value)

    return set_cuts


def test_nothing_changes_while_the_switch_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_reader_speed", "")
    assert reader_speed.on() == frozenset() and reader_speed.unknown() == []
    fields = form_reader_fields.field_list_for(None)
    prompt = form_reader_fields.build_prompt(fields, PAGE, 1)
    assert "at most 240 characters" in prompt and "shortest EXACT" not in prompt
    assert claude_datasheet.build_prompt(PAGE, 1, []) == claude_datasheet.PROMPT + (
        "Answer with JSON and nothing else.\n\nPAGE 1:\n" + PAGE.strip()
    )
    schema = form_reader_fields.schema_for(fields)
    assert (
        schema["properties"]["fields"]["items"]["properties"]["quote"]["maxLength"]
        == 240
    )
    assert reader_speed.version("v1") == "v1"
    assert reader_speed.dense("1 a\n" * 100) is False
    assert (
        reader_speed.form_read_labels({"pages": {1: {"accepted": [{"field": "X"}]}}})
        == {}
    )


def test_the_names_in_the_setting_are_read_and_unknown_ones_are_listed(cuts):
    cuts(" Short_Quote , presplit,nonsense ")
    assert reader_speed.on() == {"short_quote", "presplit"}
    assert reader_speed.unknown() == ["nonsense"]


def test_short_quote_asks_for_the_label_and_value_cells_only(cuts):
    cuts("short_quote")
    fields = form_reader_fields.field_list_for(None)
    prompt = form_reader_fields.build_prompt(fields, PAGE, 1)
    assert "shortest EXACT span" in prompt and "at most 240 characters" not in prompt
    schema = reader_speed.shorten_schema(form_reader_fields.schema_for(fields))
    quote = schema["properties"]["fields"]["items"]["properties"]["quote"]
    assert quote["maxLength"] == reader_speed.SHORT_QUOTE_CHARS
    merged = claude_datasheet.build_prompt(PAGE, 1, [])
    assert "shortest EXACT span" in merged
    assert "Never write a quote that is not on the page." in merged
    assert reader_speed.version("v1") == "v1+short_quote"


def test_short_quote_does_not_loosen_the_gate(cuts):
    """The cut is in the request; a quote that is not on the page is still refused."""
    cuts("short_quote")
    field = form_reader_fields.field_list_for(None)[0]
    item = {
        "value": "10",
        "unit": "barg",
        "quote": "Design pressure 99 barg",
        "status": "found",
    }
    assert form_reader.verify(field, item, PAGE, {}) is not None


class _Both:
    """One fake engine for the form reader and the whole-page reader, recording
    the whole-page prompts it was asked."""

    engine = "fake-engine"

    def __init__(self):
        self.merge_prompts = []

    def __call__(self, prompt: str) -> str:
        if "FIELDS:" in prompt:  # the form reader
            keys = [
                ln.split(":")[0].strip(" -")
                for ln in prompt.split("FIELDS:")[1].splitlines()
                if ln.startswith("  - ")
            ]
            rows = [
                {
                    "field_key": key,
                    "value": "10" if key == "design_pressure" else "",
                    "unit": "barg" if key == "design_pressure" else "",
                    "quote": "Design pressure  10 barg"
                    if key == "design_pressure"
                    else "",
                    "status": "found" if key == "design_pressure" else "not_on_page",
                }
                for key in keys
            ]
            return json.dumps({"fields": rows})
        self.merge_prompts.append(prompt)
        return json.dumps(
            {
                "facts": [
                    {
                        "field": "Design temperature",
                        "value": "120",
                        "unit": "C",
                        "quote": "Design temperature  120 C",
                        "kind": "offered",
                    }
                ]
            }
        )


def _read(monkeypatch, fake):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(
        datasheet_ai,
        "model_call_for",
        lambda engine=None, packet_shape=None: (fake, None),
    )
    return form_reader_run.read_both({1: PAGE}, None, [])


def test_skip_form_read_tells_the_whole_page_pass_what_the_form_read(cuts, monkeypatch):
    cuts("skip_form_read")
    fake = _Both()
    run = _read(monkeypatch, fake)
    prompt = fake.merge_prompts[0]
    assert (
        "SKIP THESE FIELDS" in prompt
        and "Design pressure" in prompt.split("PAGE 1:")[0]
    )
    labels = {f["field"] for f in run["pages"][1]["accepted"]}
    assert "Design pressure" in labels and "Design temperature" in labels


def test_without_the_cut_the_whole_page_pass_is_told_nothing(cuts, monkeypatch):
    cuts("")
    fake = _Both()
    _read(monkeypatch, fake)
    assert "SKIP THESE FIELDS" not in fake.merge_prompts[0]


def _dense_page(lines: int) -> str:
    return "\n".join(f"Item {n} value {n} mm" for n in range(1, lines + 1))


class _Counting:
    engine = "fake-engine"

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"facts": []})


def test_presplit_reads_a_dense_page_in_parts_without_the_whole_page_attempt(cuts):
    page = _dense_page(reader_speed.DENSE_LINES + 10)
    cuts("")
    whole = _Counting()
    datasheet_ai.read_pages({1: page}, whole)
    assert any(page in p for p in whole.prompts), (
        "off: the whole page is the first attempt"
    )
    cuts("presplit")
    parts = _Counting()
    out = datasheet_ai.read_pages({1: page}, parts)
    assert parts.prompts and not any(page in p for p in parts.prompts)
    assert len(parts.prompts) == 4  # two parts, two runs each
    assert out["pages"][1].get("error") is None


def test_a_page_with_few_numbers_is_not_split(cuts):
    cuts("presplit")
    fake = _Counting()
    datasheet_ai.read_pages({1: PAGE}, fake)
    assert any(PAGE.strip() in p for p in fake.prompts) and len(fake.prompts) == 2


def test_presplit_takes_its_threshold_from_the_setting(cuts):
    page = _dense_page(reader_speed.DENSE_LINES + 10)
    cuts("presplit")
    assert (
        reader_speed.dense(page) is True
        and reader_speed.dense_lines() == reader_speed.DENSE_LINES
    )
    cuts("presplit=80")
    assert reader_speed.on() == {"presplit"} and reader_speed.dense_lines() == 80
    assert reader_speed.dense(page) is False
    assert reader_speed.dense(_dense_page(80)) is True
    cuts("presplit=abc")  # not a number: the default stands
    assert reader_speed.dense_lines() == reader_speed.DENSE_LINES
    cuts("short_quote,presplit=0")
    assert reader_speed.dense_lines() == reader_speed.DENSE_LINES


def test_wide_cap_raises_the_whole_page_readers_answer_budget(cuts, monkeypatch):
    seen = []

    class Recorder:
        def __init__(self, model, timeout, retry_timeouts=False):
            pass

        def reason(self, packet):
            seen.append(packet.num_predict)
            raise RuntimeError("stop after the first call")

    from app import reasoning_provider

    monkeypatch.setattr(reasoning_provider, "OllamaProvider", Recorder)
    monkeypatch.setattr(datasheet_ai.settings, "datasheet_ai_reader", "ollama")
    for value, expected in (("", datasheet_ai.OLLAMA_NUM_PREDICT), ("wide_cap", 4096)):
        cuts(value)
        call, why = datasheet_ai.model_call_for("ollama")
        assert call is not None, why
        with pytest.raises(Exception):
            call("p")
        assert seen[-1] == expected
    cuts("wide_cap")
    assert reader_speed.predict_cap(2048) == 4096 and reader_speed.on() == {"wide_cap"}


def test_the_merge_pass_counts_what_it_added_and_repeated_per_page():
    """order 246.3: the per-page counts that show where the whole-page call adds nothing."""
    fact = {
        "field": "Design pressure",
        "value": "10",
        "unit": "barg",
        "kind": "offered",
    }
    other = {
        "field": "Design temperature",
        "value": "50",
        "unit": "C",
        "kind": "offered",
    }
    form = {
        "pages": {
            1: {"accepted": [dict(fact)]},
            2: {"accepted": [dict(fact)]},
            3: {"error": "x"},
        },
        "reasons": {},
        "form": {"fields": 2},
    }
    merge = {
        "pages": {
            1: {"accepted": [dict(fact), dict(other)]},
            2: {"accepted": [dict(fact)]},
            3: {"accepted": [dict(other)]},
        }
    }
    out = form_reader_run.add_merge_reading(form, merge)
    assert out["form"]["merge_by_page"] == {
        1: {"form": 1, "merge_new": 1, "merge_same": 1},
        2: {"form": 1, "merge_new": 0, "merge_same": 1},
        3: {"form": 0, "merge_new": 1, "merge_same": 0},
    }


PAGE_ONE = "Design pressure  10 barg\n"
PAGE_TWO = "Design pressure  10 barg\nOther note 77 and 88 and 99\n"


def _two_page_run(monkeypatch, fake):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(
        datasheet_ai,
        "model_call_for",
        lambda engine=None, packet_shape=None: (fake, None),
    )
    return form_reader_run.read_both({1: PAGE_ONE, 2: PAGE_TWO}, None, [])


def test_the_fully_read_pages_are_counted_for_every_run_switch_or_not(
    cuts, monkeypatch
):
    cuts("")
    fake = _Both()
    run = _two_page_run(monkeypatch, fake)
    assert run["form"]["pages_fully_agreed"] == [1]
    assert run["form"]["pages_merge_skipped"] == []
    assert (
        len(fake.merge_prompts) == 2 * 2
    )  # both pages, two runs each: nothing skipped


def test_skip_agreed_pages_makes_no_whole_page_call_for_a_fully_read_page(
    cuts, monkeypatch
):
    cuts("skip_agreed_pages")
    fake = _Both()
    run = _two_page_run(monkeypatch, fake)
    assert run["form"]["pages_merge_skipped"] == [1]
    assert all("PAGE 1:" not in p for p in fake.merge_prompts)
    assert any("PAGE 2:" in p for p in fake.merge_prompts)
    labels = {f["field"] for f in run["pages"][1]["accepted"]}
    assert "Design pressure" in labels  # the form's reading stands for the skipped page


def test_a_page_with_refused_or_no_readings_or_errors_is_never_agreed():
    texts = {1: "Design pressure 10 barg", 2: "x", 3: "y", 4: "z"}
    ok = {"field": "Design pressure", "value": "10", "quote": "Design pressure 10 barg"}
    form = {
        "pages": {
            1: {"accepted": [ok]},
            2: {"accepted": [ok], "rejected": [{"reason": "quote_not_on_page"}]},
            3: {"accepted": []},
            4: {"accepted": [ok], "error": "timed out"},
        }
    }
    assert reader_speed.agreed_pages(texts, form) == [1]


def test_the_allowed_unexplained_numbers_come_from_the_setting(cuts):
    texts = {1: "Design pressure 10 barg 11 12 13"}
    form = {
        "pages": {
            1: {"accepted": [{"value": "10", "quote": "Design pressure 10 barg"}]}
        }
    }
    cuts("skip_agreed_pages")
    assert (
        reader_speed.agreed_pages(texts, form) == []
        and reader_speed.unexplained_numbers(texts[1], form["pages"][1]["accepted"])
        == 3
    )
    cuts("skip_agreed_pages=3")
    assert reader_speed.agreed_pages(texts, form) == [1]
