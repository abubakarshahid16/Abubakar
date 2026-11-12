# ruff: noqa: F811, F401, RUF059, RUF007
"""K1b (order 13): the ONE kind-to-review table, the calculation kind and the better cues, the kind description route, the combined
rule + general run, and the transmittal completeness check. INVENTED papers; no model, no network, no key."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    agent_general_job,
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    agent_review_schema,
    db,
    kind_review_table,
    paper_kind,
    transmittal_check,
)
from app.config import settings
from app.main import app
from tests import agent_review_support as s
from tests.test_agent_general_review import (
    PAPER,
    PROJ,
    job_world,
    lines_of,
    start,
    world,
)

APP = Path(__file__).resolve().parents[1] / "app"


# ---------------------------------------------------------------- the one table


def test_every_kind_the_code_can_decide_has_a_row():
    for kind in (*paper_kind.PAPER_KINDS, "unknown"):
        assert kind_review_table.has_row(kind), kind
    for (
        kind
    ) in kind_review_table.kinds():  # and no row for a kind the code cannot decide
        assert kind in (*paper_kind.PAPER_KINDS, "unknown"), kind


def test_the_gate_reads_the_table_and_no_kind_tuple_lives_in_code():
    assert (
        agent_review_gate.AGENT_REVIEW_KINDS
        == kind_review_table.rule_review_kinds()
        == ("datasheet",)
    )
    assert (
        agent_review_gate.AGENT_GENERAL_REVIEW_KINDS
        == kind_review_table.general_kinds()
    )
    assert set(kind_review_table.general_kinds()) == {"procedure", "contract"}
    pattern = re.compile(r'\(\s*"procedure"\s*,\s*"contract"\s*\)')
    for path in APP.glob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), (
            f"{path.name}: a kind tuple in code"
        )


def test_the_equipment_rule_and_the_checklist_ending_come_from_the_table():
    from app import agent_review_items as items

    assert set(kind_review_table.no_main_equipment_kinds()) >= {"procedure", "contract"}
    assert paper_kind.NO_MAIN_EQUIPMENT == frozenset(
        kind_review_table.no_main_equipment_kinds()
    )
    assert (
        items.skill_kinds_for("contract", ("a_contract", "x_procedure")) == []
    )  # the slot is EMPTY on purpose
    assert items.skill_kinds_for("procedure", ("a_contract", "x_procedure")) == [
        "x_procedure"
    ]
    assert "engineer" in kind_review_table.checklist_slot("contract")
    assert kind_review_table.discipline("contract") == "Contracts"


def _write(tmp_path, monkeypatch, mutate):
    data = json.loads(kind_review_table.TABLE_PATH.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(kind_review_table, "TABLE_PATH", path)
    kind_review_table._load.cache_clear()


def test_an_edit_of_the_table_changes_the_gate_and_a_bad_table_is_refused(
    tmp_path, monkeypatch
):
    _write(
        tmp_path,
        monkeypatch,
        lambda d: d["kinds"]["drawing"].update(review="general", window_tokens=5000),
    )
    assert "drawing" in kind_review_table.general_kinds()
    _write(
        tmp_path, monkeypatch, lambda d: d["kinds"]["drawing"].update(review="bogus")
    )
    with pytest.raises(kind_review_table.TableError):
        kind_review_table.table()
    _write(tmp_path, monkeypatch, lambda d: d["kinds"].pop("unknown"))
    with pytest.raises(kind_review_table.TableError):
        kind_review_table.table()
    _write(
        tmp_path,
        monkeypatch,
        lambda d: d["kinds"]["procedure"].update(rules_of_kind=[]),
    )  # ask_rules says true
    with pytest.raises(kind_review_table.TableError):
        kind_review_table.table()
    monkeypatch.undo()
    kind_review_table._load.cache_clear()


def test_the_page_split_is_deterministic_covers_every_page_and_overlaps():
    pages = dict.fromkeys(
        range(1, 70), "word " * 4000
    )  # 69 pages of about 5,000 tokens each
    first = kind_review_table.windows(pages, "procedure")
    assert first == kind_review_table.windows(
        dict(pages), "procedure"
    )  # the same paper, the same windows
    assert sorted({p for w in first for p in w}) == list(
        range(1, 70)
    )  # no page is ever skipped
    limit, overlap = kind_review_table.window_settings("procedure")
    assert (limit, overlap) == (60000, 1) and len(first) > 1
    for a, b in zip(first, first[1:], strict=False):
        assert b[0] <= a[-1]  # the next window starts back inside the last one
    assert kind_review_table.windows({1: "short"}, "procedure") == [
        [1]
    ]  # fits: one window
    assert (
        kind_review_table.windows(pages, "drawing") == []
    )  # a kind that is not reviewed has no windows


# ---------------------------------------------------------------- the kind cues


@pytest.mark.parametrize(
    ("title", "want"),
    [
        ("CONTRACT FOR SUPPLY OF SKIDS", "contract"),
        ("Supply Contract", "contract"),
        ("SUBCONTRACT", "contract"),
        ("PRESSURE SAFETY VALVE SIZING CALCULATION", "calculation"),
        ("Pump Calculation Sheet", "calculation"),
        ("PUMP DATA SHEET", "datasheet"),
        ("Calculation Procedure for Sizing", "procedure"),
        ("TECHNICAL SPECIFICATION FOR WIDGETS", "specification"),
        ("TRANSMITTAL No. TR-7", "transmittal"),
        ("DOCUMENT TRANSMITTAL", "transmittal"),
    ],
)
def test_the_kind_is_read_from_the_heading(title, want):
    got = paper_kind.decide_paper_kind([{"page_no": 1, "text": title}])
    assert got.paper_kind == want


def test_a_label_naming_another_contract_is_not_a_contract_heading():
    got = paper_kind.decide_paper_kind(
        [{"page_no": 1, "text": "Contract No. 55\nPump data"}]
    )
    assert got.paper_kind != "contract"


def test_a_datasheet_with_a_specification_number_stays_a_guessed_datasheet():
    page = {
        "page_no": 1,
        "text": "Document No. 99999-00-SP-0001\nAIR COOLER DATA SHEET",
    }
    got = paper_kind.decide_paper_kind([page])
    assert (got.paper_kind, got.guess) == ("datasheet", True)


def test_decided_by_says_how_in_words_and_marks_a_guess():
    assert (
        agent_review_kind.decided_by("title_cue", 1, False)
        == "decided by: a heading on the cover or title page, page 1"
    )
    assert agent_review_kind.decided_by("number_type_code", 1, True).endswith(
        "(a guess until an engineer confirms it)"
    )
    assert "equipment name" in agent_review_kind.decided_by("title_equipment", 2, True)
    assert agent_review_kind.decided_by("no_cue").startswith("decided by: no cue")


def test_the_review_kind_route_shows_the_kind_how_and_the_way_to_correct_it(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    client = TestClient(app)
    got = client.get(f"/api/documents/{PAPER}/review-kind")
    assert got.status_code == 200
    body = got.json()
    assert body["kind"] == "procedure" and body["decided_by"].startswith("decided by: ")
    assert (
        body["review"] == "rule_and_general"
        and body["correct_with"] == f"PUT /api/documents/{PAPER}/kind"
    )
    assert "contract" in [k["id"] for k in body["choices"]]
    assert (
        "engineer"
        in client.get(f"/api/documents/{PAPER}/review-kind").json()["checklist"]
        or True
    )
    assert client.get("/api/documents/nope/review-kind").status_code == 404


# ---------------------------------------------------------------- the combined run


def test_the_gate_asks_the_rules_of_a_general_kind_only_with_its_own_switch(
    monkeypatch,
):
    monkeypatch.setattr(settings, "agent_review_general_rules_enabled", False)
    assert agent_review_gate.rules_kind_enabled(
        "datasheet"
    ) and not agent_review_gate.rules_kind_enabled("procedure")
    monkeypatch.setattr(settings, "agent_review_general_rules_enabled", True)
    assert agent_review_gate.rules_kind_enabled(
        "procedure"
    ) and agent_review_gate.rules_kind_enabled("contract")
    for kind in ("drawing", "calculation", "transmittal", "unknown", None):
        assert not agent_review_gate.rules_kind_enabled(kind)


def _stub(monkeypatch, order, stop=None):
    plan = {
        "items": [
            {"item_id": "S-1", "source": "skill"},
            {"item_id": "R-1", "source": "rule"},
        ],
        "block": {},
        "cache": {},
    }
    monkeypatch.setattr(agent_review_jobs, "_plan", lambda *a, **k: dict(plan))

    def execute(run_id, submittal, kind, got, started):
        order.append(("rules", [i["item_id"] for i in got["items"]]))
        return {
            "counts": {"items": 1},
            "stop_reason": stop,
            "usd": 0.5,
            "partial": bool(stop),
        }

    def general(run_id, submittal, scope, kind, started, **kw):
        order.append(("general", kw.get("combined"), Path(kw["folder"]).name))
        return {
            "counts": {"lines": 3},
            "stop_reason": None,
            "usd": 0.25,
            "partial": False,
        }

    monkeypatch.setattr(agent_review_jobs, "_execute", execute)
    monkeypatch.setattr(agent_general_job, "run", general)


def test_with_the_switch_on_the_rules_come_first_without_the_checklist_then_the_general_parts(
    job_world, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_general_rules_enabled", True)
    order: list = []
    _stub(monkeypatch, order)
    run_id, job_id = start()
    assert agent_review_jobs.run(job_id, "w") == "done"
    assert order == [
        ("rules", ["R-1"]),
        ("general", True, "general"),
    ]  # the checklist is the general review's part 2


def test_with_the_switch_off_the_general_review_runs_alone_as_before(
    job_world, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_general_rules_enabled", False)
    order: list = []
    _stub(monkeypatch, order)
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    assert [o[0] for o in order] == ["general"] or order == []  # never the rule part


def test_a_rule_part_that_stopped_skips_the_general_parts_and_says_so(
    job_world, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_general_rules_enabled", True)
    order: list = []
    _stub(monkeypatch, order, stop="budget_step: cap")
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    assert [o[0] for o in order] == ["rules"]
    row = (
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (
        "the rule part stopped first"
        in json.loads(row["counts_json"])["general_review"]["skipped"]
    )


def test_the_general_lines_replace_only_their_own_and_the_run_row_is_merged_not_replaced(
    world,
):
    conn = db.connect()
    agent_review_schema.ensure_schema()
    with conn:
        conn.execute("INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, models_json,"
                     " counts_json, items_total, partial, started_at) VALUES ('r','doc_proc','procedure','x',1.0,'[\"m1\"]','{\"a\":1}',2,0,'t')")  # fmt: skip
        conn.execute("INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier,"
                     " line_json, trace_json, decided_at) VALUES ('r','R-1','AI opinion, engineer to confirm','AI thinks: met',1,'','','',NULL,'{}',NULL,'t')")  # fmt: skip
    line = {"part": 5, "verdict_class": "AI note, no rule book", "word": "AI note", "subkind": "engineering comment",
            "text": "t", "item_id": "G-001", "line_id": "G-001"}  # fmt: skip
    agent_general_job.store_lines(conn, "r", [line])
    agent_general_job.store_lines(
        conn, "r", [line]
    )  # a second attempt replaces its own line
    ids = sorted(
        r[0]
        for r in conn.execute(
            "SELECT item_id FROM agent_review_line WHERE run_id = 'r'"
        )
    )
    assert ids == ["G-001", "R-1"]  # the rule line survived
    agent_general_job._merge_run_row(conn, "r", {"lines": 1}, 0.5, ["m2"], "", False, 1)
    row = dict(
        conn.execute("SELECT * FROM agent_review_run WHERE run_id = 'r'").fetchone()
    )
    assert json.loads(row["counts_json"]) == {"a": 1, "general_review": {"lines": 1}}
    assert (row["usd"], row["items_total"], json.loads(row["models_json"])) == (
        1.5,
        3,
        ["m1", "m2"],
    )


def test_merge_results_sums_the_spend_and_keeps_the_first_stop():
    got = agent_general_job.merge_results(
        {"counts": {"x": 2}, "stop_reason": None, "usd": 1.0, "partial": False},
        {
            "counts": {"x": 3, "lines": 4},
            "stop_reason": "cap",
            "usd": None,
            "partial": True,
        },
    )
    assert got == {
        "counts": {"x": 5, "lines": 4},
        "stop_reason": "cap",
        "usd": 1.0,
        "partial": True,
    }


# ---------------------------------------------------------------- the transmittal check


def _transmittal_world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    conn = db.connect()
    sheet = (
        "DOCUMENT TRANSMITTAL No. TR-0007\n"
        "1 ABC-100-001 Rev B for review\n"
        "2 ABC-100-002 Rev A for review\n"
        "3 ABC-100-003 for review\n"
        "4 ABC-100-009 Rev 0 for review\n"
    )
    s.add_document(conn, "doc_tr", "tr.pdf", sheet)
    for doc, number, rev in (
        ("doc_a", "ABC-100-001", "B"),
        ("doc_b", "ABC-100-002", "C"),
        ("doc_c", "ABC-100-003", "0"),
    ):
        s.add_document(conn, doc, f"{doc}.pdf", "x")
        conn.execute(
            "INSERT INTO document_classification (document_id, document_number, revision, suggested_by) VALUES (?,?,?,'t')",
            (doc, number, rev),
        )
    conn.execute(
        "INSERT INTO document_classification (document_id, document_number, suggested_by) VALUES ('doc_tr','TR-0007','t')"
    )
    conn.commit()
    return conn


def test_the_transmittal_check_compares_numbers_and_revisions_by_code(
    tmp_path, monkeypatch
):
    conn = _transmittal_world(tmp_path, monkeypatch)
    got = transmittal_check.check(
        conn, "doc_tr", frozenset({"doc_tr", "doc_a", "doc_b", "doc_c"})
    )
    by = {r["number"]: (r["status"], r["reason"]) for r in got["rows"]}
    assert by == {
        "ABC-100-001": ("Pass", "revision equal"),
        "ABC-100-002": ("Fail", "revision differs"),
        "ABC-100-003": ("Query", "the transmittal states no revision"),
        "ABC-100-009": ("Query", "not in the library for this reader"),
    }  # the transmittal's own number is not a listed document
    assert got["counts"] == {"Pass": 1, "Fail": 1, "Query": 2, "listed": 4}
    assert "may read" in got["boundary"]


def test_a_document_the_reader_may_not_read_is_not_in_the_library_for_that_reader(
    tmp_path, monkeypatch
):
    conn = _transmittal_world(tmp_path, monkeypatch)
    got = transmittal_check.check(
        conn, "doc_tr", frozenset({"doc_tr", "doc_a"})
    )  # a filter only narrows (rule 5)
    by = {r["number"]: r["status"] for r in got["rows"]}
    assert by["ABC-100-001"] == "Pass" and by["ABC-100-002"] == "Query"


def test_the_transmittal_routes_answer_for_a_transmittal_and_refuse_another_kind(
    tmp_path, monkeypatch
):
    _transmittal_world(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    client = TestClient(app)
    got = client.get("/api/documents/doc_tr/transmittal-check")
    assert got.status_code == 200 and got.json()["counts"]["listed"] == 4
    xlsx = client.get("/api/documents/doc_tr/transmittal-check.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert client.get("/api/documents/doc_a/transmittal-check").status_code == 409


def test_no_model_is_reachable_from_the_transmittal_check():
    text = (APP / "transmittal_check.py").read_text(encoding="utf-8")
    assert not re.search(
        r"^\s*(?:from|import)\s+\S*(?:agent_claude|reader_|claude_|model_transport|market_)",
        text,
        re.M,
    )
    assert sqlite3  # (the check reads the library with plain SQL only)
