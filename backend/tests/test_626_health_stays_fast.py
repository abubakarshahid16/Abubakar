"""#626: `/api/health` stays fast while the background jobs run in the same process.

The owner saw health take 7 to 9 s on an idle app. #629 shared the model client and paced the
risk scan; `scripts/measure_health_under_load.py` (#724) measures on a copy of the real library
but is run by hand, so nothing stopped a later change from putting the jobs back in front of
health. This holds it in the suite: the real `risks.run_detection` and the real
`acronyms.warm_all` run again and again on an invented library while the real app answers health
in this same process (same interpreter, same GIL, same thread pool). Invented data, no model, no
network. The numbers of the live-size library stay the tool's job; this is the standing floor.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import acronyms, db, risks
from app.config import settings
from app.db import connect
from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import measure_health_under_load as tool

DOCUMENTS = 30
CHUNKS_EACH = 20
HEALTH_LIMIT_S = 0.5
#: ONE call may pass the limit, but never by this much. A shared CI runner can stall one call for
#: a GC pause or a scheduler slice (seen: 0.504 s on #1726, and on #1727); a job that really
#: blocks health holds a call for a whole step, which the slowed steps below make longer than this.
OUTLIER_CEILING_S = 1.0


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w626.sqlite")
    db.reset_connection()
    db.init_db()
    acronyms.reset_cache()
    yield
    db.reset_connection()
    acronyms.reset_cache()


def _library() -> None:
    with connect() as conn:
        for d in range(DOCUMENTS):
            doc = f"doc{d}"
            conn.execute(
                "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status,"
                " uploaded_at) VALUES (?, ?, ?, 1, '/nowhere', 'ready', '2026-01-01')",
                (doc, f"{doc}.pdf", f"sha-{doc}"),
            )
            for c in range(CHUNKS_EACH):
                conn.execute(
                    "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
                    " text, token_count, content_hash) VALUES (?, ?, ?, ?, 1, 1, ?, 12, ?)",
                    (
                        f"{doc}-{c}",
                        doc,
                        f"{doc}.pdf",
                        c,
                        f"The Pressure Safety Valve (PSV{d}{c}) relieves at the set pressure.",
                        f"h-{doc}-{c}",
                    ),
                )


def _slow(monkeypatch, module, name, seconds):
    """The real step, made slower than the limit by a real wait: a job that ran INSIDE a health
    call would then fail the limit. (On the small invented library one pass takes milliseconds,
    which no regression could ever be seen through.)"""
    real = getattr(module, name)

    def slowed(*args, **kwargs):
        time.sleep(seconds)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, slowed)


class _TimedClient:
    """The test client, keeping every health time (the tool reports only the summary)."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.seconds: list[float] = []

    def get(self, url: str):
        started = time.perf_counter()
        response = self.client.get(url)
        if response.status_code == 200:
            self.seconds.append(time.perf_counter() - started)
        return response


def _acronym_rebuild() -> None:
    acronyms.reset_cache()
    acronyms.warm_all()


@pytest.mark.parametrize(
    ("name", "job", "module", "step", "seconds"),
    [
        ("risk_detection", risks.run_detection, risks, "detect_automatic_risks", 1.2),
        ("acronym_rebuild", _acronym_rebuild, acronyms, "_build_document_map", 0.05),
    ],
)
def test_health_stays_under_the_limit_while_the_job_runs(
    monkeypatch, name, job, module, step, seconds
):
    _library()
    _slow(monkeypatch, module, step, seconds)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        timed = _TimedClient(client)
        out = tool.probe_while(timed, job, every=0.05)
    over = [round(s, 3) for s in timed.seconds if s >= HEALTH_LIMIT_S]
    out = {**out, "over_limit": over}
    assert out["job_error"] is None, out
    # Longer than the outlier ceiling, so a job that ran inside (or locked out) one health call
    # could not hide as the one allowed outlier.
    assert out["job_seconds"] > OUTLIER_CEILING_S, f"the job was not slow enough: {out}"
    assert out["non_200"] == 0, out
    # Not the slowest single call: one call on a shared runner can stall for reasons that are not
    # the job (#1726, #1727 went red on max_s 0.504 and passed on re-run). The typical call must
    # be fast, at most ONE may pass the limit, and that one by less than the ceiling.
    assert out["median_s"] < HEALTH_LIMIT_S, f"{name}: {out}"
    assert len(over) <= 1, f"{name}: more than one health call over the limit: {out}"
    assert out["max_s"] < OUTLIER_CEILING_S, f"{name}: {out}"
    assert out["calls"] >= 5, f"health was not asked while the job ran: {out}"
