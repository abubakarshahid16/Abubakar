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
    out = at.safe_args(
        {
            "page": 4,
            "clause": "5.2.1",
            "query": "invented sentence here",
            "doc": "doc-7",
        }
    )
    assert out == {
        "page": 4,
        "clause": "5.2.1",
        "doc": "doc-7",
        "other_keys": ["query"],
    }
    assert "page" not in at.safe_args({"page": "a long invented quote of text"})


def test_log_has_no_text_and_reason_is_cut(tmp_path):
    w = at.TraceWriter(tmp_path)
    long = " ".join(f"w{i}" for i in range(50))
    w.step(
        doc="d1",
        item_id="i1",
        step=1,
        tool="search",
        args={"query": "secret words"},
        result={"ok": True, "cites": [{"doc": "d1", "page": 3}]},
        reason=long,
    )
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
    assert json.loads((tmp_path / "state.json").read_text())["completed"] == {
        "a": "GREEN"
    }
    text = w2.refresh_live().read_text()
    for key in (
        "STEP",
        "DONE",
        "PROOF",
        "RUNNING",
        "PROGRESS",
        "MODEL",
        "RESULTS",
        "SPEND",
        "PROBLEMS",
        "NEXT",
        "Last 5",
    ):
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


def test_reason_withheld_when_it_has_a_quote_mark(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.step(
        doc="d",
        item_id="i",
        step=1,
        tool="search",
        args={},
        result={"ok": True},
        reason='he said "x" ok',
    )
    assert "reason withheld" in (tmp_path / "live.log").read_text()
    assert "he said" not in (tmp_path / "i.trace.jsonl").read_text()


def test_reason_withheld_when_13_words_copied_from_a_result(tmp_path):
    w = at.TraceWriter(tmp_path)
    src = " ".join(f"w{i}" for i in range(30))
    w.step(
        doc="d",
        item_id="i",
        step=1,
        tool="open_page",
        args={},
        result={"ok": True, "result": {"t": src}},
        reason=" ".join(f"w{i}" for i in range(5, 18)),
    )
    w.step(
        doc="d",
        item_id="i",
        step=2,
        tool="search",
        args={},
        result={"ok": True},
        reason=" ".join(f"w{i}" for i in range(5, 17)),
    )
    lines = (tmp_path / "live.log").read_text().splitlines()
    assert "reason=reason withheld" in lines[0] and "reason withheld" not in lines[1]


def test_reason_is_capped_at_160_chars(tmp_path):
    w = at.TraceWriter(tmp_path)
    assert len(w.clean_reason("i", "x" * 400)) == 160


def test_problem_line_in_live_log(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.problem("unknown tool zz", doc="d", item_id="i")
    assert (
        "PROBLEM" in (tmp_path / "live.log").read_text()
        and "unknown tool zz" in w.refresh_live().read_text()
    )


def test_finish_item_removes_checkpoint(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.save_checkpoint("i", [])
    w.finish_item(
        doc="d", item_id="i", finding={"color": "RED"}, why="recorded", usd=0, steps=1
    )
    assert not (tmp_path / "i.ckpt.json").exists()


def test_symlink_into_a_git_tree_is_refused(tmp_path):
    tree = tmp_path / "work"
    (tree / "sub").mkdir(parents=True)
    (tree / ".git").mkdir()
    link = tmp_path / "link"
    link.symlink_to(tree / "sub")
    with pytest.raises(at.UnsafeRoot):
        at.resolve_root(link)


def test_symlink_into_this_repo_is_refused(tmp_path):
    link = tmp_path / "toRepo"
    link.symlink_to(at.REPO_ROOT / "docs")
    with pytest.raises(at.UnsafeRoot):
        at.resolve_root(link)


@pytest.mark.parametrize("kind", ["dir", "file"])
def test_a_parent_holding_a_dot_git_is_refused(tmp_path, kind):
    tree = tmp_path / "other"
    tree.mkdir()
    if kind == "dir":
        (tree / ".git").mkdir()
    else:
        (tree / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(at.UnsafeRoot):
        at.resolve_root(tree / "out")


def test_sink_refuses_a_git_tree(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(at.UnsafeRoot):
        at.FindingSink(tmp_path / "run")
