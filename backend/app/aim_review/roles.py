"""THE NINE ROLES ON THE GENERAL REVIEW: the stored record of what each role SENT and PRODUCED (owner order of 15 Nov 2026, the
nine-role senior reviewer; lead-4, 26 Nov 2026: built on the general method, not on the old engine, whose spec
`order13/nine/SPEC.md` sections B and F carry over unchanged). Behind AIM_U13_ENABLED (off; no new switch). Off: this module is
never imported, no table is made, every request and every stored byte is main's (`updates.nine_wrap` returns the model as given).

The nine roles are the general review's own steps (C's map, lead-4 26 Nov):

  1 Reader            page reading, the page pictures, naming the paper     5 Checklist         the checklist step
  2 Project context   the reference papers                                  6 Second reviewer   the attack, the second read, the
  3 Librarian         rule-book selection                                                       whole-paper check
  4 Reviewer          the judge                                             7 Code              code's number checks (no call)
  8 Decision rule     the labels code gives each line (no call)             9 Writer            the editor, the card and the sheet

THE ONE WAY OUT. Every model call of a run passes through `Recorded.ask` (the run's model; `engine.run` wraps its `_Carried` in it),
so the record is written at the one place a request leaves, FROM that request: a "sent" call row before it is handed on, then one
read row per document the call declares (`carries`: the same ids the approval gate is given, `claude_approved.carrying`), with the
pages whose exact text is in the request, found by code (`paper._marked` for the paper; the "[page n]" window markers of a
reference paper). So the record cannot name a document the gate was not told of, and the gate cannot be told of one the record
leaves out. A request holding a page of the paper under review that does not declare the paper is REFUSED before it leaves.

IDS, NUMBERS, CODES AND CHECKSUMS ONLY: never a title, a file name, any document text or any model output. Money: each step keeps
its own ledger line (its USD 5 step cap) and the run its USD 15 cap, as today; this module changes neither (`claude_spend` untouched).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import UTC, datetime

ROLE_NAMES = {
    1: "Reader",
    2: "Project context",
    3: "Librarian",
    4: "Reviewer",
    5: "Checklist",
    6: "Second reviewer",
    7: "Code",
    8: "Decision rule",
    9: "Writer",
}
#: The general review's step names, each under its role. A step not named here is the reviewer's (role 4) and is counted apart.
ROLE_OF_STEP = {
    "aim_read_pages": 1,
    "aim_unread_pages": 1,
    "aim_unread_check": 1,
    "aim_page_pictures": 1,
    "aim_identify": 1,
    "aim_reference": 2,
    "aim_select": 3,
    "aim_judge": 4,
    "aim_checklist": 5,
    "aim_checklist_knowledge": 5,
    "aim_checklist_retry": 5,
    "aim_attack": 6,
    "aim_attack_items": 6,
    "aim_second_read": 6,
    "aim_answered": 6,
    "aim_edit": 9,
}
CODE_ROLES = (7, 8)  # roles that make no call: code's own work, recorded as counts
ROLES, CALLS, READS = (
    "agent_review_role",
    "agent_review_role_call",
    "agent_review_role_read",
)
NOT_REACHED = "not reached"
NO_CALL = "no call of this role in this run"
#: Failures raised BEFORE anything was sent (`engine._NOT_SENT`): the call row says "refused", never "failed".
NOT_SENT = (
    "run_cap",
    "gate_closed",
    "bad_shape",
    "stop",
    "build_saw_paper",
    "undeclared_paper",
)
_REF_PAGE = re.compile(r"\[page (\d+)\]\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_schema(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {ROLES} (
            run_id TEXT NOT NULL, role_no INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9), role TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('ran', 'ran_partly', 'not_run')), why TEXT,
            engine TEXT CHECK (engine IS NULL OR engine IN ('claude', 'local', 'code')),
            models_json TEXT NOT NULL DEFAULT '[]', calls INTEGER NOT NULL DEFAULT 0, usd REAL CHECK (usd IS NULL OR usd >= 0),
            started_at TEXT, finished_at TEXT, produced_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (run_id, role_no),
            CHECK (state = 'ran' OR (why IS NOT NULL AND length(trim(why)) > 0)))"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {CALLS} (
            run_id TEXT NOT NULL, role_no INTEGER NOT NULL CHECK (role_no BETWEEN 1 AND 9), call_id TEXT NOT NULL,
            step TEXT NOT NULL, engine TEXT NOT NULL CHECK (engine IN ('claude', 'local')), model TEXT NOT NULL,
            request_sha256 TEXT NOT NULL, chars INTEGER NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('sent', 'answered', 'failed', 'refused')), error_code TEXT, sent_at TEXT NOT NULL,
            PRIMARY KEY (run_id, call_id))"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {READS} (
            run_id TEXT NOT NULL, role_no INTEGER NOT NULL, call_id TEXT NOT NULL, seq INTEGER NOT NULL, document_id TEXT NOT NULL,
            document_kind TEXT NOT NULL CHECK (document_kind IN ('paper', 'rule_book', 'project_document')),
            pages_json TEXT NOT NULL, chars INTEGER, text_sha256 TEXT, pictures INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, call_id, seq))"""
    )


