"""Order 216 item 3: put the `state:approved` label on a pull request by rule,
so an approved-and-green PR no longer waits for a person to click.

The label goes ON when BOTH hold for the PR's CURRENT head:
  (a) every check run on the head has finished green (skipped and neutral runs
      do not count; at least one real run must have passed), and
  (b) a comment from the repository's owner, a member or a collaborator says
      "approved" and names that exact head, by at least the first 8 characters
      of its sha ("approved at 42baceb9"). A comment that negates it ("not
      approved", "unapproved", "changes requested", "approval withheld") never
      counts, and a comment on an older head names an older sha.
It comes OFF the moment a new head is pushed, or a check on the head fails.

LABELS ONLY. This never merges, never pushes, never edits a comment, and the
workflow that runs it has no `contents: write`. It never checks out or runs
code from the pull request (`pull_request_target` runs the base branch), and
it reads comment text only through a regular expression: nothing from a
comment reaches a shell.

LIMIT, stated plainly: every session posts as the owner's account, so (b)
cannot tell a reviewer from the author. The rule still gives what it can: the
sha in the comment must be the current head, so an approval can never carry
over a later push.

    python scripts/auto_label.py        # in the workflow (needs GITHUB_TOKEN)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

LABEL = "state:approved"
MIN_SHA = 8
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
BAD_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}
IGNORED_CONCLUSIONS = {"skipped", "neutral"}
_APPROVED = re.compile(r"\bapproved\b", re.IGNORECASE)
_NEGATED = re.compile(
    r"\b(not|never|un|dis|isn'?t|wasn'?t)[\s-]*approved\b|\bapproval\s+(withheld|revoked|withdrawn)\b"
    r"|\bchanges\s+requested\b|\brequest(ed)?\s+changes\b",
    re.IGNORECASE,
)
_SHA = re.compile(rf"\b[0-9a-f]{{{MIN_SHA},40}}\b", re.IGNORECASE)


def approves(body: str, head_sha: str) -> bool:
    """Does this comment approve exactly this head?"""
    text = body or ""
    if not _APPROVED.search(text) or _NEGATED.search(text):
        return False
    head = head_sha.lower()
    return any(head.startswith(token.lower()) for token in _SHA.findall(text))


def checks_state(check_runs: list[dict]) -> str:
    """'green', 'red' or 'pending' for the runs on one head."""
    real = [
        run for run in check_runs if run.get("conclusion") not in IGNORED_CONCLUSIONS
    ]
    if any(run.get("conclusion") in BAD_CONCLUSIONS for run in real):
        return "red"
    if not real or any(run.get("status") != "completed" for run in real):
        return "pending"
    return "green" if all(run.get("conclusion") == "success" for run in real) else "red"


def decide(
    *,
    event: str,
    head_sha: str,
    comments: list[dict],
    check_runs: list[dict],
    labelled: bool,
) -> str:
    """'add', 'remove' or 'keep'."""
    if (
        event == "pull_request_target"
    ):  # a new head was pushed: the old approval is void
        return "remove" if labelled else "keep"
    state = checks_state(check_runs)
    approved = any(
        c.get("author_association") in TRUSTED
        and (c.get("user") or {}).get("type") != "Bot"
        and approves(c.get("body") or "", head_sha)
        for c in comments
    )
    if state == "green" and approved:
        return "keep" if labelled else "add"
    if labelled and state == "red":
        return "remove"
    return "keep"


def pr_numbers(event: str, payload: dict) -> list[int]:
    if event == "issue_comment":
        issue = payload.get("issue") or {}
        return (
            [issue["number"]] if "pull_request" in issue and issue.get("number") else []
        )
    if event == "pull_request_target":
        number = (payload.get("pull_request") or {}).get("number")
        return [number] if number else []
    if event == "workflow_run":
        return [
            p["number"]
            for p in (payload.get("workflow_run") or {}).get("pull_requests") or []
            if p.get("number")
        ]
    return []


class Api:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None):
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "DELETE":
                return None
            raise
        return json.loads(raw) if raw else None

    def pages(self, path: str, key: str | None = None) -> list[dict]:
        found, page = [], 1
        while page <= 10:
            data = self.call(
                "GET", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}"
            )
            items = data.get(key, []) if key else data
            found += items
            if len(items) < 100:
                break
            page += 1
        return found


def run(api, event: str, payload: dict) -> list[str]:
    done = []
    for number in pr_numbers(event, payload):
        pr = api.call("GET", f"/pulls/{number}")
        if pr.get("state") != "open":
            continue
        head = pr["head"]["sha"]
        labelled = any(label["name"] == LABEL for label in pr.get("labels", []))
        action = decide(
            event=event,
            head_sha=head,
            comments=api.pages(f"/issues/{number}/comments"),
            check_runs=api.pages(f"/commits/{head}/check-runs", key="check_runs"),
            labelled=labelled,
        )
        if action == "add":
            api.call("POST", f"/issues/{number}/labels", {"labels": [LABEL]})
        elif action == "remove":
            api.call("DELETE", f"/issues/{number}/labels/{LABEL.replace(':', '%3A')}")
        done.append(f"#{number}: {action}")
    return done


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    payload = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    api = Api(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    for line in run(api, event, payload) or ["no pull request in this event"]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
