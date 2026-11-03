"""AI engineering review pass, part 2: the runner. Lane 6 (owner order 3 Nov 2026). OFF by default.

After the draft CRS, one model call reads the submittal and the draft rows like a senior engineer and PROPOSES (remove a
comment that is wrong in context, add a missed one, reword one, a short document-understanding note). Every proposal then
goes through `ai_review_proposals.verify_all`: code accepts only what it verifies; a Pass is never created and a Fail is
never removed without a verified reason. This module asks, parses, hands the proposals to the verifier and STORES the
verdicts; it changes no finding and no CRS row (the display reads `accepted` and `overrides`, part 3).

ENGINE. Local by default. `AI_ENGINEERING_REVIEW_PASS_ENGINE=claude` and every document of the review on the approved list:
Claude (through `reasoning_provider`, so `reader_transport` and the USD caps); otherwise the local model, and the summary
says so. A failing model stops the pass for the run (recorded), never the review. Counts and reason codes only in logs.

STORED, per run: `crs_ai_review` (one row per proposal: its state accepted or refused, the refusal reason, the proposal as
JSON), `crs_ai_review_runs` (the summary), `crs_ai_review_override` (an engineer's restore of a removed row, reversible and
append-only).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from . import ai_review_proposals as arp
from . import claude_approved, crs_ai_review_view, local_engine_bar
from .ai import output_limits
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

STEP = "ai_review_pass"
PROMPT_VERSION = "ai-review-pass-v1"
MAX_OUTPUT_TOKENS = 4000
MAX_PAGE_CHARS = 6000
MAX_PACKET_CHARS = 60000
LOCAL_PAGE_CHARS = 3000
MAX_ROWS = 80
MAX_ROW_CHARS = 400
MALFORMED = "model_malformed"

SCHEMA = {
    "type": "object",
    "required": ["proposals"],
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type", "reason", "confidence"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string", "enum": list(arp.TYPES)},
                    "row_key": {"type": ["string", "null"]},
                    "page": {"type": ["integer", "null"]},
                    "clause": {"type": ["string", "null"]},
                    "standard": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "row_value": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                    "text": {"type": ["string", "null"]},
                    "basis": {"type": ["string", "null"], "enum": [*arp.BASES, None]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "page": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                        },
                    },
                    "understanding": {"type": ["object", "null"]},
                    "confidence": {"type": "string", "enum": list(arp.CONFIDENCES)},
                },
            },
        }
    },
}

SYSTEM = """You are a senior engineer reviewing a contractor's submittal for an operating company. You are given the \
submittal's pages and the DRAFT review comments (rows) a program produced. Read both like a senior engineer and PROPOSE \
changes. You only propose; a program checks every proposal and keeps only what it can verify on the pages.

