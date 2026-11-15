#!/usr/bin/env python
"""ONE chat question to Claude through the chat's own function, to read the API's answer to it (12 Nov 2026, the chat 400).

    ANTHROPIC_API_KEY=... python -m scripts.trial_chat_once --data-dir <COPY of the data folder> \\
        --out <result.json> [--question "<text>"] [--max-usd 0.20] [--model <id>]
    python -m scripts.trial_chat_once --data-dir <copy> --out x.json --plan     # sends nothing: prints the two model ids

Run from the repository root (or a worktree of it). The key comes ONLY from the caller's environment; this script never reads,
prints or stores it and checks only that it is present. No HTTP server, no copy of the request builder: it calls
`chat_claude_first.answer`, the function the chat route calls for a Claude answer, with NO document selected and NO history, under
`claude_spend` (the cap holds: `--max-usd` bounds this run, the app's own caps stay on top) and through `reader_transport.stream`.

PRINTS first, before anything is sent: the model id the chat lane uses (setting `claude_reasoning_model`, env
CLAUDE_REASONING_MODEL; pass `--model` to use the live value, it is only a model id) and the ones the AI reviewer uses
(constants in `agent_claude`), and says so when they differ.

WRITES `--out` (JSON): http_status, error_type, error_message (OUR fixed sentence for a known cause, as `reader_transport` reports it: never the API's own words, never the request, never a key), model, calls, bytes_sent, answered, answer_chars (a length, never the
text), cost_usd.

EXIT: 0 an answer came | 3 the API refused the request | 2 refused to start | 1 anything else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

MAX_QUESTION_CHARS = 300
DEFAULT_QUESTION = "What is the difference between gauge pressure and absolute pressure?"
EXIT_ANSWERED, EXIT_OTHER, EXIT_REFUSED_TO_START, EXIT_API_REFUSED = 0, 1, 2, 3
_SHAPE = re.compile(r"^(?P<status>\d{3}) from \S+(?: \((?P<kind>[a-z_]+)(?:: (?P<message>.*))?\))?$")


class Refused(Exception):
    """The trial would not start. The message holds a cause word, never a text."""


def live_roots() -> list[Path]:
    roots = {(Path.home() / "project" / "Abubakar").resolve()}
    try:
        from app.config import shared_backend_dir

        roots.add(Path(shared_backend_dir()).resolve().parent)
    except Exception:  # noqa: BLE001 - a missing helper must not weaken the check
        pass
    return sorted(roots)


def refuse_live(data_dir: Path) -> None:
    from app import live_guard

    resolved = Path(data_dir).resolve()
    if not resolved.is_dir():
        raise Refused("the data folder does not exist")
    for root in live_roots():
        if resolved == root or root in resolved.parents:
            raise Refused("the data folder is under the live checkout")
    if live_guard.is_live_shaped(resolved):
        raise Refused("the data folder is a live-shaped path")
    if (BACKEND / ".env").exists():
        raise Refused("a backend/.env sits beside this code and would be read by the settings: run from a worktree without one")


def model_lines(model_override: str | None = None) -> tuple[str, str, bool]:
    """(chat model, reviewer models, differ). Names and ids only."""
    from app import agent_claude
    from app.config import settings

    chat = model_override or settings.claude_reasoning_model
    reviewer = f"{agent_claude.LEAD_MODEL} (lead), {agent_claude.SECOND_MODEL} (second reader)"
    return chat, reviewer, chat not in (agent_claude.LEAD_MODEL, agent_claude.SECOND_MODEL)


def apply_settings(data_dir: Path, max_usd: float, model: str | None) -> None:
    """What the chat's Claude lane needs, for THIS process only; the key is neither read nor set here."""
    from app.config import settings

    data = Path(data_dir).resolve()
    settings.data_dir = data
    settings.upload_dir = data / "uploads"
    settings.db_path = data / "rag_intelligence.sqlite"
    settings.claude_spend_log = data / "claude_spend.jsonl"
    settings.claude_cache_dir = data / "claude_cache"
    settings.startup_warmup = False
    settings.reasoning_provider = "per_task"
    settings.chat_model_engine = "claude"
    settings.standards_reader_enabled = True
    settings.standards_reader_allow_public_egress = True
    for name, value in (
        ("REASONING_PROVIDER", "per_task"),
        ("CHAT_MODEL_ENGINE", "claude"),
        ("STANDARDS_READER_ENABLED", "true"),
        ("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true"),
    ):
        os.environ[name] = value
    if model:
        settings.claude_reasoning_model = model
    spent = 0.0
    log = settings.claude_spend_log
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not entry.get("reserved") and isinstance(entry.get("cost_usd"), (int, float)):
                spent += float(entry["cost_usd"])
    settings.claude_budget_usd_per_step = min(float(settings.claude_budget_usd_per_step), max_usd)
    settings.claude_budget_usd_total = min(float(settings.claude_budget_usd_total), spent + max_usd)


