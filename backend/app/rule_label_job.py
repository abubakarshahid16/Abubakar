"""The rule-label job (owner decision 1, 11 Nov 2026): label each rule with its paper kind and field, then let a SECOND,
DIFFERENT Claude model answer the same question; code decides (`rule_labels.decide`) and finds the quote on the page.

WHAT IT DOES, per rule:
  1. CODE finds the rule's quote word for word on the rule-book page it cites (`compiled_rule_proof.quote_verified`
     on the page text as the app cites it, recognised (OCR) text over the text layer). A rule whose quote is not found
     is `quote_not_found` and is NEVER sent to a model.
  2. Pass a, then pass b with a different model, each shown ONLY rule-book text: the clause number and the quote. A
     model answers per rule: paper kind, field (datasheet only, from the app's fixed field list), and its own
     reading (comparator, numbers, unit, strength). It echoes the quote's first three words, so code can tell the
     answer belongs to THIS rule; a model never sees the other pass's answers or any paper.
  3. `rule_labels.decide` reads both answers by code (numbers and units against the quote, readings compared as
     numbers) and sets the state. A model error, an unreadable answer or a wrong echo leaves the rule unlabelled for
     that pass. No AI word decides a state.

WRITES ONLY A DATABASE COPY. `refuse_live` (the project's `live_guard`) refuses a live-shaped path, a symlink or hard
link to one, its `-wal` file and its folder; every public function that takes a connection checks the connection's own
file again. The live database receives labels only through the server's import route (`rule_label_import`). The
existing tables, `rulebook_approval` among them, are never written.

MONEY. Every call goes through `agent_claude._call` (`reader_transport` + `claude_spend.metered`: the app's caps), and
first through an INJECTED order ledger (`reserve` before the send, `settle` with the real usage after; see
`CapLedger`): a paid pass without one is refused. Only standards of the families the owner opened to the Claude lane
(SAES, ISO, API, ASME, NACE) are sent, each declared with `claude_approved.per_request_consent`.

Run it with `scripts/run_rule_labels.py`. The switch `agent_review_enabled` must be on (the tables are created only
then).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote as urlquote

from . import agent_claude, claude_spend, live_guard, rule_label_ocr, rule_labels
from .compiled_rule_proof import quote_verified
from .rule_label_lane import (  # noqa: F401 - CapLedger: the script's name for it
    CapLedger,
    Lane,
    OrderStopReached,
)
from .rule_label_prompt import (
    BATCH_RULES,
    build_parts,
    field_list,
    max_tokens_for,
    parse_answers,
    system_text,
    user_text,
)
from .rule_label_schema import (
    LABELLED_A,
    NEEDS_HUMAN,
    create_tables,
    require_on,
)

logger = logging.getLogger(__name__)

EXPORT_FORMAT = "rule-labels-v1"
DEFAULT_MODEL_A = "claude-sonnet-5-5"
DEFAULT_MODEL_B = "claude-opus-5-5"
#: The families of standards the owner opened to the Claude lane (CLAUDE.md rule 1; 3 Nov 2026, #1584).
ALLOWED_FAMILIES = frozenset({"SAES", "ISO", "API", "ASME", "NACE"})
SOURCES = ("requirement", "rulebook")


class LabelError(RuntimeError):
    """A refusal with a plain reason (never rule-book or paper text)."""


# ------------------------------------------------------------------------------------------------ the database copy


def refuse_live(path: str | os.PathLike) -> Path:
    """The resolved path of a database COPY, or LabelError when it is a live database (by the project's `live_guard`: its
    shape, a link to a known live file, its `-wal`/`-shm` file) or sits in a live database's folder."""
    real = Path(path).expanduser().resolve()
    base = real.with_name(re.sub(r"-(wal|shm)$", "", real.name))
    if live_guard.is_live_shaped(real) or live_guard.is_live_shaped(base):
        raise LabelError("this is the live database; work on a COPY")
    if any(
        real.parent == Path(f).resolve().parent for f in live_guard.known_live_files()
    ):
        raise LabelError("this is the live database folder; work on a COPY")
    if not real.is_file():
        raise LabelError(f"no database copy at {real.name}")
    return real


