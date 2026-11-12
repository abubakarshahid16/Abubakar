#!/usr/bin/env python
"""Trial on a COPY that runs a real AI review and CHECKS every result (order 12, N3 part A).

    # free, lane closed: no Claude call, no local model. Every item ends "Not reviewed", but the plan, every route, the
    # contract and the Rules used page are still checked. It FAILS if the plan is empty or a route breaks.
    python scripts/trial_on_copy.py --lane closed --data-dir <copy of the data folder> --copy-to <new folder> --document <id>

    # open lane, real answers (paid: started by the lead). The key comes ONLY from the caller's environment; this script
    # never reads, prints or stores it, and checks only that it is there. Cap: --max-usd (the app's own caps stay on top).
    ANTHROPIC_API_KEY=... REASONING_PROVIDER=claude STANDARDS_READER_ENABLED=true STANDARDS_READER_ALLOW_PUBLIC_EGRESS=true \\
        python scripts/trial_on_copy.py --lane open --data-dir <copy> --copy-to <new folder> --document <id> --max-usd 2

WHAT IT DOES (in one process, one temporary server on a free loopback port, real HTTP):
  1. refuses any path under the live checkout, a live-shaped database, a backend/.env beside the code, a key in the closed lane;
  2. copies the data folder (`--copy-to`, APFS clone when it can) so the source stays as it was, or works in place (`--in-place`);
  3. starts the app on the copy with the standing approval ON (CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED, a block file made from the
     register-named documents of the copy: never printed) and, closed lane, with no key and a dead local-engine address;
  4. imports the two label files through the admin routes (when `<data>/labels/` holds them);
  5. starts ONE AI review of `--document` and waits;
  6. CHECKS and prints a table (below); optionally starts ONE normal review (`--normal-review`) and checks it;
  7. exits 0 only when every check passed; 1 when any check failed; 2 when it refused to start.

THE CHECKS (each one PASS or FAIL, with counts or cause words only, never a paper or rule-book text):
  run completed | agent-status lane matches the mode | summary, lines, every trace, rules-used, both CRS copies answer 200 |
  every stored class/word/tier is legal by the contract | the class/word table gives a legal pair for every line the core can
  make | rules asked > 0, or the plan says why none | Rules used lists asked and left out, one reason each | no Pass or Fail
  without the code's proof fields | the contractor copy holds proven Fail only | spend (closed: none; open: >0 and under the cap,
  at least one answer) | standing approval (the paper and every asked rule book on the list, the register never) | optional:
  the normal review completed and says nothing was "skipped in a Claude-lane run".
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

PASS, FAIL = "PASS", "FAIL"
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
#: The words the app uses when it stops a step on purpose. Cause words, no text.
SKIPPED_TEXT = "skipped in a Claude-lane run"


class Refused(Exception):
    """The trial would not start. The message holds a cause word, never a text."""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    @property
    def word(self) -> str:
        return PASS if self.ok else FAIL


@dataclass
class TrialConfig:
    data_dir: Path
    document: str
    lane: str = "closed"
    db: Path | None = None
    labels_dir: Path | None = None
    max_usd: float = 2.0
    normal_review: bool = False
    allow_local_models: bool = False
    require_rules_asked: bool = False
    timeout: float = 1800.0
    port: int = 0
    sets: dict = field(default_factory=dict)
    skills_dir: str | None = None
    #: point E: ask the AI reviewer for fresh first-reader answers (ignore and replace the stored ones)
    fresh: bool = False
    #: 12 Nov 2026 (owner, #1584): start from the ONE Review button's route with this engine choice: "automatic", "claude" or
    #: "local". None (default) keeps the older start (`/api/reviews/agent-run`). "local" also checks that nothing was booked
    #: to the Claude ledger and that no AI review ran.
    engine: str | None = None


# ------------------------------------------------------------------------------------------------ safety


def live_roots() -> list[Path]:
    """The live checkout(s): the main checkout of this repository (the ledger and `.env` home) and the owner's usual path."""
    roots = {(Path.home() / "project" / "Abubakar").resolve()}
    try:
        from app.config import shared_backend_dir

        roots.add(Path(shared_backend_dir()).resolve().parent)
    except Exception:  # noqa: BLE001 - a missing helper must not weaken the check above
        pass
    return sorted(roots)


def refuse_live(paths: dict[str, Path]) -> None:
    """Raise `Refused` for a path under a live checkout, a live-shaped database, or a `.env` beside the code."""
    from app import live_guard

    roots = live_roots()
    for what, p in paths.items():
        rp = Path(p).resolve()
        for root in roots:
            if rp == root or root in rp.parents:
                raise Refused(f"{what} is under the live checkout")
        if live_guard.is_live_shaped(rp):
            raise Refused(f"{what} is a live-shaped database path")
    if (BACKEND / ".env").exists():
        raise Refused(
            "a backend/.env sits beside this code and would be read by the settings: run from a worktree without one"
        )


def _bad_name(name: str) -> bool:
    return any(w in name.upper() for w in SECRET_WORDS)


def copy_data(src: Path, dest: Path) -> None:
    """A copy of the data folder (all of the sqlite files and their -wal/-shm), APFS clone when possible."""
    if dest.exists():
        raise Refused("the copy folder already exists: give a new one")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        done = subprocess.run(["cp", "-cR", str(src), str(dest)], capture_output=True)
        if done.returncode == 0:
            return
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)


# ------------------------------------------------------------------------------------------------ settings and server


def effective_cap(requested: float, settings) -> float:
    """`--max-usd` can only LOWER the owner's caps, never raise one."""
    return min(
        float(requested),
        float(settings.claude_budget_usd_per_step),
        float(settings.claude_budget_usd_total),
    )


def ledger_lines(data_dir: Path) -> int:
    log = Path(data_dir) / "claude_spend.jsonl"
    return log.read_text().count("\n") if log.is_file() else 0


def ledger_spent(data_dir: Path) -> float:
    """USD already booked in the copy's ledger (a repeat run on the same copy starts from it)."""
    log, total = Path(data_dir) / "claude_spend.jsonl", 0.0
    if log.is_file():
        for line in log.read_text().splitlines():
            try:
                total += float(json.loads(line).get("cost_usd") or 0)
            except (ValueError, TypeError, AttributeError):
                continue
    return round(total, 6)


