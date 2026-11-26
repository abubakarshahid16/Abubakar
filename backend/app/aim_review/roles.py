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

THE LEDGER. A call row's `request_sha256` is the digest of the request's parts (system, cached block, prompt). The money ledger
keeps the digest of the whole request BODY, which only the Claude call builds, with the key in its request. So the two are matched
by step and by the exact documents a call declared (`scripts/nine_record_check.py`, invariant 7): every ledger reservation of the
run must match a record call.

IDS, NUMBERS, CODES AND CHECKSUMS ONLY: never a title, a file name, any document text or any model output. Money: each step keeps
its own ledger line (its USD 5 step cap) and the run its USD 15 cap, as today; this module changes neither (`claude_spend` untouched).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
#: The page-picture stage's prompt names its page (`picture_stage._transcribe`: "Page n. Transcribe it.").
_PICTURE_PAGE = re.compile(r"Page (\d+)\.")
PICTURE_STEP = "aim_page_pictures"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_schema(conn=None) -> None:
    """The record's tables exist afterwards. With no connection (the app's schema sweep calls every module's `ensure_schema()` bare),
    one is opened and committed, like the other stores."""
    if conn is None:
        from app import db

        own = db.connect()
        ensure_schema(own)
        own.commit()
        return
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
            request_sha256 TEXT NOT NULL, chars INTEGER NOT NULL, book_text_unmatched INTEGER NOT NULL DEFAULT 0,
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


def _upgrade(conn) -> None:
    """A call table made before the rule-book piece count gets that count (a table of an earlier build of this branch)."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({CALLS})")}
    if "book_text_unmatched" not in cols:
        conn.execute(
            f"ALTER TABLE {CALLS} ADD book_text_unmatched INTEGER NOT NULL DEFAULT 0"
        )


def _db():
    from app import db

    conn = db.connect()  # thread-local: the judge's calls run side by side, each thread writes on its own connection
    ensure_schema(conn)
    _upgrade(conn)
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


#: How a rule cut at its size ends in the material (`material.material`).
_CUT = " [CUT: rule text longer than shown]"
_WS = re.compile(r"\s+")


def probes(request: str) -> list[tuple[str, str]]:
    """The rule-book text pieces a request holds, as the steps write them, each once: a rule's text and a page of a book read by its
    pages (`material._material_line`), and a held item's clause window (`steps._shown_item`: whitespace folded, as the judge gets
    it). An always-on or knowledge item's "clause_text" is the app's own facts, not a book's text: not a piece."""
    from .steps import HELD

    dec, out, seen = json.JSONDecoder(), [], set()
    for m in re.finditer(r'\{"', request):
        try:
            o, _end = dec.raw_decode(request, m.start())
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        if "rule" in o and isinstance(o.get("text"), str):
            piece = ("rule", o["text"].removesuffix(_CUT))
        elif isinstance(o.get("page_text"), str):
            piece = ("page", o["page_text"])
        elif (
            o.get("source") == HELD
            and isinstance(o.get("clause_text"), str)
            and o["clause_text"].strip()
        ):
            piece = ("window", o["clause_text"])
        else:
            continue
        if piece[1] and piece not in seen:
            seen.add(piece)
            out.append(piece)
    return out


class Books:
    """The stored rules and pages of the run's rule books, each read once (the record's own reading: nothing is sent)."""

    def __init__(self) -> None:
        self._lock, self._rules, self._pages = threading.Lock(), {}, {}

    def rules(self, doc: str) -> dict[str, int]:
        """{a rule's text as the material sends it (cut at its size): its page}."""
        from .material import RULE_CHARS

        with self._lock:
            if doc not in self._rules:
                rows = _db().execute("SELECT page, source_text, requirement_text FROM standard_requirements WHERE standard_document_id = ?",
                                     (doc,)).fetchall()  # fmt: skip
                self._rules[doc] = {
                    str(r[1] or r[2] or "")[:RULE_CHARS]: int(r[0] or 0)
                    for r in rows
                    if (r[1] or r[2])
                }
            return self._rules[doc]

    def pages(self, doc: str) -> dict[int, tuple[str, str]]:
        """{page: (its stored text, the same text whitespace-folded)} (`agent_review_standards.read_book`, as `library.BookText`)."""
        with self._lock:
            if doc not in self._pages:
                from app import agent_review_standards

                pages = agent_review_standards.read_book(_db(), doc).pages
                self._pages[doc] = {
                    int(p): (t, _WS.sub(" ", t)) for p, t in pages.items() if t
                }
            return self._pages[doc]


