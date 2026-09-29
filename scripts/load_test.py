"""Load test: how the backend behaves when several engineers use it at once.

    python3.12 scripts/load_test.py                       # defaults
    python3.12 scripts/load_test.py --docs 20 --levels 1,2,5,10,20 \
        --requests-per-level 100 --workloads documents,answer,crs,chat,mixed \
        --out /tmp/load.json --seed 7

SYNTHETIC ONLY. Every run builds a throwaway corpus in a fresh temporary
directory - N standards-like PDFs (numbered clauses, requirement sentences with
numbers and units) plus a few submittal-like datasheets - and points
`data_dir`, `upload_dir` and `db_path` at it before anything opens a database.
The live database is never opened and no client document is read. The results
JSON goes to `--out`, default inside that temporary directory, never the repo.

HOW THE SERVER IS DRIVEN, AND WHY. A real uvicorn server in a SEPARATE
PROCESS on 127.0.0.1, started by this script (`--_serve`, internal), with
many client threads in this process each holding its own keep-alive HTTP
connection. Chosen over in-process `TestClient` threads because:

  * it is what the engineers actually hit: one uvicorn event loop, FastAPI's
    shared threadpool for the sync routes, real HTTP parsing and JSON
    serialisation - `TestClient` gives every client its own event loop and
    thread limiter, which is NOT how requests queue in production;
  * the clients do not share the server's GIL, so the load generator does not
    steal CPU time from the process being measured (it still shares the
    machine's cores - stated in the results);
  * the lifespan runs exactly as `run.py` runs it (ingest worker, warm-up,
    vector store start-up), so background threads are present as in use.

Differences from `run.py`, stated: the server process calls
`tests/env_isolation.isolate` first (the suite's proven isolation - every
setting at the code default, `backend/.env` NOT read, no Claude, no SMTP, no
market lane, a network guard that refuses anything but loopback), then points
the three storage paths at the temp directory and sets `AUTH_MODE=disabled`
(the same approach the test suite uses: an unrestricted scope, no login).
`server_header=False` as in `run.py`.

WORKLOADS, each measured separately (closed loop: C threads, each sends its
next request as soon as the previous one returns, until the level's request
budget is spent):

  documents  GET /api/documents                               (read, SQLite)
  answer     GET /api/answer?tier=extract                     (FTS5 + dense +
             cross-encoder rerank; the verbatim tier, NO model generation,
             so Ollama is not needed)
  crs        GET /api/reviews/runs/{id}/crs/preview            (read; the run
             and its findings are inserted directly into the synthetic DB -
             a real review run needs the full pipeline, which is not what is
             being measured here)
  chat       POST /api/conversations/{id}/ask  tier=extract    (the chat's
             route: same retrieval as `answer`, PLUS it WRITES both turns to
             SQLite - the write path under concurrency)
  mixed      40% documents, 35% answer, 10% crs, 15% chat, seeded

ERRORS. Any non-2xx or client-side exception is an error, classified as
`http_<status>`, `exception:<Type>`, or - when the body names it -
`sqlite_locked` / `sqlite_schema_changed`. The server's stderr is captured and
scanned afterwards for tracebacks and for those two SQLite messages, because a
500 body is deliberately generic (errors.safe_error) and would hide them.

WARM-UP. Before timing, the script waits for the server, then sends
`--warmup` requests per workload sequentially (default 3). The first answer
loads the embedder and reranker ONNX sessions; that one-off cost is excluded
from every timed number.

WHAT THE NUMBERS ARE. Synthetic corpus, the machine this runs on. They say how
latency and throughput move with concurrency on THAT machine for THAT corpus.
They are not the owner's PC and not the client's library.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"

ALL_WORKLOADS = ("documents", "answer", "crs", "chat", "mixed")
DEFAULT_LEVELS = (1, 2, 5, 10, 20)
#: The mixed workload's shares. Sum to 1.0.
MIX = (("documents", 0.40), ("answer", 0.35), ("crs", 0.10), ("chat", 0.15))
LABEL = "synthetic corpus, sandbox machine, not the owner's PC"


# =============================================================== pure parts

def percentile(values: list[float], p: float) -> float | None:
    """The p-th percentile (0-100) by linear interpolation between closest
    ranks - numpy's default method. None for an empty list, never 0: no
    sample is not a latency of zero."""
    if not values:
        return None
    if not 0 <= p <= 100:
        raise ValueError("p must be between 0 and 100")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100.0
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def classify_error(status: int | None, body: str = "", exc: BaseException | None = None) -> str | None:
    """None for a success, else the error's class.

    SQLite's two concurrency messages win over the status, because they are
    what this test is looking for and a 500 alone does not say which it was.
    """
    text = f"{body} {exc or ''}".lower()
    if "database is locked" in text:
        return "sqlite_locked"
    if "schema has changed" in text:
        return "sqlite_schema_changed"
    if exc is not None:
        return f"exception:{type(exc).__name__}"
    if status is None:
        return "exception:NoStatus"
    if 200 <= status < 300:
        return None
    return f"http_{status}"


@dataclass
class Sample:
    workload: str       # for mixed: the sub-workload actually sent
    ms: float
    error: str | None


def aggregate(samples: list[Sample], wall_seconds: float) -> dict:
    """Requests, errors by class, throughput and latency for one level.

    Latency percentiles are over SUCCESSFUL requests only - a fast 500 must
    not make the system look quicker. Throughput counts every completed
    request (successes and errors) over the level's wall time, and the
    successful throughput is given alongside so the two cannot be confused.
    """
    errors: dict[str, int] = {}
    ok_ms: list[float] = []
    for s in samples:
        if s.error is None:
            ok_ms.append(s.ms)
        else:
            errors[s.error] = errors.get(s.error, 0) + 1
    n = len(samples)

    def r(v):
        return None if v is None else round(v, 1)

    return {
        "requests": n,
        "ok": len(ok_ms),
        "errors": sum(errors.values()),
        "errors_by_type": dict(sorted(errors.items())),
        "wall_seconds": round(wall_seconds, 3),
        "throughput_rps": round(n / wall_seconds, 2) if wall_seconds > 0 else None,
        "ok_throughput_rps": round(len(ok_ms) / wall_seconds, 2) if wall_seconds > 0 else None,
        "p50_ms": r(percentile(ok_ms, 50)),
        "p95_ms": r(percentile(ok_ms, 95)),
        "max_ms": r(max(ok_ms) if ok_ms else None),
    }


def parse_levels(text: str) -> list[int]:
    levels = [int(x) for x in text.split(",") if x.strip()]
    if not levels or any(n < 1 for n in levels):
        raise argparse.ArgumentTypeError("levels must be positive integers, e.g. 1,2,5")
    return levels


def parse_workloads(text: str) -> list[str]:
    names = [x.strip() for x in text.split(",") if x.strip()]
    unknown = [n for n in names if n not in ALL_WORKLOADS]
    if not names or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown workload(s) {unknown}; choose from {','.join(ALL_WORKLOADS)}")
    return names


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--docs", type=int, default=20, help="standards-like PDFs to generate (default 20)")
    p.add_argument("--sheets", type=int, default=3, help="submittal-like datasheets (default 3)")
    p.add_argument("--pages", type=int, default=4, help="pages per standard (default 4)")
    p.add_argument("--levels", type=parse_levels, default=list(DEFAULT_LEVELS),
                   help="concurrency levels, comma separated (default 1,2,5,10,20)")
    p.add_argument("--requests-per-level", type=int, default=100,
                   help="requests sent at each level of each workload (default 100)")
    p.add_argument("--workloads", type=parse_workloads, default=list(ALL_WORKLOADS),
                   help=f"comma separated, from {','.join(ALL_WORKLOADS)}")
    p.add_argument("--warmup", type=int, default=3, help="untimed requests per workload first")
    p.add_argument("--out", type=Path, default=None,
                   help="results JSON (default: results.json in the temp directory)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--keep", action="store_true", help="keep the temp directory afterwards")
    p.add_argument("--_serve", dest="serve_dir", type=Path, help=argparse.SUPPRESS)
    p.add_argument("--_port", dest="serve_port", type=int, help=argparse.SUPPRESS)
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.docs < 1:
        raise SystemExit("--docs must be at least 1")
    if args.requests_per_level < 1:
        raise SystemExit("--requests-per-level must be at least 1")
    return args


def pick_mixed(rng: random.Random) -> str:
    x = rng.random()
    acc = 0.0
    for name, share in MIX:
        acc += share
        if x < acc:
            return name
    return MIX[-1][0]


#: Lines worth keeping from a traceback: the "File ..., line N" frames, the
#: code line under each, and the exception line. Never a local variable dump.
_FRAME = re.compile(r'^\s*File "(.+)", line (\d+), in (.+)$')


def scan_server_log(text: str) -> dict:
    """Tracebacks and SQLite concurrency messages in the server's stderr."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("Traceback (most recent call last)"):
            current = [line]
            blocks.append(current)
            continue
        if current is not None:
            if line.startswith(" ") or _FRAME.match(line):
                current.append(line)
            else:
                current.append(line)      # the exception line ends the block
                current = None
    by_exc: dict[str, dict] = {}
    for block in blocks:
        last = block[-1].strip()
        key = last.split(":")[0] if last else "?"
        entry = by_exc.setdefault(key, {"count": 0, "message": last[:200], "excerpt": block[-9:]})
        entry["count"] += 1
    lower = text.lower()
    return {
        "tracebacks": len(blocks),
        "by_exception": by_exc,
        "database_is_locked": lower.count("database is locked"),
        "schema_has_changed": lower.count("schema has changed"),
    }


