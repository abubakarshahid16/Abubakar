"""#1471: the CRS bench scores saved runs by the stated counting rule, replays
the current code on a throw-away copy, and never makes a model call (invented data)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest
from tools import crs_bench

from app import comparison, datasheets, db, model_transport, standards, submittal_review
from app.config import settings

NOW = "2026-11-01T00:00:00Z"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "bench.sqlite")
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    monkeypatch.setattr(settings, "ai_division_scope_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, text, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,?,?,?,0,0)",
            (doc_id, 1, text, len(text)),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)",
            (f"{doc_id}-1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )


@pytest.fixture
def run_id():
    _doc("std", "COMPANY_STANDARD", "x", document_number="STD-1")
    _doc(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        "Design pressure 9 barg\n",
        equipment_type="Centrifugal Pump",
    )
    standards.create_requirement(
        standard_document_id="std",
        chunk_id="std-1",
        clause="4.2",
        page=1,
        requirement_text="The design pressure shall be at least 12 barg.",
        source_text="The design pressure shall be at least 12 barg.",
        structured={
            "requirement_type": "numeric_limit",
            "subject": "design pressure",
            "operator": ">=",
            "raw_value": "12",
            "raw_unit": "barg",
        },
    )
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Design pressure",
        raw_value="9 barg",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES (?,?,?,'manual',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    comparison.run_comparison(run, allowed_document_ids=frozenset({"std", "sub"}))
    return run


def _add(
    run,
    status,
    *,
    origin=None,
    section=None,
    finding="x",
    page=None,
    quote=None,
    requirement_id=None,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
            "required_action,created_at,updated_at,review_run_id,compliance_status,origin,"
            "contractor_section,contractor_page,contractor_evidence_text,requirement_id)"
            " VALUES (?,?,'c','low','r',?,'a',?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                "sub",
                finding,
                NOW,
                NOW,
                run,
                status,
                origin,
                section,
                page,
                quote,
                requirement_id,
            ),
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _score(run, case):
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return crs_bench.score(conn, run, case)
    finally:
        conn.close()


def test_counts_follow_the_counting_rule(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    _add(
        run_id, "MISSING_INFORMATION", origin="datasheet_check", section="Inlet rating"
    )
    _add(
        run_id, "MISSING_INFORMATION", origin="datasheet_check", section="Inlet rating"
    )
    _add(
        run_id,
        "COMPLIANT",
        origin="datasheet_check",
        section="Viscosity",
        finding="0.01cP By Contractor is stated",
    )
    _add(
        run_id,
        "COMPLIANT",
        origin="datasheet_check",
        section="Set pressure",
        page=1,
        quote="design   PRESSURE 9 barg",
    )
    _add(run_id, "NEEDS_ENGINEER_REVIEW", page=1, quote="not on the page")
    case = {
        "kind": "datasheet",
        "untrue": [
            {
                "origin": "datasheet_check",
                "section": "Inlet rating",
                "status": "MISSING_INFORMATION",
            }
        ],
        "irrelevant": [],
        "wrong": [{"section": "Set pressure"}],
    }
    m = _score(run_id, case)
    assert m["untrue"] == 2
    assert m["wrong"] == 1  # a decided row the truth names
    assert (
        m["checklist_decided"] - base["checklist_decided"] == 1
    )  # the By Contractor Pass is not credited (D2)
    assert m["checklist_total"] - base["checklist_total"] == 4
    assert (
        m["pass_on_deferred"] - base["pass_on_deferred"] == 1
    )  # D2: By Contractor is a Query
    assert m["quotes_verified"] - base["quotes_verified"] == 1
    assert m["quotes_total"] - base["quotes_total"] == 2
    assert m["kind"] == "datasheet" and m["kind_ok"]
    assert crs_bench.gate([{"case": {"name": "t", "run": run_id}, "stored": m}])


def test_an_undecided_row_the_truth_calls_wrong_is_not_a_wrong_verdict(run_id):
    _add(run_id, "NEEDS_ENGINEER_REVIEW", section="Set pressure")
    m = _score(run_id, {"kind": "procedure", "wrong": [{"section": "Set pressure"}]})
    assert m["wrong"] == 0
    assert not m["kind_ok"]  # a pump datasheet kind is not a procedure


def test_gate_goes_red_when_a_measure_gets_worse(run_id):
    case = {
        "name": "t",
        "run": run_id,
        "kind": "datasheet",
        "untrue": [{"section": "Inlet rating"}],
    }
    before = [{"case": case, "stored": _score(run_id, case)}]
    _add(run_id, "MISSING_INFORMATION", section="Inlet rating")
    after = [{"case": case, "stored": _score(run_id, case)}]
    assert crs_bench.gate(before, before) == []
    assert any("untrue" in r for r in crs_bench.gate(after, before))


def test_replay_runs_the_current_code_on_a_copy_and_leaves_the_source_alone(run_id):
    db.reset_connection()
    source = Path(settings.db_path)
    sha = _sha(source)
    case = {"name": "t", "run": run_id, "kind": "datasheet"}
    out = crs_bench.replay(source, case)
    assert _sha(source) == sha
    assert out["errors"] == [] and out["model_calls_refused"] == 0
    assert out["findings"] >= 1 and out["pages_total"] == 1
    assert out["crs_lines"] is not None


def test_no_model_or_network_call_leaves_during_a_replay():
    real_post, real_send = model_transport.post_json, httpx.Client.send
    counter = [0]
    with crs_bench._models_refused(counter):
        with pytest.raises(crs_bench.ModelCallRefused):
            model_transport.post_json("/api/generate", {}, timeout=1)
        with pytest.raises(crs_bench.ModelCallRefused):
            httpx.Client().get("http://127.0.0.1:9/")
    assert counter[0] == 2
    assert model_transport.post_json is real_post  # restored afterwards
    assert httpx.Client.send is real_send


def test_the_script_refuses_the_live_database(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crs_bench_script", REPO / "scripts" / "crs_bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--db", str(mod.LIVE)]) == 2
    assert "refused" in capsys.readouterr().out


def test_the_truth_file_holds_no_document_text():
    truth = json.loads((REPO / "eval" / "bench" / "truth.json").read_text())
    # no "section": a label can change while the claim stays (#1569)
    allowed = {
        "origin",
        "check",
        "value",
        "page",
        "status",
        "requirement_id",
        "match_method",
        "why",
    }
    for case in truth["cases"]:
        assert len(case["run"]) == 36
        for key in ("untrue", "irrelevant", "wrong"):
            for m in case.get(key, []):
                assert set(m) <= allowed


def _m(**over):
    base = {
        "wrong": 0,
        "untrue": 0,
        "irrelevant": 0,
        "pass_on_deferred": 0,
        "sent_away": 3,
        "checklist_decided": 2,
        "rules_decided": 1,
        "quotes_verified": 4,
        "quotes_unverified": 1,
        "pages_read": 5,
        "kind_ok": True,
        "kind": "datasheet",
    }
    return {**base, **over}


@pytest.mark.parametrize("key", ["checklist_decided", "rules_decided", "pages_read"])
def test_gate_goes_red_when_a_higher_is_better_measure_drops(key):
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "stored": _m()}]
    assert crs_bench.gate([{"case": case, "stored": _m()}], before) == []
    worse = [{"case": case, "stored": _m(**{key: _m()[key] - 1})}]
    assert any(key in r for r in crs_bench.gate(worse, before))


@pytest.mark.parametrize(
    "key",
    ["untrue", "irrelevant", "pass_on_deferred", "sent_away", "quotes_unverified"],
)
def test_gate_goes_red_when_a_lower_is_better_measure_rises(key):
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "stored": _m()}]
    worse = [{"case": case, "stored": _m(**{key: _m()[key] + 1})}]
    assert any(key in r for r in crs_bench.gate(worse, before))


def test_a_measure_that_goes_blank_is_worse_never_zero():
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "stored": _m()}]
    blank = [{"case": case, "stored": _m(pages_read=None)}]
    assert any("blank" in r for r in crs_bench.gate(blank, before))


def test_a_wrong_verdict_in_the_stored_column_is_red_even_with_a_replay():
    case = {"name": "t", "run": "r"}
    res = [{"case": case, "stored": _m(wrong=1), "replay": _m()}]
    assert any("stored" in r for r in crs_bench.gate(res))


def test_an_empty_truth_matcher_is_refused_not_matched_to_everything(run_id):
    with pytest.raises(ValueError):
        _score(run_id, {"kind": "datasheet", "untrue": [{"why": "no key"}]})


def test_run_bench_itself_refuses_a_live_shaped_path(monkeypatch):
    from app import live_guard

    monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: True)
    with pytest.raises(PermissionError):
        crs_bench.run_bench(Path("x.sqlite"), {"cases": []})


def test_different_settings_are_not_compared_they_are_red():
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "config": "aaaa", "stored": _m()}]
    now = [{"case": case, "config": "bbbb", "stored": _m(checklist_decided=99)}]
    assert any("settings differ" in r for r in crs_bench.gate(now, before))


def test_stored_is_compared_with_stored_when_no_replay_ran():
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "stored": _m(irrelevant=1), "replay": _m(irrelevant=0)}]
    now = [{"case": case, "stored": _m(irrelevant=1)}]
    assert crs_bench.gate(now, before) == []


def test_a_pass_on_a_deferred_value_is_not_credited_as_decided(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    _add(
        run_id,
        "COMPLIANT",
        origin="datasheet_check",
        section="Viscosity",
        finding="0.01cP By Contractor is stated",
    )
    m = _score(run_id, {"kind": "datasheet"})
    assert m["checklist_decided"] == base["checklist_decided"]
    assert m["checklist_total"] == base["checklist_total"] + 1
    assert m["pass_on_deferred"] == base["pass_on_deferred"] + 1


def test_fewer_verified_quotes_because_rows_were_removed_is_not_red():
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "stored": _m(quotes_verified=6, quotes_unverified=0)}]
    after = [{"case": case, "stored": _m(quotes_verified=4, quotes_unverified=0)}]
    assert crs_bench.gate(after, before) == []


def test_quotes_vanishing_while_findings_stay_is_red():
    case = {"name": "t", "run": "r"}
    before = [
        {
            "case": case,
            "stored": _m(quotes_total=113, quotes_unverified=4, findings=250),
        }
    ]
    after = [
        {"case": case, "stored": _m(quotes_total=0, quotes_unverified=0, findings=248)}
    ]
    assert any("quoted findings" in r for r in crs_bench.gate(after, before))


# ------------------------------------------------- every home a decision is made
# Decisions and engineer rows are made in more places than review_findings with
# a requirement_id. Each source has its own row below the headline (never added
# together); an engineer row is not a decision; a D2 Pass is not credited.


def _add_row(
    run, status, *, origin=None, requirement="r", rationale=None, rid=None, finding="x"
):
    fid = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
            "required_action,created_at,updated_at,review_run_id,compliance_status,origin,"
            "requirement_source_text,ai_rationale,requirement_id)"
            " VALUES (?,?,'c','low',?,?,'a',?,?,?,?,?,?,?,?)",
            (
                fid,
                "sub",
                requirement,
                finding,
                NOW,
                NOW,
                run,
                status,
                origin,
                requirement,
                rationale,
                rid,
            ),
        )
    return fid


def _src(m, label):
    return m["sources"].get(label) or {"rows": 0, "decided": 0, "verdicts": 0}


def test_a_rule_linked_decision_has_its_own_row_and_a_textual_one_does_not(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    rule = _src(base, crs_bench.SRC_RULE)
    assert rule["decided"] >= 1  # the fixture's comparison decided its stored rule
    _add_row(run_id, "NON_COMPLIANT", rid="not-a-stored-rule")
    m = _score(run_id, {"kind": "datasheet"})
    assert _src(m, crs_bench.SRC_RULE) == rule  # an id with no stored rule is not one
    other = m["sources"][
        "decided - findings from the comparison (no stored rule linked)"
    ]
    assert other["decided"] == 1 and other["rows"] >= 1


def test_checklist_decisions_are_counted_on_their_own_row_d2_not_credited(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    _add_row(run_id, "NON_COMPLIANT", origin="datasheet_check")
    _add_row(
        run_id,
        "COMPLIANT",
        origin="datasheet_check",
        finding="0.01cP By Contractor is stated",
    )
    m = _score(run_id, {"kind": "datasheet"})
    before, now = (_src(x, crs_bench.SRC_CHECKLIST) for x in (base, m))
    assert now["rows"] - before["rows"] == 2
    assert (
        now["decided"] - before["decided"] == 1
    )  # the By Contractor Pass: not credited
    assert _src(m, crs_bench.SRC_RULE) == _src(base, crs_bench.SRC_RULE)


def test_equipment_kit_cards_are_engineer_rows_not_checklist_decisions(run_id):
    from app import pump_kit

    before = _src(_score(run_id, {"kind": "datasheet"}), crs_bench.SRC_CHECKLIST)
    _add_row(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        origin="datasheet_check",
        requirement=f"Rated flow is stated. [{pump_kit.KIT_WORDS}]",
    )
    m = _score(run_id, {"kind": "datasheet"})
    kit = m["sources"]["kit rows - pump (engineer rows)"]
    assert kit["type"] == crs_bench.ENGINEER and kit["rows"] == 1
    assert _src(m, crs_bench.SRC_CHECKLIST) == before
    case = {"name": "t", "run": run_id}
    assert not any(
        "kit rows" in r for r in crs_bench.gate([{"case": case, "stored": m}])
    )


def test_a_verdict_on_a_kit_row_is_shown_and_red(run_id):
    from app import vessel_kit

    _add_row(
        run_id,
        "COMPLIANT",
        origin="datasheet_check",
        requirement=f"Shell thickness. [{vessel_kit.KIT_WORDS}]",
    )
    m = _score(run_id, {"kind": "datasheet"})
    case = {"name": "t", "run": run_id}
    reasons = crs_bench.gate([{"case": case, "stored": m}])
    assert any("kit rows - vessel" in r for r in reasons)
    cell = crs_bench._source_cell(m, "kit rows - vessel (engineer rows)")
    assert cell == "1 (1 with a verdict - must be 0)"


def test_specification_parked_and_transmittal_kit_rows_each_have_a_row(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    _add_row(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        origin="spec_kit",
        rationale="spec_kit_found p1",
        rid="spec_kit:item-1",
    )
    _add_row(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        origin="spec_kit",
        rationale="spec_kit_not_found",
        rid="spec_kit:drawing:item-2",
    )
    _add_row(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        origin="spec_kit",
        rationale="spec_kit_transmittal header",
        rid="spec_kit:transmittal:number",
    )
    m = _score(run_id, {"kind": "datasheet"})
    for name in ("specification", "drawing", "transmittal"):
        slot = m["sources"][f"kit rows - {name} (engineer rows)"]
        assert slot["rows"] == 1 and slot["verdicts"] == 0
    for label in (crs_bench.SRC_CHECKLIST, crs_bench.SRC_RULE):
        assert _src(m, label) == _src(base, label)


def test_crs_rows_with_no_finding_are_counted_by_kind_playbook_by_state():
    rows = [
        {"finding_id": "f1", "row_kind": "non_compliant"},
        {"finding_id": "", "row_kind": "playbook_check", "playbook_state": "present"},
        {"finding_id": "", "row_kind": "playbook_check", "playbook_state": "missing"},
        {"finding_id": "", "row_kind": "playbook_check", "playbook_state": "missing"},
        {
            "finding_id": "",
            "row_kind": "playbook_check",
            "playbook_state": "standard_not_held",
        },
        {"finding_id": "", "row_kind": "missing_reference"},
        {"finding_id": "", "row_kind": "carried_forward"},
    ]
    out = crs_bench.crs_sources(rows)
    m = {"sources": {}, "crs_sources": out}
    cell = crs_bench._source_cell(m, crs_bench.SRC_PLAYBOOK)
    assert cell == "1 / 2 / 0; other states 1"
    label = (
        "CRS rows with no finding - missing_reference (engineer rows, not decisions)"
    )
    assert crs_bench._source_cell(m, label) == "1"
    assert crs_bench.crs_sources(None) is None
    # the CRS could not be built: blank, never 0
    assert crs_bench._source_cell({"sources": {}, "crs_sources": None}, label) == ""


def test_the_bench_counts_playbook_rows_from_the_crs_it_builds(run_id, monkeypatch):
    """The CRS is built as export builds it (main._crs_content), playbook merge included."""
    from app import crs_mapping, procedure_playbook_rows

    def rows(_sub, name, _allowed):
        return [
            {
                "finding_id": "",
                "document_name": name,
                "page_section": "",
                "comment": f"element {i}",
                "comment_by": procedure_playbook_rows.BY,
                "standard_reference": "",
                "row_kind": procedure_playbook_rows.ROW_KIND,
                "severity": "",
                "engineer_confirmed": False,
                "comment_key": crs_mapping.comment_key("playbook element", "pb", i),
                "priority": crs_mapping.PRIORITY_ENGINEER_TO_CHECK,
                "playbook_state": state,
            }
            for i, state in enumerate(("present", "unclear"))
        ], []

    monkeypatch.setattr(procedure_playbook_rows, "crs_rows", rows)
    db.reset_connection()
    case = {"name": "t", "run": run_id, "kind": "datasheet"}
    out = crs_bench.run_bench(
        Path(settings.db_path), {"cases": [case]}, do_replay=False
    )
    stored = out[0]["stored"]
    assert stored["crs_sources"][crs_bench.SRC_PLAYBOOK]["present"] == 1
    assert stored["crs_sources"][crs_bench.SRC_PLAYBOOK]["unclear"] == 1
    text = crs_bench.render_markdown(out, {"counting_rule": []}, title="t")
    assert f"| {crs_bench.SRC_PLAYBOOK} | 1 / 0 / 1 |" in text
    assert f"| {crs_bench.SRC_RULE} | " in text


HEADLINE = [
    "wrong verdicts (hard stop > 0)",
    "untrue lines",
    "irrelevant lines",
    "checklist decided",
    "standard rules decided",
    "Fail rows",
    "sent to 'needs another document'",
    "verified-quote rate",
    "pages read",
    "kind recognised",
    "Pass on 'By Contractor'/TBA (D2)",
    "CRS lines",
]


FROZEN_HEADLINE = [
    "| wrong verdicts (hard stop > 0) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |",
    "| untrue lines | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |",
    "| irrelevant lines | 1 | 0 | 45 | 45 | 4 | 4 | 0 | 0 | 0 | 0 |",
    "| checklist decided | 22/172 | 21/172 | 0/45 | 0/45 | 0/4 | 0/4 | 3/20 | 0/20"
    " | 0/3 | 0/3 |",
    "| standard rules decided | 0/186 | 0/186 | 0/295 | 0/295 | 0/274 | 0/274"
    " | 0/376 | 0/376 | 0/4964 | 0/5051 |",
    "| Fail rows | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |",
    "| sent to 'needs another document' | 45 | 45 | 274 | 274 | 266 | 265 | 259"
    " | 259 | 2161 | 1328 |",
    "| verified-quote rate | 109/113 | 108/112 | 2/2 | 2/2 | 0/0 | 0/0 | 17/19"
    " | 15/17 | 27/27 | 6/6 |",
    "| pages read | 5/5 | 5/5 | 50/69 | 50/69 | 0/25 | 0/25 | 7/7 | 7/7 | 11/11"
    " | 11/11 |",
    "| kind recognised | yes (datasheet) | yes (datasheet) | NO (datasheet)"
    " | NO (datasheet) | yes (procedure) | yes (procedure) | yes (datasheet)"
    " | yes (datasheet) | NO (datasheet) | NO (datasheet) |",
    "| Pass on 'By Contractor'/TBA (D2) | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |",
    "| CRS lines | 82 | 75 | 50 | 49 | 4 | 4 | 37 | 26 | 13 | 3 |",
]


def test_the_headline_rows_and_gate_on_the_saved_runs_are_unchanged():
    saved = json.loads((REPO / "eval" / "bench" / "baseline.json").read_text())
    assert [label for label, _ in crs_bench.ROWS] == HEADLINE
    assert crs_bench.gate(saved, saved) == []
    text = crs_bench.render_markdown(saved, {"counting_rule": []}, title="t")
    lines = text.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith("| measure |"))
    # Frozen from main's render (before #1566) of the same baseline.json: a
    # headline number that moves fails here, whatever ROWS now computes.
    assert lines[head + 2 : head + 2 + len(HEADLINE)] == FROZEN_HEADLINE
    # the new rows follow the headline, blank for results saved before them
    first_new = lines[head + 2 + len(HEADLINE)]
    assert first_new.startswith(f"| {crs_bench.SRC_RULE} |")
    assert {c.strip() for c in first_new.split("|")[2:-1]} == {""}


def test_the_headline_numbers_of_a_run_are_unchanged_by_the_new_rows(run_id):
    old = _score(run_id, {"kind": "datasheet"})
    _add_row(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        origin="spec_kit",
        rationale="spec_kit_found p1",
        rid="spec_kit:item-1",
    )
    new = _score(run_id, {"kind": "datasheet"})
    # an engineer row changes no decision count on the headline
    for key in ("checklist_decided", "rules_decided", "wrong", "fails"):
        assert new[key] == old[key]
    assert {k for k in new if k != "sources"} == {k for k in old if k != "sources"}


def test_draft_lane_rows_are_engineer_rows_never_counted_as_decisions(run_id):
    _add_row(run_id, None, origin="ai_engineering_check")
    _add_row(run_id, "NEEDS_ENGINEER_REVIEW", origin="clause_review")
    m = _score(run_id, {"kind": "datasheet"})
    for origin in ("ai_engineering_check", "clause_review"):
        slot = m["sources"][f"engineer rows - {origin} (drafts, not decisions)"]
        assert slot["type"] == crs_bench.DRAFT and slot["rows"] == 1
        assert slot["decided"] == 0
    assert not any(k.startswith("decided - findings from") for k in m["sources"])


def _set(fid, **cols):
    with db.connect() as conn:
        for col, value in cols.items():
            conn.execute(
                f"UPDATE review_findings SET {col} = ? WHERE id = ?", (value, fid)
            )


def test_a_compliant_shown_for_a_tick_is_a_safety_tick_row_not_decided(run_id):
    base = _score(run_id, {"kind": "datasheet"})
    fid = _add_row(run_id, "COMPLIANT", origin="datasheet_check")
    _set(fid, show_for_engineer_tick=1)
    m = _score(run_id, {"kind": "datasheet"})
    tick = m["sources"][crs_bench.SRC_TICK]
    assert tick["rows"] == 1 and tick["type"] == crs_bench.TICK
    assert _src(m, crs_bench.SRC_CHECKLIST) == _src(base, crs_bench.SRC_CHECKLIST)
    assert crs_bench._source_cell(m, crs_bench.SRC_TICK) == "1"


def test_draft_rows_count_only_unconfirmed_code_verdicts(run_id):
    label = "engineer rows - clause_review (drafts, not decisions)"
    _add_row(run_id, "NON_COMPLIANT", origin="clause_review")
    confirmed = _add_row(run_id, "COMPLIANT", origin="clause_review")
    _set(confirmed, confirmed_by="eng-1")
    m = _score(run_id, {"kind": "datasheet"})
    assert m["sources"][label]["verdicts"] == 1  # the confirmed one is the engineer's
    assert crs_bench._source_cell(m, label) == "2 (1 draft rows with a code verdict)"
    case = {"name": "t", "run": run_id}
    assert not any(label in r for r in crs_bench.gate([{"case": case, "stored": m}]))


def _known_untrue_case():
    truth = json.loads((REPO / "eval" / "bench" / "truth.json").read_text())
    return next(c for c in truth["cases"] if c["untrue"])


def _claim(run, status, check, *, section, page=None, quote=None):
    """A checklist row as `datasheet_checks` stores it: the check's id in the source text."""
    _add(run, status, origin="datasheet_check", section=section, page=page, quote=quote)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET requirement_source_text = ?"
            " WHERE rowid = (SELECT MAX(rowid) FROM review_findings)",
            (f"Datasheet check {check}: invented wording",),
        )


