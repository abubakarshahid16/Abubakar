"""Error codes and safe error reporting.

Two rules, both learned the hard way.

1. NO INTERNAL DETAIL EVER LEAVES THE API. A traceback tells a reader the
   absolute path of your source tree, your module layout and your line
   numbers. It reached `GET /api/health` through the worker's `last_error`
   field, which was added after the hostile-input audit had already scanned
   every other endpoint and found nothing. Full tracebacks go to the local
   log file; the API returns a code, a short message, and an identifier.

2. A CLIENT MISTAKE IS NOT AN INTERNAL FAILURE. Returning `"internal"` for a
   missing `confirm=true` makes a caller's own typo indistinguishable from a
   crash, and makes the one code that should alarm an operator meaningless.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from .config import settings

# --------------------------------------------------------------- error codes

# Caller's fault - the request was malformed or asked for something absent.
NOT_FOUND = "not_found"
INVALID_PARAMETER = "invalid_parameter"
UNKNOWN_PARAMETER = "unknown_parameter"
CONFIRM_REQUIRED = "confirm_required"

# The uploaded file was not acceptable.
NOT_PDF = "not_pdf"
ENCRYPTED_PDF = "encrypted_pdf"
TOO_LARGE = "too_large"
DUPLICATE = "duplicate"

# Processing failed on our side, but for an identifiable reason.
EXTRACT_FAILED = "extract_failed"
CHUNK_FAILED = "chunk_failed"
EMBED_FAILED = "embed_failed"
MODEL_UNAVAILABLE = "model_unavailable"
DISK_FULL = "disk_full"
NO_SEARCHABLE_CONTENT = "no_searchable_content"

# Reserved for genuine, unexpected internal failure. If an operator sees this
# it should mean something is actually wrong.
INTERNAL = "internal"

#: Authentication. These MUST be here and not only in the route.
#: `safe_error` coerces an unknown code to `internal` (see below), so a login
#: refusal would be reported to the client as a server crash - exactly the
#: failure this module exists to prevent, and it would look like a backend
#: fault rather than a wrong password.
UNAUTHENTICATED = "unauthenticated"
INVALID_CREDENTIALS = "invalid_credentials"
RATE_LIMITED = "rate_limited"
INVALID_RESET_TOKEN = "invalid_reset_token"
WEAK_PASSWORD = "weak_password"

CLIENT_ERROR_CODES = frozenset(
    {NOT_FOUND, INVALID_PARAMETER, UNKNOWN_PARAMETER, CONFIRM_REQUIRED,
     NOT_PDF, ENCRYPTED_PDF, TOO_LARGE, DUPLICATE,
     UNAUTHENTICATED, INVALID_CREDENTIALS, RATE_LIMITED,
     INVALID_RESET_TOKEN, WEAK_PASSWORD}
)

ALL_CODES = CLIENT_ERROR_CODES | {
    EXTRACT_FAILED, CHUNK_FAILED, EMBED_FAILED, MODEL_UNAVAILABLE,
    DISK_FULL, NO_SEARCHABLE_CONTENT, INTERNAL,
}


# ------------------------------------------------------------------ logging

_logger: logging.Logger | None = None


def logger() -> logging.Logger:
    """Local rotating log. The only place a traceback is ever written.

    The handler follows `settings.data_dir` rather than being cached once, so
    a reconfigured data directory does not leave the log writing to the old
    location - which is exactly how a test can pass while logging nothing.
    """
    global _logger
    target = (settings.data_dir / "logs" / "rag-intelligence.log").resolve()

    lg = logging.getLogger("rag_intelligence")
    lg.setLevel(logging.INFO)
    current = next(
        (h for h in lg.handlers if isinstance(h, RotatingFileHandler)), None
    )
    if current is not None:
        if getattr(current, "baseFilename", None) == str(target):
            _logger = lg
            return lg
        lg.removeHandler(current)
        current.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    lg.addHandler(handler)
    lg.propagate = False
    _logger = lg
    return lg


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def record_failure(
    exc: BaseException,
    *,
    code: str = INTERNAL,
    document_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Log the full traceback locally; return only what is safe to expose.

    The returned dict is the ONLY thing that may reach an API response.
    """
    logger().error(
        "failure code=%s document=%s stage=%s\n%s",
        code, document_id, stage, traceback.format_exc(),
    )
    return safe_error(code, str(exc), document_id=document_id, stage=stage)


def safe_error(
    code: str,
    message: str,
    *,
    document_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """A response-safe error: code, short message, identifier, timestamp.

    The message is truncated and stripped of anything that looks like a path
    or a traceback, so a raw exception string cannot smuggle internals out.
    """
    return {
        "code": code if code in ALL_CODES else INTERNAL,
        "message": redact(message),
        "document_id": document_id,
        "stage": stage,
        "at": _now(),
    }


_LEAK_MARKERS = ("Traceback (most recent call last)", 'File "', "\\project\\", "/project/")


def redact(message: str, limit: int = 200) -> str:
    """Strip anything that would expose the source tree or a stack."""
    if not message:
        return ""
    text = str(message).replace("\n", " ").strip()
    for marker in _LEAK_MARKERS:
        if marker in text:
            return "an internal error occurred; see the local log for details"
    # a bare absolute path anywhere in the message is also unsafe
    if ":\\" in text or text.count("/") > 3:
        return "an internal error occurred; see the local log for details"
    return text[:limit]