def format_table(results: list[dict]) -> str:
    head = f"{'workload':10} {'conc':>4} {'reqs':>5} {'err':>4} {'req/s':>7} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}  errors"
    lines = [head, "-" * len(head)]

    def c(v):
        return "" if v is None else f"{v:.1f}"

    for r in results:
        errs = ", ".join(f"{k}={v}" for k, v in r["errors_by_type"].items())
        lines.append(f"{r['workload']:10} {r['concurrency']:>4} {r['requests']:>5} {r['errors']:>4} "
                     f"{c(r['throughput_rps']):>7} {c(r['p50_ms']):>8} {c(r['p95_ms']):>8} "
                     f"{c(r['max_ms']):>8}  {errs}")
    return "\n".join(lines)


# ============================================================ synthetic corpus

TOPICS = (
    ("Design pressure", "The design pressure of the vessel shall be not less than {v} kPa", (600, 9000)),
    ("Design temperature", "The maximum design temperature shall not exceed {v} C", (60, 420)),
    ("Coating thickness", "The dry film thickness of the primer shall be at least {v} micrometres", (40, 350)),
    ("Relative humidity", "No coating shall be applied when relative humidity is above {v} %", (70, 90)),
    ("Hydrostatic test", "The hydrostatic test pressure shall be held for {v} minutes minimum", (10, 120)),
    ("Vibration limit", "Overall vibration shall not exceed {v} mm/s RMS at any bearing", (2, 12)),
    ("Corrosion allowance", "A corrosion allowance of {v} mm shall be added to all wetted parts", (1, 6)),
    ("Flange rating", "Flanges shall be rated to class {v} in accordance with ASME B16.5", (150, 2500)),
    ("Chloride content", "Chloride content of the test water shall not exceed {v} ppm", (25, 250)),
    ("Noise level", "The sound pressure level at 1 m shall not exceed {v} dBA", (80, 90)),
    ("Weld inspection", "Radiographic examination shall cover {v} % of butt welds", (10, 100)),
    ("Bolt torque", "Bolts shall be tightened to {v} N.m using a calibrated wrench", (80, 900)),
)


