"""#615: chat and search never build the corpus's acronym maps inside the
request, read the corpus fingerprint once per request, and say when a map was
not ready.

On a copy of the live library the first question after a start or an ingest
spent about 21 s building every document's map inside the request. The Gap
analysis already ran in a no-build scope (#612); search and answer did not.

Invented engineering text only (the #606 fixture: 120 documents x 40 chunks).
Dense retrieval and the reranker are off, so no model is needed.
"""
from __future__ import annotations

import pytest

from app import acronyms, search
from app.config import settings
from tests.test_w7_gaps_freeze import corpus  # noqa: F401 - fixture

QUESTION = "What NDE is required for the design pressure?"


def _search(ids):
    return search.search(QUESTION, limit=5, rerank=False, dense=False,
                         allowed_document_ids=frozenset(ids))


@pytest.fixture
def server(corpus, monkeypatch):  # noqa: F811 - the fixture above
    """The server's default: a background builder exists."""
    monkeypatch.setattr(settings, "startup_warmup", True)
    started = []
    monkeypatch.setattr(acronyms, "warm_in_background", lambda: started.append(1) or True)
    return corpus, started


def test_a_cold_search_builds_no_map_and_says_how_many_were_not_ready(server, monkeypatch):
    ids, started = server

    def refuse(*_a, **_k):
        raise AssertionError("#615: a request must not build an acronym map")
    monkeypatch.setattr(acronyms, "_build_document_map", refuse)

    result = _search(ids)

    assert result["acronym_map"] == {"documents_not_ready": len(ids), "complete": False}
    assert started, "the missing maps are handed to the background builder"


def test_once_the_maps_are_built_the_same_search_is_complete(server):
    ids, started = server
    assert acronyms.warm_all() == len(ids)

    result = _search(ids)

    assert result["acronym_map"] == {"documents_not_ready": 0, "complete": True}
    assert not started


def test_the_corpus_fingerprint_is_read_once_per_request(server, monkeypatch):
    ids, _started = server
    acronyms.warm_all()
    calls = []
    real = acronyms._signatures
    monkeypatch.setattr(acronyms, "_signatures", lambda *a, **k: calls.append(1) or real(*a, **k))

    with acronyms.serving_scope():
        for _ in range(5):          # five claims, one question
            acronyms.harvest(allowed_document_ids=frozenset(ids))

    assert len(calls) == 1


def test_a_scope_inside_a_scope_reports_to_the_outer_one(server, monkeypatch):
    ids, _started = server
    monkeypatch.setattr(acronyms, "_build_document_map",
                        lambda *a, **k: pytest.fail("built inside a request"))
    with acronyms.serving_scope() as outer:
        inner_result = _search(ids)       # opens its own scope inside
    assert len(set(outer)) == len(ids)
    assert inner_result["acronym_map"]["complete"] is False


def test_without_a_background_builder_the_request_still_builds_what_it_needs(corpus):  # noqa: F811
    """Tests and scripts run with the builder off. Skipping there would mean
    the corpus's own abbreviations are never used at all."""
    assert settings.startup_warmup is False
    ids = corpus

    result = _search(ids)

    assert result["acronym_map"] == {"documents_not_ready": 0, "complete": True}
    assert acronyms.warm_all() == 0, "the request built every map it needed"


def test_the_search_route_returns_the_record(server):
    from fastapi.testclient import TestClient

    from app.main import app
    ids, _started = server
    acronyms.warm_all()
    r = TestClient(app, base_url="http://127.0.0.1").get(
        "/api/search", params={"q": QUESTION, "mode": "keyword", "rerank": "false"})
    assert r.status_code == 200, r.text
    assert r.json()["acronym_map"] == {"documents_not_ready": 0, "complete": True}
