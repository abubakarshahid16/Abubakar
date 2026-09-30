"""AI READS, CODE CHECKS: the datasheet AI reader inside extraction.

`datasheet_ai.py` + `datasheets._extract_facts`, behind DATASHEET_AI_READER
("off" by default). Every model here is a FAKE callable: no network, no
Ollama, no Claude. The datasheet is built by the fixture with made-up rows.

What is proved, each through the pipeline where it can be:
  * flag off: no model is asked and the extraction result has no AI key;
  * rules and AI agree -> one fact, confidence above both, never "high";
  * they disagree -> both kept, both flagged `conflict`, each naming the other;
  * AI-only -> kept only when its quote is on the page, the rules' value gate
    does not apply to it, `extraction_method='model'` with the engine recorded;
  * rules-only -> unchanged;
  * unstable (two runs disagree) -> dropped;
  * engine unavailable / failing -> rules only, with the reason;
  * the claude engine goes through `claude_spend` (a cap refusal stops the
    calls) and checks REASONING_PROVIDER; the ollama engine through
    `model_transport` with the host check first.

Mutations: M1670-M1686 (`scripts/mutations/datasheet_ai.py`).
"""

from __future__ import annotations

import json

import pytest

from app import (claude_datasheet, claude_spend, datasheet_ai, datasheets, db,
                 model_transport, reader_transport, submittal_review)
from app.config import settings

KEY = "sk-ant-test-NEVER-IN-A-LOG-0000"