Proposal types:
- remove: a draft row that is wrong in context (example: different equipment tags having different MAWP is normal). Give \
"row_key", "basis" (misread, out_of_scope, tag_difference or context), the page, the "value" the page really shows, and \
"evidence": exact quotes copied from the pages, each with its page. For basis misread also give "row_value", the figure \
the row printed.
- add: a comment the draft missed. Give page, "field", "value" copied exactly from that page, "clause" and "standard" \
only if they are in the draft rows you were given, and "text", one short sentence for the contractor.
- reword: a clearer wording of a row, keeping every number, unit, clause and standard of the row. Give "row_key" and "text".
- understanding: one note: "understanding": {"equipment": "...", "tags": [...], "service": "...", "fluids": [...], \
"revision_stage": "..."} using only words printed in the submittal.
RULES, ALL MANDATORY: every figure, tag and quote must be copied exactly from a page; use no number that is not printed \
there; never say whether anything complies, passes, fails or is acceptable; confidence is low or medium; every proposal \
has a "reason" in one plain sentence; at most 30 proposals; if you have nothing to propose return an empty list."""


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_ai_review (
            review_run_id TEXT NOT NULL, proposal_id TEXT NOT NULL, ptype TEXT NOT NULL, row_key TEXT,
            state TEXT NOT NULL, refusal TEXT, row_kind TEXT, final_text TEXT, proposal TEXT NOT NULL,
            model TEXT, prompt_version TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY (review_run_id, proposal_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_ai_review_runs (
            review_run_id TEXT PRIMARY KEY, summary TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_ai_review_override (
            id INTEGER PRIMARY KEY AUTOINCREMENT, review_run_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('restore', 'unrestore')), by_user TEXT NOT NULL,
            created_at TEXT NOT NULL)""")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_prompt(rows: list[dict], pages: dict[int, str], *, local: bool) -> str:
    """The rows (compact, capped) and the pages (capped; the local model gets only the pages the rows cite)."""
    shown = []
    for row in rows[:MAX_ROWS]:
        shown.append(
            {
                "row_key": row.get("crs_row_key"),
                "kind": row.get("row_kind"),
                "where": row.get("page_section"),
                "standard": row.get("standard_reference"),
                "comment": str(row.get("comment") or "")[:MAX_ROW_CHARS],
            }
        )
    wanted = None
    if local:
        wanted = {
            int(m)
            for r in rows[:MAX_ROWS]
            for m in re.findall(r"p\.(\d+)", str(r.get("page_section") or ""))
        }
    limit = LOCAL_PAGE_CHARS if local else MAX_PAGE_CHARS
    parts = []
    for number, text in pages.items():
        if wanted is not None and number not in wanted:
            continue
        parts.append(f"--- page {number} ---\n{text[:limit]}")
    body = "\n".join(parts)[:MAX_PACKET_CHARS]
    return f"DRAFT ROWS (JSON):\n{json.dumps(shown, ensure_ascii=False)}\n\nSUBMITTAL PAGES:\n{body}"


def _provider():
    """`(provider, local_instead)`: the review's own engine setting; the local model when the documents are not approved."""
    from . import reasoning_provider as rp

    provider = rp.OllamaProvider(
        timeout=float(settings.ai_engineering_review_pass_timeout_s)
    )
    claude = rp.claude_for_task(
        settings.ai_engineering_review_pass_engine, "labelling", step=STEP
    )
    if claude is not None:
        note = claude_approved.local_instead()
        if note:
            return provider, note
        return claude, None
    return provider, None


def _ask(provider, prompt: str):
    """(parsed proposals or None, refusal, model). A transport failure raises."""
    from . import reasoning_provider as rp

    response = provider.reason(
        rp.Packet(
            prompt=prompt,
            system=SYSTEM,
            num_ctx=16384,
            num_predict=MAX_OUTPUT_TOKENS,
            json_schema=SCHEMA,
            step=STEP,
            prompt_version=PROMPT_VERSION,
            timeout_s=float(settings.ai_engineering_review_pass_timeout_s),
        )
    )
    model = f"{response.provider}:{response.model_tag}"
    state = output_limits.state_of_response(response)
    if state != output_limits.COMPLETE:
        return None, state, model
    try:
        proposals = json.loads(response.text).get("proposals")
    except (TypeError, ValueError, AttributeError):
        return None, MALFORMED, model
    if response.schema_errors or not isinstance(proposals, list):
        return None, MALFORMED, model
    return proposals, None, model


def _store(review_run_id: str, summary: dict) -> dict:
    ensure_schema()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO crs_ai_review_runs (review_run_id, summary, created_at) VALUES (?, ?, ?)",
            (review_run_id, json.dumps(summary), _now()),
        )
    return summary


def _keyed(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("crs_row_key")]


def _engine(summary: dict, provider):
    """(provider, stop). Sets summary["engine"] and "local_instead"; `stop` is the reason the pass cannot run, or None."""
    from . import reasoning_provider as rp

    own = provider is None
    try:
        if own:
            provider, summary["local_instead"] = _provider()
    except Exception as exc:  # noqa: BLE001 - never fails the review
        return None, f"no model available ({type(exc).__name__})"
    cloud = isinstance(provider, rp.ClaudeProvider)
    summary["engine"] = "claude" if cloud else "local"
    if own and not cloud and local_engine_bar.refuses(STEP):
        return None, local_engine_bar.NOTE
    return provider, None


