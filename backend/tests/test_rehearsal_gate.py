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
        # these tests measure one paper's rows; the valve-and-pump requirement (review S3) has its own tests below
        "--require",
        "PUMP",
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
        # these tests measure one paper's rows; the valve-and-pump requirement (review S3) has its own tests below
        "--require",
        "PUMP",
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
        # these tests measure one paper's rows; the valve-and-pump requirement (review S3) has its own tests below
        "--require",
        "PUMP",
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
        # these tests measure one paper's rows; the valve-and-pump requirement (review S3) has its own tests below
        "--require",
        "PUMP",
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
    # the history route (general review, 18 Nov) does not exist on an app before that update: its 404 is kept, never hidden
    assert paper["errors"] == [
        "GET /api/reviews/runs/ai-1: HTTP 404",
        "GET /api/reviews/papers/doc-x/history: HTTP 404",
    ]
    assert paper["history"] is None


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


# ------------------------------------------------------------------ history (check 5 of the general-review update)


def _old(
    rules=100,
    comments=40,
    points=200,
    runs=("rc-old-1", "ai-old-1"),
    crs=None,
    history="listed",
):
    paper = _paper(rules, comments, points, runs)
    paper["crs_check"] = crs or {
        "team": {"ok": True, "page": points, "rows_in_file": points},
        "contractor": {"ok": True, "page": points, "rows_in_file": 0},
    }
    if history == "listed":
        paper["history"] = [
            {
                "run_id": r,
                "version": "earlier version",
                "part": "rule check",
                "points": points,
            }
            for r in runs
        ]
    else:
        paper["history"] = history
    return paper


def _history(tmp_path, live, rehearsal, accept=()):
    argv = [
        "history",
        "--live",
        # the live gate needs the valve and the pump on both sides (review round 1, N3): an unchanged valve rides along
        _snap(tmp_path / "live.json", PUMP=live, VALVE=_old(runs=("rc-v", "ai-v"))),
        "--rehearsal",
        _snap(tmp_path / "reh.json", PUMP=rehearsal, VALVE=_old(runs=("rc-v", "ai-v"))),
    ]
    for a in accept:
        argv += ["--accept", a]
    return gate.main(argv)


def test_history_passes_when_every_old_review_is_unchanged(tmp_path, capsys):
    assert _history(tmp_path, _old(history=None), _old()) == 0
    assert "HISTORY: PASS" in capsys.readouterr().out


@pytest.mark.parametrize("metric", ["rules", "comments", "points"])
def test_history_refuses_a_count_that_differs_by_one(tmp_path, capsys, metric):
    changed = {
        "rules": (101, 40, 200),
        "comments": (100, 39, 200),
        "points": (100, 40, 201),
    }[metric]
    assert _history(tmp_path, _old(), _old(*changed)) == 1
    assert "changed:" in capsys.readouterr().out


def test_history_refuses_a_crs_file_with_one_row_less(tmp_path, capsys):
    crs = {
        "team": {"page": 200, "rows_in_file": 199},
        "contractor": {"page": 200, "rows_in_file": 0},
    }
    assert _history(tmp_path, _old(), _old(crs=crs)) == 1
    assert "team rows_in_file 200 -> 199" in capsys.readouterr().out


def test_history_refuses_a_re_reviewed_paper(tmp_path, capsys):
    assert _history(tmp_path, _old(), _old(runs=("rc-new-1", "ai-old-1"))) == 1
    assert "another run for rule_check" in capsys.readouterr().out


@pytest.mark.parametrize(
    "history,words",
    [
        (None, "history route could not be read"),
        (
            [{"run_id": "rc-old-1", "version": "earlier version"}],
            "ai_review not listed",
        ),
        (
            [
                {"run_id": "rc-old-1", "version": "general"},
                {"run_id": "ai-old-1", "version": "earlier version"},
            ],
            "rule_check listed as 'general'",
        ),
    ],
)
def test_history_refuses_an_old_run_not_listed_as_earlier_version(
    tmp_path, capsys, history, words
):
    assert _history(tmp_path, _old(), _old(history=history)) == 1
    assert words in capsys.readouterr().out


def test_history_zero_on_both_sides_and_missing_are_not_a_pass(tmp_path, capsys):
    assert _history(tmp_path, _old(rules=0), _old(rules=0)) == 1
    assert "0 on both sides" in capsys.readouterr().out
    assert _history(tmp_path, _old(rules=None), _old(rules=None)) == 1
    assert "NOT MEASURED" in capsys.readouterr().out


