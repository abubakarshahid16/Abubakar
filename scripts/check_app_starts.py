"""Does the app start? (order 129, CI job `app-starts`)

#1151 stopped the owner's app from starting and no check caught it: every test
builds its own app in-process, none runs `python run.py` the way a machine
does. This starts the real server twice, each time in a NEW temporary folder
shaped like a checkout (`<tmp>/backend/data/rag_intelligence.sqlite`, so the
live-database rules apply) with no backup folder and no models:

1. fresh: an empty data folder;
2. old paths: a database holding a stored path written on another machine
   (the #1151 case: the startup migration wants a backup and none can be made).

Each time `/api/health` must answer `ok` within the time limit, or the job
fails and prints the end of the server's output. Writes only inside its own
temporary folder; never the checkout's database, never `backend/.env`; no
network beyond 127.0.0.1.

    python scripts/check_app_starts.py [--timeout 120] [--port 8790]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
#: An absolute path written on another machine (the owner's Mac); the file
#: itself is in this data folder, as after a copy.
OLD_PATH = "/Users/owner/project/app/backend/data/uploads/sheet.pdf"


def _env(home: Path, port: int) -> dict[str, str]:
    data = home / "backend" / "data"
    models = home / "no-models"
    env = dict(os.environ)
    # Set explicitly, because pydantic still reads a developer's backend/.env:
    # no drop folder to scan, no login secret to check, no models anywhere.
    env.update(
        DATA_DIR=str(data),
        UPLOAD_DIR=str(data / "uploads"),
        DB_PATH=str(data / "rag_intelligence.sqlite"),
        EMBED_MODEL_DIR=str(models / "e5-small"),
        OCR_MODEL_DIR=str(models / "ocr"),
        WATCH_FOLDER="",
        AUTH_MODE="disabled",
        PORT=str(port),
        HEAVY_JOB_LOCK="off",
        PYTHONUNBUFFERED="1",
        PYTHONUTF8="1",  # the log file stays UTF-8 on Windows too
    )
    return env


def _health(port: int) -> dict | None:
    # No proxy: the server is on loopback, and a CI proxy must not answer for it.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        # As uvicorn binds: a closed connection still waiting (TIME_WAIT, left
        # by the previous start) is no server. Not on Windows, where the same
        # option would let the probe share a port another server listens on.
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def start_and_check(home: Path, port: int, timeout: float) -> tuple[bool, str]:
    """(health answered ok, the server's output) for one start in `home`."""
    if not _port_free(port):
        return False, f"port {port} is already in use: another server would answer"
    log_path = home / "server.log"
    with log_path.open("w") as log:
        server = subprocess.Popen(
            [sys.executable, "run.py"],
            cwd=BACKEND,
            env=_env(home, port),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        ok = False
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and server.poll() is None:
                answer = _health(port)
                if answer is not None:
                    # Our server, still running - not one that was there before.
                    ok = answer.get("ok") is True and server.poll() is None
                    break
                time.sleep(1)
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    return ok, log_path.read_text(errors="replace")


def seed_old_path(home: Path) -> None:
    """A row written on another machine, in the database the first start
    created, and its file in this data folder."""
    data = home / "backend" / "data"
    if data.resolve().is_relative_to(ROOT):
        raise SystemExit(f"refusing to write inside the checkout: {data}")
    (data / "uploads").mkdir(parents=True, exist_ok=True)
    (data / "uploads" / "sheet.pdf").write_bytes(b"%PDF-1.4\n")
    conn = sqlite3.connect(data / "rag_intelligence.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " uploaded_at) VALUES ('d1', 'sheet.pdf', 'abc', 9, ?,"
            " '2026-10-19T00:00:00+00:00')",
            (OLD_PATH,),
        )
    conn.close()


#: (name, how to prepare the folder, lines one of which the server's output
#: must show). The migration logs that it rewrote the paths or that it left
#: them; either proves the #1151 path ran.
STARTS = (
    ("fresh data folder", None, ()),
    (
        "old paths, no backup folder",
        seed_old_path,
        ("stored paths made relative", "Stored file paths were left as they are"),
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)

    # On Windows an indexer or antivirus may still hold server.log or the -wal
    # file for a moment: a cleanup error must not fail a start that passed.
    with tempfile.TemporaryDirectory(
        prefix="app-starts-", ignore_cleanup_errors=True
    ) as tmp:
        home = Path(tmp) / "checkout"
        (home / "backend" / "data").mkdir(parents=True)
        failed = False
        for name, prepare, must_log in STARTS:
            if prepare:
                prepare(home)
            ok, output = start_and_check(home, args.port, args.timeout)
            # Not vacuous: the old-paths start must have reached the migration.
            ok = ok and (not must_log or any(line in output for line in must_log))
            print(f"{'OK  ' if ok else 'FAIL'} app starts: {name}")
            if not ok:
                failed = True
                lines = output.splitlines()
                reason = [x for x in lines if "Error" in x or "Refused" in x]
                print("reason:", reason[-1] if reason else lines[-1] if lines else "")
                print("---- end of the server's output ----")
                print("\n".join(lines[-40:]))
                break
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
