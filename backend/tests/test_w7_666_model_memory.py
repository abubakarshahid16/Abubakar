"""#666: the model must not stay in RAM for 30 minutes after every call.

It blocked both owner PC sessions for about two hours. Four pieces, each with a
test that fails when the piece is removed:

  1. the interactive default is "5m" and follows the setting;
  2. the P1 runner unloads every model it used when it finishes - on success,
     on an error and on Ctrl+C;
  3. an administrator's route frees model memory, and refuses everyone else;
  4. a batch keeps the #662 rule (10m during, 0 at the end) - pinned in
     test_w4b_644_ai_task_runner.py and untouched here.

The transport is mocked: no Ollama is needed.
"""
from __future__ import annotations

import importlib.util
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access, auth, db, model_memory, model_transport
from app.config import Settings, settings
from app.main import app

NOW = "2026-10-09T00:00:00Z"
REPO = Path(__file__).resolve().parents[2]


class FakeOllama:
    """Stands in for the transport: records every request, answers /api/ps."""

    def __init__(self, loaded):
        self.loaded = list(loaded)
        self.posts: list[dict] = []
        self.refuse: set[str] = set()

    def get_json(self, path, *, timeout, required=True):
        assert path == "/api/ps"
        return {"models": [{"name": m} for m in self.loaded]}

    def post_json(self, path, body, *, timeout):
        sent = model_transport.with_runner_options(body)   # what would reach the socket
        self.posts.append(sent)
        if body["model"] in self.refuse:
            raise RuntimeError("refused")
        if sent["keep_alive"] == 0 and body["model"] in self.loaded:
            self.loaded.remove(body["model"])
        return {}


@pytest.fixture
def ollama(monkeypatch):
    fake = FakeOllama(["qwen3.5:4b", "qwen3.5:2b"])
    monkeypatch.setattr(model_transport, "get_json", fake.get_json)
    monkeypatch.setattr(model_transport, "post_json", fake.post_json)
    model_transport.forget_used_models()
    yield fake
    model_transport.forget_used_models()


# ------------------------------------------------ 1. the default is 5m

def test_the_interactive_default_is_five_minutes_and_follows_the_setting(monkeypatch):
    assert Settings.model_fields["ollama_keep_alive"].default == "5m"
    assert model_transport.with_runner_options({"model": "m"})["keep_alive"] == "5m"
    monkeypatch.setattr(settings, "ollama_keep_alive", "12m")
    assert model_transport.with_runner_options({"model": "m"})["keep_alive"] == "12m"


def test_the_env_example_does_not_put_thirty_minutes_back():
    text = (REPO / "backend" / ".env.example").read_text(encoding="utf-8")
    assert "OLLAMA_KEEP_ALIVE=5m" in text and "OLLAMA_KEEP_ALIVE=30m" not in text


# ------------------------------------------------ the memory module

def test_free_all_unloads_every_resident_model_and_reads_back_what_is_left(ollama):
    report = model_memory.free_all()
    assert report == {"freed": ["qwen3.5:4b", "qwen3.5:2b"], "still_loaded": [], "reachable": True}
    assert [(p["model"], p["keep_alive"]) for p in ollama.posts] == [
        ("qwen3.5:4b", 0), ("qwen3.5:2b", 0)]
    assert all(p["prompt"] == "" for p in ollama.posts)       # no text leaves with an unload


def test_a_model_that_will_not_unload_is_reported_as_still_loaded(ollama):
    ollama.refuse.add("qwen3.5:4b")
    # the fake keeps it resident when the request is refused
    report = model_memory.free_all()
    assert report["still_loaded"] == ["qwen3.5:4b"] and report["freed"] == ["qwen3.5:2b"]


def test_an_unreachable_ollama_is_a_named_state_not_a_crash(monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("down")
    monkeypatch.setattr(model_transport, "get_json", boom)
    assert model_memory.free_all() == {"freed": [], "still_loaded": [], "reachable": False}


def test_the_transport_remembers_which_models_it_sent_work_to(ollama):
    assert model_transport.models_used() == []
    model_transport.with_runner_options({"model": "a:1b"})
    model_transport.with_runner_options({"model": "a:1b"})
    model_transport.with_runner_options({"model": "b:2b"})
    assert model_transport.models_used() == ["a:1b", "b:2b"]


# ------------------------------------------------ 2. the P1 runner unloads

def _p1():
    spec = importlib.util.spec_from_file_location("run_p1_under_test", REPO / "eval" / "p1" / "run_p1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_p1_runner_unloads_the_models_it_used_when_it_finishes(ollama, monkeypatch):
    p1 = _p1()

    def run():
        model_transport.with_runner_options({"model": "qwen3.5:4b"})     # P1 asked a question
        return 0

    monkeypatch.setattr(p1, "_run", run)
    assert p1.main() == 0
    assert [(p["model"], p["keep_alive"]) for p in ollama.posts] == [("qwen3.5:4b", 0)]
    # only what it used: the other resident model is somebody else's
    assert ollama.loaded == ["qwen3.5:2b"]


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_the_p1_runner_unloads_on_an_error_and_on_ctrl_c(ollama, monkeypatch, error):
    p1 = _p1()

    def run():
        model_transport.with_runner_options({"model": "qwen3.5:4b"})
        raise error

    monkeypatch.setattr(p1, "_run", run)
    with pytest.raises(type(error)):
        p1.main()
    assert [(p["model"], p["keep_alive"]) for p in ollama.posts] == [("qwen3.5:4b", 0)]


def test_an_unload_that_fails_never_hides_the_result(ollama, monkeypatch):
    p1 = _p1()
    ollama.refuse.add("qwen3.5:4b")
    monkeypatch.setattr(p1, "_run", lambda: (model_transport.with_runner_options({"model": "qwen3.5:4b"}), 3)[1])
    assert p1.main() == 3


# ------------------------------------------------ 3. the admin route

def _user(user_id: str, *, is_admin: bool) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,?,1,?)",
            (user_id, f"{user_id}@e.test", user_id.title(), auth._hasher.hash("memory-pass"), NOW))
        if is_admin:
            conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                         " VALUES ('role_admin','admin','admins','capability',?)", (NOW,))
            conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at)"
                         " VALUES (?,'role_admin',?)", (user_id, NOW))


@pytest.fixture
def signed_in(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w7666.sqlite")
    db.reset_connection()
    db.init_db()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    yield TestClient(app)
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _headers(client, user_id):
    login = client.post("/api/auth/login", json={"email": f"{user_id}@e.test", "password": "memory-pass"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_the_route_refuses_a_non_admin_and_frees_nothing(signed_in, ollama):
    _user("eve", is_admin=False)
    response = signed_in.post("/api/admin/models/unload", headers=_headers(signed_in, "eve"))
    assert response.status_code == 404                      # the admin surface answers 404, not 403
    assert ollama.posts == [] and ollama.loaded == ["qwen3.5:4b", "qwen3.5:2b"]
    assert signed_in.post("/api/admin/models/unload").status_code in (401, 404)


def test_the_route_frees_model_memory_for_an_admin(signed_in, ollama):
    _user("ada", is_admin=True)
    response = signed_in.post("/api/admin/models/unload", headers=_headers(signed_in, "ada"))
    assert response.status_code == 200
    assert response.json() == {"reachable": True, "freed": ["qwen3.5:4b", "qwen3.5:2b"],
                               "still_loaded": []}
    assert ollama.loaded == []
