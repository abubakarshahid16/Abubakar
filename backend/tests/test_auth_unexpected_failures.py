"""Order 55d (#692): a fault in the token or password check is still a
refusal, but it is no longer silent.

`read_token`, `_token_epoch` and the password verify each caught every
exception and answered "not a token" / "wrong password". A malformed token
should stay quiet; a BUG (a broken import, a changed library) would have
logged every user out, or refused every login, with no trace. Now the
malformed cases stay quiet and anything else is logged by error type only:
never the token, never the hash.
"""
from __future__ import annotations

import logging

import pytest

from app import auth
from tests.test_auth import make_user, temp_storage  # noqa: F401 - autouse fixture

LOGGER = "rag_intelligence.auth"


def _boom(*_a, **_k):
    raise RuntimeError("SENTINEL-SECRET-INSIDE")


@pytest.mark.parametrize("token", ["", "abc", "a.b", "!!!.???", "e30.e30"])
def test_a_malformed_token_is_refused_quietly(token, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assert auth.read_token(token) is None
    assert auth._token_epoch(token) in (-1, 0)
    assert caplog.records == []


def test_a_fault_while_reading_a_token_is_refused_and_named(monkeypatch, caplog):
    user_id, _ = make_user("eng@example.com", "correct horse battery")
    token = auth.issue_token(user_id)
    assert auth.read_token(token) == user_id
    caplog.set_level(logging.WARNING, logger=LOGGER)
    monkeypatch.setattr(auth.hmac, "compare_digest", _boom)
    assert auth.read_token(token) is None
    (record,) = caplog.records
    assert "RuntimeError" in record.getMessage()
    assert token not in record.getMessage() and "SENTINEL" not in record.getMessage()


def test_a_fault_while_reading_the_epoch_is_refused_and_named(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    monkeypatch.setattr(auth, "_unb64", _boom)
    assert auth._token_epoch("abc.def") == -1
    (record,) = caplog.records
    assert "RuntimeError" in record.getMessage() and "SENTINEL" not in record.getMessage()


def test_a_fault_in_the_password_check_is_a_failed_login_and_named(monkeypatch, caplog):
    make_user("eng@example.com", "correct horse battery")
    caplog.set_level(logging.WARNING, logger=LOGGER)
    class Broken:
        verify = staticmethod(_boom)

    monkeypatch.setattr(auth, "_hasher", Broken())
    with pytest.raises(auth.AuthError):
        auth.login("eng@example.com", "correct horse battery")
    messages = [r.getMessage() for r in caplog.records]
    assert any("password check failed unexpectedly (RuntimeError)" in m for m in messages)
    assert not any("correct horse" in m or "SENTINEL" in m for m in messages)