ROWS = [
    ("Design pressure", "23.5 barg"),
    ("Design temperature", "120 C"),
    ("Max design temperature", "150 C"),
    ("Paint system", "Two coat epoxy"),
    ("Casing material", "SA-216 WCB"),
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "dsai.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _fresh_db():
    """A second extraction of the same fixture, from an empty database."""
    db.reset_connection(); settings.db_path.unlink()
    db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()


def _datasheet_pdf(path, rows) -> str:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(rows, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _ingest(path, doc_id="DS-0001"):
    import pymupdf
    doc = pymupdf.open(path)
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,?)""",
            (doc_id, "SYN-DS-0001.pdf", f"sha-{doc_id}", str(path), len(doc),
             "2026-09-30T00:00:00Z"))
        for page in range(1, len(doc) + 1):
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c{page}", doc_id, "SYN-DS-0001.pdf", page, page, page,
                 doc[page - 1].get_text(), f"h{doc_id}{page}"))
    doc.close()
    return doc_id


def _fact(field, value, unit, quote, kind="offered"):
    return {"field": field, "value": value, "unit": unit, "quote": quote, "kind": kind}


class FakeModel:
    """A `prompt -> text` callable. `answers` is one list of facts per call
    (the last repeats); `engine` is what the reader records."""

    engine = "fake-engine"

    def __init__(self, *answers, raises=None):
        self.answers = answers or ([],)
        self.raises = raises
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        facts = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        return json.dumps({"facts": facts})


def _use(monkeypatch, model, engine="ollama"):
    """Flag on, and the engine replaced by `model` (a fake)."""
    monkeypatch.setattr(settings, "datasheet_ai_reader", engine)
    monkeypatch.setattr(datasheet_ai, "model_call_for", lambda engine=None: (model, None))


def _extract(tmp_path, rows=ROWS):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", rows))
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = datasheets.list_facts(doc, allowed_document_ids=frozenset({doc}))
    return result, facts


def _by(facts, name):
    return [f for f in facts if f["field_name"] == name]


AGREE = _fact("Design pressure", "23.5", "barg", "Design pressure 23.5 barg")
#: A real misreading: the label's words are in the quote, but it is the
#: neighbouring row's value.
DISAGREE = _fact("Design temperature", "150", "C", "Max design temperature 150 C")
FREE_TEXT = _fact("Paint system", "Two coat epoxy", None, "Paint system Two coat epoxy")
NOT_ON_PAGE = _fact("Paint system", "Three coat zinc", None, "Paint system Three coat zinc")


# ======================================================== flag off

def test_flag_off_asks_no_model_and_adds_nothing(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(datasheet_ai, "model_call_for",
                        lambda engine=None: asked.append(engine) or (FakeModel([AGREE]), None))
    result, facts = _extract(tmp_path)
    assert result["facts"] == 4          # the rule readers' four facts
    assert asked == []
    assert "ai_reader" not in result
    assert all(f["extraction_method"] != "model" for f in facts)
    assert {f["confidence"] for f in facts} == {0.6}


def test_flag_on_with_an_empty_reading_leaves_the_rules_facts_unchanged(tmp_path, monkeypatch):
    """RULES-ONLY: a page the AI proves nothing on is exactly the rules'."""
    off_result, off_facts = _extract(tmp_path)
    _fresh_db()
    model = FakeModel([])
    _use(monkeypatch, model)
    on_result, on_facts = _extract(tmp_path)
    assert model.calls == 2               # one page, two runs
    keep = ("field_name", "field_value", "confidence", "validation_state",
            "extraction_method", "bbox", "raw_value", "unit")
    assert [{k: f[k] for k in keep} for f in on_facts] == \
        [{k: f[k] for k in keep} for f in off_facts]
    assert on_result["ai_reader"]["pages_read"] == 1
    assert {k: v for k, v in on_result.items() if k != "ai_reader"} == off_result


# ======================================================== the merge, through extraction

def test_agreement_is_one_fact_with_higher_confidence_never_high(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel([AGREE]))
    result, facts = _extract(tmp_path)
    [fact] = _by(facts, "design pressure")
    assert fact["extraction_method"] == "extracted"
    assert 0.6 < fact["confidence"] < 0.9       # above rules and AI, below the cap
    assert fact["confidence"] == datasheet_ai.AGREED_CONFIDENCE
    box = json.loads(fact["bbox"])
    assert box["reader"] == "datasheet_ai" and box["engine"] == "fake-engine"
    assert box["agreement"]
    assert result["ai_reader"]["agreed"] == 1
    # The other rule facts are untouched.
    assert _by(facts, "casing material")[0]["confidence"] == 0.6


def test_disagreement_keeps_both_flagged_for_the_engineer(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel([DISAGREE]))
    result, facts = _extract(tmp_path)
    both = _by(facts, "design temperature")
    assert len(both) == 2, "a disagreement must keep BOTH readings"
    rule = next(f for f in both if f["extraction_method"] == "extracted")
    ai = next(f for f in both if f["extraction_method"] == "model")
    assert rule["field_value"] == "120 C" and ai["raw_value"] == "150"
    assert rule["validation_state"] == ai["validation_state"] == datasheets.GEOMETRY_CONFLICT
    assert json.loads(ai["bbox"])["conflicts_with"] == [rule["id"]]
    assert json.loads(rule["bbox"])["conflicts_with"] == [ai["id"]]
    assert result["ai_reader"]["conflicts"] == 1
    # The neighbouring row the AI actually read is a rules-only fact, untouched.
    [maxrow] = _by(facts, "max design temperature")
    assert maxrow["validation_state"] is None and maxrow["confidence"] == 0.6


def test_a_free_text_answer_is_kept_when_its_quote_is_on_the_page(tmp_path, monkeypatch):
    """The rules' closed categorical gate drops "Two coat epoxy"; the AI's
    quote on the page is the proof, so it is kept - as the model's."""
    off_result, off_facts = _extract(tmp_path)
    assert _by(off_facts, "paint system") == []
    _fresh_db()
    _use(monkeypatch, FakeModel([FREE_TEXT]))
    result, facts = _extract(tmp_path)
    [fact] = _by(facts, "paint system")
    assert fact["field_value"] == "Two coat epoxy"
    assert fact["extraction_method"] == "model"
    assert fact["confidence"] == claude_datasheet.CONFIDENCE
    assert fact["section"] == "model:offered"
    assert fact["source_text"] == "Paint system Two coat epoxy"
    assert json.loads(fact["bbox"])["engine"] == "fake-engine"
    assert result["ai_reader"]["ai_only"] == 1


def test_a_free_text_answer_whose_quote_is_not_on_the_page_is_dropped(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel([NOT_ON_PAGE]))
    result, facts = _extract(tmp_path)
    assert _by(facts, "paint system") == []
    assert result["ai_reader"]["proposals_rejected"] == {"quote_not_on_page": 1}


def test_an_unstable_reading_is_dropped(tmp_path, monkeypatch):
    """Run one proposes the fact, run two does not: not compelled by the page."""
    _use(monkeypatch, FakeModel([FREE_TEXT], []))
    result, facts = _extract(tmp_path)
    assert _by(facts, "paint system") == []
    assert result["ai_reader"]["proposals_rejected"] == {"model_unstable": 1}


def test_a_page_read_only_by_the_ai_counts_as_read(tmp_path, monkeypatch):
    rows = [("Paint system", "Two coat epoxy")]
    off_result, _ = _extract(tmp_path, rows)
    assert off_result["pages_unparsed"] == 1
    _fresh_db()
    _use(monkeypatch, FakeModel([FREE_TEXT]))
    result, facts = _extract(tmp_path, rows)
    assert len(facts) == 1
    assert result["pages_unparsed"] == 0 and result["facts"] == 1


# ======================================================== failure is a reason

def test_an_engine_failure_falls_back_to_the_rules_with_a_reason(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel(raises=RuntimeError("down")))
    result, facts = _extract(tmp_path)
    assert result["facts"] == 4
    assert {f["extraction_method"] for f in facts} == {"extracted"}
    assert result["ai_reader"]["page_reasons"] == {1: "engine failed (RuntimeError)"}


def test_an_unavailable_engine_falls_back_to_the_rules_with_a_reason(tmp_path, monkeypatch):
    """The REAL `model_call_for`: claude asked for, REASONING_PROVIDER=ollama."""
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    result, facts = _extract(tmp_path)
    assert result["facts"] == 4
    assert "PROVIDER_OFF" in result["ai_reader"]["unavailable"]
    assert "PROVIDER_OFF" in result["ai_reader"]["page_reasons"][1]


def test_a_malformed_answer_is_a_reason_not_a_crash():
    out = datasheet_ai.read_page_text_with_ai("Design pressure 23.5 barg", 1,
                                              lambda prompt: "not json")
    assert out["accepted"] == [] and "model_malformed" in out["error"]


# ======================================================== the pure merge

def _rule(name, value, *, page=1, column=None, rid="r1"):
    number, unit, m = datasheets.measure_value(value)
    return {"id": rid, "page": page, "field_name": name, "field_value": value,
            "raw_value": number, "is_blank": 0, "value_column": column,
            "normalized_value": m.normalized_value if m else None,
            "normalized_unit": m.normalized_unit if m else None}


def _ai(name, value, unit=None, kind="offered", page=1):
    return {"page": page, "field_name": name, "field": name, "value": value,
            "unit": unit, "kind": kind, "quote": f"{name} {value}"}


def test_merge_the_four_outcomes():
    rules = [_rule("design pressure", "23.5 barg", rid="a"),
             _rule("design temperature", "120 C", rid="b"),
             _rule("casing material", "SA-216 WCB", rid="c")]
    ais = [_ai("design pressure", "23.5", "barg"),
           _ai("design temperature", "150", "C"),
           _ai("paint system", "Two coat epoxy")]
    got = {d["field_name"]: d for d in datasheet_ai.merge_readings(rules, ais)}
    assert got["design pressure"]["outcome"] == datasheet_ai.AGREED
    assert got["design temperature"]["outcome"] == datasheet_ai.CONFLICT
    assert got["design temperature"]["rules"][0]["id"] == "b"
    assert got["design temperature"]["ai"][0]["value"] == "150"
    assert got["casing material"]["outcome"] == datasheet_ai.RULES_ONLY
    assert got["paint system"]["outcome"] == datasheet_ai.AI_ONLY


def test_merge_matches_only_across_the_same_kind():
    """A rule fact read from a "Required" column is not contradicted by the
    OFFERED value of the same field - that is the other column."""
    rules = [_rule("design pressure", "25 barg", column="REQUIRED", rid="req")]
    ais = [_ai("design pressure", "25", "barg", kind="offered"),
           _ai("design pressure", "30", "barg", kind="required")]
    decisions = datasheet_ai.merge_readings(rules, ais)
    # The same number in the OFFERED column is not the rules' REQUIRED cell
    # agreeing; the AI's REQUIRED reading is what contradicts it.
    assert [d["outcome"] for d in decisions] == [datasheet_ai.CONFLICT, datasheet_ai.AI_ONLY]
    assert "agreed_ai" not in decisions[0]
    assert [a["value"] for a in decisions[0]["ai"]] == ["30"]
    assert decisions[1]["ai"]["kind"] == "offered"


def test_merge_a_second_same_kind_value_beside_an_agreement_is_a_conflict():
    rules = [_rule("design pressure", "23.5 barg")]
    ais = [_ai("design pressure", "23.5", "barg"), _ai("design pressure", "30", "barg")]
    [d] = datasheet_ai.merge_readings(rules, ais)
    assert d["outcome"] == datasheet_ai.CONFLICT
    assert d["agreed_ai"]["value"] == "23.5" and [a["value"] for a in d["ai"]] == ["30"]


# ======================================================== the engines' gates

def _claude_env(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    sent: list[dict] = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        return {"model": "claude-sonnet-4-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps({"facts": [AGREE]})}],
                "usage": {"input_tokens": 100, "output_tokens": 10}}
    send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    return sent


def test_the_claude_engine_is_metered_by_claude_spend(monkeypatch):
    sent = _claude_env(monkeypatch)
    out = datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, "claude")
    assert len(sent) == 2                     # two runs
    assert [f["field_name"] for f in out["accepted"]] == ["design pressure"]
    assert [e["step"] for e in claude_spend.entries()] == [datasheet_ai.STEP] * 2


def test_a_cap_refusal_stops_the_claude_calls(monkeypatch):
    sent = _claude_env(monkeypatch)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.000001)
    run = datasheet_ai.read_pages({1: "Design pressure 23.5 barg",
                                   2: "Design pressure 23.5 barg"}, "claude")
    assert sent == []
    assert run["stopped"] == claude_spend.BudgetExceeded.count_key
    assert run["reasons"][1].startswith("stopped by a limit")
    assert run["reasons"][2].startswith("not read: a limit stopped")