def _db():
    from app import db

    conn = db.connect()  # thread-local: the judge's calls run side by side, each thread writes on its own connection
    ensure_schema(conn)
    return conn


def start(run_id: str) -> None:
    """The nine rows of a run, all "not run: not reached"; a row a restarted run already holds is kept."""
    conn = _db()
    with conn:
        for n, name in ROLE_NAMES.items():
            conn.execute(
                f"INSERT OR IGNORE INTO {ROLES} (run_id, role_no, role, state, why) VALUES (?, ?, ?, 'not_run', ?)",
                (run_id, n, name, NOT_REACHED),
            )


def reads_of(request: str, carries, paper, step: str) -> list[dict]:
    """The read rows of ONE request, by code from its own text: one row per declared document, with the pages whose text is in it.
    The paper: each stored page whose marked text (`paper._marked`, as `steps.paper_block` sends it) stands in the request. A
    reference paper: the pages of its "[page n]" windows. A rule book: the document only (its pages are not derived yet)."""
    from .paper import _marked

    rows = []
    for doc in sorted(str(c) for c in carries or ()):
        if paper is not None and doc == paper.paper_id:
            found = [
                (n, t)
                for n, t in sorted(paper.pages.items())
                if t and _marked(n, t) in request
            ]
            text = "".join(t for _n, t in found)
            rows.append({"document_id": doc, "document_kind": "paper", "pages": [n for n, _t in found], "chars": len(text),
                         "text_sha256": _sha(text) if found else None})  # fmt: skip
        elif step == "aim_reference":
            pages = sorted({int(p) for p in _REF_PAGE.findall(request)})
            rows.append({"document_id": doc, "document_kind": "project_document", "pages": pages, "chars": None, "text_sha256": None})  # fmt: skip
        else:
            rows.append({"document_id": doc, "document_kind": "rule_book", "pages": [], "chars": None, "text_sha256": None})  # fmt: skip
    return rows


def undeclared_paper(request: str, carries, paper) -> bool:
    """A page of the paper under review stands in the request, but the call does not declare the paper."""
    from .paper import _marked

    if paper is None or str(paper.paper_id) in {str(c) for c in carries or ()}:
        return False
    return any(
        t and len(t) >= 40 and _marked(n, t) in request for n, t in paper.pages.items()
    )


class Recorded:
    """The run's model with the role record around it: every call writes its rows before it is handed on (see the module text)."""

    def __init__(self, model, run_id: str, paper_id: str) -> None:
        self.model, self.run_id, self.paper_id = model, str(run_id), str(paper_id)
        self._paper, self._loaded, self._lock = None, False, threading.Lock()

    def __getattr__(
        self, name
    ):  # dry, meter and anything else the steps read: the run's own model's
        return getattr(self.model, name)

    def _paper_now(self):
        with self._lock:
            if not self._loaded:
                from app import db

                from .paper import load_paper

                self._paper, self._loaded = (
                    load_paper(db.connect(), self.paper_id),
                    True,
                )
            return self._paper

    def _engine(self) -> str:
        inner = getattr(self.model, "model", self.model)
        return "local" if str(getattr(inner, "engine", "")) == "local" else "claude"

    def ask(self, **kw):
        from .engine import StepFailed

        step = str(kw.get("step") or "")
        role = ROLE_OF_STEP.get(step, 4)
        request = "\x00".join(
            str(kw.get(k) or "") for k in ("system", "cached", "prompt")
        )
        paper, carries = self._paper_now(), kw.get("carries") or ()
        call_id, engine = uuid.uuid4().hex, self._engine()
        conn = _db()
        with conn:
            conn.execute(
                f"INSERT INTO {CALLS} (run_id, role_no, call_id, step, engine, model, request_sha256, chars, state, sent_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?)",
                (
                    self.run_id,
                    role,
                    call_id,
                    step,
                    engine,
                    str(kw.get("model") or ""),
                    _sha(request),
                    len(request),
                    _now(),
                ),
            )
            for seq, r in enumerate(reads_of(request, carries, paper, step), 1):
                conn.execute(
                    f"INSERT INTO {READS} (run_id, role_no, call_id, seq, document_id, document_kind, pages_json, chars, text_sha256)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.run_id, role, call_id, seq, r["document_id"], r["document_kind"], json.dumps(r["pages"]), r["chars"],
                     r["text_sha256"]),
                )  # fmt: skip
        if undeclared_paper(request, carries, paper):
            self._end(call_id, "refused", "undeclared_paper")
            raise StepFailed(
                f"{step}: undeclared_paper (a page of the paper is in the request; the call does not declare it)"
            )
        try:
            out = self.model.ask(**kw)
        except StepFailed as exc:
            code = str(exc).split(":", 1)[-1].strip().split(" ", 1)[0]
            self._end(call_id, "refused" if code in NOT_SENT else "failed", code[:60])
            raise
        self._end(call_id, "answered", None)
        return out

    def _end(self, call_id: str, state: str, code: str | None) -> None:
        conn = _db()
        with conn:
            conn.execute(f"UPDATE {CALLS} SET state = ?, error_code = ? WHERE run_id = ? AND call_id = ?",
                         (state, code, self.run_id, call_id))  # fmt: skip


