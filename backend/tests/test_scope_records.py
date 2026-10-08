"""The B5 scope-record module: finder, verified reading, schema, and the
3-re-read NOT_APPLICABLE confirmation. In-memory pages, fake provider -
no DB file, no network, no client text."""
import json
import sqlite3

import pytest

from app import applicability_v2, scope_records
from app import reasoning_provider as rp

LEX = {"centrifugal pump": ("type", "Centrifugal Pump"), "pump": ("family", "Pumps")}
PUMP = applicability_v2.Profile("Centrifugal Pump", "Pumps", "Rotating")
PAGE2 = ("CONTENTS\n1 Scope ........ 2\n\n1 Scope\n1.1 This standard covers centrifugal pumps for "
         "process service. It does not apply to all pumps in domestic water service.\n")


@pytest.fixture
def pages(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    conn.executemany("INSERT INTO pages VALUES (?,?,?)",
                     [("std1", 1, "Cover page of a standard"), ("std1", 2, PAGE2)])
    monkeypatch.setattr(scope_records, "connect", lambda: conn)
    return conn


def _no_search(*_a, **_k):
    return {"hits": []}


class FakeProvider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def reason(self, packet):
        text = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return rp.Response(text=text, provider="claude", model_tag="fake", digest="d", finish_reason="stop",
                           prompt_sha256=packet.sha256, schema_errors=rp.schema_errors(text, packet.json_schema))


def _answer(covered=(), exclusions=(), limits=(), generic=False):
    return json.dumps({"covered_equipment": list(covered), "covered_activities": [], "new_construction": [],
                       "explicit_exclusions": list(exclusions), "explicit_limits": list(limits),
                       "generic_scope": generic})


def test_the_finder_prefers_the_scope_heading_and_skips_the_contents_line(pages):
    found = scope_records.find_passages("std1", search_fn=_no_search)
    assert found[0]["method"] == "heading:Scope" and found[0]["page"] == 2
    assert "covers centrifugal pumps" in found[0]["text"]
    assert len(found) <= scope_records.MAX_PASSAGES


def test_an_unverifiable_quote_is_dropped(pages):
    ans = _answer(covered=[{"term": "centrifugal pumps", "quote": "This standard covers centrifugal pumps", "page": 2},
                           {"term": "compressors", "quote": "This standard covers compressors", "page": 2}])
    out = scope_records.read_scope("std1", FakeProvider([ans]), lexicon=LEX, step="t",
                                   passages=scope_records.find_passages("std1", search_fn=_no_search))
    assert out["status"] == "PROPOSED" and out["verified_items"] == 1 and out["dropped_unverified"] == 1


def test_invalid_output_is_retried_once_then_unknown(pages):
    prov = FakeProvider(["not json", "still not json"])
    out = scope_records.read_scope("std1", prov, lexicon=LEX, step="t",
                                   passages=scope_records.find_passages("std1", search_fn=_no_search))
    assert (out["status"], out["invalid_output"], out["tries"], prov.calls) == ("UNKNOWN", True, 2, 2)


def test_a_non_numeric_limit_needs_no_min_or_max():
    """THE MUTATION TARGET (M603): requiring min/max rejected 2 of 8 real
    answers in the M-03 run."""
    ans = _answer(limits=[{"kind": "service", "term": "process service", "quote": "for process service",
                           "page": 2}])
    assert rp.schema_errors(ans, scope_records.SCHEMA) == ()


def test_not_applicable_stands_only_when_three_rereads_agree(pages):
    """THE MUTATION TARGET (M604): the confirmation step is skipped."""
    na = _answer(exclusions=[{"term": "all pumps", "quote": "It does not apply to all pumps", "page": 2}])
    ok = _answer(covered=[{"term": "centrifugal pumps", "quote": "This standard covers centrifugal pumps", "page": 2}])
    passages = scope_records.find_passages("std1", search_fn=_no_search)
    first = scope_records.read_scope("std1", FakeProvider([na]), lexicon=LEX, step="t", passages=passages)
    kept = scope_records.decide_with_confirmation("std1", FakeProvider([na, na, na]), PUMP, lexicon=LEX,
                                                  step="t", first=first, passages=passages)
    held = scope_records.decide_with_confirmation("std1", FakeProvider([na, ok, na]), PUMP, lexicon=LEX,
                                                  step="t", first=first, passages=passages)
    assert kept["decision"] == applicability_v2.NOT_APPLICABLE and kept["confirmations"] == 3
    assert held["decision"] == applicability_v2.UNKNOWN and held["confirmations"] == 2


# ------------------------------- v4 finder (b5-quality 2026-09-25, 3-sheet re-read)

def _pages(monkeypatch, rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    conn.executemany("INSERT INTO pages VALUES (?,?,?)", [("d", n, t) for n, t in rows])
    monkeypatch.setattr(scope_records, "connect", lambda: conn)


FILLER = "Body text of a clause that is not about the scope of anything at all. " * 3


def test_a_scope_heading_late_in_a_long_standard_is_found(monkeypatch):
    """THE MUTATION TARGET (M660): a corrosion standard put '1 Scope' on
    page 18 after a long change log; the finder only looked to page 10."""
    _pages(monkeypatch, [(n, FILLER) for n in range(1, 18)]
           + [(18, "1 Scope\n1.1 This standard specifies measures for pipelines and plant piping.\n")])
    found = scope_records.find_passages("d", search_fn=_no_search)
    assert (found[0]["page"], found[0]["method"]) == (18, "heading:Scope")


def test_a_heading_with_its_text_on_the_same_line_is_found_and_a_run_on_word_is_not(monkeypatch):
    """THE MUTATION TARGET (M661): 'Scope. This code applies to the
    following:' is a heading; 'Application for which the equipment ...' is a
    definition, and a lower-case wrapped word is body text."""
    _pages(monkeypatch, [(2, "Scope. This code applies to the following: (1) watertube boilers of any size.\n"),
                         (3, "Application for which the equipment is designed for continuous operation, see 4.\n"
                             "application\nof the coating shall follow the procedure in section nine here.\n")])
    methods = [(p["page"], p["method"]) for p in scope_records.find_passages("d", search_fn=_no_search)]
    assert (2, "heading:Scope") in methods
    assert not any(m.startswith("heading:") and page == 3 for page, m in methods)


def test_a_scope_that_runs_off_its_page_brings_the_next_page(monkeypatch):
    """THE MUTATION TARGET (M662): a pressure-testing standard's scope
    sentence was cut at the page end."""
    _pages(monkeypatch, [(6, "1 Scope\n1.1 This standard defines requirements governing pressure testing of "
                             "newly constructed plant piping and pipelines which are designed and\n"),
                         (7, "constructed in accordance with ASME B31.3. It does not apply to instruments.\n")])
    found = scope_records.find_passages("d", search_fn=_no_search)
    assert (found[1]["page"], found[1]["method"]) == (7, "continuation:Scope")
    assert "does not apply to instruments" in found[1]["text"]


def test_no_continuation_when_the_next_section_has_begun(monkeypatch):
    _pages(monkeypatch, [(6, "1 Scope\n1.1 This standard covers centrifugal pumps for process service.\n"
                             "2 Conflicts and Deviations\nAny conflicts shall be resolved.\n"),
                         (7, "Next page body.\n")])
    assert not any(p["method"].startswith("continuation")
                   for p in scope_records.find_passages("d", search_fn=_no_search))


def test_the_cue_context_is_the_list_intro_and_the_words_before_the_quote():
    """THE MUTATION TARGET (M663): the intro 'Specifically excluded from
    the scope are:' is what makes list item b) an exclusion."""
    page = ("1.1 This standard covers gate and globe valves. 1.2 Specifically excluded from the scope are: "
            "a) Wellhead valves classified under Class 45. b) Control, safety-relief, relief and pilot valves.")
    ctx = scope_records.cue_context("Control, safety-relief, relief and pilot valves", page)
    assert "excluded from the scope are:" in ctx and ctx.endswith("b)")
    # words AFTER a quote never lend it a cue
    assert "excluding" not in scope_records.cue_context(
        "covers centrifugal pumps", "This standard covers centrifugal pumps excluding submersible pumps.")


def test_verify_keeps_only_schema_fields_and_cuts_the_context_itself(pages):
    parsed = {"covered_equipment": [], "covered_activities": [], "new_construction": [],
              "explicit_exclusions": [{"term": "all pumps", "quote": "all pumps in domestic water service",
                                       "page": 2, "cue_context": "does not apply (model-written)"}],
              "explicit_limits": [], "generic_scope": False}
    passages = scope_records.find_passages("std1", search_fn=_no_search)
    record, _, _ = scope_records.verify(parsed, passages, "std1", LEX)
    item = record["explicit_exclusions"][0]
    assert item["cue_context"] == "It does not apply to"
    assert set(item) == {"term", "quote", "page", "cue_context"}


class FakeBatchProvider:
    def __init__(self, rounds):
        self.rounds, self.sent = list(rounds), []

    def reason_batch(self, packets, **_kw):
        self.sent.append(packets)
        texts = self.rounds[len(self.sent) - 1]
        return [rp.Response(text=t, provider="claude", model_tag="fake", digest="d", finish_reason="stop",
                            prompt_sha256=p.sha256, schema_errors=rp.schema_errors(t, p.json_schema))
                for p, t in zip(packets, texts)]


def test_a_batch_read_retries_only_the_invalid_answers_once(pages):
    """THE MUTATION TARGET (M664): the retry batch is skipped, so an invalid
    first answer is final."""
    ok = _answer(covered=[{"term": "centrifugal pumps", "quote": "This standard covers centrifugal pumps",
                           "page": 2}])
    pages.execute("INSERT INTO pages VALUES ('std2', 2, ?)", (PAGE2,))
    passages = scope_records.find_passages("std1", search_fn=_no_search)
    prov = FakeBatchProvider([["not json", ok], [ok]])
    out = scope_records.read_scope_batch({"std1": passages, "std2": passages, "none": []}, prov, lexicon=LEX,
                                         step="t")
    assert [len(batch) for batch in prov.sent] == [2, 1]
    assert prov.sent[1][0].prompt.startswith(scope_records.RETRY)
    assert (out["std1"]["status"], out["std1"]["tries"], out["std2"]["tries"]) == ("PROPOSED", 2, 1)
    assert out["none"]["why"] == "no scope passage found"


def test_a_round_the_budget_refuses_is_not_sent_and_its_standards_stay_unknown(pages):
    """THE MUTATION TARGET (M676): the per-round budget check is skipped."""
    passages = scope_records.find_passages("std1", search_fn=_no_search)
    prov = FakeBatchProvider([["{}"]])
    out = scope_records.read_scope_batch({"std1": passages}, prov, lexicon=LEX, step="t",
                                         may_send=lambda packets: False)
    assert prov.sent == []
    assert (out["std1"]["status"], out["std1"]["why"]) == ("UNKNOWN", "not read (batch not sent)")
