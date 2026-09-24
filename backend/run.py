"""Start the API.

Use this rather than invoking uvicorn directly. Two of the settings here
cannot be applied from inside the ASGI application:

  * `server_header=False` - uvicorn writes `Server: uvicorn` at the HTTP
    protocol layer, AFTER the app has returned its headers, so the response
    middleware cannot remove it. Suppressing it requires the server config.
    A test using TestClient will never see this header at all, which is how
    it was reported fixed while still being sent.
  * `host` - bound to loopback so document text is never reachable from the
    network.

    python run.py
"""

from __future__ import annotations

import sys

#: The version every pin in requirements.txt was resolved against.
#: onnxruntime 1.29.0 and numpy 2.5.3 ship per-minor-version wheels, so a
#: different 3.x resolves to different binaries - or to none at all, and the
#: failure then surfaces from inside a wheel as an opaque import error rather
#: than as "you are on the wrong Python". Checked here, before anything heavy
#: is imported, so the message is the first thing the operator sees.
REQUIRED_PYTHON = (3, 12)


def check_python() -> None:
    if sys.version_info[:2] != REQUIRED_PYTHON:
        want = ".".join(str(n) for n in REQUIRED_PYTHON)
        have = ".".join(str(n) for n in sys.version_info[:3])
        raise SystemExit(
            f"\nThis project requires Python {want}. You are running {have}.\n"
            f"  interpreter: {sys.executable}\n\n"
            f"Every pin in backend/requirements.txt was resolved against "
            f"{want}; onnxruntime and numpy ship per-minor-version wheels, so "
            f"another version installs different binaries or none at all.\n\n"
            f"Create the virtual environment with {want} explicitly:\n"
            f"    py -{want} -m venv .venv          (Windows)\n"
            f"    python{want} -m venv .venv        (macOS / Linux)\n"
        )


check_python()

import uvicorn  # noqa: E402 - after the version check, deliberately

from app.config import settings  # noqa: E402


def main() -> None:
    # THE SERVER OWNS THE LIVE DATABASE. Marked here and only here, before the
    # app is imported, so `db.connect()` lets this process - and the worker
    # processes it spawns, which inherit the environment - open the live file.
    # Every other process must pass live_guard.prepare_live_write first.
    from app import live_guard
    live_guard.mark_server_process()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        server_header=False,
        date_header=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
