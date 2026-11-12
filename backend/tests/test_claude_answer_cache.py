"""The answer cache: the same Claude request is never bought twice, on any lane.

Fake transports only; no socket, no real call. The fake counts what would have left.
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

import pytest

from app import claude_answer_cache as cache
from app import (
    claude_approved,
    claude_spend,
    reader_api,
    review_audit,
    review_audit_rows,
)
from app import reasoning_provider as rp
from app.ai import output_limits
from app.ai_call_ledger import open_ledger, snapshot
from app.config import settings

MODEL = "claude-sonnet-5-5"
OTHER_MODEL = "claude-haiku-5-5"
ANSWER = '{"answer": "yes"}'
SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / tmp_path.name)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _send(reply=ANSWER, stop="end_turn"):
    def send(url, *, headers, body, timeout):
        send.calls.append(body)
        return {
            "model": body["model"],
            "stop_reason": stop,
            "content": [{"type": "text", "text": reply}],
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }

    send.calls = []
    return send


def _packet(prompt="Is it?", **kw):
    return rp.Packet(
        prompt=prompt,
        num_ctx=4096,
        num_predict=200,
        step="a-step",
        json_schema=SCHEMA,
        **kw,
    )


def _metered_call(send, step="a-step"):
    """The lane the datasheet reader and the matcher use."""
    return output_limits.model_call_for(
        claude_spend.metered(send, step), output_limits.ROUTE_MATCH
    )


def _lines():
    return claude_spend.entries()


# ------------------------------------------------- the same call, on every lane


def test_second_identical_call_on_the_metered_lane_opens_no_socket_and_costs_0():
    """THE PILOT'S DEFECT: the reader and the matcher go through `metered`, which had no cache."""
    send = _send()
    assert _metered_call(send)("which?") == ANSWER
    before = claude_spend.spent()
    assert before > 0
    assert _metered_call(send)("which?") == ANSWER
    assert len(send.calls) == 1, "the repeat was bought again"
    assert claude_spend.spent() == before
    hit = _lines()[-1]
    assert (
        hit["cached"] is True
        and hit["cost_usd"] == 0.0
        and hit["sent"] == "not sent: cache hit"
    )


def test_second_identical_call_on_the_provider_lane_opens_no_socket_and_costs_0():
    send = _send()
    provider = rp.ClaudeProvider(MODEL, transport=send)
    first = provider.reason(_packet())
    second = provider.reason(_packet())
    assert len(send.calls) == 1 and second.cost_usd == 0.0 and first.cost_usd > 0
    assert (
        second.text == first.text
        and second.model_tag == MODEL
        and second.schema_errors == ()
    )


def test_a_stream_is_stored_and_played_back_whole_at_no_cost():
    calls = []

    def stream(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        yield {
            "type": "message_start",
            "message": {"model": MODEL, "usage": {"input_tokens": 9}},
        }
        yield {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        yield {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "He"},
        }
        yield {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "llo"},
        }
        yield {"type": "content_block_stop", "index": 0}
        yield {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        }

    provider = rp.ClaudeProvider(MODEL, stream_transport=stream)
    packet = rp.Packet(prompt="Hi", num_ctx=1, num_predict=50, step="chat")
    provider.stream(packet, lambda piece: None)
    shown = []
    again = provider.stream(packet, shown.append)
    assert len(calls) == 1 and "".join(shown) == "Hello" and again.cost_usd == 0.0


def test_a_batch_answer_serves_a_later_batch_at_no_cost():
    class Client:
        created = 0

        def batch_create(self, url, *, headers, requests):
            Client.created += 1
            self.rows = [
                {
                    "custom_id": r["custom_id"],
                    "result": {
                        "type": "succeeded",
                        "message": {
                            "model": MODEL,
                            "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": ANSWER}],
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    },
                }
                for r in requests
            ]
            return {
                "id": "b1",
                "processing_status": "ended",
                "results_url": "https://x/r",
            }

        def batch_results(self, url, *, headers):
            return self.rows

    provider = rp.ClaudeProvider(MODEL)
    provider.reason_batch([_packet()], client=Client())
    out = provider.reason_batch([_packet()], client=Client())
    assert Client.created == 1 and out[0].cost_usd == 0.0 and out[0].text == ANSWER


