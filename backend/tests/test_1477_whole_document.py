# ruff: noqa: F811
"""#1477: whole-document clause review - the count cap lifted, one time budget instead.

Fake model and fake clock: no socket, no real model. Invented documents only.
"""

from __future__ import annotations

import pytest

from app import clause_review, db
from app import reasoning_provider as rp
from app.config import settings
from tests.test_1477_clause_review import (  # noqa: F401 - fixtures
    Clock,
    Fake,
    _go,
    _resolver,
    _rows,
    _world,
    on,
)
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse

ANS = {"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}}


def _reqs(n):
    return tuple(f"Item {i}: The HAZOP chair shall be independent." for i in range(n))


@pytest.fixture
def whole(monkeypatch):
    monkeypatch.setattr(settings, "clause_review_whole_document_enabled", True)


def test_switch_off_keeps_the_60_cap(on):
    _sub, run, scope = _world(_reqs(65))
    status = _go(run, scope, Fake(ANS))
    assert len(_rows(run)) == 60 and status["not_reviewed_count"] == 5
    assert "only the first 60" in status["stopped"]
    assert "whole_document_note" not in status


def test_switch_on_reviews_every_requirement_when_the_budget_allows(on, whole):
    _sub, run, scope = _world(_reqs(65))
    status = _go(run, scope, Fake(ANS))
    assert len(_rows(run)) == 65 and status["not_reviewed"] == []
    assert status["whole_document_note"].startswith(
        "65 of 65 requirements reviewed; 0 not reviewed"
    )


def test_budget_hit_is_partial_with_the_exact_note(on, whole, monkeypatch):
    monkeypatch.setattr(settings, "clause_review_time_budget_s", 30.0)
    _sub, run, scope = _world(_reqs(9))
    clock = Clock()
    status = _go(run, scope, Fake(ANS, clock, step=10.0), clock=clock)
    assert len(_rows(run)) == 3 and status["no_evidence"] == 3
    assert status["whole_document_note"] == (
        "3 of 9 requirements reviewed; 6 not reviewed (time budget of 30 s reached); "
        "first not reviewed: 5.4, 5.5, 5.6, 5.7, 5.8, 5.9"
    )
    assert status["plain"].endswith(status["whole_document_note"] + ".")
    # not reviewed is never a row (so never a pass, never "no evidence")
    assert not any(r["standard_clause"] == "5.4" for r in _rows(run))


def test_cache_hits_do_not_consume_the_budget(on, whole, monkeypatch):
    monkeypatch.setattr(settings, "clause_review_time_budget_s", 100.0)
    _sub, run, scope = _world(_reqs(10))
    clock = Clock()
    _go(run, scope, Fake(ANS, clock, step=10.0), clock=clock)  # fills the cache
    clock2 = Clock()
    second = Fake(ANS, clock2, step=10.0)
    status = _go(run, scope, second, clock=clock2)
    assert second.packets == [] and status["cache_hits"] == 10
    assert clock2.t == 0.0 and status["not_reviewed"] == []


def test_whole_mode_never_routes_to_claude(on, whole, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    _sub, run, scope = _world(_reqs(3))
    made = []

    class Local(Fake):
        def __init__(self, *a, **k):
            super().__init__(ANS)
            made.append(1)

    monkeypatch.setattr(rp, "OllamaProvider", Local)
    monkeypatch.setattr(
        rp, "get_provider", lambda *a, **k: pytest.fail("may be Claude")
    )
    monkeypatch.setattr(rp, "ClaudeProvider", lambda *a, **k: pytest.fail("Claude"))
    assert clause_review.run(run, allowed_document_ids=scope)["ran"] and made


def test_after_the_budget_a_cached_requirement_is_still_reviewed(
    on, whole, monkeypatch
):
    sub, run, scope = _world(_reqs(4))
    monkeypatch.setattr(settings, "clause_review_time_budget_s", 20.0)
    clock = Clock()
    _go(run, scope, Fake(ANS, clock, step=10.0), clock=clock)  # caches 5.1 and 5.2
    # forget 5.1: it is uncached and first in line; 5.2 stays cached and comes later
    pages = clause_review.page_texts(sub)
    first = clause_review.requirements_for(run, scope)[0]
    passages = clause_review.retrieve(sub, first["requirement_text"], pages)
    key = clause_review.cache_key(passages, first, "fake-local")
    with db.connect() as conn:
        conn.execute("DELETE FROM clause_review_cache WHERE key = ?", (key,))
        conn.execute(
            "DELETE FROM review_findings WHERE origin = ?", (clause_review.ORIGIN,)
        )
    monkeypatch.setattr(settings, "clause_review_time_budget_s", 10.0)
    clock2 = Clock()
    second = Fake(ANS, clock2, step=10.0)
    status = _go(run, scope, second, clock=clock2)
    # 5.1 uses the whole budget (one call); 5.2 is cached, 5.3 and 5.4 are not
    assert len(second.packets) == 1 and status["cache_hits"] == 1
    assert sorted(r["standard_clause"] for r in _rows(run)) == ["5.1", "5.2"]
    assert status["whole_document_note"] == (
        "2 of 4 requirements reviewed; 2 not reviewed (time budget of 10 s reached); "
        "first not reviewed: 5.3, 5.4"
    )
