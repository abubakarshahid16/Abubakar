"""#949 form list (planner 13:40 PKT): the form of a sheet = the type's reference
roles PLUS what its included standards' evaluable requirements are about,
deduplicated, capped at 60, batched as before. Default OFF; every gate of the
form reader still applies. Invented data only; the model is a fake."""
from __future__ import annotations

import json
import uuid

import pytest

from app import db, form_reader_fields as ff, form_reader_run as fr, requirements_3b as r3, submittal_review
from app.config import settings

NOW = "2026-10-14T00:00:00Z"


def test_the_base_is_kept_and_a_new_subject_is_added_once():
    base = ff.field_list_for("Pressure Safety Valve")
    fields = ff.with_requirement_fields(base, ["widget clearance", "Widget Clearance", "design pressure", "set pressure"])
    names = [f.name.lower() for f in fields]
    assert fields[:len(base)] == base
    assert names.count("widget clearance") == 1                         # the same subject twice is one line
    assert sum(1 for f in fields if f.key.startswith("req_")) == 1  # "design/set pressure" are in the base already


def test_the_form_is_capped_and_the_base_is_never_cut():
    base = ff.field_list_for("Pressure Safety Valve")
    many = [f"invented field {i}" for i in range(200)]
    fields = ff.with_requirement_fields(base, many)
    assert len(fields) == ff.MAX_FORM_FIELDS == 60 and fields[:len(base)] == base
    assert len(ff.with_requirement_fields(base, many, cap=len(base))) == len(base)


def test_a_requirement_field_has_no_unit_kind_of_its_own_and_batches_as_before():
    fields = ff.with_requirement_fields([], ["outlet size", "inlet size"])
    assert all(f.unit_kind is None for f in fields)
    assert [len(b) for b in ff.batches(ff.with_requirement_fields([], [f"field {i}" for i in range(60)]))] == [25, 25, 10]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _std(conn, doc, rows):
    conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                 " VALUES (?,?,?,1,'x','ready',1,?)", (doc, doc + ".pdf", "sha" + doc, NOW))
    conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
                 "token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose','x',1,?,1)",
                 ("c" + doc, doc, doc + ".pdf", "h" + doc))
    for ty, subject, text in rows:
        conn.execute("INSERT INTO standard_requirements (id,standard_document_id,clause,page,requirement_text,"
                     "source_text,category,extraction_method,confidence,created_at,updated_at,chunk_id,"
                     "requirement_type,subject) VALUES (?,?,'1',1,?,?,'x','extracted',0.9,?,?,?,?,?)",
                     (str(uuid.uuid4()), doc, text, text, NOW, NOW, "c" + doc, ty, subject))


def test_the_subjects_are_those_of_the_evaluable_requirements_most_asked_first(library):
    with db.connect() as conn:
        _std(conn, "std1", [
            ("numeric_limit", "outlet size", "x"), ("numeric_limit", "outlet size", "x"),
            ("range_limit", "travel", "x"), ("nominal_value", "loop supply", "x"),
            ("cross_field_limit", "ignored subject", "The set pressure shall not exceed the maximum allowable working pressure."),
            ("statement", "not evaluable", "x"),
            ("numeric_limit", "a very long subject that goes on and on past any label length at all", "x"),
            ("numeric_limit", "café size", "x")])
    assert fr.requirement_subjects(["std1"])[0] == "outlet size"
    got = fr.requirement_subjects(["std1"])
    assert set(got) == {"outlet size", "travel", "loop supply", "set pressure"}
    assert fr.requirement_subjects([]) == [] and fr.requirement_subjects(["no-such-standard"]) == []


def test_the_standards_of_a_sheet_are_its_latest_runs_included_ones(library):
    with db.connect() as conn:
        _std(conn, "stdA", []); _std(conn, "stdB", [])
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                     " VALUES ('sheet','s.pdf','shs',1,'x','ready',1,?)", (NOW,))
    run = submittal_review.create_review_run(submittal_document_id="sheet", allowed_document_ids=frozenset({"sheet", "stdA", "stdB"}))
    with db.connect() as conn:
        for sid, inc in (("stdA", 1), ("stdB", 0)):
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
                         "selection_method,included,created_at) VALUES (?,?,?,'cited','referenced',?,?)",
                         (str(uuid.uuid4()), run, sid, inc, NOW))
    assert fr.standards_of("sheet") == ["stdA"]
    assert fr.standards_of("a-sheet-with-no-run") == []


def test_the_model_is_asked_for_the_requirement_fields_too():
    asked: list[str] = []

    def model(prompt: str) -> str:
        asked.append(prompt)
        return json.dumps({"fields": []})
    run = fr.read_document({1: "Casing note: 6 in"}, None, model_call=model, extra_subjects=["widget clearance"])
    assert run["form"] is not None
    assert any("Widget clearance" in p for p in asked), "the new field is on the form the model is shown"
    plain = []
    fr.read_document({1: "Casing note: 6 in"}, None, model_call=lambda p: (plain.append(p), json.dumps({"fields": []}))[1])
    assert not any("Widget clearance" in p for p in plain), "without extras the form is the type's own"
