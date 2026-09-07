"""Public market information: a fixture that cannot pretend to be a source.

There is one rule and every test here is a way of trying to break it: a sample
row must never reach a reader as a real finding. The interesting tests are the
ones that EDIT the fixture into something plausible and require the loader to
refuse it, because that is how this fails in practice - not by someone writing
`is_sample: false` on purpose, but by a row being pasted in from somewhere real
during a demo.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db, keyword, market
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """The market ROUTES resolve an access scope, which reads `documents`.

    Without this these tests passed on a development machine - which has a
    62 MB corpus at backend/data/rag_intelligence.sqlite - and failed in CI with
    `no such table`. The tables must be CREATED, not present by accident.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


@pytest.fixture(autouse=True)
def fresh():
    market.reload_samples()
    yield
    market.reload_samples()


def write_fixture(tmp_path, monkeypatch, rows, notice="SAMPLE DATA - NOT LIVE."):
    path = tmp_path / "market_sample.json"
    path.write_text(json.dumps({"_notice": notice, "findings": rows}), encoding="utf-8")
    monkeypatch.setattr(market, "SAMPLE_PATH", path)
    market.reload_samples()
    return path


GOOD = {
    "claim": "Illustrative row.",
    "url": "sample://not-a-real-source/x/1",
    "publisher": "Sample Publisher A",
    "published_at": None,
    "retrieved_at": "2026-09-05T00:00:00Z",
    "verification": "source_not_verified",
    "is_sample": True,
}


# ----------------------------------------------------- the shipped fixture


def test_every_shipped_row_is_a_sample_with_an_unfetchable_url():
    rows = market.findings()["findings"]
    assert rows, "no rows - an empty panel reads as 'no market findings', which is a measurement"
    for row in rows:
        assert row["is_sample"] is True
        assert row["url"].startswith("sample://")
        assert row["verification"] == "source_not_verified"


def test_the_payload_says_it_is_a_sample_even_if_only_the_list_is_rendered():
    payload = market.findings()
    assert payload["is_sample"] is True
    assert "SAMPLE DATA - NOT LIVE" in payload["notice"]
    assert payload["egress"] == {"web_search_enabled": False,
                                 "allow_public_egress": False}


def test_no_shipped_row_names_a_real_publisher_or_a_fetchable_scheme():
    """A plausible publisher on a sample row is the failure mode: a reader who
    recognises the name stops reading the label."""
    text = json.dumps(market.findings())
    for scheme in ("http://", "https://", "ftp://"):
        assert scheme not in text, f"{scheme} in the sample payload"
    for row in market.findings()["findings"]:
        assert "sample" in row["publisher"].lower(), (
            f"publisher {row['publisher']!r} does not identify itself as a sample")


# ------------------------------------------- trying to make it lie, at load


def test_a_row_that_drops_is_sample_is_refused(tmp_path, monkeypatch):
    row = {**GOOD}
    del row["is_sample"]
    write_fixture(tmp_path, monkeypatch, [row])
    with pytest.raises(market.SampleIntegrityError, match="is_sample"):
        market.findings()


def test_a_row_that_claims_to_be_real_is_refused(tmp_path, monkeypatch):
    write_fixture(tmp_path, monkeypatch, [{**GOOD, "is_sample": False}])
    with pytest.raises(market.SampleIntegrityError, match="is_sample"):
        market.findings()


def test_a_fetchable_url_is_refused(tmp_path, monkeypatch):
    """The one that would actually happen: someone pastes a real link in."""
    write_fixture(tmp_path, monkeypatch,
                  [{**GOOD, "url": "https://www.example.com/report.pdf"}])
    with pytest.raises(market.SampleIntegrityError, match="not sample://"):
        market.findings()


def test_a_row_claiming_it_was_read_is_refused(tmp_path, monkeypatch):
    write_fixture(tmp_path, monkeypatch, [{**GOOD, "verification": "source_read"}])
    with pytest.raises(market.SampleIntegrityError, match="verification"):
        market.findings()


def test_an_empty_fixture_is_refused_rather_than_rendered_as_no_findings(
        tmp_path, monkeypatch):
    write_fixture(tmp_path, monkeypatch, [])
    with pytest.raises(market.SampleIntegrityError, match="no findings"):
        market.findings()


def test_the_loader_reports_which_row_it_refused(tmp_path, monkeypatch):
    write_fixture(tmp_path, monkeypatch, [GOOD, {**GOOD, "is_sample": False}])
    with pytest.raises(market.SampleIntegrityError, match="row 1"):
        market.findings()


# ------------------------------------------------------------------ egress


def test_the_preview_is_never_sent_and_says_so():
    p = market.preview_query("offshore coating cost per square metre", "SA", 365)
    assert p["sent"] is False
    assert p["would_be_sent_to"] is None
    assert "nothing left this machine" in p["reason"]


def test_the_preview_carries_only_the_callers_own_words():
    """A query built from retrieved document text would exfiltrate the
    client's specification to a search engine one phrase at a time."""
    p = market.preview_query("  coating   thickness  ", None, None)
    assert p["query"] == "coating thickness"
    assert p["country"] is None and p["freshness_days"] is None


def test_a_long_query_is_bounded():
    p = market.preview_query("x " * 400)
    assert len(p["query"]) <= 200


def test_this_module_makes_no_network_call(monkeypatch):
    """The machine is air-gapped. A market module that can reach the network is
    the one thing this feature must not be."""
    import socket

    import httpx

    def boom(*a, **k):
        raise AssertionError("network access from the market module")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(httpx.Client, "request", boom)
    assert market.findings()["findings"]
    assert market.preview_query("anything")["sent"] is False


def test_the_module_imports_no_http_client():
    """Structural: there is no provider, so there is nothing to call with."""
    import inspect

    src = inspect.getsource(market)
    body = src.split('"""', 2)[2]
    for name in ("httpx", "requests", "urllib", "socket"):
        assert name not in body, f"{name} referenced in market.py"


# ------------------------------------------------------------------- routes


def test_the_route_labels_every_row_and_never_omits_the_notice():
    r = TestClient(app).get("/api/market/findings")
    assert r.status_code == 200
    body = r.json()
    assert body["is_sample"] is True
    assert "SAMPLE DATA - NOT LIVE" in body["notice"]
    assert all(f["is_sample"] is True for f in body["findings"])
    # The schema pins is_sample to Literal[True], so a row that lost it could
    # not be serialised at all - this asserts the response, not the intent.
    assert "source_read" not in r.text


def test_the_preview_route_does_not_send(monkeypatch):
    r = TestClient(app).post("/api/market/preview-query",
                             json={"query": "coating cost", "country": None,
                                   "freshness_days": None})
    assert r.status_code == 200
    assert r.json()["sent"] is False
    assert r.json()["would_be_sent_to"] is None
