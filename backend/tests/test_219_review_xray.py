"""Order 219: the review X-ray shows what a review stored, escaped and read-only (invented data)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from tools import review_xray

from app import comparison, datasheets, db, standards, submittal_review
from app.config import settings

NOW = "2026-10-26T00:00:00Z"
EVIL = "<script>alert('x')</script>"


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "xray.sqlite")
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
            f"INSERT INTO document_classification ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,0,0)",
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
        "sheet\n",
        equipment_type="Centrifugal Pump",
        title=EVIL,
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
        field_label=EVIL,
        raw_value="9 barg",
        page=1,
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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_nine_sections_come_in_pipeline_order(run_id):
    report = review_xray.build(settings.db_path, run_id)
    ids = [s["id"] for s in report["sections"]]
    assert ids == [
        "run",
        "pages",
        "reader_run",
        "facts",
        "classification",
        "standards",
        "coverage",
        "pairing",
        "comparison",
        "crs",
        "ai",
    ]


def test_the_values_the_review_stored_are_in_the_page(run_id):
    report = review_xray.build(settings.db_path, run_id)
    by_id = {s["id"]: s for s in report["sections"]}
    assert any(
        "Design pressure" in str(r) and "9" in str(r) for r in by_id["facts"]["rows"]
    )
    assert any(
        r[0] == "equipment type" and r[1] == "Centrifugal Pump"
        for r in by_id["classification"]["rows"]
    )
    assert any(
        str(r[0]) == "std.pdf" and r[1] == "chosen" for r in by_id["standards"]["rows"]
    )
    verdicts = {r[1] for r in by_id["comparison"]["rows"]}
    assert "NON_COMPLIANT" in verdicts  # 9 barg against at least 12 barg
    assert any(r[2].startswith(">=") for r in by_id["comparison"]["rows"])


def test_a_document_word_that_is_html_is_escaped_in_the_page(run_id):
    page = review_xray.render_html(review_xray.build(settings.db_path, run_id))
    assert EVIL not in page
    assert "&lt;script&gt;" in page


def test_it_reads_without_changing_the_database(run_id):
    before = _sha(settings.db_path)
    review_xray.build(settings.db_path, run_id)
    assert _sha(settings.db_path) == before


def test_an_unknown_run_is_refused_not_invented(run_id):
    with pytest.raises(LookupError):
        review_xray.build(settings.db_path, "no-such-run")


def test_what_the_system_did_not_store_is_said_not_guessed(run_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM page_ledger")
    by_id = {
        s["id"]: s for s in review_xray.build(settings.db_path, run_id)["sections"]
    }
    assert by_id["pages"]["rows"][0][2] == review_xray.NOT_RECORDED
    assert "no run id" in by_id["ai"]["note"]


def test_the_comment_sheet_section_shows_rows_or_says_why_it_could_not(run_id):
    section = {
        s["id"]: s for s in review_xray.build(settings.db_path, run_id)["sections"]
    }["crs"]
    assert section["rows"] or "Not built here" in section["note"]


def test_the_script_refuses_the_live_database(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "review_xray_script",
        Path(__file__).resolve().parents[2] / "scripts" / "review_xray.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--run", "x", "--db", str(script.LIVE)]) == 2
    assert "live database" in capsys.readouterr().out


def test_the_script_writes_one_local_page_for_a_copy_of_the_database(run_id, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "review_xray_script2",
        Path(__file__).resolve().parents[2] / "scripts" / "review_xray.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "page.html"
    assert (
        script.main(["--run", run_id, "--db", str(settings.db_path), "--out", str(out)])
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "Review X-ray" in text and "<script>" not in text.replace(
        "<script>alert", ""
    )
