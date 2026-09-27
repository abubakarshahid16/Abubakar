"""The four Claude review routes obey the owner's USD caps (USD 5 per step /
USD 20 in total, `claude_spend`) - checked BEFORE a call leaves, and each call
written to the one ledger the caps read.

Before this, the routes were held only by `claude_budget`'s call-count cap and
their spend went to a separate token counter that the USD caps never read.
No network: the transport is a fake closed over a list.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import (access, claude_api, claude_crs_comments, claude_datasheet, claude_recheck,
                 claude_selection, claude_spend, crs_export, db, submittal_review)
from app.config import settings
from app.main import app

KEY = "sk-ant-test-NEVER-IN-A-LOG-0123456789"
#: Stands in for document text; must never appear in an error message.
DOC_TEXT = "CONFIDENTIAL-CLAUSE-7.3.2 the pump shall be rated 40 bar"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "spend_routes.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    app.dependency_overrides.clear()
    db.reset_connection()


def _fake_transport(monkeypatch, usage=None):
    """Install a fake `reader_transport.transport()`; return the list of
    bodies it was asked to send."""
    sent: list[dict] = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        send.usage["calls"] += 1
        return {"model": "claude-sonnet-4-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "{}"}],
                "usage": usage or {"input_tokens": 1000, "output_tokens": 100}}
    send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport", lambda: send)
    return sent


def _seed_ledger(step: str, usd: float) -> None:
    path = settings.claude_spend_log
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"step": step, "cost_usd": usd}) + "\n")


# ------------------------------------------------ the check, per route step

@pytest.mark.parametrize("step", claude_api.STEPS)
def test_the_per_step_cap_refuses_before_anything_is_sent(step, monkeypatch):
    sent = _fake_transport(monkeypatch)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    model_call, _transport = claude_api._model_call_or_409(step)
    with pytest.raises(claude_spend.BudgetExceeded):
        model_call(DOC_TEXT)
    assert sent == []


@pytest.mark.parametrize("step", claude_api.STEPS)
def test_the_total_cap_counts_spend_from_other_steps(step, monkeypatch):
    sent = _fake_transport(monkeypatch)
    _seed_ledger("chat", 19.9999)          # someone else's step, near the total
    model_call, _transport = claude_api._model_call_or_409(step)
    with pytest.raises(claude_spend.BudgetExceeded, match="total"):
        model_call(DOC_TEXT)
    assert sent == []


@pytest.mark.parametrize("step", claude_api.STEPS)
def test_each_call_is_written_to_the_ledger_the_caps_read(step, monkeypatch):
    sent = _fake_transport(monkeypatch)
    model_call, _transport = claude_api._model_call_or_409(step)
    model_call(DOC_TEXT)
    assert len(sent) == 1
    entries = claude_spend.entries()
    assert [e["step"] for e in entries] == [step]
    # 1000 in / 100 out at Sonnet 4.5 list price.
    assert claude_spend.spent(step) == pytest.approx((1000 * 3.0 + 100 * 15.0) / 1e6)
    assert claude_spend.spent() == claude_spend.spent(step)
    assert DOC_TEXT not in claude_spend._ledger_path().read_text(encoding="utf-8")


def test_recorded_spend_stops_the_next_call_on_the_same_step(monkeypatch):
    """One call fits under the step cap; once it is on the ledger the next
    one no longer does. This only holds if the route's own calls are counted."""
    sent = _fake_transport(monkeypatch, usage={"input_tokens": 1_000_000, "output_tokens": 0})
    worst = claude_spend.worst_case_usd("claude-sonnet-4-5", 200, 512)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 3.0 + worst / 2)
    model_call, _transport = claude_api._model_call_or_409(claude_api.STEP_RECHECK)
    model_call("short prompt")              # costs USD 3.00 once recorded
    with pytest.raises(claude_spend.BudgetExceeded, match="per step"):
        model_call("short prompt")
    assert len(sent) == 1


def test_a_step_must_be_named():
    with pytest.raises(ValueError):
        claude_api._model_call_or_409("not-a-route")


