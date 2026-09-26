"""The chat benchmark kit (scripts/chat_benchmark.py) keeps client text where it belongs.

The questions and the answers are client material. What these tests hold:
  * the script reads and writes only inside `.cowork/`;
  * it refuses to write a report git would track;
  * its progress output never carries a question;
  * the report records what the chat did and leaves every score blank.

Runs the script against the app in-process; synthetic documents only.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "chat_benchmark.py"


@pytest.fixture
def bench(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("chat_benchmark", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cowork = tmp_path / ".cowork"
    cowork.mkdir()
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "COWORK", cowork)
    monkeypatch.setattr(mod, "git_ignores", lambda path: True)
    client = TestClient(app)

    def call(self, method, path, body=None, timeout=600):
        r = client.request(method, path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}")
        return r.json()

    monkeypatch.setattr(mod.Api, "call", call)
    return mod, cowork, client


def test_a_path_outside_cowork_is_refused(bench, tmp_path):
    mod, cowork, _ = bench
    with pytest.raises(mod.Refused):
        mod.inside_cowork(tmp_path / "report.md")
    assert mod.inside_cowork(cowork / "report.md")


def test_it_refuses_to_write_a_report_git_would_track(bench, monkeypatch):
    mod, cowork, _ = bench
    (cowork / "q.txt").write_text("general | what is barg\n", encoding="utf-8")
    monkeypatch.setattr(mod, "git_ignores", lambda path: False)
    assert mod.main(["--no-auth", "--questions", str(cowork / "q.txt"),
                     "--report", str(cowork / "r.md")]) == 2
    assert not (cowork / "r.md").exists()


def test_the_report_records_what_the_chat_did_and_leaves_scores_blank(bench, capsys):
    mod, cowork, client = bench
    upload(client)
    (cowork / "q.txt").write_text(
        "# comments are skipped\n"
        "coating | what is the dry film thickness for coating system no. 1\n"
        "\n"
        "greeting | hi\n", encoding="utf-8")
    assert mod.main(["--no-auth", "--questions", str(cowork / "q.txt"),
                     "--report", str(cowork / "r.md")]) == 0
    report = (cowork / "r.md").read_text(encoding="utf-8")
    assert "### 1. what is the dry film thickness for coating system no. 1" in report
    assert "### 2. hi" in report
    assert "**ChatGPT** (paste here)" in report and "**Claude.ai** (paste here)" in report
    assert "| This system | | | | | | /7 |" in report, "a score was filled in by the script"
    assert "git ignores" in report
    out = capsys.readouterr().out
    assert "dry film thickness" not in out, "a question was printed"
    assert "[1/2] coating" in out


def test_a_question_that_fails_is_reported_not_lost(bench, monkeypatch):
    mod, cowork, _ = bench
    (cowork / "q.txt").write_text("a | first\nb | second\n", encoding="utf-8")
    calls = {"n": 0}

    def flaky(api, question, model):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("backend down")
        return {"answer_type": "general", "answer_kind": "general", "answer": "ok",
                "used_line": "General knowledge", "sources": [], "_wall_seconds": 1.0}

    monkeypatch.setattr(mod, "ask", flaky)
    assert mod.main(["--no-auth", "--questions", str(cowork / "q.txt"),
                     "--report", str(cowork / "r.md")]) == 0
    report = (cowork / "r.md").read_text(encoding="utf-8")
    assert "**This system: did not run** - backend down" in report
    assert "### 2. second" in report and "> ok" in report