def _rows_to_store(review_run_id: str, verdicts: list, summary: dict, rows: dict) -> list[tuple]:
    """One stored row per verdict; counts the accepted and refused in the summary."""
    now, out = _now(), []
    for i, verdict in enumerate(verdicts):
        proposal = dict(verdict.proposal) if isinstance(verdict.proposal, dict) else {}
        touched = rows.get(str(proposal.get("row_key") or ""))
        if verdict.accepted and touched and proposal.get("type") in ("remove", "reword"):
            # The row's own words and place, kept so the removal can be shown and reversed after the row is gone.
            proposal["row_words"] = str(touched.get("comment") or "")
            proposal["row_where"] = str(touched.get("page_section") or "")
            proposal["row_standard"] = str(touched.get("standard_reference") or "")
        pid = str(proposal.get("id") or f"auto-{i + 1}")
        if verdict.accepted:
            summary["accepted"][proposal["type"]] += 1
        else:
            reason = str(verdict.reason).split(":")[0]
            summary["refused"][reason] = summary["refused"].get(reason, 0) + 1
        if any(row[1] == pid for row in out):
            pid = f"{pid}#{i + 1}"
        out.append(
            (
                review_run_id,
                pid,
                str(proposal.get("type") or ""),
                proposal.get("row_key"),
                "accepted" if verdict.accepted else "refused",
                None if verdict.accepted else verdict.reason,
                verdict.row_kind,
                verdict.final_text,
                json.dumps(proposal, ensure_ascii=False),
                summary["model"],
                PROMPT_VERSION,
                now,
            )
        )
    return out


@claude_approved.for_review  # #806 S3: the review's submittal and standards are the documents this call carries
def run(
    review_run_id: str,
    rows: list[dict],
    *,
    pages: dict[int, str],
    held: dict[str, list[str]],
    provider=None,
    out_of_scope=frozenset(),
    compare=None,
) -> dict:
    """Ask once, verify every proposal, store every verdict. Returns and stores the run's summary. Never raises."""
    ensure_schema()
    summary = {
        "enabled": bool(settings.ai_engineering_review_pass_enabled),
        "model": None,
        "proposed": 0,
        "accepted": dict.fromkeys(arp.TYPES, 0),
        "refused": {},
        "stopped": None,
        "local_instead": None,
        "engine": None,
    }
    if not summary["enabled"]:
        summary["stopped"] = "off (AI_ENGINEERING_REVIEW_PASS_ENABLED=false)"
        return _store(review_run_id, summary)
    provider, summary["stopped"] = _engine(summary, provider)
    if summary["stopped"]:
        return _store(review_run_id, summary)
    context = arp.Context(
        pages=pages,
        rows={r["crs_row_key"]: r for r in _keyed(rows)},
        held=held,
        out_of_scope=frozenset(out_of_scope),
        compare=compare,
    )
    try:
        proposals, refusal, summary["model"] = _ask(
            provider, build_prompt(rows, pages, local=summary["engine"] == "local")
        )
    except Exception as exc:  # noqa: BLE001 - never fails the review
        log.info("ai review pass: the model call failed (%s)", type(exc).__name__)
        summary["stopped"] = (
            f"the model call failed ({type(exc).__name__}); the draft CRS stands"
        )
        return _store(review_run_id, summary)
    if proposals is None:
        summary["stopped"] = (
            f"the model's answer was not usable ({refusal}); the draft CRS stands"
        )
        return _store(review_run_id, summary)
    verdicts = arp.verify_all(proposals, context)
    summary["proposed"] = len(verdicts)
    stored = _rows_to_store(review_run_id, verdicts, summary, context.rows)
    with connect() as conn:
        conn.execute(
            "DELETE FROM crs_ai_review WHERE review_run_id = ?", (review_run_id,)
        )
        conn.executemany(
            "INSERT INTO crs_ai_review (review_run_id, proposal_id, ptype, row_key, state, refusal, row_kind,"
            " final_text, proposal, model, prompt_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            stored,
        )
    log.info(
        "ai review pass: run %s proposed %d accepted %s refused %s",
        review_run_id,
        summary["proposed"],
        summary["accepted"],
        summary["refused"],
    )
    return _store(review_run_id, summary)


