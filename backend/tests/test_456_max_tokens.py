"""#456 (C-H5): one output cap per model-call route, and a reply the cap cut
off is the NAMED state `truncated` - never parsed as a complete answer, and
no verdict is stored from it. A reply with nothing readable is `unknown`.

No network: every transport and provider here is a fake. Nothing in this file
sends document text anywhere, and nothing asserts on reply text in a log.
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace

import pytest

from app import (
    access,
    claude_api,
    claude_recheck,
    claude_selection,
    claude_spend,
    comparison,
    crs_wording,
    db,
    reader_api,
    submittal_review,
)
from app import reasoning_provider as rp
from app.ai import output_limits as ol
from app.config import settings

KEY = "sk-ant-test-NEVER-IN-A-LOG-0123456789"
DOC_TEXT = "CONFIDENTIAL-CLAUSE-7.3.2 the pump shall be rated 40 bar"


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def lane(tmp_path, monkeypatch):
    """The Claude lane open on paper (flags, key, provider), with the ledger
    and database in a temp folder. Nothing can leave: the transport is faked."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "max_tokens.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _transport(monkeypatch, *, stop_reason="end_turn", text='{"agree": true, "quote": "90 dB(A)"}',
               content=True):
    """A fake `reader_transport.transport()`; returns the bodies it sent."""
    sent: list[dict] = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        payload = {"model": "claude-sonnet-4-5", "stop_reason": stop_reason,
                   "usage": {"input_tokens": 100, "output_tokens": 50}}
        if content:
            payload["content"] = [{"type": "text", "text": text}]
        return payload
    send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport", lambda: send)
    return sent


def _response(text: str, finish_reason: str, provider: str = rp.OLLAMA) -> rp.Response:
    return rp.Response(text=text, provider=provider, model_tag="fake-1", digest="d",
                       finish_reason=finish_reason, prompt_sha256="p", tokens_out=7)


SENTENCE = "The noise level shall not exceed 90 dB(A)."


def _finding(status=comparison.COMPLIANT) -> dict:
    return {"id": "f1", "compliance_status": status, "requirement": SENTENCE,
            "requirement_source_text": SENTENCE, "standard_clause": "5.3.3",
            "matched_phrase": "noise level", "contractor_evidence_text": "85 dB(A)",
            "value": "85", "unit": "dB(A)", "ai_rationale": "within the limit",
            "unresolved_evidence": [], "confirmed_by": None}