def _book_pieces(
    doc: str, pieces: list[tuple[str, str]], books: Books
) -> list[tuple[int, str]]:
    """(page, text) of each piece that is this book's own stored text: a rule by its text, a page by its whole text, a window
    found inside one of its folded pages."""
    out = []
    rules = books.rules(doc)
    for kind, text in pieces:
        if kind == "rule" and text in rules:
            out.append((rules[text], text))
        elif kind in ("page", "window"):
            for p, (raw, flat) in sorted(books.pages(doc).items()):
                if (kind == "page" and raw == text) or (
                    kind == "window" and text in flat
                ):
                    out.append((p, text))
                    break
    return out


def reads_of(
    request: str, carries, paper, step: str, books: Books | None = None
) -> tuple[list[dict], int]:
    """The read rows of ONE request, by code from its own text, and the count of rule-book pieces no declared book holds: one row
    per declared document, with the pages whose text is in it. The paper: each stored page whose marked text (`paper._marked`, as
    `steps.paper_block` sends it) stands in the request. A reference paper: the pages of its "[page n]" windows. A rule book: the
    pages of the rules, pages and clause windows of it the request holds (`probes`), with their size and checksum; a book the
    call only names (the librarian's catalogue) holds none (chars 0)."""
    from .paper import _marked

    rows, pieces = [], probes(request)
    matched: set[tuple[str, str]] = set()
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
            mine = (
                _book_pieces(doc, pieces, books) if books is not None and pieces else []
            )
            matched |= {(k, x) for k, x in pieces if any(x == y for _p, y in mine)}
            text = "".join(x for _p, x in mine)
            rows.append({"document_id": doc, "document_kind": "rule_book", "pages": sorted({p for p, _x in mine}), "chars": len(text),
                         "text_sha256": _sha(text) if mine else None})  # fmt: skip
    return rows, (
        len([x for x in pieces if x not in matched]) if books is not None else 0
    )


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
        self.books = Books()

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
        reads, unmatched = reads_of(request, carries, paper, step, self.books)
        conn = _db()
        with conn:
            conn.execute(
                f"INSERT INTO {CALLS} (run_id, role_no, call_id, step, engine, model, request_sha256, chars, book_text_unmatched,"
                " state, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?)",
                (
                    self.run_id,
                    role,
                    call_id,
                    step,
                    engine,
                    str(kw.get("model") or ""),
                    _sha(request),
                    len(request),
                    unmatched,
                    _now(),
                ),
            )
            for seq, r in enumerate(reads, 1):
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

    @property
    def pictures(self) -> Recorded:
        """The page-picture reader's hook (`pictures._Metered`): its calls leave by their own route, so they are recorded here."""
        return self

    def picture_sent(self, packet, model: str) -> str:
        """A page picture of the paper about to be sent: a "sent" call row of the reader (role 1) and the paper's read row with its page,
        the picture count and the checksum of the picture bytes (no text is in it). The page is the one the stage names in its prompt."""
        m = _PICTURE_PAGE.match(str(getattr(packet, "prompt", "") or ""))
        images = tuple(getattr(packet, "images", ()) or ())
        blob = b"".join(
            i if isinstance(i, bytes | bytearray) else str(i).encode() for i in images
        )
        call_id = uuid.uuid4().hex
        conn = _db()
        with conn:
            conn.execute(f"INSERT INTO {CALLS} (run_id, role_no, call_id, step, engine, model, request_sha256, chars, state, sent_at)"
                         " VALUES (?, 1, ?, ?, 'claude', ?, ?, ?, 'sent', ?)",
                         (self.run_id, call_id, PICTURE_STEP, str(model or ""), hashlib.sha256(blob).hexdigest(),
                          len(str(getattr(packet, "prompt", "") or "")), _now()))  # fmt: skip
            conn.execute(f"INSERT INTO {READS} (run_id, role_no, call_id, seq, document_id, document_kind, pages_json, chars, text_sha256,"
                         " pictures) VALUES (?, 1, ?, 1, ?, 'paper', ?, 0, ?, ?)",
                         (self.run_id, call_id, self.paper_id, json.dumps([int(m.group(1))] if m else []),
                          hashlib.sha256(blob).hexdigest() if blob else None, len(images)))  # fmt: skip
        return call_id

    def picture_end(self, call_id: str, state: str, code: str | None) -> None:
        self._end(call_id, state, code)

    def _end(self, call_id: str, state: str, code: str | None) -> None:
        conn = _db()
        with conn:
            conn.execute(f"UPDATE {CALLS} SET state = ?, error_code = ? WHERE run_id = ? AND call_id = ?",
                         (state, code, self.run_id, call_id))  # fmt: skip


