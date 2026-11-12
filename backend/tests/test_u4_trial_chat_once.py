"""`scripts/trial_chat_once.py`: one general chat question to Claude through the chat's own function. Fake transport only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app import claude_spend
from app.config import settings
from tests.test_chat import temp_storage  # noqa: F401 - autouse fixture
from tests.test_chat_pr1_model_lane import _stream_events

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("trial_chat_once_under_test", REPO / "scripts" / "trial_chat_once.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(module, tmp_path, **over):
    data = tmp_path / "copy"
    data.mkdir(exist_ok=True)
    ns = module.argparse.Namespace(data_dir=str(data), out=str(tmp_path / "out.json"), question=module.DEFAULT_QUESTION,
                                   max_usd=0.20, model=None, plan=False, document=None)
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def lane(monkeypatch, tmp_path):
    for name in ("REASONING_PROVIDER", "CHAT_MODEL_ENGINE", "STANDARDS_READER_ENABLED",
                 "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-invented-not-real")
    for name in ("reasoning_provider", "chat_model_engine", "standards_reader_enabled",
                 "standards_reader_allow_public_egress", "claude_reasoning_model", "claude_budget_usd_per_step",
                 "claude_budget_usd_total", "claude_spend_log", "claude_cache_dir", "data_dir", "upload_dir", "db_path"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    return _load()


def _answer_stream(seen):
    def stream(url, *, headers, body, timeout, cancel=None):
        seen.append(body)
        yield from _stream_events({"model": body["model"], "stop_reason": "end_turn",
                                   "content": [{"type": "text", "text": "Gauge pressure ignores the atmosphere."}],
                                   "usage": {"input_tokens": 900, "output_tokens": 20}})
    return stream


def _rejecting_stream(seen, message):
    def stream(url, *, headers, body, timeout, cancel=None):
        seen.append(body)
        raise httpx.HTTPStatusError(f"400 from api.anthropic.com (invalid_request_error: {message})",
                                    request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                                    response=httpx.Response(400))
        yield  # pragma: no cover

    return stream


def test_an_answer_exits_zero_and_the_result_holds_lengths_not_text(lane, tmp_path):
    seen: list = []
    code, record = lane.run(_args(lane, tmp_path), stream=_answer_stream(seen))
    assert code == 0 and record["answered"] is True and record["http_status"] == 200
    assert record["answer_chars"] == len("Gauge pressure ignores the atmosphere.") and "Gauge" not in json.dumps(record)
    assert record["calls"] == 1 and record["bytes_sent"] > 1000 and record["model"]
    # the chat's own request: the fixed prompt, the tools and the question; no document, no history
    first = seen[0]
    assert first["messages"] == [{"role": "user", "content": lane.DEFAULT_QUESTION}]
    assert claude_spend.entries()[0]["step"] == "chat"  # through claude_spend, charged to chat
    assert settings.reasoning_provider == "per_task" and settings.chat_model_engine == "claude"


def test_an_api_refusal_exits_three_with_the_apis_type_and_message(lane, tmp_path):
    code, record = lane.run(_args(lane, tmp_path), stream=_rejecting_stream([], "max_tokens: must be positive"))
    assert code == 3 and record["answered"] is False
    assert record["http_status"] == 400 and record["error_type"] == "invalid_request_error"
    assert record["error_message"] == "max_tokens: must be positive"
    assert "sk-invented" not in json.dumps(record) and "messages" not in json.dumps(record)


def test_main_writes_the_out_file_and_prints_both_model_ids_first(lane, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(lane, "run", lambda args, stream=None: (3, {"http_status": 400, "error_type": "x"}))
    data = tmp_path / "copy"
    data.mkdir()
    out = tmp_path / "o.json"
    code = lane.main(["--data-dir", str(data), "--out", str(out), "--model", "claude-sonnet-5-5"])
    text = capsys.readouterr().out
    assert code == 3 and json.loads(out.read_text())["http_status"] == 400
    assert text.index("chat lane model: claude-sonnet-5-5") < text.index("AI reviewer models:")
    assert "claude-sonnet-5-5 (lead), claude-opus-5-5 (second reader)" in text
    assert "uses a reviewer model id" in text
    code = lane.main(["--data-dir", str(data), "--out", str(out), "--model", "claude-sonnet-4"])
    assert "MODEL IDS DIFFER" in capsys.readouterr().out and code == 3


def test_plan_sends_nothing(lane, tmp_path, capsys):
    called = []
    lane.run = lambda *a, **k: called.append(1)
    data = tmp_path / "copy"
    data.mkdir()
    assert lane.main(["--data-dir", str(data), "--out", str(tmp_path / "o.json"), "--plan"]) == 0
    assert called == [] and not (tmp_path / "o.json").exists()


def test_it_refuses_the_live_folder_a_document_and_a_missing_key(lane, tmp_path, monkeypatch):
    live = Path.home() / "project" / "Abubakar" / "backend" / "data"
    assert lane.main(["--data-dir", str(live), "--out", str(tmp_path / "o.json")]) == 2
    assert lane.main(["--data-dir", str(tmp_path / "does-not-exist"), "--out", str(tmp_path / "o.json")]) == 2
    with pytest.raises(lane.Refused, match="no document"):
        lane.run(_args(lane, tmp_path, document=["doc_1"]), stream=_answer_stream([]))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(lane.Refused, match="no ANTHROPIC_API_KEY"):
        lane.run(_args(lane, tmp_path))
    assert not (tmp_path / "o.json").exists()


def test_the_spend_cap_holds_before_anything_is_sent(lane, tmp_path):
    seen: list = []
    code, record = lane.run(_args(lane, tmp_path, max_usd=0.0001), stream=_answer_stream(seen))
    assert seen == [] and code == 1 and record["answered"] is False
