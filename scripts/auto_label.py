"""Order 216 item 3: put the `state:approved` label on a pull request by rule,
so an approved-and-green PR no longer waits for a person to click.

The label goes ON when BOTH hold for the PR's CURRENT head:
  (a) every one of REQUIRED_CHECKS is present on the head and green (a check not
      yet created counts as pending, so a PR cannot be labelled before its tests
      have started; skipped and neutral runs are ignored), and
  (b) the NEWEST comment from the owner, a member or a collaborator that
      approves or withdraws this head approves it, in the one form
      "approved at <first 8 or more characters of the head sha>". A hedge or
      negation in that sentence ("not yet", "will be", "once", "cannot", "was
      ... earlier", "unapproved", "changes requested") means it is not an
      approval, and a later comment that names the head and refuses or hedges
      cancels an earlier approval. A comment on an older head names an older sha.
It comes OFF the moment a new head is pushed, or a check on the head fails.

LABELS ONLY. This never merges, never pushes, never edits a comment, and the
workflow that runs it has no `contents: write`. It never checks out or runs
code from the pull request (`pull_request_target` runs the base branch), and
it reads comment text only through a regular expression: nothing from a
comment reaches a shell.

LIMIT, stated plainly: every session posts as the owner's account, so (b)
cannot tell a reviewer from the author: the PR's own author could post "approved at
<sha>" once the checks are green. Only a reviewer's comment should say it; s2's
proof before release is unchanged. The rule still gives what it can: the
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
#: The checks every pull request here always shows. "Green" needs EVERY one present
#: and successful, because a small workflow (gitleaks) finishes in seconds while the
#: tests have not even created their jobs. A renamed check stops the label until this
#: list is updated: that is the safe direction.
REQUIRED_CHECKS = (
    "backend (pytest)",
    "backend lint, anchors and benchmarks",
    "backend shard 1/3",
    "backend shard 2/3",
    "backend shard 3/3",
    "does the app start?",
    "frontend (vitest + tsc)",
    "accessibility (axe serious/critical gate)",
    "gitleaks",
    "no-client-data guard",
    "dependency audit (python)",
    "dependency audit (frontend)",
)
#: The ONLY form that approves: "approved at <sha>" (or "on"), the sha being the head's.
_APPROVAL = re.compile(
    rf"\bapproved\s+(?:at|on)\s+`?([0-9a-f]{{{MIN_SHA},40}})\b", re.IGNORECASE
)
#: Words that make a sentence about approval a hedge, a refusal or a withdrawal.
_HEDGE = re.compile(
    r"\b(not|never|yet|cannot|can'?t|won'?t|wouldn'?t|would|will|once|if|until|unless|isn'?t|wasn'?t|"
    r"withheld|revoked|withdrawn|pending|wait|earlier|older|previous|changes\s+requested|"
    r"request(?:ed)?\s+changes)\b|\b(?:un|dis)[\s-]*approved\b",
    re.IGNORECASE,
)
_SHA = re.compile(rf"\b[0-9a-f]{{{MIN_SHA},40}}\b", re.IGNORECASE)
_SENTENCE = re.compile(r"[.;!?\n]+")


def _names_head(text: str, head_sha: str) -> bool:
    return any(
        head_sha.lower().startswith(token.lower()) for token in _SHA.findall(text)
    )


def approves(body: str, head_sha: str) -> bool:
    """Does this comment approve exactly this head? Only "approved at <sha>" does,
    with that sha the head's, in a sentence that holds no hedge or negation."""
    head = head_sha.lower()
    for sentence in _SENTENCE.split(body or ""):
        found = _APPROVAL.search(sentence)
        if (
            found
            and head.startswith(found.group(1).lower())
            and not _HEDGE.search(sentence)
        ):
            return True
    return False


def withdraws(body: str, head_sha: str) -> bool:
    """A comment that names this head and refuses, hedges on or withdraws approval."""
    text = body or ""
    return (
        _names_head(text, head_sha)
        and bool(_HEDGE.search(text))
        and not approves(text, head_sha)
    )


def checks_state(check_runs: list[dict]) -> str:
    """'green', 'red' or 'pending' for the runs on one head."""
    real = [
        run for run in check_runs if run.get("conclusion") not in IGNORED_CONCLUSIONS
    ]
    if any(run.get("conclusion") in BAD_CONCLUSIONS for run in real):
        return "red"
    by_name = {run.get("name"): run for run in real}
    for name in REQUIRED_CHECKS:
        run = by_name.get(name)
        if run is None or run.get("status") != "completed":
            return "pending"
    if any(run.get("status") != "completed" for run in real):
        return "pending"
    return "green" if all(run.get("conclusion") == "success" for run in real) else "red"


def approved_now(comments: list[dict], head_sha: str) -> bool:
    """The newest trusted human comment that approves or withdraws THIS head decides."""
    for c in reversed(comments):  # the API lists comments oldest first
        if (
            c.get("author_association") not in TRUSTED
            or (c.get("user") or {}).get("type") == "Bot"
        ):
            continue
        body = c.get("body") or ""
        if approves(body, head_sha):
            return True
        if withdraws(body, head_sha):
            return False
    return False


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
    if state == "green" and approved_now(comments, head_sha):
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