# ------------------------------------------------- what changes the key


@pytest.mark.parametrize(
    "change",
    [
        {"model": OTHER_MODEL},
        {"prompt": "Is it not?"},
        {"system": "another instruction"},
        {"effort": "low"},
        {"num_predict": 9999},
        {"tools": ({"name": "t", "input_schema": {"type": "object"}},)},
        {"prompt_version": "v2"},
    ],
)
def test_a_changed_model_prompt_system_effort_budget_tools_or_version_misses(change):
    send = _send()
    rp.ClaudeProvider(MODEL, transport=send).reason(_packet())
    model = change.get("model", MODEL)
    fields = {
        "prompt": "Is it?",
        "num_ctx": 4096,
        "num_predict": 200,
        "step": "a-step",
        "json_schema": SCHEMA,
        **{k: v for k, v in change.items() if k != "model"},
    }
    answer = rp.ClaudeProvider(model, transport=send).reason(rp.Packet(**fields))
    assert len(send.calls) == 2, f"{change} was served the old answer"
    assert answer.cost_usd > 0


def test_a_changed_step_or_version_misses_on_the_metered_lane():
    send = _send()
    _metered_call(send)("which?")
    _metered_call(send, step="another")("which?")
    assert len(send.calls) == 2
    call = output_limits.model_call_for(
        claude_spend.metered(send, "a-step", version="v2"), output_limits.ROUTE_MATCH
    )
    call("which?")
    assert len(send.calls) == 3


def test_a_stability_check_compares_two_answers_the_model_really_gave():
    """Asking twice through one wrapper must not compare an answer with itself, and
    a re-run gets the same pair, free."""
    send = _send()
    call = _metered_call(send)
    assert [call("which?"), call("which?")] == [ANSWER, ANSWER]
    assert len(send.calls) == 2, (
        "the second ask of the stability check was served the first answer"
    )
    call = _metered_call(send)
    call("which?"), call("which?")
    assert len(send.calls) == 2, "the re-run paid again"


# ------------------------------------------------- only complete answers


@pytest.mark.parametrize(
    "stop", ["refusal", "max_tokens", "tool_use", "pause_turn", ""]
)
def test_a_refusal_or_cut_off_is_not_stored_on_the_metered_lane(stop):
    send = _send(stop=stop)
    for _ in range(2):
        with contextlib.suppress(output_limits.Truncated, output_limits.Unreadable):
            _metered_call(send)("which?")
    assert len(send.calls) == 2
    assert not list(Path(settings.claude_cache_dir).rglob("*.json"))


def test_a_refusal_is_not_stored_on_the_provider_lane():
    send = _send(stop="refusal")
    provider = rp.ClaudeProvider(MODEL, transport=send)
    for _ in range(2):
        provider.reason(_packet())
    assert len(send.calls) == 2
    assert not list(Path(settings.claude_cache_dir).rglob("*.json"))


def test_a_cut_off_is_not_stored_on_the_provider_lane():
    send = _send(stop="max_tokens")
    provider = rp.ClaudeProvider(MODEL, transport=send)
    for _ in range(2):
        provider.reason(_packet())
    assert len(send.calls) == 2


def test_an_invalid_or_empty_reply_is_not_stored():
    prose = _send(reply="not json at all")
    assert _metered_call(prose)("which?")
    assert _metered_call(prose)("which?")
    assert len(prose.calls) == 2
    empty = _send(reply="   ")
    provider = rp.ClaudeProvider(MODEL, transport=empty)
    for _ in range(2):
        provider.reason(_packet(prompt="other"))
    assert len(empty.calls) == 2