def open_copy(
    path: str | os.PathLike, *, read_only: bool = False
) -> sqlite3.Connection:
    p = refuse_live(path)
    if read_only:
        conn = sqlite3.connect("file:" + urlquote(str(p)) + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
    else:
        conn = sqlite3.connect(str(p), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def require_copy(conn: sqlite3.Connection) -> None:
    """The connection's own file is not a live database: checked again by every function that writes."""
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path:
        refuse_live(path)


# ------------------------------------------------------------------------------------------------ the rules


@dataclass(frozen=True)
class Rule:
    """One rule to label: where it lives and its words. `version_id` is the rule-book version with the same quote on
    the same page, when the rule book is in this database."""

    source: str
    ref: str
    sdid: str
    standard: str
    clause: str | None
    page: int | None
    quote: str
    version_id: str | None = None


def _book_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\.pdf$", "", str(name).strip().lower()))


def family_of(standard: str) -> str:
    from .standards_inventory import family_from_identifier

    return family_from_identifier(standard)


def select_rules(
    conn: sqlite3.Connection,
    *,
    source: str = "requirement",
    books: Sequence[str] = (),
    ids: Sequence[str] = (),
    limit: int = 0,
) -> list[Rule]:
    """The rules of one source in a stable order. 'requirement': the current `standard_requirements` rows (quote = the
    verbatim `source_text`); 'rulebook': the latest `rulebook_version` of each rule with its provenance. `books` are a
    standard's name or document id; `ids` narrow to those rules. Naming nothing selects nothing (never 'all by
    accident')."""
    if source not in SOURCES:
        raise LabelError(f"source must be one of {SOURCES}")
    if not books and not ids:
        raise LabelError("name rule books (--book) or rule ids (--ids-file)")
    bridge = rule_labels.bridge_map(conn) if source == "requirement" else {}
    if source == "requirement":
        have = {r[1] for r in conn.execute("PRAGMA table_info(standard_requirements)")}
        gone = (
            " WHERE s.superseded_at IS NULL"
            if "superseded_at" in have and not ids
            else ""
        )
        sql = (
            "SELECT s.id, s.standard_document_id, COALESCE(d.filename, s.standard_document_id), s.clause, s.page,"
            " s.source_text FROM standard_requirements s LEFT JOIN documents d ON d.id = s.standard_document_id"
            f"{gone} ORDER BY 3, s.page, s.id"
        )
    else:
        sql = (
            "SELECT v.id, p.standard_document_id, r.standard, p.clause, p.page, p.quote FROM rulebook_version v"
            " JOIN rulebook_rule r ON r.id = v.rule_id JOIN rulebook_provenance p ON p.rule_version_id = v.id"
            " WHERE v.version_no = (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
            " ORDER BY 3, p.page, v.id, p.id"
        )
    wanted_ids, wanted_books = (
        set(ids),
        {_book_key(b) for b in books} | {str(b) for b in books},
    )
    rules, seen = [], set()
    for ref, sdid, standard, clause, page, quote in conn.execute(sql):
        if ref in seen:
            continue
        if wanted_ids and ref not in wanted_ids:
            continue
        if (
            not wanted_ids
            and _book_key(standard) not in wanted_books
            and sdid not in wanted_books
        ):
            continue
        seen.add(ref)
        folded = " ".join(str(quote or "").split())
        version_id = ref if source == "rulebook" else bridge.get((sdid, page, folded))
        rules.append(
            Rule(source, ref, sdid, str(standard), clause, page, folded, version_id)
        )
    return rules[: int(limit)] if limit else rules


class PageText:
    """A standard's pages as the app cites them (`compiled_rule_report.pages_of`), read once per document."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn, self._pages, self._origin = conn, {}, {}

    def get(self, sdid: str, page: int | None) -> str | None:
        if sdid not in self._pages:
            from . import compiled_rule_report

            self._pages[sdid] = compiled_rule_report.pages_of(self.conn, sdid)
            self._origin[sdid] = compiled_rule_report.page_origin(self.conn, sdid)
        return self._pages[sdid].get(int(page)) if page is not None else None

    def low_confidence_ocr(self, sdid: str, page: int | None, quote: str) -> bool:
        """The quote-level OCR rule (`rule_label_ocr`), by the boxes this database holds, else the strict page rule."""
        self.get(sdid, page)
        origin = self._origin[sdid].get(int(page)) if page is not None else None
        return rule_label_ocr.quote_is_low(self.conn, sdid, page, quote, origin)


def quote_found(rule: Rule, pages: PageText) -> bool:
    """CODE, no model: the quote stands word for word on the page the rule cites (the app's own check)."""
    return bool(
        rule.page is not None
        and quote_verified(rule.quote, pages.get(rule.sdid, rule.page))
    )


# ------------------------------------------------------------------------------------------------ writing a label


def _answer_json(p: rule_labels.PassAnswer) -> str:
    return json.dumps(
        {
            "paper_kind": p.paper_kind,
            "field": p.field,
            "reading": dict(p.reading),
            "valid": p.valid,
        },
        sort_keys=True,
    )


def _pass_from_row(row: sqlite3.Row, which: str) -> rule_labels.PassAnswer | None:
    """A stored pass back as an answer (for `decide`), or None when it is not stored whole or its hash does not match."""
    raw = row[f"{which}_answer_json"]
    if row[f"{which}_model"] is None or not raw:
        return None
    try:
        content = json.loads(raw)
    except ValueError:
        return None
    if rule_labels.answer_hash(content) != row[f"{which}_answer_sha256"]:
        return None
    return rule_labels.PassAnswer(
        row[f"{which}_model"],
        row[f"{which}_prompt"],
        content["paper_kind"],
        content["field"],
        content["reading"],
        bool(content["valid"]),
        row[f"{which}_answer_sha256"],
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _store(
    conn: sqlite3.Connection,
    rule: Rule,
    *,
    page: int | None,
    found: bool,
    a: rule_labels.PassAnswer | None,
    b: rule_labels.PassAnswer | None,
    low_ocr: bool = False,
) -> str | None:
    """Decide, then write the row (insert, or update = a re-label, which appends an event). The state is
    `rule_labels.decide`'s and nothing else's. Returns the state, or None when there is nothing to write."""
    d = rule_labels.decide(
        a, b, quote_found=found, quote_text=rule.quote, quote_ocr_low=low_ocr
    )
    if d is None:
        return None
    cols = {
        "rule_version_id": rule.version_id,
        "paper_kind": d.paper_kind,
        "field": d.field,
        "state": d.state,
        "disagreement": d.disagreement,
        "a_model": a.model if a else None,
        "a_prompt": a.prompt if a else None,
        "a_answer_sha256": a.answer_sha256 if a else None,
        "a_answer_json": _answer_json(a) if a else None,
        "b_model": b.model if b else None,
        "b_prompt": b.prompt if b else None,
        "b_answer_sha256": b.answer_sha256 if b else None,
        "b_answer_json": _answer_json(b) if b else None,
        "reading_json": json.dumps(dict(d.reading), sort_keys=True)
        if d.reading
        else None,
        "quote_page": page if found else None,
        "quote_sha256": rule_labels.quote_hash(rule.quote),
        "quote_recovery": None,
        "labelled_at": _now(),
    }
    with conn:
        have = conn.execute(
            "SELECT 1 FROM rule_label WHERE source = ? AND rule_ref = ?",
            (rule.source, rule.ref),
        ).fetchone()
        if have:
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(
                f"UPDATE rule_label SET {sets} WHERE source = ? AND rule_ref = ?",
                (*cols.values(), rule.source, rule.ref),
            )
        else:
            names = ", ".join(["source", "rule_ref", *cols])
            conn.execute(
                f"INSERT INTO rule_label ({names}) VALUES ({','.join('?' * (len(cols) + 2))})",
                (rule.source, rule.ref, *cols.values()),
            )
    return d.state


# ------------------------------------------------------------------------------------------------ a pass


def _text_of(answer: dict) -> str:
    return "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


def _batches(rules: Sequence[Any], size: int) -> list[list[Any]]:
    size = max(1, int(size))
    return [list(rules[i : i + size]) for i in range(0, len(rules), size)]


def _same_question(rules: Sequence[Rule]) -> list[list[Rule]]:
    """Rules with the same document, page and quote are one question; the answer is stored for each."""
    groups: dict[tuple, list[Rule]] = {}
    for r in rules:
        groups.setdefault((r.sdid, r.page, r.quote), []).append(r)
    return list(groups.values())


def _models_of(conn: sqlite3.Connection, other: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT {other}_model FROM rule_label WHERE {other}_model IS NOT NULL"
        )
    ]


def check_models(model: str, other_models: Sequence[str]) -> None:
    """Pass a and pass b must use two DIFFERENT models (against what the other pass recorded)."""
    if not model or not model.strip():
        raise LabelError("a model id is needed")
    if any(
        rule_labels.family(m) == rule_labels.family(model) for m in other_models if m
    ):
        raise LabelError("pass a and pass b must use two different models")


class _Pass:
    """The state of one pass: what to ask, asking it, and storing what came back."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        pass_: str,
        model: str,
        lane: Lane,
        pages: PageText,
        out: Callable[[str], None],
    ) -> None:
        self.conn, self.pass_, self.model, self.lane, self.pages, self.out = (
            conn,
            pass_,
            model,
            lane,
            pages,
            out,
        )
        self.counts: Counter = Counter()
        self.fields = field_list()
        self.system = system_text(self.fields)
        self.stop_event = threading.Event()
        self.stopped = ""

    def _row(self, r: Rule):
        return self.conn.execute(
            "SELECT * FROM rule_label WHERE source = ? AND rule_ref = ?",
            (r.source, r.ref),
        ).fetchone()

    def _skip_reason(self, r: Rule) -> str | None:
        """Why this rule is not asked in this pass (a count key), or None when it is. A rule whose quote is not found in
        pass a gets its `quote_not_found` row here and is never sent."""
        row = self._row(r)
        if family_of(r.standard) not in ALLOWED_FAMILIES:
            return "not_sent_family_not_allowed"
        if self.pass_ == "a":
            if row is not None and row["a_model"] is not None:
                return "already_done"
            if not quote_found(r, self.pages):
                _store(self.conn, r, page=r.page, found=False, a=None, b=None)
                return "quote_not_found"
            return None
        if row is None or row["a_model"] is None:
            return "waiting_for_pass_a"
        if row["b_model"] is not None:
            return "already_done"
        if row["state"] != LABELLED_A or row["a_prompt"] != rule_labels.PROMPT_VERSION:
            return "not_asked_pass_a_not_current"
        if row["quote_sha256"] != rule_labels.quote_hash(r.quote) or not quote_found(
            r, self.pages
        ):
            return "not_asked_quote_changed"
        return None

    def todo(self, rules: Sequence[Rule]) -> list[Rule]:
        out = []
        for r in rules:
            why = self._skip_reason(r)
            if why:
                self.counts[why] += 1
            else:
                out.append(r)
        return out

    def ask(self, batch: list[list[Rule]], run_id: str):
        """(batch, the answer | the exception | None when the run has stopped). Runs in a worker thread: no database."""
        from . import claude_approved

        if self.stop_event.is_set():
            return batch, None
        reps = [g[0] for g in batch]
        try:
            with (
                claude_approved.per_request_consent(sorted({r.sdid for r in reps})),
                claude_spend.for_run(run_id),
            ):
                parts = build_parts(reps, self.system)
                return batch, self.lane.call(
                    self.model, parts, max_tokens_for(len(reps), self.model), len(reps)
                )[0]
        except Exception as exc:  # noqa: BLE001 - handled in `settle` by type; never the text
            logger.warning("rule label call failed: %s", type(exc).__name__)
            return batch, exc

    def _stop_or_error(self, answer: Any, n_rules: int) -> bool:
        if isinstance(
            answer,
            (
                agent_claude.AgentBudgetStop,
                agent_claude.AgentGateClosed,
                OrderStopReached,
            ),
        ):
            self.stop_event.set()
            self.stopped = self.stopped or str(
                getattr(answer, "code", None) or type(answer).__name__
            )
        elif not isinstance(answer, Exception):
            return False
        else:
            self.counts[
                "errors:" + str(getattr(answer, "code", type(answer).__name__))
            ] += 1
        self.counts["unlabelled_error"] += n_rules
        return True

    def settle(self, batch: list[list[Rule]], answer: Any) -> None:
        """Store what a call returned (main thread only). Nothing is approved on an error or an unreadable answer."""
        n_rules = sum(len(g) for g in batch)
        if answer is None:
            self.counts["unlabelled_not_sent_after_stop"] += n_rules
            return
        if self._stop_or_error(answer, n_rules):
            return
        used = agent_claude._answered_model(answer)
        used = self.model if used == "unknown" else used
        if self.pass_ == "b" and any(
            rule_labels.family(used) == rule_labels.family(m)
            for m in _models_of(self.conn, "a")
        ):
            self.counts["unlabelled_same_model_answered"] += (
                n_rules  # the answering model is pass a's: never pass b
            )
            return
        got = parse_answers(_text_of(answer), [g[0] for g in batch], self.fields, used)
        for n, group in enumerate(batch, 1):
            if got.get(n) is None:
                self.counts["unlabelled_unreadable_or_wrong_rule"] += len(group)
                continue
            for r in group:
                self._store_one(r, got[n])
        self.out(
            f"BATCH {len(batch)} questions | order USD {self.lane.ledger.run_usd:.4f}"
        )

    def _store_one(self, r: Rule, ans: rule_labels.PassAnswer) -> None:
        a = ans if self.pass_ == "a" else _pass_from_row(self._row(r), "a")
        if a is None:
            self.counts["unlabelled_pass_a_unreadable"] += 1
            return
        low = self.pages.low_confidence_ocr(r.sdid, r.page, r.quote)
        state = _store(
            self.conn,
            r,
            page=r.page,
            found=True,
            a=a,
            b=ans if self.pass_ == "b" else None,
            low_ocr=low,
        )
        self.counts["answered"] += 1
        self.counts["state:" + str(state)] += 1


def run_pass(
    conn: sqlite3.Connection,
    rules: Sequence[Rule],
    *,
    pass_: str,
    model: str,
    lane: Lane,
    pages: PageText | None = None,
    batch_size: int = BATCH_RULES,
    concurrency: int = 1,
    out: Callable[[str], None] = print,
) -> dict:
    """One pass over `rules`; returns counts only. The database `conn` is written from THIS thread only.

    Pass a: a rule with no answer yet is checked for its quote by code; not found -> a `quote_not_found` row, never
    sent; found -> asked. Pass b: only rules that pass a answered (`labelled_a`, same prompt version, quote unchanged)
    and never with pass a's model family. A cap or the ledger's stop ends the run (the rest is not sent) and is
    reported in `stopped`; nothing is ever approved on an error."""
    if pass_ not in ("a", "b"):
        raise LabelError("pass must be a or b")
    require_on()
    require_copy(conn)
    create_tables(conn)
    check_models(model, _models_of(conn, "b" if pass_ == "a" else "a"))
    run = _Pass(conn, pass_, model, lane, pages or PageText(conn), out)
    todo = run.todo(rules)
    questions = _same_question(todo)
    run.counts.update(rules=len(rules), sent=len(todo), unique_sent=len(questions))
    jobs: list[tuple[list[list[Rule]], str]] = []
    for book in dict.fromkeys(g[0].standard for g in questions):
        run_id = f"rule-label-{pass_}-{_book_key(book)}"
        jobs += [
            (b, run_id)
            for b in _batches(
                [g for g in questions if g[0].standard == book], batch_size
            )
        ]
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        for fut in as_completed([pool.submit(run.ask, b, rid) for b, rid in jobs]):
            run.settle(*fut.result())
    run.counts["stopped"] = run.stopped
    for key in (
        "answered",
        "unlabelled_error",
        "unlabelled_unreadable_or_wrong_rule",
        "unlabelled_same_model_answered",
    ):
        run.counts.setdefault(key, 0)
    return dict(run.counts)


# ------------------------------------------------------------------------------------------------ estimate, report, export


def estimate(rules: Sequence[Rule], model: str, batch_size: int = BATCH_RULES) -> dict:
    """Calls and the app's own WORST-CASE USD for asking `rules` once with `model` (no call is made). The real cost is
    below it; thinking is allowed for in the output room."""
    system = system_text(field_list())
    questions = _same_question(
        [r for r in rules if family_of(r.standard) in ALLOWED_FAMILIES]
    )
    calls, worst, tokens_in = 0, 0.0, 0
    for book in dict.fromkeys(g[0].standard for g in questions):
        for b in _batches([g for g in questions if g[0].standard == book], batch_size):
            chars = len(system) + len(user_text([g[0] for g in b]))
            calls += 1
            tokens_in += int(chars / 3.5)
            worst += claude_spend.worst_case_usd(
                model, chars, max_tokens_for(len(b), model)
            )
    return {
        "rules": len(rules),
        "unique_questions": len(questions),
        "calls": calls,
        "input_tokens_estimate": tokens_in,
        "usd_worst_case_by_app_formula": round(worst, 4),
        "model": model,
    }


def report(conn: sqlite3.Connection) -> dict:
    """Counts by state, by paper kind and by disagreement cause. No text."""
    out: dict[str, Any] = {
        "rules": 0,
        "by_state": {},
        "by_paper_kind": {},
        "needs_human_by_cause": {},
    }
    if (
        conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'rule_label'").fetchone()
        is None
    ):
        return out
    for state, kind, cause in conn.execute(
        "SELECT state, paper_kind, disagreement FROM rule_label"
    ):
        out["rules"] += 1
        out["by_state"][state] = out["by_state"].get(state, 0) + 1
        if kind:
            out["by_paper_kind"][kind] = out["by_paper_kind"].get(kind, 0) + 1
        for part in str(cause or "").split(","):
            if part and state == NEEDS_HUMAN:
                out["needs_human_by_cause"][part] = (
                    out["needs_human_by_cause"].get(part, 0) + 1
                )
    return out


_EXPORT_COLUMNS = (
    "source",
    "rule_ref",
    "rule_version_id",
    "paper_kind",
    "field",
    "state",
    "disagreement",
    "a_model",
    "a_prompt",
    "a_answer_sha256",
    "b_model",
    "b_prompt",
    "b_answer_sha256",
    "quote_page",
    "quote_sha256",
    "quote_recovery",
    "labelled_at",
)


def export_rows(conn: sqlite3.Connection) -> list[dict]:
    """Every label as a row a file can carry: ids, hashes, page, kind, field, state, models, versions and the agreed
    reading. NO quote text, no answer text."""
    rows = []
    for r in conn.execute("SELECT * FROM rule_label ORDER BY source, rule_ref"):
        d = {c: r[c] for c in _EXPORT_COLUMNS}
        d["reading"] = json.loads(r["reading_json"]) if r["reading_json"] else None
        rows.append(d)
    return rows


def write_export(conn: sqlite3.Connection, out: str | os.PathLike) -> int:
    """Write the label file; returns the number of rows. Reads only the copy; the file holds no document text."""
    rows = export_rows(conn)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format": EXPORT_FORMAT,
                "prompt_versions": [rule_labels.PROMPT_VERSION],
                "rows": rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return len(rows)
