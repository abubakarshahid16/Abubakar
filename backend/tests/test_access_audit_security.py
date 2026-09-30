"""The security audit of 2026-09-30: nine verified defects, one test each.

Every test here was written against the defect first (the probes in the audit
reproduced each one) and each has a mutation in
`scripts/mutations/audit_security.py` (M1480-M1499) that puts the defect back
and must turn it red.

Most of these only exist under `AUTH_MODE=demo_required` - under `disabled`
every caller is unrestricted and a negative assertion passes for the wrong
reason - so the `secure` fixture asserts the mode before any test runs. Tokens
are REAL (`auth.issue_token`, resolved by `auth.resolve_user_id`), because two
of the defects (password reset) live in the token check itself.
"""

from __future__ import annotations

import importlib.util
import io
import re
import secrets
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import access, admin, auth, db, deliverables, model_transport, upload
from app.config import (
    ModelHostRefused, Settings, UnsafeBindRefused, settings, trusted_host_names,
)
from app.db import connect
from app.main import app

REPO = Path(__file__).resolve().parents[2]


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    admin.ensure_schema()
    conn = connect()
    with conn:
        for rid, name, kind in (("r_admin", "admin", "capability"),
                                ("r_mech", "Mechanical", "discipline")):
            conn.execute("INSERT INTO roles (id, name, description, kind, created_at)"
                         " VALUES (?, ?, '', ?, ?)", (rid, name, kind, _now()))
        for uid, rid in (("u_admin", "r_admin"), ("u1", "r_mech")):
            conn.execute("INSERT INTO users (id, email, display_name, password_hash,"
                         " is_active, created_at) VALUES (?, ?, ?, 'x', 1, ?)",
                         (uid, f"{uid}@example.com", uid, _now()))
            conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at)"
                         " VALUES (?, ?, ?)", (uid, rid, _now()))
        for doc in ("doc_mine", "doc_hidden"):
            conn.execute("INSERT INTO documents (id, filename, sha256, size_bytes,"
                         " stored_path, status, uploaded_at) VALUES"
                         " (?, ?, ?, 1, '/dev/null', 'ready', ?)",
                         (doc, f"{doc}.pdf", secrets.token_hex(32), _now()))
        conn.execute("INSERT INTO document_role_access (document_id, role_id,"
                     " permission, granted_at) VALUES ('doc_mine', 'r_mech', 'read', ?)",
                     (_now(),))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    assert settings.auth_mode == access.AUTH_REQUIRED, \
        "fixture ran under `disabled`; every assertion below is vacuous"
    yield TestClient(app)
    access.set_user_resolver(None)