def question_bank() -> list[str]:
    return [
        "what is the design pressure of the vessel",
        "maximum design temperature",
        "dry film thickness of the primer",
        "relative humidity limit for coating application",
        "how long is the hydrostatic test pressure held",
        "vibration limit at the bearing",
        "corrosion allowance for wetted parts",
        "flange rating class",
        "chloride content of the test water",
        "sound pressure level limit",
        "radiographic examination of butt welds",
        "bolt tightening torque",
    ]


def standard_pages(n: int, pages: int, rng: random.Random) -> list[list[str]]:
    out = []
    for p in range(1, pages + 1):
        lines = [f"SYN-STD-{n:03d} Rev {rng.randint(0, 5)}  Synthetic Engineering Standard"]
        for k in range(2):
            title, sentence, (lo, hi) = rng.choice(TOPICS)
            clause = f"{p + 3}.{k + 1}"
            lines += [clause, title,
                      sentence.format(v=rng.randint(lo, hi)) + ".",
                      "The contractor shall record the measured value in the inspection",
                      "report and submit it to the company for review before acceptance.",
                      f"Deviation from clause {clause} requires written approval by the company."]
        lines.append(f"Page {p} of {pages}")
        out.append(lines)
    return out


def datasheet_pages(n: int, rng: random.Random) -> list[list[str]]:
    """A submittal-like datasheet. Written as sentences, not "Label: value"
    rows: a page of bare label/value lines is classified as an index page and
    excluded from search, which would leave the datasheet unsearchable."""
    lines = [f"EQUIPMENT DATASHEET  SYN-DS-{n:03d}  Rev A",
             f"Pressure vessel V-{rng.randint(1, 9999):04d} proposed by Synthetic Fabricators Ltd"]
    for i, (title, _s, (lo, hi)) in enumerate(TOPICS[:8], start=1):
        lines += [f"{i}. {title}",
                  f"The contractor proposes a {title.lower()} of {rng.randint(lo, hi)} for this item,",
                  "as calculated in the attached design report submitted for review."]
    return [lines]


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    import pymupdf
    doc = pymupdf.open()
    for block in pages:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 90 + i * 15), line)
    doc.save(str(path))
    doc.close()


