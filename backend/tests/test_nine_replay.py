# ruff: noqa: F811
"""PROOF THAT OFF = TODAY: a whole fake-model AI review is run with the nine-role switch OFF and every request body and every stored line is
written to a file (`NINE_REPLAY_OUT`). The same test file run on the main checkout (before the nine-role code) must write the same file.
Invented paper, rule book and model; no network."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app import agent_review_jobs, db
from app.config import settings
from tests.test_agent_review_job import (  # noqa: F401 - fixture
    lines_of,
    run_job,
    start,
    world,
)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def test_a_whole_review_with_the_switch_off_writes_the_same_requests_and_lines(
    world, monkeypatch
):
    if hasattr(settings, "agent_review_nine_roles_enabled"):
        monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    sent: list[str] = []
    real, env = agent_review_jobs.lane()

    def recording(url, *, headers, body, timeout):
        sent.append(hashlib.sha256(_canon(body).encode()).hexdigest())
        return real(url, headers=headers, body=body, timeout=timeout)

    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (recording, env))
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    lines = lines_of(run_id)
    dump = {
        "requests": sorted(sent),
        "lines": {
            k: {
                c: v[c]
                for c in ("verdict_class", "word", "verdict", "reason", "line_json")
                if c in v
            }
            for k, v in lines.items()
        },
    }
    tables = sorted(
        r[0]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'agent_review_role%' OR name LIKE 'agent_review_fact%'"
        )
    )
    assert tables == []  # no nine-role table is made while the switch is off
    out = os.environ.get("NINE_REPLAY_OUT")
    if out:
        # the run id and the stored times differ between runs: they are not part of the comparison
        text = _canon(dump)
        for noise in (run_id,):
            text = text.replace(noise, "RUN")
        Path(out).write_text(text)
    assert dump["requests"] and dump["lines"]


# ------------------------------------------------------------------------------------------------ SPEC G.6 step 3: a whole nine-role run


def test_a_whole_nine_role_run_with_recorded_answers_writes_nine_rows_and_the_record_check_passes(
    world, monkeypatch
):
    """The switch ON, an invented paper and book, the fake model for today's path and a fake transport for the new roles. The role record
    is checked by `scripts/nine_record_check.py` (read only): nine rows, reads and calls agree."""
    import importlib.util
    from pathlib import Path

    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    real, env = agent_review_jobs.lane()
    seen: list[str] = []

    def composite(url, *, headers, body, timeout):
        content = body["messages"][0]["content"]
        if any(
            str(c.get("text", "")).startswith("[document block")
            for c in content
            if isinstance(c, dict)
        ):
            seen.append("nine")
            return {
                "model": body["model"], "stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}],
                "usage": {"input_tokens": 500, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            }  # fmt: skip
        seen.append("today")
        return real(url, headers=headers, body=body, timeout=timeout)

    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (composite, env))
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    assert "today" in seen  # the checklist asked today's way
    rows = {
        r["role_no"]: dict(r)
        for r in db.connect().execute(
            "SELECT * FROM agent_review_role WHERE run_id = ?", (run_id,)
        )
    }
    assert sorted(rows) == list(range(1, 10)) and all(r["state"] for r in rows.values())
    assert (
        rows[5]["state"] == "ran"
        and rows[7]["engine"] == "code"
        and rows[9]["state"] in ("ran", "ran_partly")
    )
    spec = importlib.util.spec_from_file_location(
        "nine_record_check",
        Path(__file__).resolve().parents[2] / "scripts" / "nine_record_check.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    problems = script.check(db.connect(), run_id, None)
    assert problems == [], problems
