"""r2 S7: under demo_required these answered 200 to a caller who named no
identity at all. Routes that expose corpus-derived content now say 401.
`/api/health` stays public, and so does everything the login screen calls
before it has a token (`/api/auth/me`). Mutations: scripts/mutations/
r2_security.py M1988.
"""

from __future__ import annotations

import pytest

from app import access
from app.config import settings

from tests.r2_security_support import h, temp_storage, world  # noqa: F401

PROTECTED = [
    ("get", "/api/classification/vocabulary"),
    ("get", "/api/classification/coverage"),
    ("get", "/api/metrics"),
    ("get", "/api/management/report"),
    ("get", "/api/reviews/templates"),
    ("get", "/api/reviews/baseline-rules"),
    ("get", "/api/reviews/dashboard"),
    ("get", "/api/reviews/findings"),
    ("get", "/api/reviews/runs"),
    ("get", "/api/reviews/vision-reader-status"),
    ("post", "/api/market/search"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_no_identity_is_401(world, method, path):
    r = getattr(world, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401, (path, r.status_code, r.text[:200])
    assert r.json()["detail"]["code"] == "unauthenticated"


@pytest.mark.parametrize("method,path", PROTECTED)
def test_a_bad_token_is_401_too(world, method, path):
    r = getattr(world, method)(path, headers={"Authorization": "Bearer not-a-token"},
                               **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401, path


@pytest.mark.parametrize("path", ["/api/classification/vocabulary", "/api/reviews/templates",
                                  "/api/classification/coverage"])
def test_an_identified_caller_still_gets_an_answer(world, path):
    for user in ("u_none", "u_sub", "u_admin"):
        assert world.get(path, headers=h(user)).status_code == 200, (user, path)


def test_the_public_and_login_routes_stay_open(world):
    assert world.get("/api/health").status_code == 200
    # What the login screen asks before it has a token: an answer, not a 401
    # from the gate (the route itself answers 401 `unauthenticated` for
    # "no token", which is how the screen learns to show the form).
    assert world.get("/api/auth/me").json()["detail"]["code"] == "unauthenticated"
    assert world.get("/api/market/findings").status_code == 200
    assert world.get("/api/watch/status").status_code == 200


def test_under_disabled_nothing_changes(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    assert world.get("/api/classification/vocabulary").status_code == 200
    assert world.get("/api/reviews/templates").status_code == 200
