"""PR #1014 (#440, audit F10): the SMTP lane sends only over verified TLS.
Entries for `notifications.py` (danger zone: a socket module) and the load-time
check in `config.py`; each deletes one part of the fix and a test in
tests/test_440_smtp_tls.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_440_smtp_tls.py"
_N = APP / "notifications.py"
_TAG = ("egress", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1014-01", phase=1014, description="TLS switched off after startup is not refused before the socket",
             path=_N, anchor="    if not settings.smtp_starttls and not settings.smtp_ssl:\n",
             replacement="    if False:\n",
             target=_T, keyword="switched_off_after_startup", tags=_TAG),
    Mutation(id="M1014-02", phase=1014, description="a server that refuses STARTTLS is sent to in plain text",
             path=_N,
             anchor='        raise SmtpTlsRefused(\n            "the SMTP server did not complete STARTTLS; nothing was sent") from exc\n',
             replacement="        pass\n",
             target=_T, keyword="without_starttls or failed_handshake", tags=_TAG),
    Mutation(id="M1014-03", phase=1014, description="STARTTLS uses smtplib's default context (no certificate check)",
             path=_N, anchor="        smtp.starttls(context=context)\n",
             replacement="        smtp.starttls()\n",
             target=_T, keyword="verifying_context", tags=_TAG),
    Mutation(id="M1014-04", phase=1014, description="SMTP_SSL is ignored and a plain connection is opened",
             path=_N, anchor="    if settings.smtp_ssl:\n        try:\n",
             replacement="    if False:\n        try:\n",
             target=_T, keyword="smtps_wraps", tags=_TAG),
    Mutation(id="M1014-05", phase=1014, description="the lane uses a context that verifies nothing",
             path=_N, anchor="        with _open_tls(ssl.create_default_context()) as smtp:\n",
             replacement="        with _open_tls(ssl._create_unverified_context()) as smtp:\n",
             target=_T, keyword="verifying_context", tags=_TAG),
    Mutation(id="M1014-06", phase=1014, description="settings with no TLS mode load without complaint",
             path=APP / "config.py", anchor="        if not self.smtp_starttls and not self.smtp_ssl:\n",
             replacement="        if False:\n",
             target=_T, keyword="refuse_no_tls", tags=_TAG),
)