def test_the_claude_engine_needs_reasoning_provider_claude(monkeypatch):
    sent = _claude_env(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    call, why = datasheet_ai.model_call_for("claude")
    assert call is None and "PROVIDER_OFF" in why
    assert sent == []


def test_the_ollama_engine_goes_through_model_transport(monkeypatch):
    posted = []

    def post_json(path, body, *, timeout):
        posted.append((path, body["model"]))
        return {"response": json.dumps({"facts": [AGREE]}), "model": "local-0001",
                "done_reason": "stop"}
    monkeypatch.setattr(model_transport, "post_json", post_json)
    monkeypatch.setattr(settings, "datasheet_ai_ollama_model", "local-0001")
    out = datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, "ollama")
    assert posted == [("/api/generate", "local-0001")] * 2
    assert out["engine"] == "ollama" and len(out["accepted"]) == 1


def test_the_ollama_engine_refuses_a_host_the_model_url_check_refuses(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://model-host.example:11434")
    monkeypatch.setattr(model_transport, "post_json",
                        lambda *a, **k: pytest.fail("a refused host was called"))
    call, why = datasheet_ai.model_call_for("ollama")
    assert call is None and "ollama engine unavailable" in why


def test_off_and_unknown_engines_are_reasons():
    assert datasheet_ai.model_call_for("off") == (None, "DATASHEET_AI_READER is off")
    call, why = datasheet_ai.model_call_for("gpt")
    assert call is None and "not one of" in why