def empty_approved_list() -> bool:
    """Set the copy's approved list aside, so every approval after this was made by the app in THIS run (a list copied from the
    live data proves nothing). Returns whether a list was set aside."""
    from app import claude_approved

    path = claude_approved.list_path()
    if not path.is_file():
        return False
    path.rename(path.with_name(path.name + ".from-copy"))
    return True


def apply_settings(cfg: TrialConfig) -> dict:
    """Point the app at the copy and set the lane. Returns facts for the report (names and booleans only)."""
    from app import claude_approved
    from app.config import settings

    data = Path(cfg.data_dir).resolve()
    db = Path(cfg.db).resolve() if cfg.db else data / "rag_intelligence.sqlite"
    settings.data_dir = data
    settings.upload_dir = data / "uploads"
    settings.db_path = db
    settings.claude_spend_log = data / "claude_spend.jsonl"
    settings.claude_cache_dir = data / "claude_cache"
    settings.agent_review_enabled = True
    settings.host = "127.0.0.1"
    settings.auth_mode = "disabled"
    settings.startup_warmup = False
    settings.claude_auto_approve_reviews_enabled = True  # the standing approval, #1584 comment 6806441133, to be confirmed by the owner (the thing under trial)
    settings.claude_approved_list_enforced = True
    if cfg.skills_dir:
        os.environ["AGENT_SKILLS_DIR"] = cfg.skills_dir
    for name, value in cfg.sets.items():
        os.environ[name.upper()] = str(value)
        if hasattr(settings, name.lower()):
            current = getattr(settings, name.lower())
            setattr(
                settings,
                name.lower(),
                type(current)(value)
                if not isinstance(current, bool)
                else str(value).lower() in ("1", "true", "yes", "on"),
            )
    if cfg.lane == "closed":
        settings.reasoning_provider = "ollama"
        settings.standards_reader_enabled = False
        settings.standards_reader_allow_public_egress = False
        settings.anthropic_api_key = ""
        settings.ollama_url = (
            "http://127.0.0.1:9"  # a dead address: no local model can answer
        )
        for name in ("ANTHROPIC_API_KEY",):
            os.environ.pop(name, None)
        os.environ["REASONING_PROVIDER"] = "ollama"
        os.environ["STANDARDS_READER_ENABLED"] = "false"
        os.environ["STANDARDS_READER_ALLOW_PUBLIC_EGRESS"] = "false"
    else:
        cap = effective_cap(cfg.max_usd, settings)
        cfg.max_usd = cap  # the spend check compares with the cap really in force
        # `--max-usd` bounds THIS run's spend. The app's total cap counts the whole ledger, and a repeat run on the same copy
        # (`--in-place`) starts from what the first run spent: without this the repeat is refused ("usd_cap_reached: total")
        # before its first call and every line is "Not reviewed" (12 Nov, valve and real pump). The owner's caps still win.
        before = ledger_spent(data)
        settings.claude_budget_usd_per_step = min(
            float(settings.claude_budget_usd_per_step), cap
        )
        settings.claude_budget_usd_total = min(
            float(settings.claude_budget_usd_total), before + cap
        )
    return {
        "key_present": bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or getattr(settings, "anthropic_api_key", "")
        ),
        "provider": str(settings.reasoning_provider),
        "auto_approve": bool(settings.claude_auto_approve_reviews_enabled),
        "block_file": str(claude_approved.block_file_path().name),
    }


def check_open_lane_inputs(facts: dict) -> None:
    from app.config import settings

    if not facts["key_present"]:
        raise Refused(
            "open lane: no key in the caller's environment (never read from a file by this script)"
        )
    if str(settings.reasoning_provider).lower() not in ("claude", "per_task"):
        raise Refused(
            "open lane: REASONING_PROVIDER must say claude or per_task in the caller's environment"
        )
    if not (
        settings.standards_reader_enabled
        and settings.standards_reader_allow_public_egress
    ):
        raise Refused(
            "open lane: both STANDARDS_READER_* egress flags must be true in the caller's environment"
        )


def write_block_file(data_dir: Path, db: Path) -> tuple[int, bool]:
    """The block file of the copy, from its register-named documents. (count of register hashes, sentinel used).
    With none in the copy a sentinel hash that matches no file keeps the fail-closed rule satisfied (said in the report)."""
    spec_path = ROOT / "scripts" / "write_block_file.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("write_block_file", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod.hashes_from_db(str(db))
    sentinel = False
    if not found:
        found, sentinel = {"0" * 64}, True
    mod.write(str(data_dir), found)
    return (0 if sentinel else len(found)), sentinel


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """The app, in this process, on a loopback port (real HTTP, real worker thread, real startup)."""

    def __init__(self, port: int):
        import uvicorn

        from app.main import app

        self.port = port or free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self.server.install_signal_handlers = lambda: None
        self.thread = threading.Thread(
            target=self.server.run, daemon=True, name="trial-server"
        )

    def start(self, timeout: float = 300.0) -> None:
        self.thread.start()
        end = time.time() + timeout
        while time.time() < end:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise Refused("the app did not start")
            time.sleep(0.2)
        raise Refused("the app did not start in time")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(60)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class Http:
    def __init__(self, base: str):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(
        self, method: str, path: str, body: dict | None = None, timeout: float = 120.0
    ) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"content-type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except OSError:
            return 0, b""

    def get_json(self, path: str):
        code, raw = self.call("GET", path)
        try:
            return code, json.loads(raw) if raw else None
        except ValueError:
            return code, None


def ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------------------------------------ the checks