def wrap(model, run_id: str, paper_id: str) -> Recorded:
    """The run's model with the role record around it; the nine rows are written now ("not run: not reached")."""
    start(str(run_id))
    return Recorded(model, run_id, paper_id)


def finish(run_id: str, result: dict) -> None:
    """Each role's row at the run's end, from its call rows and the run's stored calls and lines (counts only). A role with calls
    "ran", or "ran partly" when a call failed or was refused; a role with no call "not run" with the reason; the two code roles ran."""
    conn = _db()
    calls = [dict(r) for r in conn.execute(f"SELECT role_no, step, engine, model, state, error_code FROM {CALLS} WHERE run_id = ?",
                                           (str(run_id),))]  # fmt: skip
    reads = [dict(r) for r in conn.execute(f"SELECT role_no, document_kind, document_id, pages_json FROM {READS} WHERE run_id = ?",
                                           (str(run_id),))]  # fmt: skip
    usd_of: dict[int, float] = {}
    for c in result.get("calls") or []:
        if isinstance(c, dict) and c.get("engine") != "local":
            n = ROLE_OF_STEP.get(str(c.get("step") or ""), 4)
            usd_of[n] = usd_of.get(n, 0.0) + float(c.get("usd") or 0.0)
    lines = [x for x in result.get("lines") or [] if isinstance(x, dict)]
    with conn:
        for n in ROLE_NAMES:
            mine = [c for c in calls if c["role_no"] == n]
            produced = _produced(
                n, mine, [r for r in reads if r["role_no"] == n], lines
            )
            if n in CODE_ROLES:
                state, why, engine, usd = "ran", None, "code", None
            elif not mine:
                state, why, engine, usd = "not_run", NO_CALL, None, None
            else:
                bad = sorted(
                    {
                        str(c["error_code"] or c["state"])
                        for c in mine
                        if c["state"] in ("failed", "refused", "sent")
                    }
                )
                state, why = (
                    ("ran_partly", ("calls not answered: " + ", ".join(bad))[:120])
                    if bad
                    else ("ran", None)
                )
                engine = mine[0]["engine"]
                usd = None if engine == "local" else round(usd_of.get(n, 0.0), 6)
            conn.execute(
                f"UPDATE {ROLES} SET state = ?, why = ?, engine = ?, models_json = ?, calls = ?, usd = ?, finished_at = ?,"
                " produced_json = ? WHERE run_id = ? AND role_no = ?",
                (state, why, engine, json.dumps(sorted({c["model"] for c in mine})), len(mine), usd, _now(),
                 json.dumps(produced, sort_keys=True), str(run_id), n),
            )  # fmt: skip


def _produced(n: int, calls: list[dict], reads: list[dict], lines: list[dict]) -> dict:
    """Counts only, per role (SPEC section B, in the general review's terms)."""
    out: dict = (
        {"calls_answered": sum(1 for c in calls if c["state"] == "answered")}
        if n not in CODE_ROLES
        else {}
    )
    if n == 1:
        out["paper_pages_sent"] = len(
            {
                p
                for r in reads
                if r["document_kind"] == "paper"
                for p in json.loads(r["pages_json"])
            }
        )
    if n == 2:
        out["project_documents_read"] = len(
            {
                r["document_id"]
                for r in reads
                if r["document_kind"] == "project_document"
            }
        )
    if n == 3:
        out["rule_books_offered"] = len(
            {r["document_id"] for r in reads if r["document_kind"] == "rule_book"}
        )
    if n == 7:
        out["lines_compared_by_code"] = sum(
            1 for x in lines if x.get("code_compare_json") or x.get("code_compare")
        )
    if n == 8:
        for x in lines:
            k = "lines " + str(x.get("label") or "Question")
            out[k] = out.get(k, 0) + 1
    return out