# ------------------------------------------------ the routes, end to end

def _stub_modules(monkeypatch):
    """Every module the routes call, reduced to 'ask the model once about
    DOC_TEXT' - so what is under test is the route's wiring to the lane."""
    run = {"id": "run-x", "submittal_document_id": "doc-1"}
    monkeypatch.setattr(claude_api, "_run_or_404", lambda rid, scope: run)
    monkeypatch.setattr(claude_api, "_datasheet_summary", lambda sid, scope: {"text": DOC_TEXT})
    monkeypatch.setattr(claude_selection, "candidates_from_corpus", lambda **kw: [])
    monkeypatch.setattr(claude_selection, "select_standards",
                        lambda summary, candidates, call: {"answer": call(DOC_TEXT)})
    monkeypatch.setattr(claude_selection, "store_selection", lambda *a, **kw: {})
    monkeypatch.setattr(claude_datasheet, "read_datasheet",
                        lambda sid, *, allowed_document_ids, model_call: {"a": model_call(DOC_TEXT)})
    monkeypatch.setattr(claude_datasheet, "store_facts", lambda *a, **kw: {})
    monkeypatch.setattr(claude_recheck, "recheck_run",
                        lambda rid, call, *, allowed_document_ids: {"a": call(DOC_TEXT)})
    monkeypatch.setattr(claude_crs_comments, "draft_run",
                        lambda rid, call, **kw: {"a": call(DOC_TEXT)})
    monkeypatch.setattr(claude_crs_comments, "apply_drafts", lambda view, drafts: {})
    monkeypatch.setattr(crs_export, "build_crs_view", lambda rows, meta: {})
    from app import main
    monkeypatch.setattr(main, "_crs_content", lambda rid, scope: ([], {}, "sub.pdf", "stamp"))


ROUTES = [
    ("post", "/api/reviews/runs/run-x/claude/select-standards", claude_api.STEP_SELECT_STANDARDS),
    ("post", "/api/reviews/runs/run-x/claude/read-datasheet", claude_api.STEP_READ_DATASHEET),
    ("post", "/api/reviews/runs/run-x/claude/recheck", claude_api.STEP_RECHECK),
    ("get", "/api/reviews/runs/run-x/claude/crs-draft", claude_api.STEP_CRS_DRAFT),
]


@pytest.mark.parametrize("method,path,step", ROUTES)
def test_a_route_over_the_cap_answers_409_and_sends_nothing(method, path, step, monkeypatch):
    sent = _fake_transport(monkeypatch)
    _stub_modules(monkeypatch)
    _seed_ledger(step, 4.9999)              # this route's step is at its cap
    response = getattr(TestClient(app), method)(path)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == claude_api.MODEL_DISABLED
    assert "not sent" in detail["message"]
    assert DOC_TEXT not in response.text and "CONFIDENTIAL" not in response.text
    assert sent == []


@pytest.mark.parametrize("method,path,step", ROUTES)
def test_a_route_under_the_cap_charges_its_own_step(method, path, step, monkeypatch):
    sent = _fake_transport(monkeypatch)
    _stub_modules(monkeypatch)
    response = getattr(TestClient(app), method)(path)
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    assert [e["step"] for e in claude_spend.entries()] == [step]
    usd = response.json()["usd_spent"]
    assert usd["step"] == step and usd["step_usd"] > 0 and usd["total_usd"] == usd["step_usd"]


def test_the_409_helper_is_what_the_routes_raise(monkeypatch):
    """`_capped` turns a USD refusal into the same 409 the routes use for
    'model disabled', and the message carries no prompt text."""
    sent = _fake_transport(monkeypatch)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 0.0)
    model_call, transport = claude_api._model_call_or_409(claude_api.STEP_CRS_DRAFT)
    with pytest.raises(HTTPException) as caught:
        claude_api._capped(model_call, lambda call: call(DOC_TEXT), transport)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == claude_api.MODEL_DISABLED
    assert "0 calls made before it" in caught.value.detail["message"]
    assert DOC_TEXT not in json.dumps(caught.value.detail)
    assert sent == []
