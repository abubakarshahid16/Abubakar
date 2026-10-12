"""Chat benchmark kit (owner order 2026-09-26, chat redesign PR 7).

Runs the owner's benchmark questions through THIS system's chat, on the
laptop, against the running backend, and writes a report with a column for
each comparison (ChatGPT, Claude.ai) for the owner to paste and score.

WHY IT RUNS ON THE LAPTOP AND NOWHERE ELSE. The questions are about the
client's documents and the answers quote them, so both are client material.
The question file and the report live in `.cowork/`, which git ignores by
default (`.gitignore`, DEFAULT-DENY); this script refuses to read or write
anywhere else, and refuses to start if git would track the report. The cloud
build never sees either file.

WHAT IT MEASURES AND WHAT IT DOES NOT. For each question it records what the
chat actually did: the kind of answer, the used-line, how many points were
found on the page, the sources, the time and the Claude cost. It does NOT
score correctness - that is the owner's judgement against the documents, and
the report leaves the score columns empty rather than guessing them.

    python scripts/chat_benchmark.py --email you@example.com
    python scripts/chat_benchmark.py --no-auth          # AUTH_MODE=disabled

Question file, `.cowork/chat-benchmark-questions.txt`: one question per line,
optionally `category | question`; blank lines and `#` comments are skipped.
The password is asked for and held in memory only; the token is never
printed, logged or written.
"""
from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COWORK = REPO / ".cowork"
QUESTIONS = COWORK / "chat-benchmark-questions.txt"
REPORT = COWORK / "CHAT-BENCHMARK-2026-09.md"

#: What the owner scores, per system, per question. Blank until scored.
RUBRIC = (
    ("Correct", "0-2", "the answer is right about the documents or the engineering"),
    ("Grounded", "0-2", "every claim about the documents is on the page it names"),
    ("Cites the page", "0-1", "a reader can open the page the answer stood on"),
    ("Honest about limits", "0-1", "says 'not in the documents' / 'needs an engineer' when it should"),
    ("Clear", "0-1", "an engineer can act on it without re-reading"),
)


class Refused(RuntimeError):
    pass


def inside_cowork(path: Path) -> Path:
    """The path, only if it is inside `.cowork/`."""
    resolved = path.resolve()
    if COWORK.resolve() not in resolved.parents:
        raise Refused(f"{path} is outside .cowork/; client questions and answers stay there")
    return resolved