def _stored_finding(status) -> str:
    fid = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('d1','s.pdf','sha-d1',1,'s.pdf','ready',1,'2026-09-18T00:00:00Z')
            ON CONFLICT(id) DO NOTHING""")
        columns = {"id": fid, "document_id": "d1", "category": "requirement_deviation",
                   "severity": "major", "requirement": SENTENCE, "finding": "x",
                   "required_action": comparison._required_action(status),
                   "created_at": "2026-09-18T00:00:00Z", "updated_at": "2026-09-18T00:00:00Z",
                   "review_run_id": "run", "compliance_status": status,
                   "ai_rationale": "engine said so"}
        conn.execute(f"INSERT INTO review_findings ({','.join(columns)})"
                     f" VALUES ({','.join('?' * len(columns))})", list(columns.values()))
    return fid


def _row(fid: str) -> dict:
    return dict(db.connect().execute("SELECT * FROM review_findings WHERE id = ?", (fid,)).fetchone())


# ------------------------------------------- (a) a length-cut reply is `truncated`

@pytest.mark.parametrize("stop", sorted(ol.LENGTH_STOPS))
def test_both_engines_length_stops_are_the_one_truncated_state(stop):
    """Ollama says `length`, Anthropic says `max_tokens`: one state, and a
    cut-off reply WITH text is still truncated - the cap is checked first."""
    assert ol.state_of(stop, '{"agree": tr') == ol.TRUNCATED
    assert ol.state_of(stop, "") == ol.TRUNCATED


def test_the_provider_maps_anthropics_stop_to_the_same_word():
    """`Response.truncated` and `state_of` must never disagree (rule 8)."""
    assert rp._STOP["max_tokens"] == "length"
    cut = _response('{"agree": tr', "length")
    assert cut.truncated and ol.state_of_response(cut) == ol.TRUNCATED
    whole = _response('{"agree": true}', "stop")
    assert not whole.truncated and ol.state_of_response(whole) == ol.COMPLETE


def test_complete_text_refuses_a_truncated_reply_by_name(caplog):
    cut = _response('{"agree": tr', "length")
    with caplog.at_level(logging.INFO, logger="app.ai.output_limits"), \
            pytest.raises(ol.Truncated) as info:
        ol.complete_text(cut, ol.ROUTE_RECHECK)
    assert info.value.state == ol.TRUNCATED and info.value.route == ol.ROUTE_RECHECK
    assert info.value.tokens_out == 7
    # The log names the route and a count - never the reply.
    assert "route=recheck" in caplog.text and "agree" not in caplog.text
    assert ol.complete_text(_response("ok", "stop"), ol.ROUTE_RECHECK) == "ok"


def test_the_claude_lane_raises_truncated_and_the_recheck_stores_no_verdict(lane, monkeypatch):
    """The whole path: a Messages reply with `stop_reason: max_tokens` -> the
    route's model_call raises `Truncated` -> the recheck names it and keeps
    `agree` None -> `store_recheck` changes nothing on the finding."""
    sent = _transport(monkeypatch, stop_reason="max_tokens", text='{"agree": false, "quote": "9')
    model_call, _t = claude_api._model_call_or_409(claude_api.STEP_RECHECK)
    with pytest.raises(ol.Truncated):
        model_call(DOC_TEXT)
    assert len(sent) == 1
    # Ledger: the cut-off call was still paid for and is on the ledger by name
    # (`claude_spend.metered` writes Anthropic's spelling; the provider lane
    # writes Ollama's - both are the one length state here).
    assert [e["finish_reason"] in ol.LENGTH_STOPS for e in claude_spend.entries()] == [True]

    result = claude_recheck.recheck_finding(_finding(comparison.COMPLIANT), model_call)
    assert result["agree"] is None and result["error"] == ol.TRUNCATED
    assert result["raise_to_engineer"] is False

    fid = _stored_finding(comparison.COMPLIANT)
    out = claude_recheck.store_recheck(fid, result)
    assert out["stored"] is False and out["raised"] is False
    assert out["reasons"] == [ol.TRUNCATED]
    row = _row(fid)
    assert row["compliance_status"] == comparison.COMPLIANT
    assert row["ai_rationale"] == "engine said so"


def test_a_truncated_second_answer_is_no_verdict_either():
    """Rule 5 needs both answers; the first was complete, the second was cut."""
    answers = iter(['{"agree": true, "quote": "90 dB(A)"}', ol.Truncated(ol.ROUTE_RECHECK)])

    def model_call(prompt):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer
    result = claude_recheck.recheck_finding(_finding(), model_call)
    assert result["agree"] is None and result["error"] == ol.TRUNCATED
    assert claude_recheck.note_for(result) is None


def test_the_selection_names_a_truncated_reply_and_selects_nothing():
    def model_call(prompt):
        raise ol.Truncated(ol.ROUTE_SELECT_STANDARDS, 512)
    out = claude_selection.select_standards(
        {"equipment_type": "pump"}, [{"code": "API 610", "document_id": "d1"}], model_call)
    assert out["accepted"] == [] and out["error"] == ol.TRUNCATED


def test_crs_wording_counts_a_truncated_reply_by_name_and_keeps_the_template(lane):
    class Cut:
        def reason(self, packet):
            self.packet = packet
            return _response('{"comment": "The pump shall', "length")
    provider = Cut()
    row = {"standard_reference": "API 610", "page_section": "p. 3", "comment": "Pump rated 40 bar."}
    text, refused, model = crs_wording._ask(provider, row)
    assert text is None and refused == ol.TRUNCATED
    assert model == "ollama:fake-1"
    assert refused != crs_wording.MALFORMED, "a cut-off reply is not a bad answer, it is no answer"


def test_the_matcher_names_a_truncated_claude_reply(lane, monkeypatch):
    monkeypatch.setattr(settings, "match_engine", "claude")
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    sent = _transport(monkeypatch, stop_reason="max_tokens", text='{"choice": 0, "reason": "the')
    import app.reader_transport as reader_transport
    monkeypatch.setattr(reader_transport, "transport",
                        claude_api.reader_transport_mod.transport)
    answer, why = comparison._ask_claude_for_a_pair("which candidate?")
    assert answer is None and why == comparison.MODEL_TRUNCATED
    assert sent and sent[0]["max_tokens"] == ol.max_tokens_for(ol.ROUTE_MATCH) == 200


def test_the_task_runner_calls_a_cut_off_empty_reply_truncated_not_empty():
    from app import ai_task_runner
    spec = ai_task_runner.TaskSpec(name="t", version="v", instruction="i",
                                   schema={"type": "object"}, num_predict=10)
    problems = ai_task_runner._reply_problems(spec, _response("", "length"), "x")
    assert problems == ["the reply was cut off before it ended"]
    assert ai_task_runner._reply_problems(spec, _response("", "stop"), "x") == ["the reply was empty"]


# ------------------------------------------ (b) each route picks its own cap

def test_an_unlisted_route_gets_the_lanes_previous_global_value():
    assert ol.max_tokens_for("no-such-route") == ol.DEFAULT_MAX_TOKENS == 512
    assert ol.max_tokens_for(None) == ol.DEFAULT_MAX_TOKENS
    # The two homes of that number agree (rule 8).
    assert reader_api.ReaderSettings.max_tokens == ol.DEFAULT_MAX_TOKENS


def test_every_listed_route_has_its_own_positive_cap():
    assert set(ol.ROUTE_MAX_TOKENS) >= {
        ol.ROUTE_DATASHEET_READ, ol.ROUTE_MATCH, ol.ROUTE_CRS_WORDING, ol.ROUTE_APPLICABILITY,
        ol.ROUTE_ENGINEERING_CHECK, ol.ROUTE_CHAT, ol.ROUTE_RECHECK}
    for route in ol.ROUTE_MAX_TOKENS:
        assert ol.max_tokens_for(route) > 0, route


def test_a_setting_backed_route_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "chat_max_output_tokens", 1234)
    assert ol.max_tokens_for(ol.ROUTE_CHAT) == 1234
    monkeypatch.setattr(settings, "datasheet_ai_claude_max_tokens", 4321)
    assert ol.max_tokens_for(ol.ROUTE_DATASHEET_READ) == 4321


@pytest.mark.parametrize("step", claude_api.STEPS)
def test_each_claude_route_sends_its_own_max_tokens(step, lane, monkeypatch):
    sent = _transport(monkeypatch)
    model_call, _t = claude_api._model_call_or_409(step)
    model_call(DOC_TEXT)
    assert sent[0]["max_tokens"] == ol.max_tokens_for(claude_api.ROUTES[step])


def test_the_recheck_and_datasheet_routes_differ_from_each_other_and_the_default(lane, monkeypatch):
    """The point of a per-route table: the datasheet page gets the budget
    #501 measured it needs, the recheck a small one, and neither is 512."""
    caps = {}
    for step in (claude_api.STEP_RECHECK, claude_api.STEP_READ_DATASHEET):
        sent = _transport(monkeypatch)
        claude_api._model_call_or_409(step)[0](DOC_TEXT)
        caps[step] = sent[0]["max_tokens"]
    assert caps[claude_api.STEP_RECHECK] == 600
    assert caps[claude_api.STEP_READ_DATASHEET] == settings.datasheet_ai_claude_max_tokens
    assert ol.DEFAULT_MAX_TOKENS not in caps.values()