def static_pair_check() -> Check:
    """The core's class/word table gives a LEGAL contract pair for every line it can make (no data needed)."""
    from app import agent_review_jobs as jobs
    from app.agent_review_verdict import FAIL as VF
    from app.agent_review_verdict import PASS as VP
    from app.agent_review_verdict import QUERY, RULE_NOT_APPROVED
    from app.api import agent_review_schemas as contract

    bad: dict[tuple[str, str], int] = {}
    n = 0
    for verdict in (VP, VF, QUERY, None):
        for ai in (VP, VF, None):
            for reason in (None, "not_applicable", "absent", "met"):
                for error in (None, "stop_max_tokens", "gate_closed"):
                    for silence in (False, True):
                        for tier in (None, RULE_NOT_APPROVED):
                            for hold in (False, True):
                                line = {
                                    "item_id": "T",
                                    "verdict": verdict,
                                    "ai_verdict": ai,
                                    "reason_code": reason,
                                    "error": error,
                                    "silence_query": silence,
                                    "rule_tier": tier,
                                    "conditional_hold": hold,
                                    "why": "invented",
                                }
                                cls, word = jobs.contract_class_and_word(line)
                                n += 1
                                if (
                                    cls not in contract.LINE_TABLE
                                    or word not in contract.LINE_TABLE[cls][0]
                                ):
                                    bad[(cls, word)] = bad.get((cls, word), 0) + 1
    if bad:
        pairs = "; ".join(f'"{c}"+"{w}" x{k}' for (c, w), k in sorted(bad.items()))
        return Check(
            "class/word table legal for every core line",
            False,
            f"{len(bad)} illegal pair(s) of {n} lines: {pairs}",
        )
    return Check(
        "class/word table legal for every core line",
        True,
        f"{n} synthetic lines, all legal",
    )


