"""W5b-08 (#532): the reference-standards coverage report. INVENTED library.

Mutations: M4981-M4989, `python scripts/mutation_check.py --phase 4981`.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import db, standards_inventory
from app.main import app
from tests.test_standards_3b import _doc, _scope, temp_storage  # noqa: F401 - autouse


def _report(*doc_ids):
    return standards_inventory.reference_coverage(allowed_document_ids=_scope(*doc_ids))


def _entry(report, identifier):
    for group in report["groups"]:
        for e in group["entries"]:
            if e["identifier"] == identifier:
                return e
    raise AssertionError(f"{identifier} not listed")


def _group(report, group_id):
    return next(g for g in report["groups"] if g["id"] == group_id)


def test_a_held_standard_is_held_with_the_edition_printed_in_its_file_name():
    doc = _doc("d61511", "x.pdf", "IEC 61511-1 2016.pdf")
    report = _report(doc)
    e = _entry(report, "IEC 61511")
    assert e["status"] == "held" and e["edition"] == "2016" and e["document_id"] == doc
    assert report["state"] == "ok"


def test_a_standard_not_in_the_library_is_missing():
    doc = _doc("d61511", "x.pdf", "IEC 61511-1 2016.pdf")
    report = _report(doc)
    for name in ("IEC 61508", "IEC 61882", "API 521"):
        e = _entry(report, name)
        assert e["status"] == "missing" and e["document_id"] is None and e["edition"] is None


def test_another_number_of_the_same_family_is_not_the_one_listed():
    doc = _doc("d520", "x.pdf", "API 520 Part 1 2020.pdf")
    assert _entry(_report(doc), "API 521")["status"] == "missing"


def test_an_edition_that_is_not_printed_is_not_stated_never_guessed():
    doc = _doc("d61882", "x.pdf", "IEC 61882.pdf")
    e = _entry(_report(doc), "IEC 61882")
    assert e["status"] == "held" and e["edition"] is None


def test_the_recorded_revision_is_the_edition_when_the_name_prints_none():
    doc = _doc("d61882", "x.pdf", "IEC 61882.pdf")
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET revision = 'Ed. 2' WHERE document_id = ?", (doc,))
    assert _entry(_report(doc), "IEC 61882")["edition"] == "Ed. 2"


def test_a_superseded_held_standard_is_held_and_says_so():
    doc = _doc("d61511", "x.pdf", "IEC 61511-1 2003.pdf")
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET superseded_by = 'someone-new' WHERE document_id = ?", (doc,))
    e = _entry(_report(doc), "IEC 61511")
    assert e["status"] == "held" and e["superseded"] is True


def test_a_standard_the_caller_may_not_read_is_missing_for_that_caller():
    doc = _doc("d61511", "x.pdf", "IEC 61511-1 2016.pdf")
    other = _doc("dother", "y.pdf", "other.pdf")
    assert _entry(_report(other), "IEC 61511")["status"] == "missing"
    assert _entry(_report(doc), "IEC 61511")["status"] == "held"


def test_a_group_with_no_entries_says_nothing_is_listed_not_that_all_are_held():
    group = _group(_report(), "company_procedure")
    assert group["listed"] == 0 and group["entries"] == []
    assert group["held"] == 0 and group["missing"] == 0


def test_the_counts_add_up_and_state_their_boundary():
    doc = _doc("d61511", "x.pdf", "IEC 61511-1 2016.pdf")
    report = _report(doc)
    fs = _group(report, "functional_safety")
    assert fs["listed"] == 2 and fs["held"] == 1 and fs["missing"] == 1
    assert "caller may read" in report["scope"]


def test_an_unreadable_list_is_could_not_check_not_an_empty_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(standards_inventory, "WATCHLIST_PATH", tmp_path / "missing.json")
    report = _report()
    assert report["state"] == "could_not_check" and report["groups"] == [] and report["reason"]
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(standards_inventory, "WATCHLIST_PATH", bad)
    assert _report()["state"] == "could_not_check"


def test_the_list_is_data_a_new_entry_needs_no_code_change(tmp_path, monkeypatch):
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"groups": [{"id": "g", "label": "G", "entries": [
        {"identifier": "ISO 9999", "title": "invented"}]}]}), encoding="utf-8")
    monkeypatch.setattr(standards_inventory, "WATCHLIST_PATH", path)
    doc = _doc("d9", "x.pdf", "ISO 9999 2011.pdf")
    e = _entry(_report(doc), "ISO 9999")
    assert e["status"] == "held" and e["edition"] == "2011"


def test_the_route_returns_the_report_for_the_caller():
    _doc("d61511", "x.pdf", "IEC 61511-1 2016.pdf")
    r = TestClient(app).get("/api/standards/coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ok" and {g["id"] for g in body["groups"]} >= {"functional_safety", "hazop"}
    fs = next(g for g in body["groups"] if g["id"] == "functional_safety")
    assert {e["identifier"]: e["status"] for e in fs["entries"]} == {
        "IEC 61508": "missing", "IEC 61511": "held"}
