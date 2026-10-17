"""#440 (audit F10): the SMTP lane sends only over verified TLS.

WHAT WAS WRONG. `notifications.send_email` called `starttls()` only when
`SMTP_STARTTLS` was true, so `SMTP_STARTTLS=false` sent every message - and
the login - in plain text, and nothing refused it. When it did upgrade, it
used `smtplib`'s default context, which checks neither the certificate nor
the host name.

NOW. Exactly one of STARTTLS or SMTPS must be on, at load and again just
before the socket. A server that does not offer STARTTLS, or a handshake that
fails, raises `SmtpTlsRefused`: no login, no message, a "failed" audit row.
Both modes use `ssl.create_default_context()`.
"""
from __future__ import annotations

import smtplib
import ssl
from typing import ClassVar

import pytest

from app import db, notifications
from app.config import NotificationConfigError, Settings, SmtpTlsRefused, settings
from app.db import connect


class Server:
    """One fake SMTP connection; class lists record what happened."""
    opened: ClassVar[list] = []
    sent: ClassVar[list] = []
    logins: ClassVar[list] = []
    contexts: ClassVar[list] = []
    starttls_error: ClassVar[BaseException | None] = None

    def __init__(self, host, port, timeout=None, context=None):
        Server.opened.append(type(self).__name__)
        if context is not None:
            Server.contexts.append(context)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None):
        Server.contexts.append(context)
        if Server.starttls_error is not None:
            raise Server.starttls_error

    def close(self):
        pass

    def login(self, username, password):
        Server.logins.append(username)

    def send_message(self, message):
        Server.sent.append(message)


class ServerSSL(Server):
    pass


@pytest.fixture(autouse=True)
def smtp_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "tls.sqlite")
    db.reset_connection()
    db.init_db()
    for name, value in {
        "smtp_enabled": True, "smtp_host": "smtp.example.test", "smtp_port": 587,
        "smtp_username": "smtp-user", "smtp_password": "smtp-password",
        "smtp_from": "epc@example.test", "smtp_recipient": "controls@example.test",
        "smtp_starttls": True, "smtp_ssl": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    for name in ("opened", "sent", "logins", "contexts"):
        setattr(Server, name, [])
    Server.starttls_error = None
    monkeypatch.setattr(notifications.smtplib, "SMTP", Server)
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", ServerSSL)
    yield
    db.reset_connection()


def _send() -> bool:
    return notifications.send_email(subject="s", body="b", trigger="daily_summary",
                                    resource_type="management_summary", resource_id=None)


def _audit_outcomes() -> list[str]:
    return [r["outcome"] for r in connect().execute(
        "SELECT outcome FROM audit_events WHERE action = 'notification.email'")]


def _verifies(context) -> bool:
    return (isinstance(context, ssl.SSLContext) and context.check_hostname
            and context.verify_mode == ssl.CERT_REQUIRED)


def test_a_server_without_starttls_is_refused_and_nothing_is_sent():
    """THE ACCEPTANCE CASE: a server that does not offer TLS."""
    Server.starttls_error = smtplib.SMTPNotSupportedError(
        "STARTTLS extension not supported by server.")
    with pytest.raises(SmtpTlsRefused, match="STARTTLS"):
        _send()
    assert Server.sent == [] and Server.logins == [], "credentials or mail went out in plain text"
    assert _audit_outcomes() == ["failed"]


def test_a_failed_handshake_is_refused_and_nothing_is_sent():
    Server.starttls_error = ssl.SSLCertVerificationError("certificate verify failed")
    with pytest.raises(SmtpTlsRefused):
        _send()
    assert Server.sent == [] and Server.logins == []


def test_starttls_runs_before_login_with_a_verifying_context():
    assert _send() is True
    assert Server.opened == ["Server"]
    assert len(Server.contexts) == 1 and _verifies(Server.contexts[0])
    assert Server.logins == ["smtp-user"] and len(Server.sent) == 1
    assert _audit_outcomes() == ["sent"]


def test_smtps_wraps_from_the_first_byte_with_a_verifying_context(monkeypatch):
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_ssl", True)
    monkeypatch.setattr(settings, "smtp_port", 465)
    assert _send() is True
    assert Server.opened == ["ServerSSL"], "a plain connection was opened for SMTPS"
    assert len(Server.contexts) == 1 and _verifies(Server.contexts[0])
    assert len(Server.sent) == 1


def test_tls_switched_off_after_startup_is_refused_before_any_socket(monkeypatch):
    """The load-time validator is not enough: the settings object can change
    later, so the refusal must also sit just before the socket."""
    monkeypatch.setattr(settings, "smtp_starttls", False)
    with pytest.raises(SmtpTlsRefused):
        _send()
    assert Server.opened == [], "a socket was opened with TLS switched off"


def test_settings_refuse_no_tls_and_both_tls_modes():
    base = {"smtp_enabled": True, "smtp_host": "h", "smtp_from": "a@example.test",
            "smtp_recipient": "b@example.test"}
    with pytest.raises(SmtpTlsRefused, match="SMTP_STARTTLS=true or SMTP_SSL=true"):
        Settings(**base, smtp_starttls=False, smtp_ssl=False)
    with pytest.raises(NotificationConfigError, match="only one"):
        Settings(**base, smtp_starttls=True, smtp_ssl=True)
    assert Settings(**base).smtp_starttls is True       # the default stays valid
    assert Settings(**base, smtp_starttls=False, smtp_ssl=True).smtp_ssl is True
    # SMTP off: no TLS demand at all (the air-gapped default)
    assert Settings(smtp_starttls=False).smtp_enabled is False
