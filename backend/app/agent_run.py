"""The runner of the agent proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED` (off by default).

It turns `agent_loop` into a scored experiment, on a COPY of the database only:

  open_readonly     the copy is opened with sqlite `mode=ro` (and `query_only`); the live database file is refused
                    (`live_guard.is_live_shaped`), so a typo can never point a proof run at live data.
  build_scope       `allowed_document_ids` = the reviewed document plus the standards documents the copy holds that
                    the EDITION MAP names. The map is never guessed from file names (an edition is never guessed,
                    CLAUDE.md rule 4): it is the `editions` argument, else `<run_dir>/editions.json`
                    ({"standard identifier": "edition year"}). A standard is in scope when a held document's file name
                    is that standard (`standard_ids.same_standard`) and prints that edition. No map, or no such
                    document: nothing extra is in scope and `get_clause` says "not held".
  run_review        loads the skill, runs the items one by one through `agent_loop.run_items` (each item's result is
                    saved at once, so a killed run resumes), applies the second opinion to GREEN and RED findings
                    (a disagreement, no answer, or the SAME model reporting itself both times -> YELLOW), then
                    writes RESULTS.md, EXAMPLES.md and crs.xlsx under the run directory.
  crs_rows_from_findings / write_crs_xlsx
                    the bridge to the answer-key scorer (see below).

PRIVACY. Every tool reader here is bound to the read-only copy: nothing falls back to `app.db.connect()` (which would
open the configured, possibly live, database read-write). The local files this module writes (findings, EXAMPLES.md,
crs.xlsx) hold comment text, so the run directory must be outside the git work tree (`agent_trace.resolve_root`
refuses otherwise). RESULTS.md holds counts, spend, minutes and model names only: no document or standard text.
Model names are the ones the provider's RESPONSE reported (`reply["model"]`), never the configured name.

THE SCORER BRIDGE. `answer_key_score.py` reads a workbook whose sheet is named "CRS" and matches a problem by the
problem's field words and its page appearing together in ONE row (each word's first four letters, case-folded, as a
substring of the row's text); rows with five or more filled cells count as comment rows. So the "CRS" sheet holds the
problems only (RED and YELLOW), one row each, with the skill item's TOPIC words, the page and the comment text in the
row. GREEN rows go to a separate "Checked OK" sheet: a row for something that complies would be scored as a problem
the system raised. The "Contractor" sheet is the contractor copy: RED and YELLOW rows whose comment a contractor can
act on (no engineer, model or colour words). Nothing about the answer key is read or used here (teaching to the test
would void the proof).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import agent_loop, agent_trace, heavy_lock, live_guard
from .agent_run_crs import (
    CHECKED_SHEET as CHECKED_SHEET,
)
from .agent_run_crs import (
    CONTRACTOR_HEADERS as CONTRACTOR_HEADERS,
)
from .agent_run_crs import (
    CONTRACTOR_SHEET as CONTRACTOR_SHEET,
)
from .agent_run_crs import (
    CRS_HEADERS as CRS_HEADERS,
)
from .agent_run_crs import (
    CRS_SHEET as CRS_SHEET,
)
from .agent_run_crs import (
    FILES,
    _clean,
    _read_json,
    _write_json,
    quote_verified,
    write_examples,
    write_results,
)
from .agent_run_crs import (
    MIN_FILLED_CELLS as MIN_FILLED_CELLS,
)
from .agent_run_crs import (
    crs_rows_from_findings as crs_rows_from_findings,
)
from .agent_run_crs import (
    write_crs_xlsx as write_crs_xlsx,
)

ENABLE_ENV = "AGENT_REVIEW_ENABLED"
USD_CAP_ITEM = 5.0  # CLAUDE.md rule 1: per step USD 5 (the clause review step USD 10)
USD_CAP_TOTAL = 10.0  # the owner's cap for the whole agent test, read from the ledger
LEDGER_STEP = "agent_review"
USD_CAP_RUN = 15.0  # at most USD 15 for one whole review run

_TRUE = ("1", "true", "yes", "on")


class LiveDatabaseRefused(RuntimeError):
    """The path is a live database: a proof run uses a copy."""


class NotEnabled(RuntimeError):
    """`AGENT_REVIEW_ENABLED` is not set in the process environment."""


class SkillMissing(RuntimeError):
    """No skill dict was given and `agent_skills` is not built yet."""


def enabled(env: dict | None = None) -> bool:
    """The switch, read from the PROCESS environment only (never from .env)."""
    value = (os.environ if env is None else env).get(ENABLE_ENV, "")
    return str(value).strip().lower() in _TRUE


# ---- the read-only copy -----------------------------------------------------------------------------------------


def open_readonly(db_path: str | os.PathLike) -> sqlite3.Connection:
    """The database COPY, read-only. Refuses the live database and a missing file."""
    path = Path(db_path).expanduser()
    if live_guard.is_live_shaped(path):
        raise LiveDatabaseRefused(
            "this is the live database; run on a copy (sqlite backup of it)"
        )
    if not path.is_file():
        raise FileNotFoundError(f"no database copy at {path.name}")
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


class Readers:
    """The tools' readers, all bound to ONE read-only connection."""

    def __init__(self, conn: sqlite3.Connection, allowed: Iterable[str]) -> None:
        self.conn = conn
        self.allowed = frozenset(allowed)

    def page(self, doc: str, page: int) -> str | None:
        row = self.conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (doc, page),
        ).fetchone()
        return None if row is None else (row["text"] or "")

    def standard_pages(self, doc: str) -> list[tuple[int, str]]:
        return [
            (r["page_no"], r["text"] or "")
            for r in self.conn.execute(
                "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
                (doc,),
            )
        ]

    def resolver(self, standard: str, edition: str) -> str | None:
        return resolve_standard(self.conn, self.allowed, standard, edition)

    def search(self, query: str, allowed: frozenset[str]) -> dict:
        """KEYWORD search over the copy's pages (no model, no embedding). The proof run's search; the hybrid
        `search.search` opens the configured database, so it is not used on a copy."""
        tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 3}
        if not tokens or not allowed:
            return {"hits": []}
        marks = ",".join("?" * len(allowed))
        scored = []
        for r in self.conn.execute(
            f"SELECT document_id, page_no, text FROM pages WHERE document_id IN ({marks})",
            sorted(allowed),
        ):
            low = (r["text"] or "").lower()
            hit = [t for t in tokens if t in low]
            if hit:
                at = min(low.find(t) for t in hit)
                scored.append(
                    (
                        -len(hit),
                        r["document_id"],
                        r["page_no"],
                        (r["text"] or "")[max(0, at - 200) : at + 1000],
                    )
                )
        scored.sort(key=lambda s: s[:3])
        return {
            "hits": [
                {"document_id": d, "page_start": p, "text": t}
                for _n, d, p, t in scored[:10]
            ]
        }


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def resolve_standard(
    conn: sqlite3.Connection, candidates: Iterable[str], standard: str, edition: str
) -> str | None:
    """The candidate document whose file name is `standard` and prints `edition`, else None."""
    from . import standard_ids

    want = _fold(edition)
    if not want:
        return None
    for doc in sorted(candidates):
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (doc,)
        ).fetchone()
        if row is None:
            continue
        stem = re.sub(r"\.(pdf|docx?)$", "", row["filename"] or "", flags=re.I)
        if standard_ids.same_standard(standard, stem) and want in _fold(stem):
            return doc
    return None