def _isolate_settings(root: Path) -> None:
    """Code defaults, no `backend/.env`, loopback only; storage under root."""
    sys.path.insert(0, str(BACKEND))
    from app.config import settings
    from tests import env_isolation
    env_isolation.isolate(settings)
    env_isolation.install_network_guard()
    settings.data_dir = root
    settings.upload_dir = root / "uploads"
    settings.db_path = root / "load.sqlite"
    settings.auth_mode = "disabled"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)


def build_corpus(root: Path, *, docs: int, sheets: int, pages: int, seed: int) -> dict:
    """Generate, upload and fully ingest the synthetic corpus. Returns ids."""
    _isolate_settings(root)
    from fastapi.testclient import TestClient

    from app import db, keyword, submittal_review
    from app.ingest import IngestionWorker
    from app.main import app

    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    submittal_review.ensure_schema()
    rng = random.Random(seed)
    client = TestClient(app)          # no `with`: no lifespan, no worker thread
    pdf_dir = root / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    worker = IngestionWorker()
    ids: dict[str, list[str]] = {"standards": [], "sheets": []}
    started = time.perf_counter()
    plan = [("standards", f"syn-standard-{i:03d}.pdf", standard_pages(i, pages, rng)) for i in range(1, docs + 1)]
    plan += [("sheets", f"syn-datasheet-{i:03d}.pdf", datasheet_pages(i, rng)) for i in range(1, sheets + 1)]
    for kind, name, content in plan:
        path = pdf_dir / name
        write_pdf(path, content)
        with open(path, "rb") as fh:
            resp = client.post("/api/documents", files={"file": (name, fh, "application/pdf")})
        resp.raise_for_status()
        doc_id = resp.json()["document"]["id"]
        worker.process(doc_id)
        ids[kind].append(doc_id)
    conn = db.connect()
    status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) n FROM documents GROUP BY status")}
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    try:
        embedded = conn.execute("SELECT COALESCE(SUM(embedded_count),0) FROM documents").fetchone()[0]
    except Exception:
        embedded = None
    run_id = _insert_review_run(conn, ids["sheets"][0] if ids["sheets"] else ids["standards"][0],
                                ids["standards"][0], rng) if ids["standards"] else None
    db.reset_connection()
    return {"ids": ids, "status": status, "chunks": chunks, "embedded_chunks": embedded,
            "review_run_id": run_id, "ingest_seconds": round(time.perf_counter() - started, 1)}


