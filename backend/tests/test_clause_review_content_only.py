# ruff: noqa: F811
"""A procedure's requirement about equipment or hardware: one summary line, not one row each.

Invented text only, fake model and fake batches. The AI proposes in the same ask, code checks its words.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app import (
    absence,
    access,
    claude_spend,
    clause_review,
    clause_review_claude,
    comparison,
    db,
    review_audit,
)
from app import main as main_mod
from app import reasoning_provider as rp
from app.config import settings
from tests.test_1477_clause_review import (  # noqa: F401 - fixtures and helpers
    GOOD_CHAIR,
    REQ_ACTIONS,
    REQ_CHAIR,
    Fake,
    _resolver,
    _rows,
    _world,
    on,
)
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_clause_review_claude import (  # noqa: F401 - fixtures
    _start,
    fake,
    lane,
)

REQ_GAUGE = "Pressure gauges shall have a stainless steel case and a 100 mm dial."
HARDWARE = {
    "answer": "no_evidence",
    "page": None,
    "quote": None,
    "about": "equipment_design",
    "about_quote": "stainless steel case",
}
CONTENT = {
    "answer": "no_evidence",
    "page": None,
    "quote": None,
    "about": "procedure_content",
    "about_quote": None,
}


@pytest.fixture
def content_only(monkeypatch):
    monkeypatch.setattr(settings, "clause_review_content_only_enabled", True)


def _local(run, scope, answers):
    model = Fake(answers)
    status = clause_review.run(run, allowed_document_ids=scope, provider=model)
    return status, model


def _set_kind(kind="procedure", state="confirmed"):
    with db.connect() as conn:
        conn.execute("UPDATE document_kinds SET kind = ?, state = ?", (kind, state))


# ------------------------------------------------------------------ switch off


def test_off_by_default_and_the_ask_is_the_same_as_today(on):
    assert settings.clause_review_content_only_enabled is False
    _sub, run, scope = _world((REQ_GAUGE,))
    status, model = _local(run, scope, {"Pressure gauges": HARDWARE})
    [packet] = model.packets
    assert packet.system == clause_review.SYSTEM
    assert packet.json_schema == clause_review.SCHEMA
    assert packet.prompt_version == clause_review.PROMPT_VERSION
    assert len(_rows(run)) == 1 and status["no_evidence"] == 1
    assert "not_for_kind" not in status and "not_for_kind" not in status["results"]
    assert "not for this document kind" not in status["plain"]


def test_off_keeps_the_cache_key(on):
    req = {"id": "q1", "requirement_text": "x"}
    assert clause_review.cache_key([], req, "m") == clause_review.cache_key(
        [], req, "m"
    )
    assert (
        clause_review.clause_review_kind.cache_model("m", "procedure", "confirmed")
        == "m"
    )


# ------------------------------------------------------- only a confirmed procedure


@pytest.mark.parametrize(
    "kind, state",
    [
        ("procedure", "suggested"),
        ("procedure", "contested"),
        ("procedure", "unknown"),
        ("specification", "confirmed"),
    ],
)
def test_any_other_kind_or_state_keeps_todays_behaviour(on, content_only, kind, state):
    _sub, run, scope = _world((REQ_GAUGE,))
    _set_kind(kind, state)
    status, model = _local(run, scope, {"Pressure gauges": HARDWARE})
    [packet] = model.packets
    assert packet.system == clause_review.SYSTEM
    assert packet.json_schema == clause_review.SCHEMA
    assert len(_rows(run)) == 1 and "not_for_kind" not in status


# ------------------------------------------------------------- what code decides


def test_a_hardware_requirement_gets_no_row_and_the_line_says_so(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    status, model = _local(
        run, scope, {"Pressure gauges": HARDWARE, "HAZOP chair": CONTENT}
    )
    assert len(model.packets) == 2  # the same ask, no second pass
    [row] = _rows(run)
    assert row["standard_clause"] == "5.2"
    assert status["not_for_kind"] == ["5.1"]
    assert (
        "1 of 2 applicable requirement(s) not for this document kind" in status["plain"]
    )
    for said in ("not checked", "not decided", "not compliant", "not 'not mentioned'"):
        assert said in status["plain"]


def test_it_never_counts_as_reviewed_or_checked(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    status, _model = _local(
        run, scope, {"Pressure gauges": HARDWARE, "HAZOP chair": CONTENT}
    )
    assert status["results"] == {
        "applicable": 2, "reviewed": 1, "verified_quote": 0, "no_passage_found": 1,
        "unverifiable": 0, "unreadable": 0, "failed": 0, "not_reviewed": 0,
        "not_for_kind": 1, "adds_up": True,
    }  # fmt: skip
    assert status["no_evidence"] == 1
    assert "1 of 2 requirement(s) read" in status["plain"]
    assert status["not_ai_reviewed_count"] == 0


@pytest.mark.parametrize(
    "answer",
    [
        {**HARDWARE, "about": "unsure"},
        {"answer": "no_evidence", "page": None, "quote": None},  # the field left out
        {**HARDWARE, "about": "something else"},
        {**HARDWARE, "about_quote": None},
        {**HARDWARE, "about_quote": "words not in that requirement at all"},
        {**HARDWARE, "about_quote": "steel case"},  # too few words to show anything
    ],
)
def test_unsure_or_unproved_goes_to_a_row_never_to_the_line(on, content_only, answer):
    _sub, run, scope = _world((REQ_GAUGE,))
    status, _model = _local(run, scope, {"Pressure gauges": answer})
    assert len(_rows(run)) == 1 and status["no_evidence"] == 1
    assert "not_for_kind" not in status
    assert "not for this document kind" not in status["plain"]


def test_a_verified_quote_stays_a_row_whatever_its_kind(on, content_only):
    _sub, run, scope = _world((REQ_CHAIR,))
    status, _model = _local(
        run,
        scope,
        {
            "HAZOP chair": {
                "answer": "quote",
                "page": 1,
                "quote": GOOD_CHAIR,
                "about": "equipment_design",
                "about_quote": "HAZOP chair shall be",
            }
        },
    )
    [row] = _rows(run)
    assert row["contractor_evidence_text"] == GOOD_CHAIR and status["verified"] == 1


def test_an_unverified_quote_stays_a_row_whatever_its_kind(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE,))
    status, _model = _local(
        run,
        scope,
        {
            "Pressure gauges": {
                **HARDWARE,
                "answer": "quote",
                "page": 1,
                "quote": "words the model made up and no page holds",
            }
        },
    )
    assert len(_rows(run)) == 1 and status["unverified"] == 1


def test_an_unreadable_answer_stays_a_row(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE,))
    status, _model = _local(run, scope, {"Pressure gauges": "not json"})
    assert len(_rows(run)) == 1 and status["unreadable"] == 1


def test_the_ask_says_what_to_propose_and_when_in_doubt(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE,))
    _status, model = _local(run, scope, {"Pressure gauges": HARDWARE})
    [packet] = model.packets
    for word in ("equipment_design", "procedure_content", "unsure", "about_quote"):
        assert word in packet.system
    assert packet.json_schema["required"] == clause_review.SCHEMA["required"]
    assert packet.prompt_version != clause_review.PROMPT_VERSION


def test_a_stored_answer_from_before_the_switch_is_not_reused_without_the_field(
    on, content_only
):
    from app import clause_review_kind

    assert clause_review_kind.cache_model("m", "procedure", "confirmed") != "m", (
        "an old answer has no `about`, so every requirement would stay a row"
    )
    assert clause_review_kind.cache_model("m", "procedure", "suggested") == "m"


def test_nothing_in_the_code_names_a_standard_or_a_field():
    from app import clause_review_kind

    source = Path(clause_review_kind.__file__).read_text(encoding="utf-8").lower()
    for word in ("saes", "api ", "asme", "iso ", "gauge", "flange", "psv", "hazop"):
        assert word not in source


# ------------------------------------------------------------------ to the CRS


def _crs(run, copy):
    return main_mod._crs_content(run, access.unrestricted_scope(), copy)


def _cells(workbook: bytes) -> str:
    """Every cell of every sheet of the file itself: what the reader of that copy can see."""
    book = load_workbook(io.BytesIO(workbook))
    return "\n".join(
        str(cell)
        for sheet in book.worksheets
        for row in sheet.iter_rows(values_only=True)
        for cell in row
        if cell is not None
    )


def _file(run, copy):
    workbook, _name = main_mod._crs_workbook(run, access.unrestricted_scope(), copy)
    return _cells(workbook)


def test_follow_one_row_to_the_crs_cell_and_the_line_to_the_notes(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    _local(run, scope, {"Pressure gauges": HARDWARE, "HAZOP chair": CONTENT})
    rows, _meta, _n, _s = _crs(run, "internal")
    mine = [r for r in rows if r["row_kind"] == "clause_review"]
    assert len(mine) == 1 and mine[0]["engineer_confirmed"] is False
    assert "HAZOP chair" in mine[0]["ai_review_comment"]
    assert "engineer to confirm" in mine[0]["comment_by"]
    assert "not issued" in mine[0]["comment"].lower()
    assert "Pressure gauges" not in json.dumps(rows, default=str)
    cells = _file(run, "internal")
    assert "HAZOP chair" in cells and "Pressure gauges" not in cells
    assert "1 of 2 applicable requirement(s) not for this document kind" in cells
    assert "Rule ids not for this document kind: 5.1" in cells


def test_the_rule_ids_are_never_on_the_contractors_copy(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    _local(run, scope, {"Pressure gauges": HARDWARE, "HAZOP chair": CONTENT})
    cells = _file(run, "issue")
    assert "Rule ids not for this document kind" not in cells
    assert "not for this document kind" not in cells and "Pressure gauges" not in cells


def test_the_line_alone_does_not_mark_the_sheet_incomplete_nor_count_a_part(
    on, content_only
):
    _sub, run, scope = _world((REQ_GAUGE,))
    _local(run, scope, {"Pressure gauges": HARDWARE})
    ai = clause_review._stored_ai_status(db.connect(), run)
    parts = absence.unchecked_parts(run_status="completed", outcome={}, ai_status=ai)
    assert [p["part"] for p in parts] == ["clause_review_not_for_kind"]
    assert all(p.get("detail") for p in parts)
    assert absence.notice_for(parts) == ""


def test_the_audit_prints_the_line(on, content_only):
    _sub, run, scope = _world((REQ_GAUGE,))
    status, _model = _local(run, scope, {"Pressure gauges": HARDWARE})
    audit = review_audit.build(run, access.unrestricted_scope(), None)
    assert status["plain"] in review_audit.render_markdown(audit)
    [step] = [s for s in audit["ai_use"]["steps"] if s["name"] == "clause_review"]
    assert step["results"]["not_for_kind"] == 1


# ------------------------------------------------------------------ Claude lane


def test_on_the_claude_lane_the_kind_comes_in_the_same_ask(fake, content_only):
    fake.answer = lambda text: HARDWARE if "Pressure gauges" in text else CONTENT
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    status = _start(run, scope)
    assert len(fake.sent()) == 2  # one ask each
    assert "equipment_design" in fake.sent()[0]["params"]["system"][0]["text"]
    assert len(_rows(run)) == 1 and status["not_for_kind"] == ["5.1"]
    assert status["results"]["adds_up"] and status["results"]["reviewed"] == 1
    assert status["pending"] is False


def test_off_the_claude_lane_ask_is_the_same_as_today(fake):
    _sub, run, scope = _world((REQ_GAUGE,))
    _start(run, scope)
    assert "equipment_design" not in json.dumps(fake.sent()[0]["params"])


def test_a_suggested_kind_on_the_claude_lane_keeps_todays_ask(fake, content_only):
    fake.answer = lambda text: HARDWARE
    _sub, run, scope = _world((REQ_GAUGE,))
    _set_kind(state="suggested")
    status = _start(run, scope)
    assert "equipment_design" not in json.dumps(fake.sent()[0]["params"])
    assert len(_rows(run)) == 1 and "not_for_kind" not in status


def test_a_retried_job_does_not_take_the_line_for_a_lost_row(fake, content_only):
    fake.answer = lambda text: HARDWARE if "Pressure gauges" in text else CONTENT
    _sub, run, scope = _world((REQ_GAUGE, REQ_CHAIR))
    first = _start(run, scope)
    charged = [e for e in claude_spend.entries() if float(e.get("cost_usd") or 0) > 0]
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _rows(run) == []
    again = _start(run, scope)
    assert len(_rows(run)) == 1 and again["not_for_kind"] == first["not_for_kind"]
    assert again["results"] == first["results"] and len(fake.created) == 1
    assert [
        e for e in claude_spend.entries() if float(e.get("cost_usd") or 0) > 0
    ] == charged


def test_the_line_needs_no_stored_answer_after_a_retried_job(fake, content_only):
    import shutil

    fake.answer = lambda text: HARDWARE
    _sub, run, scope = _world((REQ_GAUGE,))
    first = _start(run, scope)
    shutil.rmtree(settings.claude_cache_dir)
    comparison.run_comparison(run, allowed_document_ids=scope)
    again = _start(run, scope)
    assert again["not_for_kind"] == first["not_for_kind"]
    assert (
        again["results"]["not_for_kind"] == 1 and again["results"]["not_reviewed"] == 0
    )


def test_a_repeat_review_reads_the_stored_answer_and_keeps_the_line(fake, content_only):
    from tests.test_clause_review_claude import _second_run

    fake.answer = lambda text: HARDWARE
    sub, run, scope = _world((REQ_GAUGE,))
    _start(run, scope)
    again = _second_run(sub, scope)
    second = _start(again, scope)
    assert len(fake.created) == 1 and second["cache_hits"] == 1
    assert _rows(again) == [] and second["not_for_kind"] == ["5.1"]
    assert second["usd"]["charged"] == 0


def test_the_worst_case_stays_inside_the_step_cap_with_the_field(
    fake, content_only, monkeypatch
):
    """351 longest asks on a model that thinks by default: the extra words are in the cached block."""
    from app import claude_batch_run

    req = {"clause": "5.1.2.3", "requirement_text": "x" * 1200}
    longest = [{"page": 100, "text": "y" * 815} for _ in range(4)]
    packet = clause_review_claude.packet_for("procedure", req, longest, "confirmed")
    assert "equipment_design" in packet.system
    worst = claude_batch_run.worst_usd("claude-sonnet-5-5", packet) * 351
    assert 8.0 < worst < settings.claude_budget_usd_clause_review
    assert rp.schema_errors(json.dumps(HARDWARE), packet.json_schema) == ()