def test_a_callers_own_check_decides_what_is_kept_and_what_is_served():
    send = _send()
    wanted = {"keep": False}

    def keep_if(_text):
        return wanted["keep"]

    def call():
        return output_limits.model_call_for(
            claude_spend.metered(send, "a-step", keep_if=keep_if),
            output_limits.ROUTE_MATCH,
        )("q")

    call()
    call()
    assert len(send.calls) == 2, "an answer its caller's check refused was kept"
    wanted["keep"] = True
    call()
    call()
    assert len(send.calls) == 3


def test_the_matcher_keeps_only_a_choice_that_passes_its_own_check(monkeypatch):
    from app import comparison, reader_transport

    send = _send(reply='{"choice": 7, "reason": "out of range"}')
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(settings, "match_engine", "claude")
    candidates = [{"field_name": "noise", "raw_value": "1"}]
    requirement = {"requirement_text": "noise shall be low", "field_name": "noise"}
    for _ in range(2):
        assert (
            comparison._ask_model_once(requirement, candidates)[1]
            == comparison.MODEL_OUT_OF_RANGE
        )
    assert len(send.calls) == 2


# ------------------------------------------------- the approved list and documents


def _approve(tmp_path, monkeypatch, shas):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    (tmp_path / claude_approved.LIST_NAME).write_text(
        json.dumps({"documents": [{"sha256": s, "status": "approved"} for s in shas]}),
        encoding="utf-8",
    )


def _library(monkeypatch, known: dict[str, str]):
    """The library's answer without a database: id -> file hash, unknown ids None."""
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: {d: known.get(d) for d in ids}
    )
    monkeypatch.setattr(claude_approved, "_blocked_ids", lambda hashes: frozenset())
    monkeypatch.setattr(  # no database either: no document here is a contract
        claude_approved, "contracts_without_yes", lambda ids: frozenset()
    )


def test_a_blocked_document_never_gets_a_stored_answer(tmp_path, monkeypatch):
    _library(monkeypatch, {"doc1": "aaa"})
    _approve(tmp_path, monkeypatch, ["aaa"])
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("which?")
        (tmp_path / claude_approved.LIST_NAME).write_text(
            json.dumps({"documents": []}), "utf-8"
        )
        with pytest.raises(claude_spend.DocumentNotApproved):
            _metered_call(send)("which?")
    assert len(send.calls) == 1
    assert _lines()[-1]["refused"] == claude_approved.NOT_APPROVED
    assert not any(e.get("cached") for e in _lines())


def test_an_undeclared_caller_never_gets_a_stored_answer(tmp_path, monkeypatch):
    _library(monkeypatch, {})
    _approve(tmp_path, monkeypatch, [])
    send = _send()
    with claude_approved.carrying(()):
        _metered_call(send)("which?")
    with pytest.raises(claude_spend.DocumentNotApproved):
        _metered_call(send)("which?")
    assert len(send.calls) == 1


def test_a_withdrawn_document_stops_serving_even_for_a_caller_that_no_longer_declares_it(
    tmp_path, monkeypatch
):
    """`refusal()` knows only what THIS caller declares; the file knows what it carried."""
    _library(monkeypatch, {"doc1": "aaa"})
    _approve(tmp_path, monkeypatch, ["aaa"])
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("which?")
    (tmp_path / claude_approved.LIST_NAME).write_text(
        json.dumps({"documents": []}), "utf-8"
    )
    with claude_approved.carrying(()):
        _metered_call(send)("which?")
    assert len(send.calls) == 2, "a withdrawn document's answer was served"


