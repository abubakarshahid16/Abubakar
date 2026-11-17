"""The rehearsal gate (owner order, 17 Nov 2026): no live update if any paper's rules asked or comments drop by more than 30%, go to
zero, or WRONG goes up. Forged snapshots only (invented ids, no document text)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "rehearsal_gate_script", REPO / "scripts" / "rehearsal_gate.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _paper(rules=100, comments=40, points=200, runs=("rc-live-1", "ai-live-1")):
    return {
        "document_id": "doc-invented-1",
        "runs": {"rule_check": runs[0], "ai_review": runs[1]},
        "rules_asked": rules,
        "comments": comments,
        "points": points,
        "errors": [],
    }


def _snap(path: Path, **papers) -> str:
    path.write_text(
        json.dumps({"schema": gate.SCHEMA, "papers": papers}), encoding="utf-8"
    )
    return str(path)


def _kww(path: Path, **wrong) -> str:
    path.write_text(
        json.dumps({k: {"keep": 1, "weak": 1, "wrong": v} for k, v in wrong.items()}),
        encoding="utf-8",
    )
    return str(path)


def _run(tmp_path, live, rehearsal, wrong_live=5, wrong_rehearsal=5, accept=()):
    argv = [
        "compare",
        "--live",
        _snap(tmp_path / "live.json", PUMP=live),
        "--rehearsal",
        _snap(tmp_path / "reh.json", PUMP=rehearsal),
        "--kww-live",
        _kww(tmp_path / "kl.json", PUMP=wrong_live),
        "--kww-rehearsal",
        _kww(tmp_path / "kr.json", PUMP=wrong_rehearsal),
    ]
    for a in accept:
        argv += ["--accept", a]
    return gate.main(argv)


def _row(out: str, metric: str) -> str:
    return next(
        line
        for line in out.splitlines()
        if line.startswith("PUMP") and f" {metric} " in line
    )


NEW_RUNS = ("rc-reh-1", "ai-reh-1")


def test_a_25_percent_drop_passes(tmp_path, capsys):
    assert (
        _run(
            tmp_path, _paper(), _paper(rules=75, comments=30, points=150, runs=NEW_RUNS)
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "GATE: PASS" in out
    assert "-25.0%" in _row(out, "rules_asked")
    assert "PASS" in _row(out, "comments")


def test_a_35_percent_drop_refuses(tmp_path, capsys):
    assert _run(tmp_path, _paper(), _paper(comments=26, runs=NEW_RUNS)) == 1
    out = capsys.readouterr().out
    row = _row(out, "comments")
    assert "REFUSE" in row
    assert "-35.0%" in row
    assert "more than 30%" in row
    assert "PASS" in _row(out, "rules_asked")
    assert "GATE: REFUSED" in out


def test_exactly_30_percent_passes_31_refuses(tmp_path, capsys):
    assert _run(tmp_path, _paper(), _paper(points=140, runs=NEW_RUNS)) == 0
    capsys.readouterr()
    assert _run(tmp_path, _paper(), _paper(points=138, runs=NEW_RUNS)) == 1


def test_zero_refuses(tmp_path, capsys):
    # the 17 Nov pump: 0 rules asked after the update
    assert _run(tmp_path, _paper(rules=426), _paper(rules=0, runs=NEW_RUNS)) == 1
    row = _row(capsys.readouterr().out, "rules_asked")
    assert "REFUSE" in row
    assert "went to zero" in row


def test_zero_on_both_sides_never_passes(tmp_path, capsys):
    assert _run(tmp_path, _paper(rules=0), _paper(rules=0, runs=NEW_RUNS)) == 1
    assert "0 on both sides" in _row(capsys.readouterr().out, "rules_asked")


def test_a_missing_metric_refuses_as_not_measured(tmp_path, capsys):
    rehearsal = _paper(runs=NEW_RUNS)
    del rehearsal["comments"]
    assert _run(tmp_path, _paper(), rehearsal) == 1
    row = _row(capsys.readouterr().out, "comments")
    assert "NOT MEASURED" in row
    assert "REFUSE" in row


def test_missing_on_both_sides_never_passes(tmp_path, capsys):
    live, rehearsal = _paper(), _paper(runs=NEW_RUNS)
    live["points"] = rehearsal["points"] = None
    assert _run(tmp_path, live, rehearsal) == 1
    assert "could not be read on either side" in _row(capsys.readouterr().out, "points")


def test_a_paper_missing_from_the_rehearsal_refuses(tmp_path, capsys):
    argv = [
        "compare",
        "--live",
        _snap(tmp_path / "live.json", PUMP=_paper(), VALVE=_paper()),
        "--rehearsal",
        _snap(tmp_path / "reh.json", PUMP=_paper(runs=NEW_RUNS)),
        "--kww-live",
        _kww(tmp_path / "kl.json", PUMP=1, VALVE=1),
        "--kww-rehearsal",
        _kww(tmp_path / "kr.json", PUMP=1, VALVE=1),
    ]
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert any(
        line.startswith("VALVE") and "NOT MEASURED" in line for line in out.splitlines()
    )


def test_wrong_up_refuses(tmp_path, capsys):
    assert (
        _run(
            tmp_path, _paper(), _paper(runs=NEW_RUNS), wrong_live=9, wrong_rehearsal=10
        )
        == 1
    )
    row = _row(capsys.readouterr().out, "wrong")
    assert "WRONG went up" in row
    assert "REFUSE" in row


def test_wrong_without_tables_refuses_as_not_measured(tmp_path, capsys):
    argv = [
        "compare",
        "--live",
        _snap(tmp_path / "live.json", PUMP=_paper()),
        "--rehearsal",
        _snap(tmp_path / "reh.json", PUMP=_paper(runs=NEW_RUNS)),
    ]
    assert gate.main(argv) == 1
    assert "NOT MEASURED" in _row(capsys.readouterr().out, "wrong")


def test_wrong_is_read_from_kww_markdown_files(tmp_path, capsys):
    live_dir, reh_dir = tmp_path / "kl", tmp_path / "kr"
    live_dir.mkdir()
    reh_dir.mkdir()
    (live_dir / "PUMP-KWW.md").write_text(
        "# invented\n\nKEEP 3 / WEAK 4 / WRONG 2 of 9.\n", encoding="utf-8"
    )
    # the first totals line is this table's own; a second one (an earlier table quoted below it) is ignored
    (reh_dir / "PUMP-KWW.md").write_text(
        "KEEP 1 / WEAK 4 / WRONG 4 of 9\nbefore: KEEP 3 / WEAK 4 / WRONG 2\n",
        encoding="utf-8",
    )
    argv = [
        "compare",
        "--live",
        _snap(tmp_path / "live.json", PUMP=_paper()),
        "--rehearsal",
        _snap(tmp_path / "reh.json", PUMP=_paper(runs=NEW_RUNS)),
        "--kww-live",
        str(live_dir),
        "--kww-rehearsal",
        str(reh_dir),
    ]
    assert gate.main(argv) == 1
    row = _row(capsys.readouterr().out, "wrong")
    assert "WRONG went up" in row
    assert " 2 " in row
    assert " 4 " in row


def test_the_same_run_on_both_sides_refuses(tmp_path, capsys):
    # the copy was not re-reviewed: equal counts compare nothing
    assert _run(tmp_path, _paper(), _paper()) == 1
    assert "re-run the review on the copy" in _row(
        capsys.readouterr().out, "fresh_runs"
    )


def test_accept_turns_one_refusal_into_accepted_with_its_reason(tmp_path, capsys):
    accept = ["PUMP:comments:invented reason, merged duplicates on purpose"]
    assert (
        _run(tmp_path, _paper(), _paper(comments=10, runs=NEW_RUNS), accept=accept) == 0
    )
    out = capsys.readouterr().out
    row = _row(out, "comments")
    assert "ACCEPTED" in row
    assert "invented reason, merged duplicates on purpose" in row
    assert "1 accepted" in out


def test_accept_covers_only_the_named_metric(tmp_path, capsys):
    accept = ["PUMP:comments:invented reason"]
    assert (
        _run(
            tmp_path,
            _paper(),
            _paper(rules=0, comments=10, runs=NEW_RUNS),
            accept=accept,
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "ACCEPTED" in _row(out, "comments")
    assert "REFUSE" in _row(out, "rules_asked")


@pytest.mark.parametrize(
    "bad", ["PUMP:comments:", "PUMP:comments", "PUMP:no_such_metric:why"]
)
def test_an_accept_without_a_reason_or_metric_refuses(tmp_path, capsys, bad):
    assert (
        _run(tmp_path, _paper(), _paper(comments=10, runs=NEW_RUNS), accept=[bad]) == 1
    )
    assert "REFUSED" in capsys.readouterr().out


class _FakeClient:
    """Answers the app's routes with invented counts; a rules-used `quote` stands for rule text that must not be kept."""

    def __init__(self, routes):
        self.routes = routes
        self.asked = []

    def get(self, path, params=None):
        self.asked.append(path)
        if path in self.routes:
            return self.routes[path], None
        return None, f"GET {path}: HTTP 404"