def git_ignores(path: Path) -> bool:
    """True when git would NOT track this file."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=REPO, check=False)
    except OSError:
        return False
    return r.returncode == 0


def read_questions(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in inside_cowork(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        category, _, question = line.partition("|") if "|" in line else ("", "", line)
        out.append((category.strip() or "-", question.strip()))
    return out


class Api:
    def __init__(self, base: str, token: str | None):
        self.base = base.rstrip("/")
        self._token = token

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 600) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from None


def login(base: str, email: str) -> str:
    password = getpass.getpass(f"Password for {email}: ")
    return Api(base, None).call("POST", "/api/auth/login", {"email": email, "password": password})["token"]


def ask(api: Api, question: str, model: str) -> dict:
    conversation = api.call("POST", "/api/conversations", {})
    started = time.monotonic()
    result = api.call("POST", f"/api/conversations/{conversation['id']}/ask",
                      {"question": question, "tier": "generated", "model": model})
    result["_wall_seconds"] = round(time.monotonic() - started, 1)
    return result


def row_of(n: int, category: str, question: str, result: dict | None, error: str | None) -> dict:
    if result is None:
        return {"n": n, "category": category, "question": question, "error": error}
    v = result.get("verification") or None
    sources = result.get("sources") or []
    return {
        "n": n, "category": category, "question": question, "error": None,
        "kind": result.get("answer_kind") or result.get("answer_type"),
        "answer_type": result.get("answer_type"),
        "used_line": result.get("used_line") or "",
        "points": f"{v['verified']} of {v['total']}" if v else "",
        "sources": [f"{s.get('display_name')}" + (f" p.{s['page']}" if s.get("page") else "") for s in sources
                    if s.get("cited")],
        "seconds": result.get("_wall_seconds"),
        "cost": result.get("cost_usd"),
        "notices": result.get("notices") or [],
        "answer": result.get("answer") or result.get("reason") or "",
    }


def build_report(rows: list[dict], *, base: str, model: str, started: str) -> str:
    done = [r for r in rows if not r.get("error")]
    cost = sum(float(r["cost"] or 0) for r in done)
    lines = [
        "# Chat benchmark - 2026-09",
        "",
        f"Run {started} against `{base}` (model preference: {model}). {len(rows)} questions, "
        f"{len(done)} answered by this system, {len(rows) - len(done)} failed to run.",
        f"Claude cost for this run: USD {cost:.4f} (the per-step and total caps in `claude_spend` apply).",
        "",
        "**This file holds client questions and answers. It lives in `.cowork/`, which git ignores. "
        "Do not copy it into the repository, an issue, a PR or a chat.**",
        "",
        "Scores are left blank on purpose: correctness is judged by an engineer against the documents, "
        "not by this script. Paste ChatGPT's and Claude.ai's answers under each question, then score all three.",
        "",
        "## Scoring",
        "",
        "| Criterion | Points | Means |",
        "|---|---|---|",
        *[f"| {name} | {pts} | {means} |" for name, pts, means in RUBRIC],
        "",
        "## Summary",
        "",
        "| # | Category | Kind | Points found | Sources | Seconds | Cost (USD) | This system | ChatGPT | Claude.ai |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['n']} | {r['category']} | failed | | | | | | | |")
            continue
        cost_cell = "" if r["cost"] is None else f"{float(r['cost']):.4f}"
        lines.append(f"| {r['n']} | {r['category']} | {r['kind']} | {r['points']} | {len(r['sources'])} | "
                     f"{r['seconds']} | {cost_cell} | /7 | /7 | /7 |")
    lines += ["", "## Questions and answers", ""]
    for r in rows:
        lines += [f"### {r['n']}. {r['question']}", "", f"Category: {r['category']}", ""]
        if r.get("error"):
            lines += [f"**This system: did not run** - {r['error']}", ""]
        else:
            lines += [f"**This system** ({r['used_line']})", ""]
            if r["points"]:
                lines.append(f"Points found on the page: {r['points']}")
            if r["sources"]:
                lines.append("Sources: " + "; ".join(r["sources"]))
            for notice in r["notices"]:
                lines.append(f"Note: {notice}")
            lines += ["", "> " + r["answer"].replace("\n", "\n> "), ""]
        lines += ["**ChatGPT** (paste here)", "", "> ", "", "**Claude.ai** (paste here)", "", "> ", "",
                  "| | Correct | Grounded | Cites the page | Honest about limits | Clear | Total |",
                  "|---|---|---|---|---|---|---|",
                  "| This system | | | | | | /7 |", "| ChatGPT | | | | | | /7 |", "| Claude.ai | | | | | | /7 |", ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", help="sign in as this user (password is asked for)")
    parser.add_argument("--no-auth", action="store_true", help="the backend runs with AUTH_MODE=disabled")
    parser.add_argument("--model", choices=["auto", "claude", "local"], default="auto")
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)

    try:
        questions = read_questions(args.questions)
        report = inside_cowork(args.report)
    except (Refused, FileNotFoundError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if not git_ignores(report):
        print(f"refused: git would track {report}; it would publish client answers", file=sys.stderr)
        return 2
    if not questions:
        print(f"no questions in {args.questions}", file=sys.stderr)
        return 2
    if not args.no_auth and not args.email:
        print("give --email (or --no-auth for AUTH_MODE=disabled)", file=sys.stderr)
        return 2

    token = None if args.no_auth else login(args.base, args.email)
    api = Api(args.base, token)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for n, (category, question) in enumerate(questions, start=1):
        print(f"[{n}/{len(questions)}] {category}", flush=True)   # never the question text
        try:
            rows.append(row_of(n, category, question, ask(api, question, args.model), None))
        except Exception as exc:  # noqa: BLE001 - one failed question must not lose the rest
            rows.append(row_of(n, category, question, None, str(exc)[:300]))
    report.write_text(build_report(rows, base=args.base, model=args.model, started=started), encoding="utf-8")
    print(f"wrote {report.relative_to(REPO)} ({len(rows)} questions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