def legal_rows_check(conn: sqlite3.Connection, run_id: str) -> Check:
    """Every stored line of THIS run validates against the contract's own model (the one the lines route uses)."""
    from pydantic import ValidationError

    from app.api import agent_review_schemas as contract

    bad: dict[tuple, int] = {}
    rows = conn.execute(
        "SELECT item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, part, text_source"
        " FROM agent_review_line WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    for r in rows:
        try:
            contract.AgentLine.model_validate(dict(r))
        except ValidationError:
            key = (r["verdict_class"], r["word"], r["rule_tier"])
            bad[key] = bad.get(key, 0) + 1
    if not rows:
        from app import agent_review_text

        stop = conn.execute(
            "SELECT stop_reason FROM agent_review_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        code = str((stop[0] if stop else None) or "").split(":")[0]
        if (
            code in agent_review_text.STOP_CODES
        ):  # a paper with no stored text is refused: no line is expected
            return Check(
                "stored lines legal by the contract",
                True,
                f"no line expected: the run stopped, {code}",
            )
        return Check(
            "stored lines legal by the contract", False, "the run stored no line"
        )
    if bad:
        pairs = "; ".join(
            f'"{c}"+"{w}"+tier {t!r} x{k}'
            for (c, w, t), k in sorted(bad.items(), key=str)
        )
        return Check(
            "stored lines legal by the contract",
            False,
            f"{sum(bad.values())} of {len(rows)} lines illegal: {pairs}",
        )
    return Check("stored lines legal by the contract", True, f"{len(rows)} lines")


def proof_problem(line: dict, cls: str) -> str | None:
    """Why a Pass or Fail line is not proven by code (None: proven). Cause words only."""
    from app.agent_review_verdict import BY_CODE, USABLE_TIERS

    if cls != "Proven by code":
        return "Pass or Fail outside the class Proven by code"
    qc = line.get("quotes_checked") or {}
    if not qc.get("paper"):
        return "paper quote not verified by code"
    if not qc.get("clause"):
        return "rule quote not verified by code"
    by_code = line.get("decided_by") == BY_CODE and bool(
        (line.get("compare") or {}).get("decided")
    )
    agreed = line.get("second_opinion") == "agreed" or (
        isinstance(line.get("second_opinion"), dict)
        and line["second_opinion"].get("agree") is True
    )
    if not (by_code or agreed):
        return "neither numbers compared by code nor a second opinion that agrees"
    if not (
        line.get("tier") in USABLE_TIERS
        or (line.get("checklist") is True and line.get("tier") is None)
    ):
        return "the rule is not approved"
    return None


def proof_check(conn: sqlite3.Connection, run_id: str) -> Check:
    bad: dict[str, int] = {}
    proven = {"Pass": 0, "Fail": 0}
    for r in conn.execute(
        "SELECT item_id, verdict_class, word, line_json FROM agent_review_line WHERE run_id = ?",
        (run_id,),
    ):
        if r["word"] in ("Pass", "Fail"):
            try:
                line = json.loads(r["line_json"])
            except ValueError:
                line = {}
            why = proof_problem(line, r["verdict_class"])
            if why:
                bad[why] = bad.get(why, 0) + 1
            else:
                proven[r["word"]] += 1
        elif r["verdict_class"] == "Proven by code":
            bad["class Proven by code without Pass or Fail"] = (
                bad.get("class Proven by code without Pass or Fail", 0) + 1
            )
    if bad:
        return Check(
            "Pass/Fail only with code proof",
            False,
            "; ".join(f"{why} x{k}" for why, k in sorted(bad.items())),
        )
    return Check(
        "Pass/Fail only with code proof",
        True,
        f"proven Pass {proven['Pass']}, proven Fail {proven['Fail']}",
    )


AI_WORDS = ("ai opinion", "ai reviewer's view", "query", "not proven", "one ai reader")


def contractor_rows(blob: bytes) -> list[dict]:
    """The rows of the contractor copy's comment sheet as {ref}: the rows under the 'Item No' header. Since order 13 the sheet shows no
    item id and no Status (a contractor-facing copy has the nine company columns only); a proven Fail is told by its rule book and
    clause (`Standard Reference`), matched against the stored lines."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(blob), read_only=True)
    out: list[dict] = []
    head: list | None = None
    for row in wb.worksheets[0].iter_rows(values_only=True):
        first = row[0] if row else None
        if head is None:
            if first == "Item No" and "Standard Reference" in row:
                head = list(row)
            continue
        if first not in (None, ""):
            out.append({"ref": str(row[head.index("Standard Reference")] or "")})
    if head is None:
        raise ValueError("no Item No / Standard Reference header row")
    if "Status" in head:
        raise ValueError("the contractor copy carries a Status column")
    return out


def _ai_word_cells(blob: bytes) -> int:
    """Cells of the whole contractor workbook (every sheet) with an AI opinion word or a code word."""
    from openpyxl import load_workbook

    from app import crs_ai_words

    n = 0
    for sheet in load_workbook(io.BytesIO(blob), read_only=True).worksheets:
        for row in sheet.iter_rows(values_only=True):
            for cell in row:
                text = str(cell or "").lower()
                if text and (
                    any(w in text for w in AI_WORDS) or crs_ai_words.has_banned(text)
                ):
                    n += 1
    return n


def contractor_check(
    conn: sqlite3.Connection, run_id: str, blob: bytes | None
) -> Check:
    name = "contractor copy holds proven Fail only"
    if blob is None:
        return Check(name, False, "the copy was not read")
    try:
        rows = contractor_rows(blob)
        ai_cells = _ai_word_cells(blob)
    except Exception as exc:  # noqa: BLE001
        return Check(name, False, f"not a readable workbook ({type(exc).__name__})")
    proven = collections.Counter(
        f"{r['rule_book']} clause {r['clause']}".strip()
        for r in conn.execute(
            "SELECT rule_book, clause, line_json FROM agent_review_line WHERE run_id = ? AND verdict_class = 'Proven by code'"
            " AND word = 'Fail'",
            (run_id,),
        )
        if not json.loads(r["line_json"] or "{}").get(
            "recommendation"
        )  # a 'should' Fail is never on the contractor copy
    )
    shown = collections.Counter(r["ref"] for r in rows)
    extra, missing = (
        shown - proven,
        proven - shown,
    )  # multiset match, both directions; a blank reference matches nothing
    if extra or missing or ai_cells:
        return Check(
            name,
            False,
            f"{sum(extra.values())} row(s) that are not a proven Fail, {sum(missing.values())} proven Fail row(s) missing;"
            f" {ai_cells} cell(s) with AI wording",
        )
    return Check(
        name,
        True,
        f"{len(rows)} row(s) = the {sum(proven.values())} proven Fail line(s), each matched once by its rule book and clause, no AI wording",
    )


def stop_is_true_check(conn: sqlite3.Connection, run_id: str, stop: str) -> list[Check]:
    """A text stop must be TRUE of the copy it ran on, counted straight from the tables (not by the module that wrote it)."""
    code = stop.split(":")[0]
    run = conn.execute(
        "SELECT submittal_document_id FROM agent_review_run WHERE run_id = ?", (run_id,)
    ).fetchone()
    from app import agent_review_text as t

    if run is None or code not in (t.NO_TEXT, t.NOT_INDEXED, t.STILL_READING):
        return []
    doc = run[0]
    with_text = conn.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ? AND TRIM(COALESCE(text, '')) <> ''",
        (doc,),
    ).fetchone()[0]
    chunks = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ? AND TRIM(COALESCE(text, '')) <> ''",
        (doc,),
    ).fetchone()[0]
    status = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (doc,)
    ).fetchone()
    status = status[0] if status else None
    true = {
        t.NO_TEXT: with_text == 0 and status not in t.IN_PROGRESS,
        t.NOT_INDEXED: with_text > 0 and chunks == 0 and status not in t.IN_PROGRESS,
        t.STILL_READING: status in t.IN_PROGRESS and (with_text == 0 or chunks == 0),
    }[code]
    return [
        Check(
            "the text stop is true of this copy",
            bool(true),
            f"{code}: pages with text {with_text}, chunks {chunks}, status {status}",
        )
    ]


def rules_check(
    conn: sqlite3.Connection, run_id: str, used: dict | None, require_asked: bool
) -> list[Check]:
    out: list[Check] = []
    rows = conn.execute(
        "SELECT * FROM agent_review_rule WHERE run_id = ?", (run_id,)
    ).fetchall()
    asked = [r for r in rows if r["asked"]]
    left = [r for r in rows if not r["asked"]]
    run = conn.execute(
        "SELECT stop_reason, items_total, paper_kind, equipment_json FROM agent_review_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    stop = (run["stop_reason"] if run else None) or ""
    notes = []
    with contextlib.suppress(ValueError, TypeError):
        notes = (
            (json.loads(run["equipment_json"] or "{}") or {}).get("notes") or []
            if run
            else []
        )
    # only a stop the PLAN made explains an empty rule list; a lane stop (gate_closed, not_approved, a cap) says nothing about rules
    from app import agent_review_gate, agent_review_text

    plan_stop = (
        stop.split(":")[0]
        if stop.split(":")[0]
        in (
            "paper_kind_unknown",
            agent_review_gate.KIND_NOT_ENABLED,
            "refused",
            *agent_review_text.STOP_CODES,
        )
        else ""
    )
    out.extend(stop_is_true_check(conn, run_id, stop))
    reasons: dict[str, int] = {}
    for r in left:
        reasons[r["left_out_reason"]] = reasons.get(r["left_out_reason"], 0) + 1
    if asked:
        out.append(
            Check(
                "rules asked > 0, or the plan says why none",
                True,
                f"asked {len(asked)}, left out {len(left)}",
            )
        )
    elif require_asked:
        out.append(
            Check(
                "rules asked > 0, or the plan says why none",
                False,
                f"asked 0 (strict); left out {len(left)}",
            )
        )
    elif (
        plan_stop == agent_review_text.NO_RULE
        and agent_review_text.NO_CAUSE_MARK in stop
    ):
        out.append(
            Check(
                "rules asked > 0, or the plan says why none",
                False,
                "asked 0; the plan's own cause is unknown (the fallback sentence): the old silent defect",
            )
        )
    elif left or plan_stop or notes:
        why = (
            f"left out {len(left)} {reasons}"
            if left
            else (
                f"the plan stopped: {plan_stop}"
                if plan_stop
                else f"{len(notes)} equipment note(s)"
            )
        )
        out.append(
            Check(
                "rules asked > 0, or the plan says why none",
                True,
                f"asked 0; the plan says why: {why}",
            )
        )
    else:
        out.append(
            Check(
                "rules asked > 0, or the plan says why none",
                False,
                "asked 0, left out 0, no stop reason, no note: an empty plan with no word about it",
            )
        )
    # the Rules used page
    if used is None:
        out.append(
            Check(
                "Rules used lists asked + left out, one reason each",
                False,
                "the route gave no page",
            )
        )
        return out
    problems = []
    if len(used.get("asked") or []) != len(asked):
        problems.append(
            f"asked on the page {len(used.get('asked') or [])} vs {len(asked)} stored"
        )
    if len(used.get("left_out") or []) != len(left):
        problems.append(
            f"left out on the page {len(used.get('left_out') or [])} vs {len(left)} stored"
        )
    if sum((used.get("left_out_counts") or {}).values()) != len(
        used.get("left_out") or []
    ):
        problems.append("the per-reason counts do not add up to the left-out list")
    if any(not x.get("reason") for x in used.get("left_out") or []):
        problems.append("a left-out rule without a reason")
    keys = [r["rule_key"] for r in rows]
    if len(keys) != len(set(keys)):
        problems.append("a rule listed twice")
    for x in used.get("asked") or []:
        if not (
            x.get("rule_book")
            and x.get("clause")
            and x.get("quote")
            and x.get("tier")
            and x.get("paper_kind")
        ):
            problems.append(
                "an asked rule without book, clause, quote, tier or paper kind"
            )
            break
    if run and used.get("paper_kind") != run["paper_kind"]:
        problems.append("the page's paper kind differs from the run's")
    books = {(r["standard_document_id"], r["rule_book"]) for r in rows}
    if len(used.get("books") or []) < len(books):
        problems.append(
            f"coverage lists {len(used.get('books') or [])} book(s) for {len(books)}"
        )
    detail = f"asked {len(asked)}, left out {len(left)}, books {len(books)}, reasons {reasons}"
    out.append(
        Check(
            "Rules used lists asked + left out, one reason each",
            not problems,
            "; ".join(problems) if problems else detail,
        )
    )
    return out


# ------------------------------------------------------------------------------------------------ the standing approval


def approval_check(
    conn: sqlite3.Connection, run_id: str, submittal: str, data_dir: Path
) -> Check:
    """The paper and every rule book that was ASKED are on the approved list; no register-named document is."""
    from app import claude_approved

    approved = claude_approved.approved_hashes()
    ids = {submittal} | {
        r["standard_document_id"]
        for r in conn.execute(
            "SELECT standard_document_id FROM agent_review_rule WHERE run_id = ? AND asked = 1",
            (run_id,),
        )
        if r["standard_document_id"]
    }
    sha = {
        r["id"]: (r["sha256"] or "").strip().lower()
        for r in conn.execute(
            f"SELECT id, sha256 FROM documents WHERE id IN ({','.join('?' * len(ids))})",
            sorted(ids),
        )
    }
    missing = [i for i in sorted(ids) if sha.get(i) not in approved]
    register = [
        r["sha256"].strip().lower()
        for r in conn.execute("SELECT filename, sha256 FROM documents")
        if claude_approved.is_register_name(r["filename"]) and r["sha256"]
    ]
    leaked = [h for h in register if h in approved]
    blocked_in_file = set()
    with contextlib.suppress(Exception):
        blocked_in_file = set(
            json.loads((Path(data_dir) / claude_approved.BLOCK_FILE_NAME).read_text())[
                "blocked_sha256"
            ]
        )
    problems = []
    by_hook = {
        str(r.get("sha256") or "").strip().lower()
        for r in claude_approved._entries()
        if str(r.get("status") or "").strip().lower() == claude_approved.APPROVED
        and str(r.get("source") or "").startswith(claude_approved.AUTO_SOURCE)
    }
    not_by_hook = [
        i for i in sorted(ids) if sha.get(i) in approved and sha.get(i) not in by_hook
    ]
    if not_by_hook:
        problems.append(
            f"{len(not_by_hook)} document(s) approved by a row the app did not add in this run (ids: {', '.join(not_by_hook[:5])})"
        )
    if missing:
        problems.append(
            f"{len(missing)} of {len(ids)} declared document(s) not approved (ids: {', '.join(missing[:5])})"
        )
    if leaked:
        problems.append(f"{len(leaked)} register-named document(s) are approved")
    if register and not set(register) <= blocked_in_file:
        problems.append("a register hash is not in the block file")
    return Check(
        "standing approval: paper and asked rule books approved, register blocked",
        not problems,
        "; ".join(problems)
        if problems
        else f"{len(ids)} document(s) approved, {len(register)} register document(s) blocked",
    )


def normal_review_check(
    outcome_json: str | None, status: str | None, route_text: str = ""
) -> Check:
    """The normal review completed and nothing says a step was skipped in a Claude-lane run."""
    try:
        outcome = json.loads(outcome_json or "{}") or {}
    except ValueError:
        outcome = {}
    skipped = outcome.get("ai_steps_skipped") or []
    said = SKIPPED_TEXT in (outcome_json or "") or SKIPPED_TEXT in route_text
    problems = []
    if status != "completed":
        problems.append(f"status {status}")
    if skipped:
        problems.append(
            f"{len(skipped)} AI step(s) skipped by the local-engine bar: {', '.join(sorted(str(s.get('step')) for s in skipped))}"
        )
    if said and not skipped:
        problems.append("the record says a step was skipped in a Claude-lane run")
    return Check(
        "normal review completed, no step skipped in a Claude-lane run",
        not problems,
        "; ".join(problems) or "completed, nothing skipped",
    )


# ------------------------------------------------------------------------------------------------ the run


def job_trouble(db: Path | None, run_id: str) -> str | None:
    """A review job that failed an attempt and is waiting to retry never reaches a final status for minutes: say so now, with the
    error code and the count (cause words only). None when the job is running, finished, or the copy cannot be read."""
    if db is None:
        return None
    try:
        conn = ro(db)
        row = conn.execute(
            "SELECT state, retries, error_code FROM jobs WHERE review_run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if (
        row is not None
        and row["error_code"]
        and row["state"] in ("retrying", "poisoned")
    ):
        return f"job {row['state']} after {row['error_code']} (retries {row['retries']}): the review did not finish"
    return None


def wait_for(http: Http, run_id: str, timeout: float, db: Path | None = None) -> str:
    end = time.time() + timeout
    status = "unknown"
    while time.time() < end:
        code, body = http.get_json(f"/api/reviews/runs/{run_id}")
        if code == 200 and isinstance(body, dict):
            status = str(body.get("status"))
            if status in ("completed", "failed", "cancelled"):
                return status
        trouble = job_trouble(db, run_id)
        if (
            trouble
        ):  # fail fast, and say why, instead of waiting out the queue's retries
            return f"failed: {trouble}"
        time.sleep(2.0)
    return f"timeout (last status {status})"


def import_labels(http: Http, labels_dir: Path | None) -> list[Check]:
    out: list[Check] = []
    if labels_dir is None:
        return out
    for name, route in (
        (
            "ocr-boxes.json",
            "/api/admin/ocr-boxes/import",
        ),  # first: labels on scanned pages are judged by them
        ("rule-labels.json", "/api/admin/rule-labels/import"),
        ("rule-equipment.json", "/api/admin/rule-equipment/import"),
    ):
        f = Path(labels_dir) / name
        if name == "ocr-boxes.json" and not f.is_file():
            continue  # optional: a trial without box evidence is the strict page rule, as before
        if not f.is_file():
            out.append(Check(f"label import {name}", False, "file missing"))
            continue
        status, raw = http.call("POST", route, {"path": str(f)}, timeout=600)
        try:
            counts = json.loads(raw) if raw else {}
        except ValueError:
            counts = {}
        ok = (
            status == 200
            and counts.get("unknown_rule", 0) == 0
            and counts.get("stored", 0) > 0
        )
        out.append(Check(f"label import {name}", ok, f"HTTP {status} {counts}"))
    return out


def route_checks(http: Http, run_id: str, ids: list[str]) -> tuple[list[Check], dict]:
    """Every result route answers 200 and a body the contract accepts. Returns the checks and the bodies kept."""
    kept: dict = {}
    out: list[Check] = []
    base = f"/api/reviews/runs/{run_id}"
    code, summary = http.get_json(f"{base}/agent/summary")
    out.append(Check("route summary 200", code == 200, f"HTTP {code}"))
    kept["summary"] = summary if code == 200 else None
    out.append(steadiness_check(summary if code == 200 else None))
    got, cursor, code = [], 0, 200
    while True:
        code, page = http.get_json(f"{base}/agent/lines?limit=500&cursor={cursor}")
        if code != 200 or not isinstance(page, dict):
            break
        got += page.get("lines") or []
        if not page.get("next"):
            break
        cursor = int(page["next"])
    out.append(
        Check(
            "route lines 200",
            code == 200,
            f"HTTP {code}, {len(got)} line(s) read"
            if code == 200
            else f"HTTP {code}: the line list does not load",
        )
    )
    bad_trace = []
    for item in ids:
        c, _ = http.get_json(
            f"{base}/agent/lines/{urllib.request.quote(item, safe='')}/trace"
        )
        if c != 200:
            bad_trace.append(f"{item}:{c}")
    text_state = (
        ((summary or {}).get("paper_text") or {}).get("state") if code == 200 else None
    )
    text_stop = text_state in ("no text", "not indexed")
    out.append(
        Check(
            "route trace 200 for every line",
            not bad_trace and (bool(ids) or text_stop),
            (
                f"{len(ids)} line(s)"
                if ids
                else f"no line expected: the paper has {text_state}"
            )
            if not bad_trace
            else f"{len(bad_trace)} failed: {', '.join(bad_trace[:5])}",
        )
    )
    code, used = http.get_json(f"{base}/rules-used")
    out.append(Check("route rules-used 200", code == 200, f"HTTP {code}"))
    kept["used"] = used if code == 200 else None
    if text_stop or text_state == "partly readable":
        sentence = ((summary or {}).get("paper_text") or {}).get("sentence")
        on_used = (
            ((used or {}).get("paper_text") or {}) if isinstance(used, dict) else {}
        )
        ok = bool(sentence) and on_used.get("sentence") == sentence
        if text_stop:
            ok = (
                ok
                and (summary or {}).get("stop_reason", "").endswith(sentence or "?")
                and (
                    (used or {}).get("stop_reason")
                    == (summary or {}).get("stop_reason")
                )
            )
        out.append(
            Check(
                "a paper with missing text says so on the summary and on Rules used",
                ok,
                f"state {text_state}; pages not read {(summary or {}).get('paper_text', {}).get('pages_not_read')}",
            )
        )
    for copy in ("internal", "contractor"):
        c, blob = http.call("GET", f"{base}/agent/crs?copy={copy}")
        valid = c == 200 and blob[:2] == b"PK"
        out.append(
            Check(
                f"route CRS {copy} 200 (an xlsx)", valid, f"HTTP {c}, {len(blob)} bytes"
            )
        )
        kept[copy] = blob if valid else None
    return out, kept


def spend_check(
    cfg: TrialConfig,
    summary: dict | None,
    data_dir: Path,
    lines_before: int = 0,
) -> Check:
    usd = (summary or {}).get("usd")
    lines = (
        ledger_lines(data_dir) - lines_before
    )  # lines this run added (a copied ledger has lines already)
    counts = (summary or {}).get("counts_by_class") or {}
    answered = sum(v for k, v in counts.items() if k != "Not reviewed")
    if cfg.lane == "closed":
        ok = not usd and lines == 0
        return Check(
            "spend: none in the closed lane", ok, f"usd {usd}, ledger lines {lines}"
        )
    problems = []
    reused = (summary or {}).get("answers_reused") or 0
    if (
        not usd or usd <= 0
    ) and not reused:  # a run that reused every answer spent nothing, on purpose
        problems.append("no spend recorded")
    elif usd > cfg.max_usd:
        problems.append(f"usd {usd} above the cap {cfg.max_usd}")
    if answered == 0:
        stop = (summary or {}).get("stop_reason")
        problems.append(
            "every line is Not reviewed: the lane answered nothing"
            + (f" (the run stopped: {stop})" if stop else "")
        )
    return Check(
        "spend under the cap and real answers",
        not problems,
        "; ".join(problems)
        or f"usd {usd}, {answered} line(s) answered of {sum(counts.values())}",
    )


def stop_check(cfg: TrialConfig, summary: dict | None) -> Check | None:
    """Open lane: a run that a cap or a refusal stopped did not finish its review, and the trial says so with the stop reason
    (code and numbers, never a text) instead of passing on 'completed'. A repeat run that reviewed nothing fails here."""
    if cfg.lane != "open" or summary is None:
        return None
    stop = summary.get("stop_reason")
    return Check(
        "run not stopped by a cap or a refusal",
        not stop,
        str(stop) if stop else "finished whole",
    )


def steadiness_check(summary: dict | None) -> Check:
    """Point E, free: lines that changed class since the previous finished run of this paper, and how many were decisions; the
    answers reused instead of asked. Information only (always PASS): ids are in the run's trace, never here."""
    got = (summary or {}).get("changed_since_previous")
    reused = (summary or {}).get("answers_reused")
    said = (
        f"lines that changed class since the previous run: {got['changed']} of {got['lines_compared']} "
        f"(of which decisions: {got['decisions']})"
        if got
        else "lines that changed class since the previous run: no earlier finished run, or this run did not finish whole"
    )
    return Check(
        "steadiness (information)",
        True,
        f"{said}; answers reused: {reused if reused is not None else 'not kept'}",
    )


def engine_follow(
    http, cfg: TrialConfig, first: str, db: Path, data: Path, ledger_before: int
):
    """After a start from the ONE Review button: wait for the rule check, then for the AI review that follows it (its run id is
    on the first run's stored choice). Returns (the AI review's run id or None, the checks of the choice). For "local": no AI review
    runs and the Claude ledger gets no new line."""
    checks: list[Check] = []
    final = wait_for(http, first, cfg.timeout, db)
    checks.append(Check("rule check completed", final == "completed", final))
    follow = None
    deadline = time.time() + cfg.timeout
    while cfg.engine != "local" and time.time() < deadline:
        conn = ro(db)
        try:
            row = conn.execute(
                "SELECT followed_by FROM review_engine_choice WHERE run_id = ?",
                (first,),
            ).fetchone()
        finally:
            conn.close()
        word = (row["followed_by"] if row else None) or ""
        if word:
            follow = word if not word.startswith("not started") else None
            if follow is None:
                checks.append(Check("AI review follows the rule check", False, word))
            break
        time.sleep(2.0)
    if cfg.engine == "local":
        checks.append(
            Check(
                "no Claude call (ledger unchanged)",
                ledger_lines(data) == ledger_before,
                f"lines {ledger_before} -> {ledger_lines(data)}",
            )
        )
        conn = ro(db)
        try:
            ai = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_run'"
                ).fetchone()
                and conn.execute(
                    "SELECT 1 FROM agent_review_run WHERE submittal_document_id = ? AND run_id != ? AND started_at >= "
                    "(SELECT started_at FROM review_runs WHERE id = ?)",
                    (cfg.document, first, first),
                ).fetchone()
            )
        finally:
            conn.close()
        checks.append(Check("no AI review ran (Local only)", not ai))
    return follow, checks


