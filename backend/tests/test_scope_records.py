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
    return json.dumps({"covered_equipment": list(covered), "covered_activities": [],
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