def wrap(model, run_id: str, paper_id: str) -> Recorded:
    """The run's model with the role record around it; the nine rows are written now ("not run: not reached")."""
    start(str(run_id))
    return Recorded(model, run_id, paper_id)


def project_held(conn, paper_id: str) -> dict[str, int]:
    """Role 2 by code when it makes no call (SPEC A.3: "it RAN and its note lists what is not available"): what the library holds
    of this paper's project, counts only. A project paper with no recorded project, or no paper id, holds nothing found."""
    from app import claude_approved

    from .references import PACKAGE_ROLE

    try:
        row = conn.execute(
            "SELECT project FROM document_classification WHERE document_id = ?",
            (paper_id,),
        ).fetchone()
        project = str(row[0] or "").strip() if row else ""
        earlier = conn.execute(
            "SELECT count(*) FROM document_classification WHERE superseded_by = ?",
            (paper_id,),
        ).fetchone()[0]
        same = conn.execute("SELECT document_role, count(*) FROM document_classification WHERE project = ? AND document_id != ?"
                            " GROUP BY document_role", (project, paper_id)).fetchall() if project else []  # fmt: skip
    except sqlite3.Error:
        return {"project_recorded": 0}
    roles_held = {str(r[0] or ""): int(r[1]) for r in same}
    return {
        "project_recorded": int(bool(project)),
        "project_specifications_held": roles_held.get(
            claude_approved.SPECIFICATION_ROLE, 0
        ),
        "earlier_revisions_held": int(earlier),
        "related_papers_held": roles_held.get("CONTRACTOR_SUBMITTAL", 0),
        "contract_documents_held": roles_held.get(PACKAGE_ROLE, 0),
    }


def finish(run_id: str, result: dict) -> None:
    """Each role's row at the run's end, from its call rows and the run's stored calls and lines (counts only). A role with calls
    "ran", or "ran partly" when a call failed or was refused; a role with no call "not run" with the reason; the two code roles ran."""
    conn = _db()
    calls = [dict(r) for r in conn.execute(f"SELECT role_no, step, engine, model, state, error_code, book_text_unmatched FROM {CALLS} WHERE run_id = ?",
                                           (str(run_id),))]  # fmt: skip
    reads = [dict(r) for r in conn.execute(f"SELECT role_no, document_kind, document_id, pages_json, pictures FROM {READS} WHERE run_id = ?",
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
            if n == 2:
                produced |= project_held(conn, _paper_of(conn, str(run_id)))
            if n in CODE_ROLES or (
                n == 2 and not mine
            ):  # role 2 with no call ran by code: what the project holds
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


def _paper_of(conn, run_id: str) -> str:
    try:
        row = conn.execute(
            "SELECT paper_document_id FROM aim_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row else ""


def _produced(n: int, calls: list[dict], reads: list[dict], lines: list[dict]) -> dict:
    """Counts only, per role (SPEC section B, in the general review's terms)."""
    out: dict = (
        {"calls_answered": sum(1 for c in calls if c["state"] == "answered")}
        if n not in CODE_ROLES
        else {}
    )
    if n == 1:
        out["page_pictures_sent"] = sum(int(r.get("pictures") or 0) for r in reads)
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
    if n not in CODE_ROLES and any(r["document_kind"] == "rule_book" for r in reads):
        out["rule_books_declared"] = len(
            {r["document_id"] for r in reads if r["document_kind"] == "rule_book"}
        )
        out["rule_book_pages_sent"] = len({(r["document_id"], p) for r in reads if r["document_kind"] == "rule_book"
                                           for p in json.loads(r["pages_json"])})  # fmt: skip
        out["book_text_not_matched"] = sum(
            int(c.get("book_text_unmatched") or 0) for c in calls
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