def test_a_lapsed_approval_stops_serving_even_for_a_caller_that_no_longer_declares_it(
    tmp_path, monkeypatch
):
    """#1584: the row still reads approved, but its role no longer qualifies."""
    _library(monkeypatch, {"doc1": "aaa"})
    _approve(tmp_path, monkeypatch, ["aaa"])
    lapsed = {"on": False}
    monkeypatch.setattr(
        claude_approved,
        "_lapsed_ids",
        lambda hashes: frozenset(hashes) if lapsed["on"] else frozenset(),
    )
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("which?")
    with claude_approved.carrying(()):
        _metered_call(send)("which?")
    assert len(send.calls) == 1, (
        "the answer should be served before the approval lapses"
    )
    lapsed["on"] = True
    with claude_approved.carrying(()):
        _metered_call(send)("which?")
    assert len(send.calls) == 2, "a lapsed document's answer was served"


def test_a_blocked_file_stops_serving_even_with_the_guard_off_and_undeclared(
    monkeypatch,
):
    """#1584: a block wins over the guard; the file knows what its prompt carried."""
    _library(monkeypatch, {"doc1": "aaa"})
    blocked = {"on": False}
    monkeypatch.setattr(
        claude_approved,
        "_blocked_ids",
        lambda hashes: frozenset(hashes) if blocked["on"] else frozenset(),
    )
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("which?")
    blocked["on"] = True
    with claude_approved.carrying(()):
        _metered_call(send)("which?")
    assert len(send.calls) == 2, "a blocked document's answer was served"


def test_a_deleted_document_leaves_nothing_served(monkeypatch):
    known = {"doc1": "aaa"}
    _library(monkeypatch, known)
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("which?")
        _metered_call(send)("which?")
        assert len(send.calls) == 1
        known.clear()
        known["doc1"] = "a-new-revision"
        _metered_call(send)("which?")
    assert len(send.calls) == 2, "a replaced file's answer was served"


def test_forget_documents_removes_the_files_that_carried_it_and_no_others(monkeypatch):
    _library(monkeypatch, {"doc1": "aaa", "doc2": "bbb"})
    send = _send()
    with claude_approved.carrying(["doc1"]):
        _metered_call(send)("one")
    with claude_approved.carrying(["doc2"]):
        _metered_call(send)("two")
    assert cache.forget_documents(["doc1"]) == 1
    left = list(Path(settings.claude_cache_dir).rglob("*.json"))
    assert (
        len(left) == 1 and "doc2" in json.loads(left[0].read_text("utf-8"))["documents"]
    )


# ------------------------------------------------- corrupt, off, where it lives


@pytest.mark.parametrize(
    "junk",
    ["{not json", "[]", "null", '{"text": "old shape"}', '{"stop_reason": "end_turn"}'],
)
def test_a_corrupt_file_is_a_miss_not_a_crash(junk):
    send = _send()
    _metered_call(send)("which?")
    for path in Path(settings.claude_cache_dir).rglob("*.json"):
        path.write_text(junk, encoding="utf-8")
    assert _metered_call(send)("which?") == ANSWER
    assert len(send.calls) == 2


def test_a_binary_file_is_a_miss_not_a_crash():
    send = _send()
    _metered_call(send)("which?")
    for path in Path(settings.claude_cache_dir).rglob("*.json"):
        path.write_bytes(b"\xff\xfe\x00bad")
    assert _metered_call(send)("which?") == ANSWER
    assert len(send.calls) == 2


def test_answer_reuse_off_reads_and_keeps_nothing(monkeypatch):
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    send = _send()
    _metered_call(send)("which?")
    _metered_call(send)("which?")
    assert len(send.calls) == 2
    assert not list(Path(settings.claude_cache_dir).rglob("*.json"))


def test_the_default_folder_moves_with_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_cache_dir", None)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "elsewhere")
    assert cache._root() == (tmp_path / "elsewhere").resolve() / "claude_cache"


