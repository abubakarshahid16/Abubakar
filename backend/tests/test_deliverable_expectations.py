from __future__ import annotations

from app import db, deliverables


def test_expected_deliverable_reports_missing_then_registered(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "expected.sqlite")
    db.reset_connection(); db.init_db(); deliverables.ensure_schema()
    deliverables.configure_expectation({"wbs_code": "1.2", "deliverable_type": "drawing", "title": "IFC drawing", "required": True})
    assert deliverables.expected_missing()[0]["state"] == "missing"
    deliverables.create({"wbs_code": "1.2", "title": "IFC drawing", "deliverable_type": "drawing"}, created_by=None)
    assert deliverables.expected_missing()[0]["state"] == "registered"
    db.reset_connection()
