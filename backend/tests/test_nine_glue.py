# ruff: noqa: F811
"""B5: the role-4 glue against the REAL Runner, with chapters chosen and a fake transport that returns real-shaped findings (invented paper,
two invented rule books, an invented model; no network). The switch is ON; every request of the nine roles goes through the strict seam."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import (
    agent_review_jobs,
    crs_completeness,
    db,
    nine_call,
    nine_reviewer,
    review_shown,
)
from app.config import settings
from tests import agent_review_support as s
from tests import test_agent_review_job as tj
from tests.test_agent_review_job import (  # noqa: F401 - fixture
    lines_of,
    run_job,
    start,
    world,
)

STD2 = "doc_std2"
FINDINGS = [
    {  # matches the approved rule R-coat: both quotes are in the sent pages
        "issue": "coating layers",
        "field_label": "Coating layers",
        "paper_page": 1,
        "paper_quote": "Coating layers two",
        "clause": "4.4",
        "clause_page": 1,
        "clause_quote": "The coating shall be applied in two layers of equal depth.",
        "verdict": "met",
        "reasoning": "two layers are stated",
    },
    {  # two findings on ONE rule that disagree: one Query, never a winner
        "issue": "coating thickness",
        "field_label": "Coating thickness",
        "paper_page": 1,
        "paper_quote": "Coating thickness: 0.35 mm",
        "clause": "4.1",
        "clause_page": 1,
        "clause_quote": "The coating thickness shall be at least 0.2 mm on every outside surface.",
        "verdict": "met",
        "reasoning": "0.35 is over 0.2",
    },
    {
        "issue": "coating thickness again",
        "field_label": "Coating thickness",
        "paper_page": 1,
        "paper_quote": "Coating thickness: 0.35 mm",
        "clause": "4.1",
        "clause_page": 1,
        "clause_quote": "The coating thickness shall be at least 0.2 mm on every outside surface.",
        "verdict": "not_met",
        "reasoning": "doubtful",
    },
    {  # no approved rule row behind it (R-colour is not asked of this paper): an F- item, an opinion at most
        "issue": "colour",
        "field_label": "Colour",
        "paper_page": 1,
        "paper_quote": "Marking blue",
        "clause": "4.5",
        "clause_page": 1,
        "clause_quote": "The housing shall be painted in a single colour.",
        "verdict": "not_met",
        "reasoning": "blue marking",
    },
    {  # a clause page that was not sent: its book was never in the request
        "issue": "valve colour",
        "field_label": "Valve colour",
        "paper_page": 1,
        "paper_quote": "Marking blue",
        "book_id": STD2,
        "clause": "9.9",
        "clause_page": 1,
        "clause_quote": "The valve shall be red.",
        "verdict": "not_met",
        "reasoning": "not red",
    },
]


class Lane:
    """The fake model of today's path, with the new roles answered from a script: the reader and the librarian say nothing, the reviewer returns FINDINGS."""

    def __init__(self, today):
        self.today, self.bodies = today, []
        self.reviewer_marker = nine_reviewer.SYSTEM[:40]

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(body)
        system = json.dumps(body.get("system"))
        content = body["messages"][0]["content"]
        text = json.dumps(content)
        usage = {
            "input_tokens": 800,
            "output_tokens": 60,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        if self.reviewer_marker in system:
            words = json.dumps({"findings": FINDINGS})
        elif (
            "[document block" in text
            and "Rule" not in system
            and "senior engineer" not in system
        ):
            words = (
                "{}" if "chapter titles" not in text else json.dumps({"chapters": []})
            )
        else:
            return self.today(url, headers=headers, body=body, timeout=timeout)
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": words}],
            "usage": usage,
        }


