"""#1690 agent_trace: local only, numbers not text, resume state."""
import json

import pytest

from app import agent_trace as at


def test_root_inside_repo_is_refused():
    with pytest.raises(at.UnsafeRoot):
        at.resolve_root(at.REPO_ROOT / "docs" / "x")


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(at.ENV_NAME, str(tmp_path / "t"))
    assert at.resolve_root() == (tmp_path / "t").resolve()


def test_args_keep_numbers_never_text():
    out = at.safe_args({"page": 4, "clause": "5.2.1", "query": "invented sentence here", "doc": "doc-7"})
    assert out == {"page": 4, "clause": "5.2.1", "doc": "doc-7", "other_keys": ["query"]}
    assert "page" not in at.safe_args({"page": "a long invented quote of text"})


def test_log_has_no_text_and_reason_is_cut(tmp_path):
    w = at.TraceWriter(tmp_path)
    long = " ".join(f"w{i}" for i in range(50))
    w.step(doc="d1", item_id="i1", step=1, tool="search", args={"query": "secret words"},
           result={"ok": True, "cites": [{"doc": "d1", "page": 3}]}, reason=long)
    log = (tmp_path / "live.log").read_text()
    assert "secret" not in log and "w19" in log and "w20" not in log
    assert "at=3" in log
    assert "secret" not in (tmp_path / "i1.trace.jsonl").read_text()


def test_resume_state_and_live_md(tmp_path):
    w = at.TraceWriter(tmp_path, total=20, clock=lambda: 1000.0)
    w.mark_done("a", "GREEN")
    w.add_spend(1.5)
    w2 = at.TraceWriter(tmp_path, total=20)
    assert w2.is_done("a") and not w2.is_done("b") and w2.spend == 1.5
    assert json.loads((tmp_path / "state.json").read_text())["completed"] == {"a": "GREEN"}
    text = w2.refresh_live().read_text()
    for key in ("STEP", "DONE", "PROOF", "RUNNING", "PROGRESS", "MODEL", "RESULTS", "SPEND", "PROBLEMS", "NEXT",
                "Last 5"):
        assert key in text
    assert "GREEN 1" in text and "USD 1.50" in text


def test_live_md_refreshed_every_10_items(tmp_path):
    w = at.TraceWriter(tmp_path, total=20)
    for n in range(9):
        w.mark_done(f"i{n}", "YELLOW")
    assert not (tmp_path / "LIVE.md").exists()
    w.mark_done("i9", "RED")
    assert (tmp_path / "LIVE.md").exists()


def test_checkpoint_roundtrip_removed_on_done(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.save_checkpoint("x", [{"tool": "search"}])
    assert w.load_checkpoint("x") == [{"tool": "search"}]
    w.mark_done("x", "GREEN")
    assert w.load_checkpoint("x") == []
