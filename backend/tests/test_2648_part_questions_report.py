"""Order 264.8 step 0: the Part-question report says WHY questions wait, with counts only. Invented text."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import datasheets, db, submittal_review
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import part_questions_report as report

NOW = "2026-10-28T00:00:00Z"
QUESTIONS = [
    {
        "standard": "Std One",
        "part": "Part AA",
        "page": 3,
        "requirements": 40,
        "construction": "vessels constructed of carbon and low alloy steel",
        "quote": "x",
    },
    {
        "standard": "Std One",
        "part": "Part BB",
        "page": 9,
        "requirements": 25,
        "construction": "vessels of welded construction",
        "quote": "y",
    },
    {
        "standard": "Std One",
        "part": "Part CC",
        "page": 12,
        "requirements": 7,
        "construction": "vessels for low temperature service",
        "quote": "z",
    },
    {
        "standard": "Std One",
        "part": "Part DD",
        "page": 15,
        "requirements": 3,
        "construction": "equipment of a particular kind",
        "quote": "w",
    },
]


@pytest.fixture
def copy(tmp_path, monkeypatch):
    """A review copy: one submittal, one run whose scope record holds QUESTIONS, two stored facts."""
    path = tmp_path / "copy.sqlite"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", path)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('sub','sheet.pdf','s',1,'sheet.pdf','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES ('sub','test','CONTRACTOR_SUBMITTAL')"
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
            "text,token_count,content_hash,retrievable) VALUES ('c1','sub','f.pdf',0,1,1,NULL,"
            "'prose','x',1,'h',1)"
        )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at,outcome_json)"
            " VALUES ('run1','sub','done',?,?,?)",
            (
                NOW,
                NOW,
                json.dumps(
                    {"requirement_split": {"division_scope": {"questions": QUESTIONS}}}
                ),
            ),
        )
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="c1",
        field_label="Shell material",
        raw_value="SA-516 Gr 70",
        page=1,
    )
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="c1",
        field_label="Joint efficiency",
        raw_value="0.85",
        page=1,
    )
    yield path
    db.reset_connection()


def test_the_report_counts_questions_by_class_and_says_whether_the_sheet_carries_a_settling_fact(
    copy,
):
    out = report.run(copy, "run1")
    assert out["questions"] == 4 and out["requirements_waiting"] == 75
    by = out["by_class"]
    assert by["material"] == {
        "questions": 1,
        "requirements": 40,
        "sheet_has_a_settling_fact": True,
    }
    assert by["joining"] == {
        "questions": 1,
        "requirements": 25,
        "sheet_has_a_settling_fact": True,
    }
    # the sheet states no minimum design metal temperature and no design temperature
    assert by["temperature"] == {
        "questions": 1,
        "requirements": 7,
        "sheet_has_a_settling_fact": False,
    }
    assert (
        by["other"]["questions"] == 1
        and by["other"]["sheet_has_a_settling_fact"] is None
    )
    assert out["settling_roles_present"]["material"] == ["shell_material"]
    assert out["settling_roles_present"]["joining"] == ["joint_efficiency"]
    assert out["settling_roles_present"]["temperature"] == []


def test_the_report_prints_no_part_name_scope_sentence_or_value(copy):
    text = json.dumps(report.run(copy, "run1")).lower()
    for word in (
        "part aa",
        "std one",
        "carbon",
        "welded",
        "sa-516",
        "0.85",
        "quote",
        "sheet.pdf",
    ):
        assert word not in text


def test_it_refuses_a_live_shaped_path_and_an_unknown_run(copy, tmp_path):
    with pytest.raises(SystemExit):
        report.run(copy, "no-such-run")
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    with pytest.raises(SystemExit) as refused:
        report.run(live, "run1")
    assert "live database" in str(refused.value)


@pytest.mark.parametrize(
    ("phrase", "klass"),
    [
        ("vessels of carbon steel construction", "material"),
        ("brazed or welded vessels", "joining"),
        ("service below the minimum temperature", "temperature"),
        ("equipment of a particular kind", "other"),
        ("", "other"),
    ],
)
def test_a_phrase_is_put_in_one_class(phrase, klass):
    assert report.classify(phrase) == klass