def test_chosen_chapters_and_real_shaped_findings_become_lines_through_the_real_runner(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    tj._DOC, tj._CACHE = s.item_doc(
        ids=("R-coat", "R-frame", "R-mark")
    )  # R-colour is not asked: a finding on it has no rule behind it
    with db.connect() as conn:
        s.add_document(
            conn, STD2, "INV-STD-200.pdf", "9.9 Valve\nThe valve shall be red."
        )
    real, env = agent_review_jobs.lane()
    lane = Lane(real)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (lane, env))
    run_id, job_id = start()
    with db.connect() as conn:
        review_shown.ensure_schema(conn)
        review_shown.record_in(
            conn, run_id, [s.PAPER, s.STD, STD2], "2026-11-16T00:00:00Z"
        )
        from app import review_engine

        review_engine.record_in(
            conn,
            run_id,
            {"choice": "claude", "text_leaves": True, "parts": []},
            "starter1",
            then_ai=False,
            bar_claude=False,
            now="2026-11-16T00:00:00Z",
        )
    assert run_job(job_id) == "done"

    rows = {
        r["role_no"]: dict(r)
        for r in db.connect().execute(
            "SELECT * FROM agent_review_role WHERE run_id = ?", (run_id,)
        )
    }
    assert sorted(rows) == list(range(1, 10)) and rows[4]["state"] in (
        "ran",
        "ran_partly",
    )
    produced = json.loads(rows[4]["produced_json"])
    assert (
        produced["raw_findings"] == 5
        and produced["findings_kept"] == 5
        and produced["findings"] == 4
    )  # the two on one rule joined into one line

    lines = lines_of(run_id)
    by_member = {k: json.loads(v["line_json"]) for k, v in lines.items()}
    joined = [ln for ln in by_member.values() if ln.get("nine_underlying") == 2]
    assert (
        len(joined) == 1 and len(joined[0]["nine_members"]) == 2
    )  # members kept, not dropped
    f_lines = {k: ln for k, ln in by_member.items() if k.startswith("F-")}
    assert (
        len(f_lines) == 3
    )  # the colour finding, the one whose clause page was not sent, and the disagreeing pair (it matched a rule it does not cover)
    for k, ln in f_lines.items():
        assert lines[k]["verdict_class"] not in ("Proven by code",) and ln.get(
            "not_proven_reason"
        )  # an opinion at most, with its reason
    assert (
        lines["R-coat"]["verdict_class"] == "AI verdict, two readers agree"
    )  # the REAL tier lookup over a real label row: a matched, covered rule reaches the two-reader class
    assert {"R-coat", "R-mark", "R-frame"} <= set(
        lines
    )  # the covered rule, the unmentioned one and the contradicted one
    assert (
        by_member["R-coat"].get("nine_underlying") == 1
        and by_member["R-coat"]["nine_members"]
    )  # a matched finding is the rule's own line
    assert (
        "nine_underlying" not in by_member["R-mark"]
    )  # the checklist's line is today's line
    asked = [i for batch in world.lead_asked for i in batch]
    assert "R-coat" not in asked and {"R-mark", "R-frame"} <= set(
        asked
    )  # covered is not asked again; contradicted and unmentioned are
    # the record, the completeness (N points = N lines = N rows) and the checker of the role record
    from app import access
    from app import review_points_service as svc

    scope = access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )
    got = crs_completeness.checked_files(s.PAPER, scope)
    assert got["team"][1]["ok"] and got["contractor"][1]["ok"], got["team"][1][
        "sentence"
    ]
    listing = svc.assemble(s.PAPER, scope)
    assert any((p.get("underlying") or 0) == 2 for p in listing["points"])
    spec = importlib.util.spec_from_file_location(
        "nine_record_check",
        Path(__file__).resolve().parents[2] / "scripts" / "nine_record_check.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.check(db.connect(), run_id, None) == []
    assert any(
        "senior engineer" in json.dumps(b.get("system")) for b in lane.bodies
    )  # the reviewer really asked, through the seam
    assert nine_call.engine_of_run(run_id) == "claude"
    _ = pytest