def test_history_accept_names_one_row_with_its_reason(tmp_path, capsys):
    rc = _history(
        tmp_path,
        _old(rules=0),
        _old(rules=0),
        accept=("PUMP:rules_asked:a general review asks no rules",),
    )
    out = capsys.readouterr().out
    assert rc == 0 and "ACCEPTED" in out and "asks no rules" in out


def test_snapshot_keeps_the_history_routes_ids_and_words_only():
    routes = {
        "/api/reviews/papers/doc-h/history": {
            "runs": [
                {
                    "run_id": "rc-9",
                    "version": "earlier version",
                    "part": "rule check",
                    "status": "completed",
                    "points": 12,
                    "files": [{"label": "SECRET-FILE-NAME", "url": "/x"}],
                }
            ]
        }
    }
    paper = gate.snapshot_paper(_FakeClient(routes), "doc-h")
    assert paper["history"] == [
        {
            "run_id": "rc-9",
            "version": "earlier version",
            "part": "rule check",
            "status": "completed",
            "points": 12,
            "files": 1,
        }
    ]
    assert "SECRET" not in json.dumps(paper)


# ------------------------------------------------------------------ the live gate's guards (review round 1, N1 to N3)


def test_n3_the_gate_refuses_without_the_valve_or_the_pump(tmp_path, capsys):
    argv = [
        "history",
        "--live",
        _snap(tmp_path / "l.json", PUMP=_old()),
        "--rehearsal",
        _snap(tmp_path / "r.json", PUMP=_old()),
    ]
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert (
        "VALVE is not in the live snapshot" in out
        and "VALVE is not in the rehearsal snapshot" in out
    )