def run_for_job(review_run_id: str, scope) -> dict | None:
    """The review job's call (a write path, never the export or preview): read the finished run's internal CRS rows, the
    submittal's pages and the held standards, then `run`. OFF unless AI_ENGINEERING_REVIEW_PASS_ENABLED. NEVER FAILS
    THE REVIEW: any failure is logged (ids only) and the draft CRS stands. Returns the run's summary, or None."""
    if not settings.ai_engineering_review_pass_enabled:
        return None
    try:
        from . import ai_engineering_check
        from .main import _crs_content

        with crs_ai_review_view.unapplied():
            rows, _meta, _name, _stamp = _crs_content(review_run_id, scope, "internal")
        submittal = (
            connect()
            .execute(
                "SELECT submittal_document_id FROM review_runs WHERE id = ?",
                (review_run_id,),
            )
            .fetchone()["submittal_document_id"]
        )
        return run(
            review_run_id,
            rows,
            pages=ai_engineering_check.datasheet_pages(submittal),
            held=ai_engineering_check._held_standards(review_run_id),
        )
    except Exception:
        log.warning(
            "ai review pass: run %s failed; the draft CRS stands",
            review_run_id,
            exc_info=True,
        )
        return None


def accepted(review_run_id: str) -> list[dict]:
    """The accepted proposals of a run, each with its stored verdict. Read only."""
    ensure_schema()
    out = []
    for r in connect().execute(
        "SELECT * FROM crs_ai_review WHERE review_run_id = ? AND state = 'accepted'"
        " ORDER BY rowid",
        (review_run_id,),
    ):
        out.append(
            {
                **json.loads(r["proposal"]),
                "proposal_id": r["proposal_id"],
                "row_kind": r["row_kind"],
                "final_text": r["final_text"],
            }
        )
    return out


def summary_of(review_run_id: str) -> dict | None:
    ensure_schema()
    row = (
        connect()
        .execute(
            "SELECT summary FROM crs_ai_review_runs WHERE review_run_id = ?",
            (review_run_id,),
        )
        .fetchone()
    )
    return json.loads(row["summary"]) if row else None


def restore(
    review_run_id: str, proposal_id: str, by_user: str, *, undo: bool = False
) -> bool:
    """An engineer puts a removed row back (or takes the restore back). Append-only; the removal record stays.
    False when there is no accepted removal of that id."""
    ensure_schema()
    found = (
        connect()
        .execute(
            "SELECT 1 FROM crs_ai_review WHERE review_run_id = ? AND proposal_id = ? AND ptype = 'remove'"
            " AND state = 'accepted'",
            (review_run_id, proposal_id),
        )
        .fetchone()
    )
    if not found or not str(by_user or "").strip():
        return False
    with connect() as conn:
        conn.execute(
            "INSERT INTO crs_ai_review_override (review_run_id, proposal_id, action, by_user, created_at)"
            " VALUES (?,?,?,?,?)",
            (
                review_run_id,
                proposal_id,
                "unrestore" if undo else "restore",
                by_user.strip(),
                _now(),
            ),
        )
    return True


def restored_ids(review_run_id: str) -> set[str]:
    """Proposal ids whose latest override is a restore."""
    ensure_schema()
    state: dict[str, str] = {}
    for r in connect().execute(
        "SELECT proposal_id, action FROM crs_ai_review_override WHERE review_run_id = ?"
        " ORDER BY id",
        (review_run_id,),
    ):
        state[r["proposal_id"]] = r["action"]
    return {k for k, v in state.items() if v == "restore"}