def test_snapshot_keeps_counts_and_reasons_only():
    routes = {
        "/api/reviews/papers/doc-x/points": {
            "runs": {"rule_check": "rc-1", "ai_review": "ai-1"},
            "points": [{"id": "p"}] * 3,
            "of": 3,
            "comment_count": 2,
            "found_during_review": 1,
            "counts": {
                "tiles": {
                    "not_met": {"total": 1},
                    "questions": {"total": 2},
                    "met": {"total": 0},
                }
            },
        },
        "/api/reviews/runs": {
            "runs": [
                {"review_run_id": "ai-1", "status": "completed", "created_at": "t"}
            ]
        },
        "/api/reviews/runs/rc-1": {
            "requirements_not_applied": [{"count": 4, "subject": "SECRET-SUBJECT"}]
        },
        "/api/reviews/runs/ai-1/rules-used": {
            "asked": [{"quote": "SECRET-RULE-TEXT"}] * 5,
            "left_out": [{"clause": "SECRET-CLAUSE"}] * 7,
            "left_out_counts": {"another equipment type": 7},
        },
        "/api/reviews/runs/ai-1/agent/summary": {
            "counts_by_class": {"Pass": 1},
            "stop_reason": None,
            "not_reviewed": 0,
        },
        "/api/reviews/papers/doc-x/crs/check": {
            "team": {"ok": True, "page": 3, "rows_in_file": 3, "missing": []}
        },
    }
    paper = gate.snapshot_paper(_FakeClient(routes), "doc-x")
    assert paper["rules_asked"] == 5
    assert paper["comments"] == 2
    assert paper["points"] == 3
    assert paper["rules_left_out"]["total"] == 7
    assert paper["rules_left_out"]["by_reason"] == {"another equipment type": 7}
    assert paper["requirements_not_applied"] == {"rule_check": 4, "ai_review": None}
    assert paper["points_per_tile"]["questions"] == 2
    assert paper["points_per_tile"]["does_not_apply"] is None
    assert paper["crs_check"]["team"]["rows_in_file"] == 3
    assert "SECRET" not in json.dumps(paper)
    assert paper["errors"] == ["GET /api/reviews/runs/ai-1: HTTP 404"]


def test_snapshot_of_an_unreadable_paper_is_null_never_zero():
    paper = gate.snapshot_paper(_FakeClient({}), "doc-y")
    assert paper["points"] is None
    assert paper["comments"] is None
    assert paper["rules_asked"] is None
    assert paper["errors"]


@pytest.mark.parametrize(
    "url", ["http://example.com:8000", "https://10.0.0.5:8000", "ftp://127.0.0.1"]
)
def test_the_token_goes_only_to_this_machine(url):
    with pytest.raises(ValueError, match="this machine"):
        gate.Client(url, "invented-token")


def test_papers_take_a_label_or_a_bare_id():
    assert gate.parse_papers(["PUMP=doc-1", "doc-2"]) == {
        "PUMP": "doc-1",
        "doc-2": "doc-2",
    }
    with pytest.raises(ValueError):
        gate.parse_papers(["PUMP=doc-1", "PUMP=doc-3"])