def load_editions(run_dir: Path, editions: dict | None) -> dict[str, str]:
    """The contract edition map: the argument, else `<run_dir>/editions.json`, else empty."""
    if editions is None:
        try:
            editions = json.loads(
                (run_dir / FILES["editions"]).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            editions = {}
    if not isinstance(editions, dict):
        return {}
    return {
        str(k): str(v) for k, v in editions.items() if str(k).strip() and str(v).strip()
    }


def build_scope(
    conn: sqlite3.Connection, document_id: str, editions: dict[str, str]
) -> tuple[frozenset[str], dict[str, str], list[str]]:
    """(allowed document ids, editions that resolve to a held document, standards named but not held)."""
    if (
        conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone()
        is None
    ):
        raise LookupError("the document is not in the database copy")
    others = [
        r["id"]
        for r in conn.execute("SELECT id FROM documents WHERE id != ?", (document_id,))
    ]
    allowed = {document_id}
    held: dict[str, str] = {}
    missing: list[str] = []
    for standard, edition in editions.items():
        doc = resolve_standard(conn, others, standard, edition)
        if doc is None:
            missing.append(standard)
        else:
            allowed.add(doc)
            held[standard] = edition
    return frozenset(allowed), held, missing


class DocumentsNotDeclared(RuntimeError):
    """A Claude run needs the documents it may carry, named explicitly, and inside the run's scope."""


def declared_documents(
    allowed: frozenset[str], document_id: str, documents: Iterable[str] | None
) -> frozenset[str]:
    """The ids a Claude run declares: EXACTLY `documents`. No default 'all'; each must be in the run's scope."""
    declared = frozenset(str(d) for d in (documents or ()) if d)
    if not declared:
        raise DocumentsNotDeclared(
            "a Claude run needs --documents: the ids it may carry"
        )
    if document_id not in declared:
        raise DocumentsNotDeclared("the document under review must be declared")
    if not declared <= allowed:
        raise DocumentsNotDeclared("a declared document is outside the run's scope")
    return declared


def _consent_module(consent: Any) -> Any:
    if consent is not None:
        return consent
    from . import claude_approved

    return claude_approved


def _ledger_default(step: str) -> float:
    from . import claude_spend

    return claude_spend.spent(step)


def default_toolbox(scope: dict, readers: Readers) -> Any:
    """The real six-tool box (`agent_tools`, PR #1693), with readers bound to the read-only copy."""
    from . import agent_tools

    ctx = agent_tools.ToolContext(
        allowed_document_ids=scope["allowed"],
        document_id=scope["document_id"],
        editions=scope["editions"],
    )
    return agent_tools.ToolBox(
        ctx,
        page_reader=readers.page,
        searcher=readers.search,
        standard_pages=readers.standard_pages,
        standard_resolver=readers.resolver,
    )


# ---- skill and items --------------------------------------------------------------------------------------------


def get_skill(kind: str, skill: dict | None = None) -> dict:
    """The skill dict {'kind','version','items':[...]}: the argument, else `agent_skills.load_skill(kind)`."""
    if skill is None:
        try:
            from . import agent_skills
        except ImportError:
            raise SkillMissing(
                "agent_skills is not built yet; pass a skill dict"
            ) from None
        skill = agent_skills.load_skill(kind)
    if not isinstance(skill, dict) or not isinstance(skill.get("items"), list):
        raise SkillMissing("the skill has no items list")
    return skill


def select_items(
    skill: dict, ids: Iterable[str] | None = None, limit: int | None = None
) -> list[dict]:
    """Skill items in `order`, optionally only `ids`, at most `limit`."""
    rows = [
        i for i in skill["items"] if isinstance(i, dict) and i.get("id") is not None
    ]
    rows.sort(key=lambda i: (i.get("order") is None, i.get("order") or 0))
    if ids is not None:
        want = {str(i) for i in ids}
        rows = [i for i in rows if str(i["id"]) in want]
    return rows[:limit] if limit is not None and limit >= 0 else rows


def loop_items(document_id: str, skill_items: list[dict]) -> list[dict]:
    return [
        {"id": str(i["id"]), "doc": document_id, "topic": i.get("topic")}
        for i in skill_items
    ]


def plan(
    skill_items: list[dict],
    *,
    usd_cap_item: float = USD_CAP_ITEM,
    usd_cap_run: float = USD_CAP_RUN,
    max_steps: int = agent_loop.MAX_STEPS,
    total_cap: float | None = None,
) -> dict:
    """The dry-run numbers: no model is called to produce them."""
    n = len(skill_items)
    return {
        "items": [str(i["id"]) for i in skill_items],
        "item_count": n,
        "max_steps": n * max_steps,
        "max_usd": round(
            min(
                n * usd_cap_item,
                usd_cap_run,
                total_cap if total_cap is not None else usd_cap_run,
            ),
            2,
        ),
        "note": "upper bounds, not a forecast",
    }


# ---- provider wrapper -------------------------------------------------------------------------------------------


class Recorder:
    """Wraps a provider: counts calls, remembers the model name each RESPONSE reported."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.calls = 0
        self.models: set[str] = set()

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        self.calls += 1
        reply = self.provider.complete(messages, tool_specs)
        if isinstance(reply, dict):
            name = reply.get("model")
            if isinstance(name, str) and name.strip():
                self.models.add(name.strip()[:80])
        return reply

    def close(self) -> None:
        with contextlib.suppress(Exception):
            getattr(self.provider, "close", lambda: None)()


# ---- second opinion ---------------------------------------------------------------------------------------------

UNKNOWN = "unknown"


def _known(models: Iterable[str]) -> set[str] | None:
    """The reported model names, or None when there are none or any is missing/'unknown' (fails closed)."""
    names = {str(m) for m in models if m}
    return names if names and UNKNOWN not in names else None


_VERSION_TAIL = re.compile(r"(?:-\d{8}|-latest|@[\w.\-]+)$")


def model_family(name: str) -> str:
    """The model name without a trailing -YYYYMMDD, -latest or @version: the same family is the same model."""
    return _VERSION_TAIL.sub("", name.strip().lower())


def models_differ(lead_models: Iterable[str], opinion_model: Any) -> bool:
    """True only when BOTH sides reported a model name and the names differ. A missing name fails closed."""
    lead = _known(lead_models)
    other = _known([opinion_model] if isinstance(opinion_model, str) else [])
    if not (lead and other):
        return False
    return not ({model_family(m) for m in lead} & {model_family(m) for m in other})


def ask_second_opinion(opinion: Any, finding: dict, trace: Any) -> dict:
    """{'agree': True|False|None, 'model': name or 'unknown'} from `opinion.second_opinion(finding, evidence)`.

    The real one is `ClaudeProvider.second_opinion` (a different model, the shared meter); built once per run."""
    evidence = {k: finding.get(k) for k in ("doc_quote", "clause_quote")}
    try:
        reply = opinion.second_opinion(
            {k: finding.get(k) for k in ("item", "color")}, evidence
        )
    except Exception as exc:
        if getattr(exc, "fatal", False):
            raise
        # recorded: counted as 'no answer' in RESULTS
        return {"agree": None, "model": UNKNOWN}
    if not isinstance(reply, dict):
        return {"agree": None, "model": UNKNOWN}
    cost = reply.get("usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
        trace.add_spend(float(cost))
    agree = reply.get("agree")
    model = reply.get("model")
    return {
        "agree": agree if isinstance(agree, bool) else None,
        "model": model if isinstance(model, str) and model.strip() else UNKNOWN,
    }


def apply_second_opinion(
    finding: dict, agree: bool | None, ran: bool, same_model: bool = False
) -> dict:
    """GREEN and RED stay only on agreement. Disagreement, no answer, or a model that is the same or unknown -> YELLOW."""
    out = dict(finding)
    if finding.get("color") not in ("GREEN", "RED"):
        return out
    if not ran:
        out["second_opinion"] = "not run"
        return out
    if agree is True and not same_model:
        out["second_opinion"] = "agreed"
        return out
    why = (
        "second opinion model is the same or unknown"
        if same_model
        else "second opinion disagreed"
        if agree is False
        else "no second opinion"
    )
    out.update(
        color="YELLOW",
        second_opinion="disagreed" if agree is False else "no answer",
        reason=agent_trace.words(f"{why}; first verdict {finding.get('color')}"),
        action=finding.get("action") or "ask the engineer",
    )
    return out


# ---- the run ----------------------------------------------------------------------------------------------------


def run_review(
    db_copy_path: str | os.PathLike,
    document_id: str,
    skill_kind: str,
    provider: Any,
    second_opinion: Any = None,
    items: Iterable[str] | None = None,
    limit: int | None = None,
    run_dir: str | os.PathLike | None = None,
    *,
    skill: dict | None = None,
    editions: dict | None = None,
    local: bool = False,
    claude: bool = False,
    documents: Iterable[str] | None = None,
    consent: Any = None,
    ledger: Callable[[str], float] | None = None,
    total_cap_usd: float = USD_CAP_TOTAL,
    usd_cap_item: float = USD_CAP_ITEM,
    usd_cap_run: float = USD_CAP_RUN,
    toolbox_factory: Callable[[dict, Readers], Any] | None = None,
    on_status: Callable[[agent_trace.TraceWriter], None] | None = None,
) -> dict:
    """Run one document on a database COPY; write the local result files. `local` takes the heavy lock."""
    conn = open_readonly(db_copy_path)
    try:
        wanted = get_skill(skill_kind, skill)
        chosen = select_items(wanted, items, limit)
        trace = agent_trace.TraceWriter(
            run_dir,
            total=len(chosen),
            model="not yet reported",
            step_name=f"agent review: {wanted.get('kind')}",
        )
        run_root = trace.root
        allowed, held = _scope_for(
            conn,
            trace,
            document_id,
            load_editions(run_root, editions),
            claude,
            documents,
        )
        readers = Readers(conn, allowed)
        scope = {"allowed": allowed, "document_id": document_id, "editions": held}
        box = (toolbox_factory or default_toolbox)(scope, readers)
        if second_opinion is not None and second_opinion is provider:
            raise ValueError(
                "the second opinion must be a different model, not the lead"
            )
        lead = Recorder(provider)
        other = (
            LocalOpinion(second_opinion, held_already=local) if second_opinion else None
        )
        trace.second_ran = other is not None
        guard = _guard(local, claude, consent, allowed)
        with guard:
            stopped = _drive(
                chosen,
                document_id,
                box,
                lead,
                other,
                trace,
                run_root,
                usd_cap_item,
                usd_cap_run,
                on_status,
                (ledger or _ledger_default) if claude else None,
                total_cap_usd,
            )
        lead.close()
        if other:
            other.unload()
        return _finish(
            chosen,
            document_id,
            wanted,
            trace,
            run_root,
            stopped,
            other is not None,
            scope,
        )
    finally:
        conn.close()


def _scope_for(conn, trace, document_id, edition_map, claude, documents):
    """(allowed ids, held editions). A Claude run is narrowed to exactly its declared documents."""
    allowed, held, missing = build_scope(conn, document_id, edition_map)
    if missing:
        trace.problem(f"{len(missing)} standards named in the edition map are not held")
    if claude:
        allowed = declared_documents(allowed, document_id, documents)
    return allowed, held


def _guard(local, claude, consent, allowed):
    """The heavy lock for a local run; the per-request consent of exactly the declared ids for a Claude run."""
    stack = contextlib.ExitStack()
    if local:
        stack.enter_context(
            heavy_lock.held(
                "agent-review", "run_agent_review", heavy_lock.wait_seconds_from_env()
            )
        )
    if claude:
        stack.enter_context(
            _consent_module(consent).per_request_consent(sorted(allowed))
        )
    return stack


def _save_meta(run_root, trace, meta, lead, second, seconds) -> dict:
    """Minutes so far and the model names the responses reported, saved after every item."""
    meta = {
        "seconds": seconds,
        "lead_models": sorted(set(meta.get("lead_models", [])) | lead.models),
        "opinion_models": sorted(
            set(meta.get("opinion_models", []))
            | {v.get("model") or UNKNOWN for v in second.values()}
        ),
    }
    _write_json(run_root / FILES["meta"], meta)
    names = ", ".join(meta["lead_models"]) or "not reported by the provider"
    trace.set_live(model=names)
    return meta


class LocalOpinion:
    """The LOCAL second opinion (`agent_local.LocalSecondOpinion`, a different model family from the Claude lead).

    Takes the shared heavy-job lock around each call (not when the lead already holds it: `held_already`) and unloads
    the model at the end (#666). Nothing here can reach Claude."""

    def __init__(self, inner: Any, *, held_already: bool = False) -> None:
        self.inner, self.held_already = inner, held_already

    def second_opinion(self, finding: dict, evidence: dict) -> dict:
        if self.held_already:
            return self.inner.second_opinion(finding, evidence)
        try:
            with heavy_lock.held(
                "agent-review", "run_agent_review", heavy_lock.wait_seconds_from_env()
            ):
                return self.inner.second_opinion(finding, evidence)
        except heavy_lock.HeavyJobBusy as exc:
            exc.fatal = True  # the run stops, resumable; the item is not made YELLOW
            raise

    def unload(self) -> None:
        for name in ("unload", "close"):
            fn = getattr(self.inner, name, None)
            if callable(fn):
                fn()
                return


def fatal_problem(exc: BaseException) -> str:
    """The PROBLEM words of a fatal stop: from its code only, never a message."""
    if isinstance(exc, heavy_lock.HeavyJobBusy):
        return "heavy lock busy"
    code = str(getattr(exc, "code", "") or "")
    if "document" in code:
        return "documents not declared"
    if type(exc).__name__ == "AgentGateClosed":
        return "gate closed"
    if code == "test_cap":
        return "budget stop: run cap reached: owner decides whether to raise it"
    return "budget stop: step cap reached: owner decides whether to raise it"


def _drive(
    chosen,
    document_id,
    box,
    lead,
    other,
    trace,
    run_root,
    cap_item,
    cap_run,
    on_status,
    ledger=None,
    total_cap=USD_CAP_TOTAL,
) -> str:
    started = time.time()
    meta = _read_json(run_root / FILES["meta"], {})
    base_seconds = float(meta.get("seconds") or 0.0)
    by_id = {str(i["id"]): i for i in chosen}
    finals = _read_json(run_root / FILES["finals"], {})
    second = _read_json(run_root / FILES["second"], {})
    stopped = ""
    try:
        for loop_item in loop_items(document_id, chosen):
            iid = loop_item["id"]
            if ledger is not None and ledger(LEDGER_STEP) >= total_cap:
                stopped = "total cap for the agent test"
                trace.problem(f"{stopped} reached: run paused, resumable")
                break
            if iid not in finals:
                out = agent_loop.run_items(
                    [loop_item],
                    box,
                    lead,
                    trace,
                    skill_for=lambda _it, i=iid: by_id[i],
                    usd_cap_item=cap_item,
                    usd_cap_run=cap_run,
                )
                if out["stopped"]:
                    stopped = out["stopped"]
                    break
                res = out["results"].get(iid)
                finding = (
                    res["finding"]
                    if res
                    else (
                        trace.sink.get(iid)
                        or agent_loop.yellow("result lost in a restart", loop_item)
                    )
                )
                finals[iid] = finding
                _write_json(run_root / FILES["finals"], finals)
            finding = finals[iid]
            if (
                other is not None
                and finding.get("color") in ("GREEN", "RED")
                and iid not in second
            ):
                second[iid] = ask_second_opinion(other, finding, trace)
                _write_json(run_root / FILES["second"], second)
            meta = _save_meta(
                run_root,
                trace,
                meta,
                lead,
                second,
                base_seconds + time.time() - started,
            )
            if len(trace.completed) % 10 == 0 and on_status:
                trace.refresh_live()
                on_status(trace)
    except Exception as exc:
        if not getattr(exc, "fatal", False):
            raise
        stopped = fatal_problem(exc)
        trace.problem(f"{stopped}: run stopped, resumable")
    return stopped


def _finish(
    chosen, document_id, wanted, trace, run_root, stopped, second_ran, scope
) -> dict:
    finals = _read_json(run_root / FILES["finals"], {})
    second = _read_json(run_root / FILES["second"], {})
    meta = _read_json(run_root / FILES["meta"], {})
    lead_models = list(meta.get("lead_models", []))
    opinion_models = list(meta.get("opinion_models", []))
    findings = []
    for item in chosen:
        iid = str(item["id"])
        if iid not in finals:
            continue
        got = second.get(iid, {})
        same = not models_differ(lead_models, got.get("model"))
        findings.append(
            apply_second_opinion(finals[iid], got.get("agree"), second_ran, same)
        )
    topics = {str(i["id"]): _clean(i.get("topic")) for i in chosen}
    rows = crs_rows_from_findings(findings, topics)
    write_crs_xlsx(rows, run_root / FILES["crs"])
    write_examples(run_root, rows)
    verified = quote_verified(findings, trace.sink)
    write_results(
        run_root,
        findings=findings,
        verified=verified,
        spend=trace.spend,
        seconds=float(meta.get("seconds") or 0.0),
        lead_models=lead_models,
        opinion_models=opinion_models,
        skill=wanted,
        document_id=document_id,
        problems=trace.problems,
        stopped=stopped,
        second_ran=second_ran,
    )
    trace.set_live(
        done=f"{len(findings)} of {len(chosen)} items",
        next="read RESULTS.md" if not stopped else "resume the run",
    )
    trace.piece_done("results written")
    return {
        "status_box": status_box(trace),
        "findings": findings,
        "items_total": len(chosen),
        "items_done": len(findings),
        "stopped": stopped,
        "spend": trace.spend,
        "quote_verified": verified,
        "lead_models": lead_models,
        "opinion_models": opinion_models,
        "run_dir": str(run_root),
        "allowed_document_ids": sorted(scope["allowed"]),
    }


STATUS_FIELDS = (
    "STEP", "DONE", "PROOF", "RUNNING", "PROGRESS", "MODEL", "RESULTS", "SPEND", "PROBLEMS", "NEXT",
)  # fmt: skip


def status_box(trace: agent_trace.TraceWriter) -> str:
    """The owner's STATUS box, from LIVE.md (rewritten first)."""
    text = trace.refresh_live().read_text(encoding="utf-8")
    fields = dict(re.findall(r"^- \*\*([A-Z]+)\*\*: (.*)$", text, re.M))
    if not getattr(trace, "second_ran", True):
        fields["RESULTS"] += " (GREEN and RED: second opinion not run: not decided)"
    body = [f"{k:9}{fields.get(k, '')}" for k in STATUS_FIELDS]
    return "\n".join(["==== STATUS ====", *body, "================"])
