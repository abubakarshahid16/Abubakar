from __future__ import annotations

import pytest
from app import db, risks


def test_risk_register_supports_all_governed_types(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path); monkeypatch.setattr(settings, "db_path", tmp_path / "risk.sqlite")
    db.reset_connection(); db.init_db(); risks.ensure_schema()
    for kind in risks.RISK_TYPES:
        risks.create({"risk_type": kind, "title": kind, "description": "test"})
    assert {row["risk_type"] for row in risks.list_items()} == set(risks.RISK_TYPES)
    db.reset_connection()


def test_unknown_risk_type_rejected(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path); monkeypatch.setattr(settings, "db_path", tmp_path / "risk2.sqlite")
    db.reset_connection(); db.init_db(); risks.ensure_schema()
    with pytest.raises(ValueError): risks.create({"risk_type": "commercial", "title": "x", "description": "x"})
    db.reset_connection()
