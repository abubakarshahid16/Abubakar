"""#626: background work must not make every request slow, and the log must
say what was running. Mutations M3001-M3008."""
from __future__ import annotations

import logging
import threading
import time

import httpx
import pytest

from app import acronyms, db, metrics, model_transport, risks, warmup
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w626.sqlite")
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


# ----------------------------------------------- one client for the metrics probe

def test_the_metrics_probe_reuses_one_http_client(monkeypatch):
    built = []
    handler_calls = []

    def handler(request):
        handler_calls.append(str(request.url))
        return httpx.Response(200, json={"models": []})

    real_client = httpx.Client
    model_transport.close_shared_client()
    monkeypatch.setattr(
        httpx, "Client",
        lambda *a, **k: (built.append(1), real_client(*a, transport=httpx.MockTransport(handler), **k))[1])
    for _ in range(5):
        assert model_transport.get_json("/api/tags", timeout=1.0) == {"models": []}
    assert len(handler_calls) == 5          # positive first: five real calls
    assert len(built) == 1                   # ... on ONE client


def test_a_per_call_timeout_still_applies(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(200, json={})

    real_client = httpx.Client
    model_transport.close_shared_client()
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    model_transport.get_json("/api/tags", timeout=2.5)
    model_transport.get_json("/api/tags", timeout=7.0)
    assert seen[0]["read"] == 2.5 and seen[1]["read"] == 7.0


# ------------------------------------------- "is Ollama reachable" is cached 30 s

def test_the_ollama_probe_is_cached_and_asked_again_after_the_ttl(monkeypatch):
    calls = []

    def fake(path, *, timeout, required=True):
        calls.append(path)
        return {"models": [{"name": settings.answer_model}]}

    monkeypatch.setattr(model_transport, "get_json", fake)
    clock = [1000.0]
    monkeypatch.setattr(metrics.time, "monotonic", lambda: clock[0])
    first = metrics._ollama_state()
    second = metrics._ollama_state()
    assert first["answer_model_reachable"] is True          # positive first
    assert second == first
    assert calls == ["/api/tags", "/api/ps"]                # asked ONCE (two paths)
    clock[0] += metrics.OLLAMA_PROBE_TTL_SECONDS + 1
    metrics._ollama_state()
    assert calls == ["/api/tags", "/api/ps"] * 2             # and again after the TTL


def test_a_changed_host_or_model_is_asked_again_at_once(monkeypatch):
    calls = []
    monkeypatch.setattr(model_transport, "get_json",
                        lambda path, *, timeout, required=True: calls.append(path) or {"models": []})
    metrics._ollama_state()
    monkeypatch.setattr(settings, "answer_model", "another-model")
    metrics._ollama_state()
    assert len(calls) == 4


def test_a_refused_host_is_never_cached(monkeypatch):
    def refuse(path, *, timeout, required=True):
        raise model_transport.ModelHostRefused("no")

    monkeypatch.setattr(model_transport, "get_json", refuse)
    for _ in range(2):
        with pytest.raises(model_transport.ModelHostRefused):
            metrics._ollama_state()


# ------------------------------------------- the detection job yields between batches

def test_risk_detection_pauses_between_batches_and_still_finds_everything(monkeypatch):
    pauses = []
    monkeypatch.setattr(risks, "_pause_between_batches", lambda: pauses.append(1))
    monkeypatch.setattr(risks, "RISK_BATCH_SIZE", 5)
    old = "2020-01-01T00:00:00Z"
    findings = [{"id": f"f{i}", "severity": "major", "document_id": "d", "owner_user_id": None,
                 "due_date": None, "status": "open", "updated_at": old,
                 "category": "x", "unresolved_evidence": "[]"} for i in range(12)]
    monkeypatch.setattr(risks, "_candidate_findings", lambda allowed: findings)
    inserted = []
    monkeypatch.setattr(risks, "_insert_many", lambda items: inserted.extend(items))
    monkeypatch.setattr(risks, "OPEN_REVIEW_STATUSES", ("open",))
    created = risks.detect_automatic_risks()
    assert len(created) == 12 == len(inserted)       # nothing lost to the batching
    assert len(pauses) == 2                          # 12 findings, batches of 5: 5+5+2


def test_the_pause_is_a_real_sleep_that_lets_other_threads_run(monkeypatch):
    slept = []
    monkeypatch.setattr(risks.time, "sleep", lambda s: slept.append(s))
    risks._pause_between_batches()
    assert slept == [risks.RISK_BATCH_PAUSE_SECONDS] and slept[0] > 0


# ------------------------------------------------------------ log lines are written

def test_risk_detection_logs_its_start_end_and_duration(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    monkeypatch.setattr(risks, "detect_automatic_risks", lambda **k: [])
    from app import deliverables, notifications
    monkeypatch.setattr(deliverables, "generate_reminders", lambda **k: 0)
    monkeypatch.setattr(notifications, "send_risk_digest", lambda created: "none")
    risks.run_detection()
    messages = [r.getMessage() for r in caplog.records]
    assert "risk detection started" in messages
    assert any(m.startswith("risk detection finished in ") and "s created=0" in m for m in messages)


def test_the_acronym_warm_up_logs_its_start_end_and_duration(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    monkeypatch.setattr(settings, "startup_warmup", True)
    monkeypatch.setattr(acronyms, "warm_all", lambda: 3)
    monkeypatch.setattr(acronyms, "_warm_thread", None)
    assert acronyms.warm_in_background() is True
    acronyms._warm_thread.join(5)
    messages = [r.getMessage() for r in caplog.records]
    assert "acronym warm-up started" in messages
    assert any(m.startswith("acronym warm-up finished in ") and "3 document map(s) built" in m
               for m in messages)


def test_the_startup_warm_up_logs_each_step_with_its_duration(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    warmup._run((("acronyms", lambda: None),))
    messages = [r.getMessage() for r in caplog.records]
    assert "startup warm-up step 'acronyms' started" in messages
    assert any(m.startswith("startup warm-up step 'acronyms' finished in ") for m in messages)