def test_n2_a_not_measured_row_is_accepted_only_when_the_reason_names_it(
    tmp_path, capsys
):
    assert (
        _history(
            tmp_path,
            _old(rules=None),
            _old(rules=None),
            accept=("PUMP:rules_asked:asks no rules by design",),
        )
        == 1
    )
    assert "accept refused: a NOT MEASURED row" in capsys.readouterr().out
    rc = _history(
        tmp_path,
        _old(rules=None),
        _old(rules=None),
        accept=(
            "PUMP:rules_asked:NOT MEASURED on both sides because the route fails on the old code",
        ),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert (
        "ACCEPTED: PUMP rules_asked: NOT MEASURED: could not be read on either side; accepted: NOT MEASURED on both"
        in out
    )


def test_n2_every_accepted_row_is_printed_with_its_reason(tmp_path, capsys):
    assert (
        _history(
            tmp_path,
            _old(rules=0),
            _old(rules=0),
            accept=("PUMP:rules_asked:invented reason one",),
        )
        == 0
    )
    assert "ACCEPTED: PUMP rules_asked: 0 on both sides" in capsys.readouterr().out


def _bound(path, papers, commit, hours_ago=0.0):
    from datetime import UTC, datetime, timedelta

    taken = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(
        timespec="seconds"
    )
    path.write_text(
        json.dumps(
            {
                "schema": gate.SCHEMA,
                "commit": commit,
                "taken_at": taken,
                "papers": papers,
            }
        )
    )
    return str(path)


@pytest.mark.parametrize(
    "case,words",
    [
        ("old", "the live snapshot is 3.0 h old (limit 2 h)"),
        (
            "wrong live commit",
            "the live snapshot was taken on aaaaaaaa, expected cccccccc",
        ),
        (
            "wrong rehearsal commit",
            "the rehearsal snapshot was taken on aaaaaaaa, expected bbbbbbbb",
        ),
        ("no commit", "the live snapshot names no commit"),
    ],
)
def test_n1_a_stale_or_unbound_snapshot_is_refused(tmp_path, capsys, case, words):
    papers = {"PUMP": _old(), "VALVE": _old(runs=("rc-v", "ai-v"))}
    live_commit = {"wrong live commit": "a" * 40, "no commit": None}.get(case, "c" * 40)
    reh_commit = "a" * 40 if case == "wrong rehearsal commit" else "b" * 40
    argv = [
        "history",
        "--live",
        _bound(tmp_path / "l.json", papers, live_commit, 3.0 if case == "old" else 0.1),
        "--rehearsal",
        _bound(tmp_path / "r.json", papers, reh_commit),
        "--live-commit",
        "c" * 40,
        "--rehearsal-commit",
        "b" * 40,
        "--max-age-hours",
        "2",
    ]
    assert gate.main(argv) == 1
    assert words in capsys.readouterr().out


def test_n1_a_fresh_bound_snapshot_passes(tmp_path, capsys):
    papers = {"PUMP": _old(), "VALVE": _old(runs=("rc-v", "ai-v"))}
    argv = [
        "history",
        "--live",
        _bound(tmp_path / "l.json", papers, "c" * 40, 0.5),
        "--rehearsal",
        _bound(tmp_path / "r.json", papers, "b" * 40),
        "--live-commit",
        "c" * 40,
        "--rehearsal-commit",
        "b" * 40,
        "--max-age-hours",
        "2",
    ]
    assert gate.main(argv) == 0, capsys.readouterr().out


def test_n1_snapshot_records_the_commit_of_a_checkout(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stdout = 0, "d" * 40 + "\n"

    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done())
    monkeypatch.setattr(gate, "Client", lambda base, tok: _FakeClient({}))
    tok = tmp_path / "t"
    tok.write_text("invented-test-token")
    out = tmp_path / "s.json"
    assert (
        gate.main(
            [
                "snapshot",
                "--base-url",
                "http://127.0.0.1:1",
                "--token-file",
                str(tok),
                "--papers",
                "PUMP=doc-x",
                "--out",
                str(out),
                "--commit-of",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert json.loads(out.read_text())["commit"] == "d" * 40
    assert calls == [["git", "-C", str(tmp_path), "rev-parse", "HEAD"]]


# ------------------------------------------------------------------ S3: compare carries the same guards as history


def test_s3_compare_needs_the_valve_and_the_pump(tmp_path, capsys):
    argv = [
        "compare",
        "--live",
        _snap(tmp_path / "l.json", PUMP=_paper()),
        "--rehearsal",
        _snap(tmp_path / "r.json", PUMP=_paper(runs=NEW_RUNS)),
        "--kww-live",
        _kww(tmp_path / "kl.json", PUMP=1),
        "--kww-rehearsal",
        _kww(tmp_path / "kr.json", PUMP=1),
    ]
    assert gate.main(argv) == 1
    assert "VALVE is not in the live snapshot" in capsys.readouterr().out


def test_s3_compare_checks_commit_and_age(tmp_path, capsys):
    papers_live = {"PUMP": _paper(), "VALVE": _paper(runs=("rc-v", "ai-v"))}
    papers_reh = {
        "PUMP": _paper(runs=NEW_RUNS),
        "VALVE": _paper(runs=("rc-v2", "ai-v2")),
    }
    argv = [
        "compare",
        "--live",
        _bound(tmp_path / "l.json", papers_live, "c" * 40, 3.0),
        "--rehearsal",
        _bound(tmp_path / "r.json", papers_reh, "a" * 40),
        "--kww-live",
        _kww(tmp_path / "kl.json", PUMP=1, VALVE=1),
        "--kww-rehearsal",
        _kww(tmp_path / "kr.json", PUMP=1, VALVE=1),
        "--live-commit",
        "c" * 40,
        "--rehearsal-commit",
        "b" * 40,
        "--max-age-hours",
        "2",
    ]
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert (
        "the live snapshot is 3.0 h old" in out
        and "taken on aaaaaaaa, expected bbbbbbbb" in out
    )


def test_s3_require_with_no_value_is_an_error(tmp_path):
    with pytest.raises(SystemExit):
        gate.main(["history", "--live", "x", "--rehearsal", "y", "--require"])


@pytest.mark.parametrize("with_age_limit", [True, False])
def test_s3_a_snapshot_dated_in_the_future_is_refused(tmp_path, capsys, with_age_limit):
    papers = {"PUMP": _old(), "VALVE": _old(runs=("rc-v", "ai-v"))}
    argv = [
        "history",
        "--live",
        _bound(tmp_path / "l.json", papers, "c" * 40, -3.0),
        "--rehearsal",
        _bound(tmp_path / "r.json", papers, "b" * 40),
    ]
    if with_age_limit:
        argv += ["--max-age-hours", "2"]
    assert gate.main(argv) == 1
    assert "the live snapshot's time is 3.0 h in the future" in capsys.readouterr().out
