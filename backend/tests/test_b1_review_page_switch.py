"""The redesigned review page's switch: off, its routes answer 404 feature_off and the status says off (owner, 12 Nov 2026)."""

from __future__ import annotations

from app.config import settings
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401 - fixture


def test_off_the_points_routes_do_not_exist_and_the_status_says_off(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", False)
    doc = _submittal()
    client = _client(doc)
    assert client.get("/api/reviews/page-v2").json() == {"enabled": False}
    assert client.get(f"/api/reviews/papers/{doc}/points").status_code == 404
    assert (
        client.post(
            f"/api/reviews/papers/{doc}/points/add", json={"text": "x"}
        ).status_code
        == 404
    )


def test_on_the_status_says_on_and_the_list_answers(monkeypatch):
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc = _submittal()
    client = _client(doc)
    assert client.get("/api/reviews/page-v2").json() == {"enabled": True}
    assert client.get(f"/api/reviews/papers/{doc}/points").status_code == 200