def _insert_review_run(conn, submittal_id: str, standard_id: str, rng: random.Random) -> str:
    """A completed review run with 12 findings, straight into the DB - the
    shape test_crs_endpoint.py uses. The CRS preview then has rows to build."""
    import uuid
    now = "2026-09-29T00:00:00Z"
    run_id = str(uuid.uuid4())
    outcome = json.dumps({"recommended_code": "Manual Review Required",
                          "reason": "synthetic load-test run"})
    with conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
                     "created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
                     (run_id, submittal_id, outcome, now, now))
        for i in range(12):
            title, sentence, (lo, hi) = TOPICS[i % len(TOPICS)]
            row = {
                "id": str(uuid.uuid4()), "document_id": submittal_id, "review_run_id": run_id,
                "category": "requirement_deviation", "severity": "major",
                "requirement": title, "finding": "value differs", "required_action": "confirm",
                "compliance_status": "NON_COMPLIANT" if i % 2 else "NEEDS_ENGINEER_REVIEW",
                "requirement_source_text": sentence.format(v=rng.randint(lo, hi)) + ".",
                "contractor_evidence_text": f"{title}: {rng.randint(lo, hi)}",
                "ai_rationale": "value_mismatch", "standard_document_id": standard_id,
                "standard_clause": f"{4 + i}.1", "standard_page": 1 + i % 4, "contractor_page": 1,
                "equipment_tag": "V-0001", "governing_sources": "[]", "citation_ids": "[]",
                "unresolved_evidence": "[]", "status": "open", "approval_status": "pending",
                "escalation_level": 0, "created_at": now, "updated_at": now,
            }
            conn.execute(f"INSERT INTO review_findings ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                         list(row.values()))
    return run_id


# ================================================================== server

def serve(root: Path, port: int) -> None:
    """Internal: the server process. Same settings the corpus was built with."""
    _isolate_settings(root)
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, server_header=False,
                log_level="warning", access_log=False)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(root: Path, port: int, log_path: Path) -> subprocess.Popen:
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--_serve", str(root), "--_port", str(port)],
        cwd=str(BACKEND), stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"server exited early (code {proc.returncode}); see {log_path}")
        try:
            status, _ = request_once(http.client.HTTPConnection("127.0.0.1", port, timeout=5),
                                     "GET", "/api/health")
            if status == 200:
                return proc
        except OSError:
            pass
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("server did not become healthy within 180 s")


# ================================================================== client