def test_no_document_text_reaches_the_log_or_the_ledger(caplog):
    secret = "THE-CLIENT-SENTENCE-XYZ"
    send = _send(reply=json.dumps({"answer": secret}))
    with caplog.at_level("DEBUG"):
        _metered_call(send)(secret)
        _metered_call(send)(secret)
        for path in Path(settings.claude_cache_dir).rglob("*.json"):
            path.write_text("{broken " + secret, encoding="utf-8")
        _metered_call(send)(secret)
    assert secret not in caplog.text
    assert secret not in Path(settings.claude_spend_log).read_text("utf-8")


# ------------------------------------------------- what the ledger and audit say


def test_spend_reports_hits_misses_and_the_usd_a_hit_saved():
    send = _send()
    _metered_call(send)("which?")
    paid = claude_spend.spent()
    _metered_call(send)("which?")
    _metered_call(send)("which?")
    report = claude_spend.cache_report()
    assert (report["hits"], report["misses"]) == (2, 1)
    assert report["saved_usd"] == pytest.approx(2 * paid)
    assert claude_spend.spent() == paid, "a hit was charged"


def test_a_hit_still_names_the_model_for_the_run_record():
    send = _send()
    _metered_call(send)("which?")
    _metered_call(send)("which?")
    assert claude_spend.models_used(since="2000-01-01T00:00:00+00:00") == [
        send.calls[0]["model"]
    ]


def test_the_audit_records_not_sent_cache_hit():
    send = _send()
    with open_ledger():
        _metered_call(send)("which?")
        _metered_call(send)("which?")
        rows = snapshot()
    assert rows[0]["cache_hits"] == 1 and rows[0]["reused"] == 1
    steps = review_audit._ledger_steps(rows)
    assert "not sent: cache hit" in steps[0]["not_sent"]
    audit = {
        "ai_use": {
            "steps": [{**steps[0]}],
            "totals": {"fresh": 0, "failed": 0, "reused": 1, "boundary": "b"},
        }
    }
    assert any("not sent: cache hit" in line for line in review_audit._md_ai(audit))
    assert review_audit_rows.cache_lines({}) == []


def test_the_whole_ledger_report_counts_hits_and_misses():
    send = _send()
    _metered_call(send)("which?")
    _metered_call(send)("which?")
    report = claude_spend.cache_report()
    assert (report["hits"], report["misses"]) == (1, 1)


def test_no_lane_reserves_without_asking_the_cache_first():
    """A new way to reach the money cannot skip the door by accident."""
    app = Path(cache.__file__).resolve().parent
    for path in app.rglob("*.py"):
        if path.name == "claude_spend.py":
            continue
        source = path.read_text("utf-8")
        if re.search(r"claude_spend\.reserve(_all)?\(", source):
            assert "claude_spend.answer_on_file" in source, (
                f"{path.name} reserves past the cache"
            )


def test_the_reader_lanes_build_one_request_for_the_key():
    """`build_request` is the source of the body the key hashes; the model is in it."""
    body = reader_api.build_request("q", cfg=reader_api.ReaderSettings.from_env())[
        "body"
    ]
    assert "model" in body and "stream" not in body
    assert cache.key_of("s", "v", body) == cache.key_of(
        "s", "v", {**body, "stream": True}
    )
    assert cache.key_of("s", "v", body) != cache.key_of(
        "s", "v", {**body, "model": "other"}
    )


def test_the_matchers_two_asks_each_have_their_own_answer(monkeypatch):
    """Its stability check builds a new wrapper per ask, so `nth` must reach the key."""
    from app import comparison, reader_transport

    send = _send()
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(settings, "match_engine", "claude")
    comparison._ask_claude_for_a_pair("which?", nth=0)
    comparison._ask_claude_for_a_pair("which?", nth=1)
    assert len(send.calls) == 2, (
        "the second ask of the stability check was served the first answer"
    )
    comparison._ask_claude_for_a_pair("which?", nth=1)
    assert len(send.calls) == 2, "the re-run paid again"
