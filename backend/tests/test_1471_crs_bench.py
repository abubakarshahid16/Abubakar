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
