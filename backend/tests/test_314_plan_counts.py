"""Order 314.2: the board's Plan tab is counted from GitHub, never by hand (invented issues, no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import board_plan_counts as bpc

NOW = datetime(2026, 10, 29, 1, 0, tzinfo=UTC)


def _issue(n, state="open", reason=None, pr=False, title="a task"):
    item = {"number": n, "state": state, "state_reason": reason, "title": title}
    if pr:
        item["pull_request"] = {"url": "x"}
    return item


def test_a_closed_issue_is_done_an_open_one_is_open_and_the_share_has_its_denominator():
    c = bpc.count_stage(
        [_issue(1, "closed", "completed"), _issue(2), _issue(3), _issue(4, "closed")]
    )
    assert (c["done"], c["open"], c["total"], c["share"]) == (2, 2, 4, "2 of 4")


def test_an_issue_closed_as_not_planned_is_neither_done_nor_open():
    c = bpc.count_stage(
        [
            _issue(1, "closed", "not_planned"),
            _issue(2, "closed", "completed"),
            _issue(3),
        ]
    )
    assert (c["done"], c["open"], c["not_planned"], c["total"]) == (1, 1, 1, 2)


def test_a_stage_with_no_issues_has_no_share_not_zero_percent():
    assert bpc.count_stage([])["share"] is None


def test_the_overall_count_adds_the_stages_and_names_the_time_and_the_boundary():
    per = {
        stage: [_issue(i, "closed", "completed"), _issue(100 + i)]
        for i, (stage, _n) in enumerate(bpc.STAGES)
    }
    got = bpc.build(per, "o/r", NOW)
    assert (
        got["overall"]["share"] == "9 of 18" and got["overall"]["stages_unread"] == []
    )
    assert got["counted_at"] == "2026-10-29T01:00:00+00:00"
    assert "not 'proven'" in got["boundary"] and "o/r" in got["source"]
    assert [s["stage"] for s in got["stages"]] == [
        "S",
        "A",
        "B",
        "C",
        "D",
        "C2",
        "E",
        "F",
        "G",
    ]
    assert got["stages"][0]["milestone"] == "https://github.com/o/r/milestone/45"


def test_a_stage_that_could_not_be_read_is_unread_never_zero():
    per = {stage: [_issue(1, "closed", "completed")] for stage, _n in bpc.STAGES}
    per["C"] = None
    got = bpc.build(per, "o/r", NOW)
    assert got["overall"]["stages_unread"] == ["C"] and got["overall"]["total"] == 8
    stage_c = next(s for s in got["stages"] if s["stage"] == "C")
    assert stage_c == {
        "stage": "C",
        "milestone": "https://github.com/o/r/milestone/48",
        "unread": True,
    }


def _runner(pages_by_milestone):
    def run(args):
        url = args[-1]
        number = int(url.split("milestone=")[1].split("&")[0])
        pages = pages_by_milestone.get(number)
        if pages is None:
            raise subprocess.CalledProcessError(1, "gh")
        return "\n".join(
            json.dumps(p) for p in pages
        )  # gh --paginate prints one array per page

    return run


def test_fetch_joins_the_pages_and_leaves_out_pull_requests():
    run = _runner(
        {45: [[_issue(1), _issue(2, pr=True)], [_issue(3, "closed", "completed")]]}
    )
    got = bpc.fetch_issues("o/r", 45, run)
    assert [i["number"] for i in got] == [1, 3]


def test_a_failing_stage_is_listed_unread_and_the_command_says_so(tmp_path, capsys):
    pages = {n: [[_issue(n * 10, "closed", "completed")]] for _s, n in bpc.STAGES}
    del pages[50]
    code = bpc.main(["--out", str(tmp_path / "plan")], _runner(pages))
    printed = json.loads(capsys.readouterr().out)
    assert code == 3 and printed["overall"]["stages_unread"] == ["C2"]
    assert printed["overall"]["share"] == "8 of 8"


def test_the_file_is_replaced_on_every_refresh_and_holds_no_titles(tmp_path, capsys):
    pages = {n: [[_issue(n, title="SECRET TITLE")]] for _s, n in bpc.STAGES}
    out = tmp_path / "plan"
    assert bpc.main(["--out", str(out)], _runner(pages)) == 0
    first = (out / "plan.js").read_text()
    pages2 = {
        n: [[_issue(n, "closed", "completed", title="SECRET TITLE")]]
        for _s, n in bpc.STAGES
    }
    assert bpc.main(["--out", str(out)], _runner(pages2)) == 0
    second = (out / "plan.js").read_text()
    assert first != second and "0 of 9" in first and "9 of 9" in second
    assert "SECRET" not in first + second + capsys.readouterr().out
    assert not list(out.glob("*.tmp"))