def run_trial(
    cfg: TrialConfig,
    *,
    lane: Callable | None = None,
    log: Callable[[str], None] = print,
) -> list[Check]:
    """Run the whole trial in this process. `lane` (tests only): replaces `agent_review_jobs.lane` with a stubbed model."""
    from app import agent_review_jobs

    if cfg.lane not in ("closed", "open"):
        raise Refused("lane must be closed or open")
    data = Path(cfg.data_dir).resolve()
    db = Path(cfg.db).resolve() if cfg.db else data / "rag_intelligence.sqlite"
    refuse_live({"data folder": data, "database": db})
    for name in cfg.sets:
        if _bad_name(name):
            raise Refused("--set will not carry a secret-looking name")
    if cfg.normal_review and not cfg.allow_local_models:
        raise Refused(
            "--normal-review may load a local model: add --allow-local-models to say you mean it"
        )
    if not db.is_file():
        raise Refused("no database in the data folder")
    facts = apply_settings(cfg)
    if cfg.lane == "open" and lane is None:
        check_open_lane_inputs(facts)
    if (
        cfg.lane == "open" and lane is not None
    ):  # a stubbed lane (tests): the stub's own invented key and open provider
        from app.config import settings

        settings.reasoning_provider = "claude"
        settings.standards_reader_enabled = (
            settings.standards_reader_allow_public_egress
        ) = True
        settings.anthropic_api_key = "test-key-not-real"
    set_aside = empty_approved_list()
    ledger_before = ledger_lines(data)
    log(
        f"approved list of the copy set aside: {set_aside}; ledger lines before: {ledger_before}"
    )
    registers, sentinel = write_block_file(data, db)
    log(
        f"settings: lane={cfg.lane} provider={facts['provider']} key_present={facts['key_present']} auto_approve={facts['auto_approve']} "
        f"register hashes={registers}{' (sentinel: none in the copy)' if sentinel else ''}"
    )
    for what, p in (("data_dir", data), ("db", db)):
        log(f"path {what}: {p}")
    checks: list[Check] = [static_pair_check()]
    original_lane = agent_review_jobs.lane
    if lane is not None:
        agent_review_jobs.lane = lane
    server = Server(cfg.port)
    try:
        server.start()
        http = Http(server.base)
        log(f"app up on {server.base}")
        code, status = http.get_json("/api/reviews/agent-status")
        want_open = cfg.lane == "open"
        checks.append(
            Check(
                "agent-status: enabled, lane matches the mode",
                code == 200
                and status.get("enabled") is True
                and status.get("claude_lane_open") is want_open,
                f"HTTP {code} {status}",
            )
        )
        labels_dir = cfg.labels_dir or (data / "labels")
        checks += import_labels(
            http, labels_dir if (labels_dir / "rule-labels.json").is_file() else None
        )
        conn = ro(db)
        n_labels = (
            conn.execute("SELECT COUNT(*) FROM rule_label").fetchone()[0]
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='rule_label'"
            ).fetchone()
            else 0
        )
        n_equip = (
            conn.execute("SELECT COUNT(*) FROM rule_equipment_label").fetchone()[0]
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='rule_equipment_label'"
            ).fetchone()
            else 0
        )
        checks.append(
            Check(
                "labels in the database",
                n_labels > 0,
                f"rule labels {n_labels}, equipment labels {n_equip}",
            )
        )
        conn.close()
        if cfg.engine:
            code, run = http.call(
                "POST",
                "/api/reviews/start",
                {
                    "submittal_document_id": cfg.document,
                    "engine": cfg.engine,
                    **({"fresh": True} if cfg.fresh else {}),
                },
            )
        else:
            code, run = http.call(
                "POST",
                "/api/reviews/agent-run",
                {
                    "submittal_document_id": cfg.document,
                    **({"fresh": True} if cfg.fresh else {}),
                },
            )
        try:
            started = json.loads(run) if run else {}
        except ValueError:
            started = {}
        run_id = started.get("review_run_id")
        first_run = run_id
        if cfg.engine and run_id:
            run_id, engine_checks = engine_follow(
                http, cfg, run_id, db, data, ledger_before
            )
        checks.append(
            Check(
                "AI review started"
                if not cfg.engine
                else f"review started (engine: {cfg.engine})",
                code == 200 and bool(first_run),
                f"HTTP {code}" + ("" if first_run else f" {str(started)[:120]}"),
            )
        )
        if cfg.engine and first_run:
            checks += engine_checks
        if run_id:
            final = wait_for(http, run_id, cfg.timeout, db)
            checks.append(Check("AI review completed", final == "completed", final))
            conn = ro(db)
            ids = [
                r["item_id"]
                for r in conn.execute(
                    "SELECT item_id FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
                    (run_id,),
                )
            ]
            rcs, kept = route_checks(http, run_id, ids)
            checks += rcs
            checks.append(legal_rows_check(conn, run_id))
            checks += rules_check(
                conn, run_id, kept.get("used"), cfg.require_rules_asked
            )
            checks.append(proof_check(conn, run_id))
            checks.append(contractor_check(conn, run_id, kept.get("contractor")))
            checks.append(spend_check(cfg, kept.get("summary"), data, ledger_before))
            stopped = stop_check(cfg, kept.get("summary"))
            if stopped is not None:
                checks.append(stopped)
            checks.append(approval_check(conn, run_id, cfg.document, data))
            conn.close()
        if cfg.normal_review and run_id:
            code, run2 = http.call(
                "POST", "/api/reviews/run", {"submittal_document_id": cfg.document}
            )
            try:
                started2 = json.loads(run2) if run2 else {}
            except ValueError:
                started2 = {}
            rid2 = started2.get("review_run_id")
            if code != 200 or not rid2:
                checks.append(Check("normal review started", False, f"HTTP {code}"))
            else:
                final2 = wait_for(http, rid2, cfg.timeout)
                conn = ro(db)
                row = conn.execute(
                    "SELECT status, outcome_json FROM review_runs WHERE id = ?", (rid2,)
                ).fetchone()
                conn.close()
                checks.append(
                    normal_review_check(
                        row["outcome_json"] if row else None,
                        row["status"] if row else final2,
                    )
                )
    finally:
        server.stop()
        agent_review_jobs.lane = original_lane
    return checks