def test_the_local_recheck_uses_the_same_route_cap(monkeypatch):
    packets = []

    class Local:
        def reason(self, packet):
            packets.append(packet)
            return _response('{"agree": true, "quote": "90 dB(A)"}', "stop")
    monkeypatch.setattr(rp, "OllamaProvider", lambda **kw: Local())
    budget = claude_api._local_recheck_call()
    assert json.loads(budget("prompt"))["agree"] is True
    assert packets[0].num_predict == ol.max_tokens_for(ol.ROUTE_RECHECK) == 600


def test_crs_wording_and_applicability_take_their_caps_from_the_table():
    from app import applicability_reasoning

    class Echo:
        def reason(self, packet):
            self.packet = packet
            return _response('{"comment": "x"}', "stop")
    provider = Echo()
    crs_wording._ask(provider, {"standard_reference": "", "page_section": "", "comment": "c"})
    assert provider.packet.num_predict == ol.max_tokens_for(ol.ROUTE_CRS_WORDING) == 300
    assert applicability_reasoning.NUM_PREDICT == ol.max_tokens_for(ol.ROUTE_APPLICABILITY) == 400


# -------------------------------------------- (c) nothing readable is `unknown`

@pytest.mark.parametrize("payload", [None, {}, {"stop_reason": "end_turn"},
                                     {"stop_reason": "end_turn", "content": []},
                                     {"stop_reason": "error", "content": [{"type": "text", "text": "x"}]}])