def request_once(conn: http.client.HTTPConnection, method: str, path: str,
                 body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    return resp.status, resp.read().decode("utf-8", errors="replace")


class Target:
    """Builds the request for each workload."""

    def __init__(self, run_id: str | None, conversation_ids: list[str]):
        self.run_id = run_id
        self.conversation_ids = conversation_ids
        self.questions = question_bank()

    def request(self, workload: str, i: int) -> tuple[str, str, dict | None]:
        q = self.questions[i % len(self.questions)]
        if workload == "documents":
            return "GET", "/api/documents?limit=50", None
        if workload == "answer":
            return "GET", "/api/answer?" + urlencode({"q": q, "tier": "extract"}), None
        if workload == "crs":
            return "GET", f"/api/reviews/runs/{self.run_id}/crs/preview", None
        if workload == "chat":
            conv = self.conversation_ids[i % len(self.conversation_ids)]
            return "POST", f"/api/conversations/{conv}/ask", {"question": q, "tier": "extract"}
        raise ValueError(workload)


def run_level(port: int, target: Target, workload: str, concurrency: int, n_requests: int,
              seed: int) -> tuple[list[Sample], float]:
    counter = iter(range(n_requests))
    lock = threading.Lock()
    samples: list[Sample] = []
    rng = random.Random(f"{seed}-{workload}-{concurrency}")
    plan = [pick_mixed(rng) if workload == "mixed" else workload for _ in range(n_requests)]

    def worker():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
        local: list[Sample] = []
        while True:
            with lock:
                i = next(counter, None)
            if i is None:
                break
            kind = plan[i]
            method, path, body = target.request(kind, i)
            t0 = time.perf_counter()
            try:
                status, text = request_once(conn, method, path, body)
                err = classify_error(status, text if status >= 300 else "")
            except Exception as exc:          # noqa: BLE001 - every failure is data
                err = classify_error(None, "", exc)
                conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
            local.append(Sample(kind, (time.perf_counter() - t0) * 1000, err))
        conn.close()
        with lock:
            samples.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return samples, time.perf_counter() - t0


def check_responses(conn: http.client.HTTPConnection, target: Target, skipped: dict) -> dict:
    """Untimed: are the routes doing real work, or answering fast with nothing?

    A load test of a search that abstains on every question would measure the
    abstention. So every question in the bank is asked once, and the result
    says how many came back with a passage - a count with its denominator.
    """
    out: dict = {}
    status, text = request_once(conn, "GET", "/api/documents?limit=200")
    out["documents_listed"] = len(json.loads(text)) if status == 200 else f"HTTP {status}"
    answered = 0
    types: dict[str, int] = {}
    for i in range(len(target.questions)):
        method, path, body = target.request("answer", i)
        status, text = request_once(conn, method, path, body)
        if status != 200:
            continue
        data = json.loads(text)
        answered += bool(data.get("answer"))
        types[str(data.get("answer_type"))] = types.get(str(data.get("answer_type")), 0) + 1
    out["answer_with_passage"] = f"{answered} of {len(target.questions)} questions"
    out["answer_types"] = types
    if "crs" not in skipped:
        status, text = request_once(conn, "GET", f"/api/reviews/runs/{target.run_id}/crs/preview")
        out["crs_rows"] = len(json.loads(text)["rows"]) if status == 200 else f"HTTP {status}"
    return out


def machine() -> dict:
    mem = None
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                mem = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return {"nproc": os.cpu_count(), "ram_gib": mem, "python": sys.version.split()[0],
            "platform": sys.platform}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.serve_dir:
        serve(args.serve_dir, args.serve_port)
        return 0

    root = Path(tempfile.mkdtemp(prefix="ragintel-load-"))
    out = args.out or root / "results.json"
    print(f"[load] temp dir {root}  ({LABEL})")
    corpus = build_corpus(root, docs=args.docs, sheets=args.sheets, pages=args.pages, seed=args.seed)
    print(f"[load] corpus: {args.docs} standards x {args.pages} pages + {args.sheets} datasheets, "
          f"{corpus['chunks']} chunks, embedded {corpus['embedded_chunks']}, status {corpus['status']}, "
          f"ingested in {corpus['ingest_seconds']} s")
    workloads = list(args.workloads)
    skipped = {}
    if "crs" in workloads and not corpus["review_run_id"]:
        workloads.remove("crs")
        skipped["crs"] = "no review run could be inserted"

    port = free_port()
    log_path = root / "server.log"
    proc = start_server(root, port, log_path)
    results: list[dict] = []
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
        conv_ids = []
        for _ in range(max(args.levels)):
            status, text = request_once(conn, "POST", "/api/conversations", {})
            if status != 200:
                raise SystemExit(f"could not create a conversation: HTTP {status}")
            conv_ids.append(json.loads(text)["id"])
        target = Target(corpus["review_run_id"], conv_ids)
        warm_t0 = time.perf_counter()
        sanity = check_responses(conn, target, skipped)
        print(f"[load] response sanity (untimed): {sanity}")
        for kind in ("documents", "answer", "crs", "chat"):
            if kind == "crs" and "crs" in skipped:
                continue
            for i in range(args.warmup):
                method, path, body = target.request(kind, i)
                status, text = request_once(conn, method, path, body)
                if status != 200:
                    raise SystemExit(f"warm-up {kind} failed: HTTP {status}: {text[:200]}")
        conn.close()
        warmup_seconds = round(time.perf_counter() - warm_t0, 1)
        print(f"[load] warm-up done in {warmup_seconds} s (excluded from timings)")
        for workload in workloads:
            for level in args.levels:
                samples, wall = run_level(port, target, workload, level, args.requests_per_level, args.seed)
                row = {"workload": workload, "concurrency": level, **aggregate(samples, wall)}
                if workload == "mixed":
                    # the blended p50 of a fast and a slow route means little;
                    # each route's own numbers inside the mix are what matter
                    row["by_kind"] = {k: aggregate([s for s in samples if s.workload == k], wall)
                                      for k, _ in MIX}
                results.append(row)
                print(format_table([row]).splitlines()[-1], flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    server_log = scan_server_log(log_path.read_text(encoding="utf-8", errors="replace"))
    report = {
        "label": LABEL,
        "machine": machine(),
        "args": {"docs": args.docs, "sheets": args.sheets, "pages": args.pages, "levels": args.levels,
                 "requests_per_level": args.requests_per_level, "workloads": workloads,
                 "warmup": args.warmup, "seed": args.seed},
        "corpus": {k: v for k, v in corpus.items() if k != "ids"},
        "skipped": skipped,
        "warmup_seconds": warmup_seconds,
        "response_sanity": sanity,
        "server_log": server_log,
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"RESULTS - {LABEL}; machine {report['machine']}")
    print(format_table(results))
    print(f"server log: {server_log['tracebacks']} tracebacks, "
          f"'database is locked' x{server_log['database_is_locked']}, "
          f"'schema has changed' x{server_log['schema_has_changed']}")
    print(f"[load] results written to {out}")
    if not args.keep and args.out is not None and root not in Path(out).resolve().parents:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