@pytest.mark.parametrize(
    ("status", "check"),
    [("MISSING_INFORMATION", "PSV-S02"), ("NEEDS_ENGINEER_REVIEW", "PSV-23")],
)
@pytest.mark.parametrize("section", ["Old label", "A completely new label", None])
def test_a_known_untrue_row_is_counted_under_any_label(run_id, status, check, section):
    """#1569: the real truth file, a row saying 'no value' under any label."""
    case = {**_known_untrue_case(), "kind": "datasheet"}
    assert _score(run_id, case)["untrue"] == 0
    _claim(run_id, status, check, section=section)
    assert _score(run_id, case)["untrue"] == 1


def test_the_value_key_decides_the_claim_only_where_the_truth_names_it(run_id):
    """Hand check: PSV-23 with a quote is true; PSV-S02 with a quote is still untrue."""
    case = {**_known_untrue_case(), "kind": "datasheet"}
    _claim(
        run_id,
        "NEEDS_ENGINEER_REVIEW",
        "PSV-23",
        section="x",
        page=1,
        quote="invented",
    )
    assert _score(run_id, case)["untrue"] == 0
    _claim(
        run_id, "MISSING_INFORMATION", "PSV-S02", section="x", page=1, quote="invented"
    )
    assert _score(run_id, case)["untrue"] == 1


