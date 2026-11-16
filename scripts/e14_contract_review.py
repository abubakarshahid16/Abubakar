"""Order 14 lane E: the AI review of ONE contract on a COPY, through `scripts.trial_on_copy` (the app's own route: the plan, then
the start with the list of documents shown, the general review), with the contract's project papers and an engineer's kind.

    # FREE dry run: the stub sender answers every call and keeps each request body in <out>/bodies.jsonl (local only); no network.
    python -m scripts.e14_contract_review --out <dir> --dry-run --kind contract --project-doc <id> [--project-doc <id> ...] \\
        [--marker <doc id>=<text> ...] -- --lane open --engine claude --data-dir <copy> --copy-to <new folder> --document <id>

    # PAID run (only from the lead's standby loop, which holds the key): the same without --dry-run and without markers.

Additions to `trial_on_copy`, in THE COPY only (the trial's own fresh copy):
  --kind KIND        the paper's kind as an engineer sets it (`document_kinds`, state confirmed), recorded as this script's step;
  --project-doc ID   a project paper of the same contract for the general review (the plan and the start carry it, max 10);
  --marker ID=TEXT   (dry run) appends TEXT to page 1 of that document: the body scan proves what left and what did not;
  --out DIR          the plan as the app answered it (plan.json) and, with --dry-run, the bodies and the marker counts.
No key is read, printed or stored here; the paid run takes it from its caller's environment, as `trial_on_copy` does.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from scripts import trial_on_copy as trial

STUB_ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "test-key-not-real",
}


class StubSender:
    """An invented Claude for the dry run: every call is kept, every answer is empty (`{}`): nothing is decided."""

    def __init__(self, out: Path):
        self.path = out / "bodies.jsonl"
        self.calls = 0
        self.usage = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "bytes_sent": 0,
        }
        self._lock = threading.Lock()

    def __call__(self, _url, *, body, **_kw):
        with self._lock:
            self.calls += 1
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(body) + "\n")
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        return {"model": "stub-not-claude", "stop_reason": "end_turn", "usage": usage, "content": [{"type": "text", "text": "{}"}]}  # fmt: skip


class _NoNetwork:
    """`httpx` as `reader_transport` sees it in a dry run: any client refuses before a socket opens."""

    def __getattr__(self, name):
        import httpx

        if name in ("Client", "AsyncClient", "post", "get", "stream", "request"):
            raise RuntimeError("dry run: no network")
        return getattr(httpx, name)


def _block_every_send(stub: StubSender) -> None:
    """THE DRY RUN SENDS NOTHING, from ANY step: the reader transport's one sender is the stub (every request kept), every other
    network function of that module refuses, and its `httpx` refuses to build a client. (Without this, the rule check's own AI
    step reached the real transport with the stub's invented key: refused by the far end, but a request had left.)"""
    from app import reader_transport as rt

    def refused(*_a, **_k):
        raise RuntimeError("dry run: no network")

    rt.transport = lambda: stub
    for name in (
        "stream",
        "list_models",
        "_gated",
        "batch_create",
        "batch_retrieve",
        "batch_cancel",
        "batch_results",
    ):
        setattr(rt, name, refused)
    rt.httpx = _NoNetwork()


def _prepare_copy(kind: str | None, paper: str, markers: dict[str, str]) -> None:
    """In the trial's copy (settings point at it by now): the engineer's kind for the paper, and the dry-run markers."""
    from app.db import connect

    conn = connect()
    with conn:
        if kind:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            conn.execute(
                "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, evidence, router_version, routed_at, confirmed_at)"
                " VALUES (?, ?, 'confirmed', 'set by the order 14 lane E script in this copy', 'e14', ?, ?)",
                (paper, kind, now, now),
            )
        for doc, text in markers.items():
            conn.execute(
                "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = (SELECT MIN(page_no) FROM pages WHERE document_id = ?)",
                (f"\n{text}\n", doc, doc),
            )


def _with_projects(projects: list[str], out: Path | None):
    """`Http.call` that adds the project papers to the plan and the start, and keeps the plan the app answered."""
    original = trial.Http.call

    def call(self, method, path, body=None, timeout=120.0):
        if path.startswith("/api/reviews/plan"):
            path += "".join(f"&project_document_ids={p}" for p in projects)
        if method == "POST" and path == "/api/reviews/start" and body is not None:
            body = {**body, "project_document_ids": projects}
        code, raw = original(self, method, path, body, timeout)
        if out is not None and path.startswith("/api/reviews/plan"):
            (out / "plan.json").write_bytes(raw or b"{}")
        return code, raw

    return call


def marker_counts(out: Path, markers: dict[str, str]) -> dict:
    """{doc id: hits of its marker in the kept request bodies}; the counts are written to <out>/markers.json."""
    text = (
        (out / "bodies.jsonl").read_text(encoding="utf-8")
        if (out / "bodies.jsonl").exists()
        else ""
    )
    counts = {doc: text.count(m) for doc, m in markers.items()}
    (out / "markers.json").write_text(json.dumps(counts, indent=1), encoding="utf-8")
    return counts


def main(argv: list[str]) -> int:
    if "--" in argv:
        mine, rest = argv[: argv.index("--")], argv[argv.index("--") + 1 :]
    else:
        mine, rest = [], argv
    ap = argparse.ArgumentParser(prog="e14_contract_review")
    ap.add_argument("--kind")
    ap.add_argument("--project-doc", action="append", default=[])
    ap.add_argument("--marker", action="append", default=[])
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(mine)
    if len(a.project_doc) > 10:
        print("at most 10 project papers")
        return 2
    paper = rest[rest.index("--document") + 1] if "--document" in rest else ""
    markers = dict(m.split("=", 1) for m in a.marker)
    if markers and not a.dry_run:
        print("markers are for the dry run only")
        return 2
    out = Path(a.out) if a.out else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
    original_set_aside = trial.empty_approved_list

    def set_aside_then_prepare() -> bool:
        result = original_set_aside()
        _prepare_copy(a.kind, paper, markers)
        return result

    trial.empty_approved_list = set_aside_then_prepare
    trial.Http.call = _with_projects(a.project_doc, out)
    stub = None
    if a.dry_run:
        if out is None:
            print("--dry-run needs --out")
            return 2
        stub = StubSender(out)
        _block_every_send(stub)
        original_run = trial.run_trial

        def run(cfg, **kw):
            return original_run(cfg, lane=lambda: (stub, STUB_ENV), **kw)

        trial.run_trial = run
    code = int(trial.main(rest) or 0)
    if stub is not None:
        print(
            f"dry run: {stub.calls} request(s) kept; marker hits {marker_counts(out, markers)}"
        )
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
