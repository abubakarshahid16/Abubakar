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

import uvicorn

from app.config import settings


def main() -> None:
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