def test_another_check_or_status_under_the_known_label_is_not_counted(run_id):
    case = {**_known_untrue_case(), "kind": "datasheet"}
    _claim(run_id, "MISSING_INFORMATION", "PSV-S01", section="Inlet rating")
    _claim(run_id, "NEEDS_ENGINEER_REVIEW", "PSV-S02", section="Inlet rating")
    assert _score(run_id, case)["untrue"] == 0


def test_a_matcher_key_the_bench_does_not_know_is_refused(run_id):
    """An unknown key used to be ignored, so the matcher quietly widened."""
    case = {"kind": "datasheet", "untrue": [{"origin": "x", "field": "inlet_rating"}]}
    with pytest.raises(ValueError, match="field"):
        _score(run_id, case)


def test_a_value_state_other_than_absent_or_present_is_refused(run_id):
    case = {"kind": "datasheet", "untrue": [{"value": "some sheet text"}]}
    with pytest.raises(ValueError, match="value"):
        _score(run_id, case)


def test_page_is_part_of_the_claim(run_id):
    _claim(run_id, "COMPLIANT", "PSV-01", section="x", page=2, quote="invented")
    on_two = {"kind": "datasheet", "untrue": [{"check": "PSV-01", "page": 2}]}
    on_three = {"kind": "datasheet", "untrue": [{"check": "PSV-01", "page": 3}]}
    assert _score(run_id, on_two)["untrue"] == 1
    assert _score(run_id, on_three)["untrue"] == 0
