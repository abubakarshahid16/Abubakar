"""Order 216 item 3: the `state:approved` label rule (scripts/auto_label.py).

Pure decisions plus a fake GitHub API; no network, no token, no model.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "auto_label", REPO / "scripts" / "auto_label.py"
)
al = importlib.util.module_from_spec(spec)
sys.modules["auto_label"] = al
spec.loader.exec_module(al)

HEAD = "42baceb9d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6"
OLD = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432"
GREEN = [
    {"status": "completed", "conclusion": "success"},
    {"status": "completed", "conclusion": "skipped"},
]


def comment(body, assoc="OWNER", kind="User"):
    return {"body": body, "author_association": assoc, "user": {"type": kind}}


def decide(comments, runs=GREEN, labelled=False, event="issue_comment", head=HEAD):
    return al.decide(
        event=event,
        head_sha=head,
        comments=comments,
        check_runs=runs,
        labelled=labelled,
    )


def test_green_and_approved_at_the_current_head_adds_the_label():
    assert (
        decide([comment("code approved at 42baceb9, nothing more from you")]) == "add"
    )


def test_an_approval_of_an_older_head_does_not_count():
    assert decide([comment(f"approved at {OLD[:8]}")]) == "keep"
    assert decide([comment("approved")]) == "keep"  # no sha at all


@pytest.mark.parametrize(
    "text",
    [
        "NOT approved at 42baceb9",
        "unapproved 42baceb9",
        "approved? no: changes requested 42baceb9",
        "approval withheld at 42baceb9",
        "not-approved 42baceb9",
        "42baceb9 is fine",
    ],
)
def test_a_negated_or_missing_approval_never_counts(text):
    assert decide([comment(text)]) == "keep"


def test_a_short_sha_is_not_enough():
    assert decide([comment("approved at 42bace")]) == "keep"


def test_only_a_trusted_human_comment_counts():
    assert decide([comment("approved at 42baceb9", assoc="NONE")]) == "keep"
    assert decide([comment("approved at 42baceb9", assoc="CONTRIBUTOR")]) == "keep"
    assert decide([comment("approved at 42baceb9", kind="Bot")]) == "keep"


@pytest.mark.parametrize(
    "runs, state",
    [
        (GREEN, "green"),
        ([*GREEN, {"status": "in_progress", "conclusion": None}], "pending"),
        ([*GREEN, {"status": "completed", "conclusion": "failure"}], "red"),
        (
            [{"status": "completed", "conclusion": "skipped"}],
            "pending",
        ),  # nothing real ran
        ([], "pending"),
        ([{"status": "completed", "conclusion": "cancelled"}], "red"),
    ],
)
def test_the_state_of_the_checks(runs, state):
    assert al.checks_state(runs) == state


def test_approved_but_not_green_gets_no_label():
    pending = [*GREEN, {"status": "in_progress", "conclusion": None}]
    red = [*GREEN, {"status": "completed", "conclusion": "failure"}]
    assert decide([comment("approved at 42baceb9")], runs=pending) == "keep"
    assert decide([comment("approved at 42baceb9")], runs=red) == "keep"


def test_the_label_comes_off_on_a_new_head_and_when_a_check_fails():
    assert decide([], event="pull_request_target", labelled=True) == "remove"
    assert decide([], event="pull_request_target", labelled=False) == "keep"
    red = [*GREEN, {"status": "completed", "conclusion": "failure"}]
    assert (
        decide([comment("approved at 42baceb9")], runs=red, labelled=True) == "remove"
    )
    pending = [*GREEN, {"status": "in_progress", "conclusion": None}]
    assert (
        decide([comment("approved at 42baceb9")], runs=pending, labelled=True) == "keep"
    )


def test_which_pull_requests_an_event_names():
    assert al.pr_numbers(
        "issue_comment", {"issue": {"number": 5, "pull_request": {}}}
    ) == [5]
    assert (
        al.pr_numbers("issue_comment", {"issue": {"number": 5}}) == []
    )  # a plain issue
    assert al.pr_numbers("pull_request_target", {"pull_request": {"number": 7}}) == [7]
    assert al.pr_numbers(
        "workflow_run", {"workflow_run": {"pull_requests": [{"number": 9}, {}]}}
    ) == [9]
    assert al.pr_numbers("push", {}) == []


class FakeApi:
    def __init__(self, labelled=False, state="open"):
        self.pr = {
            "state": state,
            "head": {"sha": HEAD},
            "labels": [{"name": al.LABEL}] if labelled else [],
        }
        self.calls = []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.pr if (method == "GET" and path.startswith("/pulls/")) else None

    def pages(self, path, key=None):
        if path.endswith("/comments"):
            return [comment("approved at 42baceb9")]
        return GREEN


def test_run_adds_the_label_and_only_the_label():
    api = FakeApi()
    out = al.run(api, "issue_comment", {"issue": {"number": 3, "pull_request": {}}})
    assert out == ["#3: add"]
    writes = [c for c in api.calls if c[0] != "GET"]
    assert writes == [
        ("POST", "/issues/3/labels", {"labels": [al.LABEL]})
    ]  # never a merge, a push or a comment


def test_run_removes_it_on_a_new_head_and_skips_a_closed_pull_request():
    api = FakeApi(labelled=True)
    assert al.run(api, "pull_request_target", {"pull_request": {"number": 3}}) == [
        "#3: remove"
    ]
    assert [c[0] for c in api.calls if c[0] != "GET"] == ["DELETE"]
    closed = FakeApi(state="closed")
    assert (
        al.run(closed, "issue_comment", {"issue": {"number": 3, "pull_request": {}}})
        == []
    )


def test_the_workflow_can_only_write_labels():
    text = (REPO / ".github" / "workflows" / "auto-label.yml").read_text()
    permissions = [
        line.strip()
        for line in text.splitlines()
        if line.startswith("  ") and ": " in line
    ][:8]
    assert "contents: read" in permissions and "contents: write" not in permissions
    assert "pull_request_target" in text
    assert "github.event.comment.body" not in text  # comment text never reaches a shell
