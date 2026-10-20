"""`GET /api/admin/database-shape` (order 173 follow-up, #881).

A tool that writes test documents and review runs asks the server whether its
database is live-shaped, because a port says nothing about it. The answer is a
boolean about the path's shape, never the path, and only an admin may ask: the
unauthenticated `/api/health` stays as narrow as `test_auth` demands (#806).
"""

from __future__ import annotations

import json

from app.api import admin as api_admin
from app.config import settings
from tests import r2_security_support as support

# The fixtures, by name (an import of them would shadow the test arguments).
temp_storage = support.temp_storage
world = support.world
h = support.h


def test_an_admin_is_told_the_suites_database_is_not_live_shaped(world):
    r = world.get("/api/admin/database-shape", headers=h("u_admin"))
    assert r.status_code == 200, r.text
    assert r.json() == {"live_shaped": False}


def test_a_live_shaped_answer_is_a_boolean_and_never_the_path(world, monkeypatch):
    monkeypatch.setattr(api_admin, "_database_is_live_shaped", lambda: True)
    r = world.get("/api/admin/database-shape", headers=h("u_admin"))
    assert r.status_code == 200, r.text
    assert r.json() == {"live_shaped": True}
    assert str(settings.db_path) not in json.dumps(r.json())


def test_the_shape_is_asked_of_the_servers_own_database_path(monkeypatch, tmp_path):
    # No request here: a path of the live shape would break the fixture's own
    # database, and the question is only which path is asked about.
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    monkeypatch.setattr(settings, "db_path", live)
    assert api_admin._database_is_live_shaped() is True
    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    assert api_admin._database_is_live_shaped() is False


def test_a_reader_and_an_anonymous_caller_get_the_same_404_as_every_admin_route(world):
    assert world.get("/api/admin/database-shape", headers=h("u_sub")).status_code == 404
    assert world.get("/api/admin/database-shape").status_code == 404


def test_the_health_route_is_not_widened_by_it(world):
    body = world.get("/api/health").json()
    assert "live_shaped" not in json.dumps(body)
    assert "database_live_shaped" not in body