def table(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [
        f"| {'check'.ljust(width)} | result | detail |",
        f"|{'-' * (width + 2)}|--------|--------|",
    ]
    lines += [f"| {c.name.ljust(width)} | {c.word}   | {c.detail} |" for c in checks]
    failed = [c for c in checks if not c.ok]
    lines.append(
        f"{len(checks) - len(failed)} of {len(checks)} checks passed"
        + ("" if not failed else f"; FAILED: {', '.join(c.name for c in failed)}")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lane", choices=("closed", "open"), required=True)
    ap.add_argument(
        "--data-dir",
        required=True,
        help="a COPY of the data folder (the database is rag_intelligence.sqlite inside)",
    )
    ap.add_argument(
        "--copy-to",
        default=None,
        help="copy the data folder here first (a new folder); the source stays as it was",
    )
    ap.add_argument(
        "--in-place",
        action="store_true",
        help="work in --data-dir itself (it is written)",
    )
    ap.add_argument(
        "--db",
        default=None,
        help="the database (default: <data dir>/rag_intelligence.sqlite)",
    )
    ap.add_argument(
        "--document", required=True, help="the document id of the paper to review"
    )
    ap.add_argument("--labels-dir", default=None, help="default <data dir>/labels")
    ap.add_argument(
        "--max-usd",
        type=float,
        default=2.0,
        help="open lane: the cap of this run, on top of the app's own caps",
    )
    ap.add_argument(
        "--normal-review",
        action="store_true",
        help="also start ONE normal review and check nothing was skipped in a Claude-lane run",
    )
    ap.add_argument(
        "--allow-local-models",
        action="store_true",
        help="needed for --normal-review: it may load the local engine",
    )
    ap.add_argument(
        "--require-rules-asked",
        action="store_true",
        help="fail when no rule was asked, even if the plan says why",
    )
    ap.add_argument(
        "--engine",
        choices=("automatic", "claude", "local"),
        default=None,
        help="start from the one Review button's route with this choice (default: the older AI review start)",
    )
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a non-secret setting for this run (e.g. REASONING_PROVIDER=per_task)",
    )
    ap.add_argument("--skills-dir", default=None)
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="ask for fresh first-reader answers: ignore the stored ones and replace them (with AGENT_REVIEW_REUSE_ANSWERS_ENABLED on)",
    )
    ap.add_argument("--out", default=None, help="write the table as JSON here")
    a = ap.parse_args(argv)
    sets = {}
    for item in a.set:
        name, _, value = item.partition("=")
        sets[name.strip()] = value
    try:
        src = Path(a.data_dir).resolve()
        if bool(a.copy_to) == bool(a.in_place):
            raise Refused("give exactly one of --copy-to (a new folder) or --in-place")
        work = Path(a.copy_to).resolve() if a.copy_to else src
        refuse_live({"data folder": src, "work folder": work})
        if a.copy_to:
            copy_data(src, work)
        db = Path(a.db).resolve() if a.db else None
        if a.copy_to and db is not None:
            with contextlib.suppress(ValueError):
                db = work / db.relative_to(src)
        cfg = TrialConfig(
            data_dir=work,
            document=a.document,
            lane=a.lane,
            db=db,
            labels_dir=Path(a.labels_dir) if a.labels_dir else None,
            max_usd=a.max_usd,
            normal_review=a.normal_review,
            allow_local_models=a.allow_local_models,
            require_rules_asked=a.require_rules_asked,
            timeout=a.timeout,
            port=a.port,
            sets=sets,
            skills_dir=a.skills_dir,
            fresh=a.fresh,
            engine=a.engine,
        )
        checks = run_trial(cfg)
    except Refused as exc:
        print(f"REFUSED | {exc}", flush=True)
        return 2
    print(table(checks))
    if a.out:
        Path(a.out).write_text(
            json.dumps(
                [
                    {"check": c.name, "result": c.word, "detail": c.detail}
                    for c in checks
                ],
                indent=1,
            ),
            encoding="utf-8",
        )
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
