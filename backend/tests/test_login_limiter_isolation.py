"""The sign-in limiter must not carry one test's failures into the next.

CI run 42679962305 (PR #1722): three routed tests in test_review_code.py got
429 `rate_limited` on a correct password because an earlier test on the same
xdist worker had filled the "testclient" host bucket, and the limiter is
process-wide. conftest's `_fresh_login_limiter` empties it around every test.

The two tests below run in file order. The first fills the host bucket the way
test_auth.py's fresh-email test does; the second asserts it starts empty.
Without the conftest fixture the second fails when the file runs on its own.
"""

from __future__ import annotations

import time

from app import auth
from app.config import settings

HOST_KEY = "host:testclient"


def test_a_test_may_fill_the_host_bucket():
    now = time.time()
    for _ in range(settings.auth_max_attempts * auth._Limiter.HOST_MULTIPLIER):
        auth._limiter.record_failure(HOST_KEY, now)
    assert auth._limiter.check(HOST_KEY, now) is not None


def test_the_next_test_starts_with_an_empty_limiter():
    assert auth._limiter.check(HOST_KEY, time.time()) is None
    assert auth._limiter.check("eng@e.test", time.time()) is None