def _h(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


# ------------------------------------------------------------ 1. DNS rebinding


def test_a_foreign_host_header_is_refused_even_with_auth_disabled():
    """The rebinding page's request carries its own name in Host. Under the
    default `disabled` mode it used to get every document."""
    client = TestClient(app)
    assert settings.auth_mode == access.AUTH_DISABLED
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    r = client.get("/api/documents", headers={"Host": "attacker.example:8000"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_parameter"


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:5173", "[::1]:8000",
                                  "LOCALHOST", "127.0.0.1"])
def test_loopback_names_and_the_vite_proxy_host_still_work(host):
    """The dev proxy forwards the browser's own Host (127.0.0.1:5173 or
    localhost:5173) - `changeOrigin` is off in vite.config.ts."""
    assert TestClient(app).get("/api/health", headers={"Host": host}).status_code == 200


def test_allowed_hosts_adds_a_name_and_testserver_is_test_configuration_only(monkeypatch):
    fresh = Settings(_env_file=None)
    assert "testserver" not in trusted_host_names(fresh), \
        "a production default trusts the TestClient's name"
    assert {"localhost", "127.0.0.1", "::1"} <= trusted_host_names(fresh)
    client = TestClient(app)
    assert client.get("/api/health", headers={"Host": "rag.lan"}).status_code == 400
    monkeypatch.setattr(settings, "allowed_hosts", "testserver, rag.lan")
    assert client.get("/api/health", headers={"Host": "rag.lan:8000"}).status_code == 200


def test_an_unauthenticated_network_bind_is_refused_at_startup():
    for host in ("0.0.0.0", "::", "192.168.1.20"):
        with pytest.raises(UnsafeBindRefused):
            Settings(_env_file=None, host=host, auth_mode="disabled")
    # The three ways it is allowed.
    Settings(_env_file=None, host="127.0.0.1", auth_mode="disabled")
    Settings(_env_file=None, host="0.0.0.0", auth_mode="demo_required")
    Settings(_env_file=None, host="0.0.0.0", auth_mode="disabled",
             allow_unauthenticated_network_bind=True)


# ------------------------------------------- 2. deliverable PATCH write-first


def test_patching_a_hidden_deliverable_changes_nothing(secure):
    item = deliverables.create({"wbs_code": "W1", "title": "ORIGINAL",
                                "deliverable_type": "spec", "document_id": "doc_hidden"},
                               created_by="u_admin")
    r = secure.patch(f"/api/deliverables/{item['id']}", json={"title": "CHANGED"},
                     headers=_h("u1"))
    assert r.status_code == 404
    assert deliverables.get(item["id"])["title"] == "ORIGINAL", \
        "the row was written before the read check refused the caller"


# ------------------------------------------------------------ 3. POST /api/risks


def _risk_count() -> int:
    from app import risks

    risks.ensure_schema()
    return connect().execute("SELECT COUNT(*) FROM risks").fetchone()[0]


def test_an_anonymous_caller_cannot_write_a_risk(secure):
    r = secure.post("/api/risks", json={"risk_type": "review", "title": "t",
                                        "description": "d"})
    assert r.status_code == 401
    assert _risk_count() == 0


def test_a_risk_on_a_hidden_document_is_refused(secure):
    r = secure.post("/api/risks", json={"risk_type": "review", "title": "t",
                                        "description": "d", "document_id": "doc_hidden"},
                    headers=_h("u1"))
    assert r.status_code == 404
    assert _risk_count() == 0
    ok = secure.post("/api/risks", json={"risk_type": "review", "title": "t",
                                         "description": "d", "document_id": "doc_mine"},
                     headers=_h("u1"))
    assert ok.status_code == 200, ok.text


def test_a_risk_description_is_length_limited(secure):
    r = secure.post("/api/risks", json={"risk_type": "review", "title": "t",
                                        "description": "x" * 100_000}, headers=_h("u1"))
    assert r.status_code == 422
    assert _risk_count() == 0


# ------------------------------------------------ 4. global settings, admin only


def test_a_non_admin_cannot_change_the_summary_schedule(secure, monkeypatch):
    monkeypatch.setattr(settings, "summary_schedule", "disabled")
    body = {"schedule": "daily", "weekday_utc": 0, "hour_utc": 3}
    assert secure.put("/api/management/summary/schedule", json=body,
                      headers=_h("u1")).status_code == 404
    assert settings.summary_schedule == "disabled"
    assert secure.put("/api/management/summary/schedule", json=body,
                      headers=_h("u_admin")).status_code == 200
    assert settings.summary_schedule == "daily"


def test_a_non_admin_cannot_change_an_escalation_rule(secure):
    before = deliverables.escalation_rules()
    body = {"level": 1, "trigger_days": 0, "recipient_role": "nobody", "action": "x"}
    assert secure.put("/api/management/escalation-rules/1", json=body,
                      headers=_h("u1")).status_code == 404
    assert deliverables.escalation_rules() == before
    assert secure.put("/api/management/escalation-rules/1", json=body,
                      headers=_h("u_admin")).status_code == 200


def test_a_non_admin_cannot_create_a_baseline_rule(secure):
    body = {"baseline_doc_type": "specification"}
    assert secure.post("/api/reviews/baseline-rules", json=body,
                       headers=_h("u1")).status_code == 404
    assert secure.get("/api/reviews/baseline-rules", headers=_h("u1")).json()["rules"] == []
    assert secure.post("/api/reviews/baseline-rules", json=body,
                       headers=_h("u_admin")).status_code == 200


def test_a_non_admin_cannot_edit_a_baseline_rule(secure):
    rule = secure.post("/api/reviews/baseline-rules", json={"baseline_doc_type": "spec"},
                       headers=_h("u_admin")).json()
    r = secure.patch(f"/api/reviews/baseline-rules/{rule['id']}",
                     json={"baseline_doc_type": "CHANGED"}, headers=_h("u1"))
    assert r.status_code == 404
    rules = secure.get("/api/reviews/baseline-rules", headers=_h("u1")).json()["rules"]
    assert [x["baseline_doc_type"] for x in rules] == ["spec"]


def test_a_non_admin_cannot_register_a_review_template(secure):
    body = {"name": "Checklist", "version": "1"}
    assert secure.post("/api/reviews/templates", json=body,
                       headers=_h("u1")).status_code == 404
    assert secure.get("/api/reviews/templates", headers=_h("u1")).json()["templates"] == []
    assert secure.post("/api/reviews/templates", json=body,
                       headers=_h("u_admin")).status_code == 200


# ---------------------------------------------- 5. password reset ends sessions


def test_an_admin_password_reset_ends_the_users_sessions(secure):
    old = _h("u1")
    assert secure.get("/api/auth/me", headers=old).status_code == 200
    r = secure.post("/api/admin/users/u1/password-reset", headers=_h("u_admin"))
    assert r.status_code == 200, r.text
    assert secure.get("/api/auth/me", headers=old).status_code == 401


def test_redeeming_a_reset_token_ends_the_sessions_issued_before_it(secure):
    issued = admin.issue_password_reset("u1", None)
    # A session that exists AFTER the reset was issued and BEFORE it is used:
    # somebody still holding the old password logs in in between.
    between = _h("u1")
    assert secure.get("/api/auth/me", headers=between).status_code == 200
    admin.redeem_password_token(issued["setup_token"], "a-new-long-passphrase-9241")
    assert secure.get("/api/auth/me", headers=between).status_code == 401


# ------------------------------------- 6. categorize_documents through transport


def _categorize_module():
    spec = importlib.util.spec_from_file_location(
        "categorize_documents_under_test", REPO / "scripts" / "categorize_documents.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_categorize_sends_document_text_only_through_the_model_transport(monkeypatch):
    """Reassign `ollama_url` after startup: the transport's second gate refuses
    before a client is built. A bare `httpx.post` never checked it, honoured
    HTTP(S)_PROXY and followed redirects."""
    mod = _categorize_module()
    ev = {"sections": "  s", "opening": "text", "excerpts": "more", "cited": [1]}
    monkeypatch.setattr(settings, "ollama_url", "http://10.9.8.7:11434")

    def explode(*a, **k):
        raise AssertionError("a client was built for a refused host")
    monkeypatch.setattr(httpx, "Client", explode)
    with pytest.raises(ModelHostRefused):
        mod.classify("f.pdf", ev)


def test_categorize_still_classifies_on_loopback(monkeypatch):
    mod = _categorize_module()
    seen = {}

    def fake(path, body, *, timeout):
        seen["path"] = path
        return {"message": {"content": '{"category": "IT", "confidence": "low", "reason": "r"}'}}
    monkeypatch.setattr(model_transport, "post_json", fake)
    out = mod.classify("f.pdf", {"sections": "", "opening": "", "excerpts": "", "cited": [1]})
    assert out["category"] == "IT" and seen["path"] == "/api/chat"


# ---------------------------------------------- 8a. CRS reply workbook limits


def _xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Item No", "Contractor's Response"])
    ws.append(["CRS-1-001", "Accepted"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_reply_sheet_that_expands_past_the_upload_limit_is_refused(monkeypatch):
    from app import crs_reply

    data = _xlsx_bytes()
    assert crs_reply.read_replies(data)[0]["response"] == "Accepted"
    monkeypatch.setattr(upload, "MAX_XLSX_UNCOMPRESSED_BYTES", 64)
    with pytest.raises(crs_reply.ReplySheetError, match="expands"):
        crs_reply.read_replies(data)


# ------------------------------------------------ 8b. /docs and /openapi.json


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_api_description_is_not_public_under_demo_required(secure, monkeypatch, path):
    assert secure.get(path).status_code == 404
    assert secure.get(path, headers=_h("u1")).status_code == 404
    monkeypatch.setattr(settings, "api_docs_enabled", True)
    assert secure.get(path).status_code == 200


def test_the_api_description_is_served_on_a_developer_machine():
    assert settings.auth_mode == access.AUTH_DISABLED
    assert TestClient(app).get("/openapi.json").status_code == 200


# ------------------------------------------------------------ 7. CI guards


def _workflow() -> str:
    return (REPO / ".github" / "workflows" / "secret-scan.yml").read_text(encoding="utf-8")


def test_the_synthetic_fixture_exclusion_matches_the_real_path():
    m = re.search(r"grep -v '(\^[^']*synthetic/)'", _workflow())
    assert m, "no synthetic-fixture exclusion in the workflow"
    assert re.search(m.group(1), "backend/tests/fixtures/synthetic/sample.pdf"), \
        "the exclusion never matches: the tests live under backend/"


def test_gitleaks_no_longer_allowlists_the_whole_env_example():
    cfg = tomllib.loads((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    entries = cfg.get("allowlists", []) + ([cfg["allowlist"]] if "allowlist" in cfg else [])
    for entry in entries:
        if entry.get("condition", "OR").upper() == "AND":
            continue          # path AND line - the narrowed placeholder entry
        for p in entry.get("paths", []):
            assert not re.search(p, "backend/.env.example"), \
                f"{p!r} hides every line of .env.example from the scanner"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _scan(repo: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "scripts" / "check_client_identifiers.py"),
                           "--root", str(repo), "--base", base],
                          capture_output=True, text=True)


# Built from parts so this file does not itself add an identifier-shaped token.
_TAG = "21-" + "PV-" + "4417B"


def test_the_ci_identifier_check_blocks_new_tokens_and_ignores_old_ones(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feature")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".github").mkdir()
    (repo / ".github" / "client-identifier-patterns.txt").write_bytes(
        (REPO / ".github" / "client-identifier-patterns.txt").read_bytes())
    (repo / "old.txt").write_text(f"already tracked {_TAG}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()

    # An edit elsewhere in a file that ALREADY holds one is not reported.
    (repo / "old.txt").write_text(f"already tracked {_TAG}\nnew harmless line\n")
    (repo / "fixture.txt").write_text("made up DS-" + "0000-DAS-M-01\n")
    _git(repo, "commit", "-qam", "harmless")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    clean = _scan(repo, base)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    (repo / "new.txt").write_text(f"see {_TAG} for the pump\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adds one")
    hit = _scan(repo, base)
    assert hit.returncode == 1, hit.stdout + hit.stderr
    assert f"new.txt:1: {_TAG}" in hit.stdout
    assert "for the pump" not in hit.stdout, "the log republished the surrounding line"

    # The developer's local list is read too, when present.
    (repo / ".githooks").mkdir()
    (repo / ".githooks" / "client-identifiers.local").write_text("FAKECLIENT\n")
    (repo / "name.txt").write_text("FAKECLIENT pumps\n")
    _git(repo, "add", "name.txt")
    _git(repo, "commit", "-qm", "name")
    assert "name.txt:1: FAKECLIENT" in _scan(repo, base).stdout


def test_the_ci_workflow_runs_the_identifier_check_on_the_diff():
    text = _workflow()
    assert "scripts/check_client_identifiers.py --base" in text
    assert "fetch-depth: 0" in text.split("no-client-data:")[1]