def _recording_stream(real, record: dict):
    """The SAME `reader_transport.stream`, wrapped only to note what the API answered. No second path to the socket."""
    import httpx

    def stream(url, *, headers, body, timeout, cancel=None):
        record["calls"] += 1
        record["bytes_sent"] += len(json.dumps({**dict(body), "stream": True}, ensure_ascii=False).encode("utf-8"))
        record["model"] = str(body.get("model") or record["model"])
        try:
            yield from real(url, headers=headers, body=body, timeout=timeout, cancel=cancel)
        except httpx.HTTPStatusError as exc:
            record["http_status"] = exc.response.status_code
            match = _SHAPE.match(str(exc))
            if match:
                record["error_type"], record["error_message"] = match.group("kind") or "", match.group("message") or ""
            raise

    return stream


def run(args, *, stream=None) -> tuple[int, dict]:
    """The trial. `stream` replaces `reader_transport.stream` (tests); the real run leaves it None."""
    from app import chat_claude_first, claude_approved, claude_spend, reader_transport

    refuse_live(Path(args.data_dir))
    if len(args.question) > MAX_QUESTION_CHARS:
        raise Refused(f"the question is longer than {MAX_QUESTION_CHARS} characters")
    if getattr(args, "document", None):
        raise Refused("no document may be selected: this trial sends a general question only")
    if stream is None and not os.environ.get("ANTHROPIC_API_KEY"):
        raise Refused("no ANTHROPIC_API_KEY in the environment")
    apply_settings(Path(args.data_dir), float(args.max_usd), args.model)
    record = {"http_status": None, "error_type": "", "error_message": "", "model": "", "calls": 0, "bytes_sent": 0,
              "answered": False, "answer_chars": 0, "cost_usd": None}
    original = reader_transport.stream
    reader_transport.stream = _recording_stream(stream or original, record)
    reasons: list[str] = []
    cost: list[float] = []
    try:
        with claude_approved.carrying(()):  # no document: exactly what the chat declares for Claude with nothing selected
            result = chat_claude_first.answer(
                args.question, history="", allowed_document_ids=frozenset(), web_enabled=False, preference="claude",
                on_fallback_cost=cost.append, on_fallback_reason=reasons.append, on_unverified=None)
    finally:
        reader_transport.stream = original
    if result and result.get("answer"):
        record.update(answered=True, answer_chars=len(str(result["answer"])), http_status=200,
                      cost_usd=result.get("cost_usd"))
        return EXIT_ANSWERED, record
    record["cost_usd"] = cost[0] if cost else None
    if record["http_status"] and record["http_status"] >= 400:
        return EXIT_API_REFUSED, record
    return EXIT_OTHER, {**record, "note": reasons[0] if reasons else "no answer and no API rejection"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", required=True, help="a COPY of the data folder (the live one is refused)")
    ap.add_argument("--out", required=True, help="where the result JSON is written")
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    ap.add_argument("--max-usd", type=float, default=0.20)
    ap.add_argument("--model", default=None, help="model id to use (default: the chat's own setting)")
    ap.add_argument("--plan", action="store_true", help="send nothing; print the model ids and exit")
    ap.add_argument("--document", action="append", help="refused: no document may be passed")
    args = ap.parse_args(argv)
    try:
        refuse_live(Path(args.data_dir))
        chat, reviewer, differ = model_lines(args.model)
        print(f"chat lane model: {chat} (setting claude_reasoning_model, env CLAUDE_REASONING_MODEL)")
        print(f"AI reviewer models: {reviewer} (constants in agent_claude)")
        print("MODEL IDS DIFFER: the chat does not use a reviewer model" if differ else "model ids: the chat uses a reviewer model id")
        if args.plan:
            return EXIT_ANSWERED
        code, record = run(args)
    except Refused as exc:
        print(f"refused to start: {exc}", file=sys.stderr)
        return EXIT_REFUSED_TO_START
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k != "note"}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
