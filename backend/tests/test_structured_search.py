from __future__ import annotations

from app import db, deliverables, review, risks, structured_search


def test_structured_search_returns_wbs_and_finding_records(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "structured.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema(); deliverables.ensure_schema()
    deliverables.create({"wbs_code": "2.1", "title": "Piping review", "deliverable_type": "review"}, created_by=None)
    found = structured_search.search("piping", kind="deliverable")
    assert found and found[0]["wbs_code"] == "2.1"
    db.reset_connection()


def test_structured_search_matches_risk_type_name(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "risk-type.sqlite")
    db.reset_connection(); db.init_db(); risks.ensure_schema()
    risks.create({"risk_type": "schedule", "title": "Late package", "description": "Due date exposure"})
    found = structured_search.search("schedule", kind="risk")
    assert found and found[0]["label"] == "Late package"
    db.reset_connection()
