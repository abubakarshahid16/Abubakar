"""Order 14, PLAN step 4: the FREE dry run of the general review on the app path, as ONE integration test.

Five invented papers of five kinds (the kind confirmed in `document_kinds`, as an engineer confirms it), a library of invented rule
books with rules labelled per kind, and for each paper what a user does through the app's routes: the plan (GET /api/reviews/plan),
the start with exactly the listed ids (POST /api/reviews/start), the worker's job (`aim_review_jobs.claim_next` + `run`, with the
method's FAKE model passed in by this test: the shipped code has no switch for it), the page (GET .../general), the file
(GET .../general/sheet) and the counts (page = database = rows on "All points"; comments = rows on "Comments"; every sheet marked).
Nothing is sent and no money is spent: the spend ledger gets no line. The Claude lane is open only in the plan's facts.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    aim_review_gate,
    aim_review_jobs,
    aim_review_store,
    db,
    job_queue,
    review_engine,
)
from app.aim_review import engine as method_engine
from app.config import settings
from app.main import app
from tests.test_aim_method_helpers import build_db
from tests.test_p3_review_jobs import _user, temp_storage  # noqa: F401 - fixture

#: kind -> (paper id, engine the user chooses): Automatic sends only a scored kind; the others are an explicit choice of Claude.
PAPERS = {
    "datasheet": ("doc_aimpaper01", "automatic"),  # A's invented datasheet (two pages)
    "procedure": ("doc_dry_proc01", "claude"),
    "contract": ("doc_dry_cont01", "claude"),
    "calculation": ("doc_dry_calc01", "claude"),
    "other": ("doc_dry_othr01", "claude"),
}
PAGES = {
    "procedure": {1: "Invented procedure step 1: the operator shall record the reading.\n",
                  2: "Invented procedure step 2: the reading is checked by a second person.\n"},
    "contract": {1: "Invented agreement clause 1: the supplier shall deliver within the agreed period.\n"},
    "calculation": {1: "Invented calculation sheet: the wall thickness found is 9 mm.\n"},
    "other": {1: "Invented study record: node 1, deviation more flow, safeguard present.\n"},
}  # fmt: skip
RULES = {
    "procedure": (
        "doc_dry_bookP1",
        "4.1",
        "Every procedure step shall name who records the reading.",
    ),
    "contract": (
        "doc_dry_bookK1",
        "2.1",
        "The agreement shall state the delivery period.",
    ),
    "calculation": (
        "doc_dry_bookC1",
        "3.1",
        "A calculation shall state the minimum wall thickness.",
    ),
    "other": (
        "doc_dry_bookO1",
        "5.1",
        "Each node shall list the safeguards for each deviation.",
    ),
}


def _hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _doc(conn, doc_id: str, role: str, pages: dict[int, str]) -> None:
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, status, uploaded_at)"
        " VALUES (?, ?, ?, 1, ?, ?, 'indexed', '2026-11-18T00:00:00Z')",
        (doc_id, f"{doc_id}.pdf", _hex(doc_id), f"/nowhere/{doc_id}", len(pages)),
    )
    conn.execute(
        "INSERT INTO document_classification (document_id, document_role, suggested_by) VALUES (?, ?, 'test')",
        (doc_id, role),
    )
    for n, t in pages.items():
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, ?, ?, ?, 0)",
            (doc_id, n, t, len(t)),
        )


def _library() -> list[str]:
    """A's invented datasheet world plus one paper and one rule book per other kind; every paper's kind confirmed."""
    build_db()
    conn = db.connect()
    with conn:
        for kind, pages in PAGES.items():
            paper = PAPERS[kind][0]
            _doc(
                conn,
                paper,
                "CONTRACT_DOCUMENT" if kind == "contract" else "CONTRACTOR_SUBMITTAL",
                pages,
            )
            book, clause, text = RULES[kind]
            _doc(conn, book, "COMPANY_STANDARD", {1: f"Section heading\n{text}\n"})
            rid = f"req_{book}"
            conn.execute(
                "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
                " created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, 'x', 'x')",
                (rid, book, clause, text, text),
            )
            conn.execute(
                "INSERT INTO rule_label (source, rule_ref, paper_kind, state, a_model, a_prompt, a_answer_sha256, b_model,"
                " b_prompt, b_answer_sha256, reading_json, quote_page, quote_sha256, labelled_at)"
                " VALUES ('requirement', ?, ?, 'ai_approved', 'model-a', 'p', ?, 'model-b', 'p', ?, ?, 1, ?, 'x')",
                (
                    rid,
                    kind,
                    _hex("a" + rid),
                    _hex("b" + rid),
                    json.dumps({"subject": "test subject"}),
                    _hex(rid),
                ),
            )
        for kind, (paper, _engine) in PAPERS.items():
            conn.execute(
                "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, ?, 'confirmed', 'x')",
                (paper, kind),
            )
    return [r[0] for r in conn.execute("SELECT id FROM documents")]


@pytest.fixture
def dry(temp_storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "claude_spend_log", settings.data_dir / "spend.jsonl")
    real = review_engine.read_facts

    def lane_open(conn, document_id, allowed):
        # the app's own facts (kind, contract, blocks), with the Claude lane "open" ONLY here: nothing can be sent anyway
        facts, reading = real(conn, document_id, allowed)
        return dataclasses.replace(
            facts,
            agent_enabled=True,
            provider="per_task",
            agent_engine_claude=True,
            lane_open=True,
            caps_ok=True,
        ), reading

    monkeypatch.setattr(review_engine, "read_facts", lane_open)
    ids = _library()
    return {"headers": _user("adm", ids, admin=True)}


def _ledger_lines() -> int:
    path = settings.claude_spend_log
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def _review(w, kind: str) -> dict:
    paper, engine = PAPERS[kind]
    client = TestClient(app)
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": paper, "engine": engine},
        headers=w["headers"],
    )
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    assert plan["method"] == "general" and plan["refused"] is None, (
        kind,
        plan.get("refused"),
    )
    shown = [d["id"] for d in plan["documents"]["leaving"]]
    assert paper in shown
    started = client.post(
        "/api/reviews/start",
        json={
            "submittal_document_id": paper,
            "engine": engine,
            "shown_document_ids": shown,
        },
        headers=w["headers"],
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["review_run_id"]
    worker = job_queue.worker_id()
    job_id = aim_review_jobs.claim_next(worker)
    assert job_id is not None
    model = method_engine.FakeModel(kind=kind, subject_key=f"dry_{kind}")
    assert aim_review_jobs.run(job_id, worker, model=model) == job_queue.DONE
    carried = (
        set().union(*(set(a.get("carries") or ()) for a in model.asked))
        if model.asked
        else set()
    )
    assert carried <= set(shown), (
        kind,
        carried - set(shown),
    )  # nothing beyond the list the screen showed
    page = client.get(f"/api/reviews/papers/{paper}/general", headers=w["headers"])
    assert page.status_code == 200, page.text
    sheet = client.get(
        f"/api/reviews/papers/{paper}/general/sheet", headers=w["headers"]
    )
    assert sheet.status_code == 200, sheet.text
    contractor = client.get(
        f"/api/reviews/papers/{paper}/general/sheet?copy=contractor",
        headers=w["headers"],
    )
    assert (
        contractor.status_code == 409
        and aim_review_gate.NO_CONTRACTOR_COPY_WORDS in contractor.text
    )
    return {"run_id": run_id, "page": page.json(), "xlsx": sheet.content, "plan": plan}


def _rows(xlsx: bytes, title: str) -> int:
    ws = load_workbook(io.BytesIO(xlsx), read_only=True)[title]
    return sum(
        1
        for row in ws.iter_rows(min_row=2, values_only=True)
        if any(v not in (None, "") for v in row)
    )


def test_the_dry_run_reviews_five_kinds_end_to_end_with_no_spend(dry):
    before = _ledger_lines()
    seen = {}
    for kind in PAPERS:
        got = _review(dry, kind)
        page, run_id = got["page"], got["run_id"]
        conn = db.connect()
        lines = aim_review_store.lines(conn, run_id)
        assert (
            page["status"] == "completed" and page["mark"] == aim_review_gate.AI_MARK
        ), kind
        assert page["points"] and len(page["points"]) == len(lines), (
            kind
        )  # page = database
        assert page["completeness"]["ok"] is True, (kind, page["completeness"])
        wb = load_workbook(io.BytesIO(got["xlsx"]), read_only=True)
        assert {"Summary", "Comments", "All points", "How it was reviewed"} <= set(
            wb.sheetnames
        )
        for ws in wb.worksheets:  # every sheet carries the mark
            assert any(
                aim_review_gate.AI_MARK in str(v)
                for row in ws.iter_rows(values_only=True)
                for v in row
                if v
            ), ws.title
        assert (
            len(lines)
            == page["completeness"]["file_rows"]
            == page["completeness"]["page"]
        ), kind
        assert len(page["comments"]) <= len(page["points"])
        seen[kind] = len(lines)
    assert set(seen) == set(PAPERS) and all(n > 0 for n in seen.values()), seen
    assert _ledger_lines() == before  # no money: not one ledger line


def test_local_only_in_the_dry_run_queues_nothing(dry):
    paper = PAPERS["datasheet"][0]
    client = TestClient(app)
    before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    r = client.post(
        "/api/reviews/start",
        json={
            "submittal_document_id": paper,
            "engine": "local",
            "shown_document_ids": [],
        },
        headers=dry["headers"],
    )
    assert r.status_code == 409 and aim_review_gate.LOCAL_NOT_AVAILABLE in r.text
    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before