def test_a_missing_or_unreadable_payload_is_unknown(payload):
    assert ol.state_of_payload(payload) == ol.UNKNOWN


def test_the_claude_lane_raises_unreadable_for_a_reply_with_no_text(lane, monkeypatch):
    _transport(monkeypatch, content=False)
    model_call, _t = claude_api._model_call_or_409(claude_api.STEP_SELECT_STANDARDS)
    with pytest.raises(ol.Unreadable) as info:
        model_call(DOC_TEXT)
    assert info.value.state == ol.UNKNOWN
    result = claude_recheck.recheck_finding(_finding(), model_call)
    assert result["agree"] is None and result["error"] == ol.UNKNOWN


def test_crs_wording_names_an_unreadable_reply_unknown():
    class Nothing:
        def reason(self, packet):
            return _response("", "stop")
    text, refused, _model = crs_wording._ask(Nothing(), {"standard_reference": "", "page_section": "",
                                                        "comment": "c"})
    assert text is None and refused == ol.UNKNOWN


def test_complete_text_raises_unreadable_for_an_error_reply():
    with pytest.raises(ol.Unreadable):
        ol.complete_text(_response("", "error", rp.CLAUDE), ol.ROUTE_CHAT)


# ------------------------------------------------ the one salvage caller (#501)

def test_the_datasheet_reader_keeps_a_cut_off_replys_text_but_never_an_empty_one(lane, monkeypatch):
    """`claude_datasheet.parse_or_cut` walks a cut-off facts array for the
    complete facts and marks the page `cut_off` (#501, owner-measured): that
    one route gets the text back. A reply with no text is still "" - it
    becomes the page's own named error, never a fact."""
    sent = _transport(monkeypatch, stop_reason="max_tokens", text='{"facts": [{"a": 1}, {"b"')
    model_call, _t = claude_api._model_call_or_409(claude_api.STEP_READ_DATASHEET)
    assert model_call(DOC_TEXT) == '{"facts": [{"a": 1}, {"b"'
    assert sent[0]["max_tokens"] == ol.max_tokens_for(ol.ROUTE_DATASHEET_READ)
    _transport(monkeypatch, stop_reason="max_tokens", content=False)
    model_call, _t = claude_api._model_call_or_409(claude_api.STEP_READ_DATASHEET)
    assert model_call(DOC_TEXT) == ""


def test_a_fake_without_a_stop_reason_is_not_complete():
    """A reply that cannot say how it ended is not one to parse."""
    assert ol.state_of_response(SimpleNamespace(text="x")) == ol.UNKNOWN
