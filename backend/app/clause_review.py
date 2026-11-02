"""AI clause review of a procedure or specification submittal (#1477, C1-6).

The review of a datasheet compares values. A procedure (a HAZOP procedure, a
SIL procedure) or a specification has no value table: what an engineer asks is
"does this document address clause 5.3 of the requirement?". This module asks
the LOCAL model exactly that, ONE requirement at a time, and lets code decide
what survives (top rule, AI-first: the AI reads and proposes, code verifies,
the engineer decides).

THE METHOD (`7-weaker-brain-research.md`, 1 Nov 2026):
  * one clause-sized question against the 4 most relevant SMALL passages
    (about 800 characters) of the submittal - not the whole document;
  * thinking on;
  * 5 to 10 decision examples of the document's kind in the prompt
    (`reference/clause_review_examples/<kind>.json`, today INVENTED and marked
    so on the file and on every row until the engineers supply real ones);
  * "no evidence" is its own answer.

WHAT THE CODE ENFORCES, NOT THE MODEL:
  * NEVER COMPLIANT. Every row is NEEDS_ENGINEER_REVIEW. A quote that checks
    out is "AI suggestion, engineer to confirm"; it is never a pass.
  * EVERY QUOTE IS VERIFIED: it must be an exact substring (white space and
    case folded) of the STORED text of the page the AI named. A quote that is
    not is dropped, never shown as evidence, and the row says so.
  * "NO EVIDENCE" IS NOT "MISSING": the passage may be there in other words, so
    the row says "the AI found no passage; engineer to check".
  * Rows are not counted in any headline (`without_rows`), carry origin
    `clause_review`, and are worded by code, never reworded by the model.
  * THIS FILE'S RUN IS THE LOCAL MODEL: `OllamaProvider`, through `model_transport`.
    The Claude lane is `clause_review_claude.py`, behind its own engine setting
    (`AI_CLAUSE_REVIEW_ENGINE`, default local; owner on #1584, 2 Nov 2026, over D1).
  * A TIME BUDGET: pages x `clause_review_seconds_per_page`. When it is spent the
    run stops cleanly and names the requirements not reviewed. Measured minutes
    per page is recorded.
  * A CACHE: key = (the text the model saw, requirement id and text, model, prompt
    version). A re-run over unchanged pages makes no model call; the cached
    quote is verified again against the stored page text on every use.

OFF unless `settings.clause_review_enabled`. The provider and the clock are
injectable, so every test runs against a fake: no socket.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from . import clause_review_status, job_progress, local_engine_bar, scope_quote
from .clause_review_kind import ask_fields, cache_model, not_for_kind
from .config import settings
from .crs_draft_lanes import CLAUSE_ORIGIN
from .db import connect

log = logging.getLogger(__name__)

ORIGIN = CLAUSE_ORIGIN
STEP = "clause_review"
PROMPT_VERSION = "clause-review-v1"
#: The kinds this review is for (`document_kinds`, the router's table).
KINDS = ("procedure", "specification")
EXAMPLES_DIR = Path(__file__).parent / "reference" / "clause_review_examples"
INVENTED_MARK = "INVENTED - replace with engineer examples"

PASSAGES = 4
PASSAGE_CHARS = 800
#: A quote shorter than this many words proves nothing (any three words are on some page).
MIN_QUOTE_WORDS = 5

NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"

#: The words on the row (rule 4: a guess is shown as a guess).
TEXT_VERIFIED = "AI suggestion, engineer to confirm"
TEXT_NO_EVIDENCE = (
    f"The AI read the {PASSAGES} most relevant passages of the document and found none "
    "that addresses this requirement; engineer to check (it may be stated in other words)."
)
TEXT_UNVERIFIED = (
    "The AI named a passage on page {page}, but its quote could not be verified in the "
    "stored text of that page, so it is not shown; engineer to check."
)
TEXT_UNREADABLE = (
    "The AI's answer for this requirement could not be read; engineer to check."
)
LABEL = "AI clause review - engineer to confirm"

SCHEMA = {
    "type": "object",
    "required": ["answer", "page", "quote"],
    "properties": {
        "answer": {"type": "string", "enum": ["quote", "no_evidence"]},
        "page": {"type": ["integer", "null"]},
        "quote": {"type": ["string", "null"]},
    },
}

SYSTEM = """You help an engineer review a contractor's document against ONE requirement.
You are shown the requirement and up to four short passages of the document, each \
marked with its page.
Decide ONE thing: does the document address this requirement?
- If a passage addresses it, answer "quote" with that page and an EXACT quotation \
copied word for word from the passage (a whole clause or sentence, at least five \
words, no ellipsis, nothing added).
- If no passage addresses it, answer "no_evidence" with page null and quote null. \
Passages about a nearby topic do not count. When unsure, answer "no_evidence".
You never say the document complies. The engineer decides that.
Answer with JSON only: {"answer": "quote" | "no_evidence", "page": number | null, "quote": string | null}."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


# ------------------------------------------------------------------ examples


@lru_cache(maxsize=8)
def _load_examples(path: str, mtime: float) -> tuple[dict, ...]:
    del mtime  # only part of the cache key: a changed file is read again
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("examples") or []
    # An example is a decision rule an engineer would own. Until they are theirs,
    # every row says it is invented; an unmarked row is refused, never silently used.
    if data.get("label") != INVENTED_MARK and not data.get("engineer_supplied"):
        raise ValueError(
            f"{path}: the file is not marked {INVENTED_MARK!r} nor engineer supplied"
        )
    for row in rows:
        if row.get("label") != INVENTED_MARK and not data.get("engineer_supplied"):
            raise ValueError(f"{path}: an example row is not marked {INVENTED_MARK!r}")
    return tuple(rows)


def examples(kind: str) -> list[dict]:
    """The decision examples of one kind (5 to 10); [] when there are none."""
    path = EXAMPLES_DIR / f"{kind}.json"
    if not path.exists():
        return []
    return list(_load_examples(str(path), path.stat().st_mtime))[:10]


def _example_text(rows: list[dict]) -> str:
    out = []
    for i, row in enumerate(rows, 1):
        passages = "\n".join(f"[page {p['page']}] {p['text']}" for p in row["passages"])
        out.append(
            f"EXAMPLE {i}\nRequirement: {row['requirement']}\nPassages:\n{passages}\n"
            f"Answer: {json.dumps(row['answer'])}\n(Why: {row['why']})"
        )
    return "\n\n".join(out)


# ------------------------------------------------------------- the document


def page_texts(document_id: str) -> dict[int, str]:
    """The submittal's STORED text by page (`pages`), the text a quote is proved against."""
    return {
        r["page_no"]: r["text"] or ""
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    }


def verify_quote(quote, page_text) -> bool:
    """Is `quote` real text of that page? An exact substring, white space and case
    folded, long enough to mean something, and not a run of codes or figures.
    Pure; the one test every AI quote passes before it is shown."""
    folded = _fold(quote)
    if not folded or "..." in folded or "…" in folded:
        return False
    if len(scope_quote._WORD.findall(folded)) < MIN_QUOTE_WORDS:
        return False
    letters = sum(ch.isalpha() for ch in folded)
    if letters / max(1, len(folded.replace(" ", ""))) < scope_quote.MIN_LETTER_SHARE:
        return False
    return folded in _fold(page_text)


_STOP = frozenset((
    "shall", "must", "should", "will", "with", "that", "this", "from", "have", "been",
    "were", "their", "there", "which", "when", "where", "each", "every", "into", "than",
    "then", "also", "such", "only", "other", "more", "less", "those", "these", "they",
    "them", "being", "under", "over", "about", "after", "before", "between",
))  # fmt: skip


def _terms(text: str) -> list[str]:
    seen = dict.fromkeys(
        w
        for w in re.findall(r"[a-z0-9][a-z0-9.\-]{3,}", text.lower())
        if w not in _STOP
    )
    return list(seen)[:12]


def _best_window(text: str, terms: list[str]) -> str:
    """The ~800 character window of `text` that holds most of the terms."""
    words = text.split()
    windows: list[str] = []
    current: list[str] = []
    size = 0
    for word in words:
        if size + len(word) + 1 > PASSAGE_CHARS and current:
            windows.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += len(word) + 1
    if current:
        windows.append(" ".join(current))
    if not windows:
        return ""
    return max(windows, key=lambda w: sum(t in w.lower() for t in terms))


def retrieve(
    document_id: str, requirement_text: str, pages: dict[int, str]
) -> list[dict]:
    """The `PASSAGES` most relevant small passages of the submittal for one
    requirement: [{"page", "text"}], ordered by relevance. The keyword index first
    (`fts_index.search`, scoped to this document alone), then the chunks that share
    the most terms; each chunk gives its best ~800 character window."""
    from . import fts_index

    terms = _terms(requirement_text)
    ranked: list[str] = []
    try:
        for hit in fts_index.search(
            " ".join(terms),
            limit=PASSAGES * 2,
            document_id=document_id,
            allowed_document_ids=frozenset({document_id}),
        ):
            ranked.append(hit["chunk_id"])
    except Exception as exc:  # noqa: BLE001 - the term-overlap fallback below still answers
        log.warning("clause review: keyword index not used: %s", type(exc).__name__)
    chunks = {
        r["id"]: r
        for r in connect().execute(
            "SELECT id, page_start, page_end, text FROM chunks WHERE document_id = ?"
            " AND COALESCE(retrievable, 1) = 1 ORDER BY ordinal",
            (document_id,),
        )
    }
    by_overlap = sorted(
        (cid for cid in chunks if cid not in ranked),
        key=lambda cid: -sum(t in (chunks[cid]["text"] or "").lower() for t in terms),
    )
    out: list[dict] = []
    for cid in [*ranked, *by_overlap]:
        row = chunks.get(cid)
        if row is None or not (row["text"] or "").strip():
            continue
        if cid in by_overlap and not any(t in row["text"].lower() for t in terms):
            continue
        window = _best_window(row["text"], terms)
        page = _page_of(
            window,
            row["page_start"] or 1,
            row["page_end"] or row["page_start"] or 1,
            pages,
        )
        out.append({"page": page, "text": window})
        if len(out) == PASSAGES:
            break
    return out


def _page_of(window: str, start: int, end: int, pages: dict[int, str]) -> int:
    if end <= start:
        return start
    head = _fold(window)[:60]
    for p in range(start, end + 1):
        if head and head in _fold(pages.get(p)):
            return p
    return start


def requirements_for(review_run_id: str, allowed: frozenset[str]) -> list[dict]:
    """The run's applicable requirements: the active requirements of every
    standard the run included, that the caller may read, in standard / page /
    clause order. Clause-sized text only (an empty one is not a question)."""
    rows = (
        connect()
        .execute(
            """SELECT q.id, q.standard_document_id, q.clause, q.page, q.requirement_text, q.source_text
           FROM standard_requirements q
           JOIN review_applicable_standards a ON a.standard_document_id = q.standard_document_id
          WHERE a.review_run_id = ? AND a.included = 1 AND q.superseded_at IS NULL
          ORDER BY q.standard_document_id, q.page, q.clause, q.id""",
            (review_run_id,),
        )
        .fetchall()
    )
    return [
        dict(r)
        for r in rows
        if r["standard_document_id"] in allowed
        and (r["requirement_text"] or "").strip()
    ]


# --------------------------------------------------------------------- model


def examples_prefix(kind: str) -> str:
    """The part of a prompt that is the same for every requirement of one kind."""
    return (
        f"DECISION EXAMPLES for a {kind} (they show how an engineer decides):\n\n"
        f"{_example_text(examples(kind))}\n\n---\n\n"
    )


def question(requirement: dict, passages: list[dict]) -> str:
    """One requirement and its few passages: all of the document an ask carries."""
    shown = (
        "\n\n".join(f"[page {p['page']}] {p['text']}" for p in passages)
        or "(no passage found)"
    )
    clause = f" (clause {requirement['clause']})" if requirement.get("clause") else ""
    return (
        f"NOW THE REAL QUESTION.\nRequirement{clause}: {requirement['requirement_text'].strip()[:1200]}\n\n"
        f"Passages of the document:\n{shown}\n\nAnswer with JSON only."
    )


def build_prompt(kind: str, requirement: dict, passages: list[dict]) -> str:
    return examples_prefix(kind) + question(requirement, passages)


def cache_key(passages: list[dict], requirement: dict, model: str) -> str:
    """What makes two asks the same: the text the model saw (with its pages), the
    requirement (id and words), the model and the prompt version."""
    seen = "\x1e".join(f"{p['page']}\x1f{p['text']}" for p in passages)
    raw = "\x1d".join(
        (
            seen,
            str(requirement["id"]),
            requirement["requirement_text"],
            model,
            PROMPT_VERSION,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("answer") not in ("quote", "no_evidence"):
        return None
    return data


def _classify(
    answer: dict | None, pages: dict[int, str]
) -> tuple[str, int | None, str | None]:
    """(outcome, page, quote). The ONLY place an AI answer becomes a row."""
    if answer is None:
        return "unreadable", None, None
    if answer["answer"] == "no_evidence":
        return "no_evidence", None, None
    page, quote = answer.get("page"), answer.get("quote")
    if (
        isinstance(page, int)
        and not isinstance(page, bool)
        and page in pages
        and verify_quote(quote, pages[page])
    ):
        return "verified", page, " ".join(str(quote).split())
    return (
        "unverified",
        page if isinstance(page, int) and not isinstance(page, bool) else None,
        None,
    )


# ----------------------------------------------------------------- the rows


def _asked(requirement: dict) -> str:
    """The requirement in a few words, so the row names what was asked."""
    words = " ".join(str(requirement["requirement_text"]).split())
    return (
        'Requirement: "' + (words if len(words) <= 220 else words[:217] + "...") + '". '
    )


def _row_text(
    outcome: str, page: int | None, quote: str | None, requirement: dict
) -> tuple[str, str | None]:
    """(the finding words, the page it may cite). A page is cited only for a
    verified quote: an unverified page is not evidence of anything."""
    asked = _asked(requirement)
    if outcome == "verified":
        return (
            f"{TEXT_VERIFIED}. {asked}The document may address it on page {page}: "
            f'"{quote}"',
            page,
        )
    if outcome == "no_evidence":
        return (asked + TEXT_NO_EVIDENCE, None)
    if outcome == "unverified":
        shown = page if page is not None else "(not given)"
        return (asked + TEXT_UNVERIFIED.format(page=shown), None)
    return (asked + TEXT_UNREADABLE, None)


def _store_row(
    review_run_id: str,
    submittal: str,
    requirement: dict,
    outcome: str,
    page: int | None,
    quote: str | None,
    engine: str,
    cached: bool,
) -> None:
    from . import review as rv

    text, cite_page = _row_text(outcome, page, quote, requirement)
    rationale = f"{LABEL}. Written by {engine}{' (stored answer)' if cached else ''}, prompt {PROMPT_VERSION}."
    conn = connect()
    with conn:
        # only this requirement's own UNDECIDED row is replaced; an engineer's
        # decision on it, and the rows of requirements not asked this time, stay.
        conn.execute(
            "DELETE FROM review_findings WHERE review_run_id = ? AND origin = ? AND requirement_id = ?"
            f" AND {rv.UNDECIDED_SQL}",
            (review_run_id, ORIGIN, requirement["id"]),
        )
        if conn.execute(
            "SELECT 1 FROM review_findings WHERE review_run_id = ? AND origin = ? AND requirement_id = ?",
            (review_run_id, ORIGIN, requirement["id"]),
        ).fetchone():
            return  # an engineer decided it: not written twice
        finding = rv.create(
            {
                "document_id": submittal,
                "category": "technical_query",
                "severity": "minor",
                "confidence": "low",
                "requirement": requirement["requirement_text"][:4000],
                "finding": text,
                "required_action": "",
                "status": "open",
                "approval_status": "pending",
                "review_run_id": review_run_id,
                "origin": ORIGIN,
                "compliance_status": NEEDS_ENGINEER_REVIEW,
                "contractor_page": cite_page,
                "contractor_evidence_text": quote if outcome == "verified" else None,
                "requirement_source_text": (
                    requirement.get("source_text") or requirement["requirement_text"]
                )[:4000],
                "ai_rationale": rationale,
                "standard_clause": requirement.get("clause"),
            },
            created_by=None,
            conn=conn,
        )
        conn.execute(
            "UPDATE review_findings SET requirement_id = ?, standard_document_id = ? WHERE id = ?",
            (requirement["id"], requirement["standard_document_id"], finding["id"]),
        )


_CACHE_TABLE = """CREATE TABLE IF NOT EXISTS clause_review_cache (
    key         TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    answer      TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL
)"""


def ensure_schema(conn=None) -> None:
    """The stored-answer table, created on first use (like `field_naming`'s
    table), never by an edit of the shared schema. Key = sha256(the text the
    model saw, requirement id and words, model, prompt version); `answer` is the
    model's raw JSON, verified again on every use."""
    (conn or connect()).execute(_CACHE_TABLE)


#: Where the run's own outcome is kept: under this key of `review_runs.ai_check_status`,
#: the AI steps' record every screen and the CRS already read (`ai_check_status`).
STATUS_KEY = "clause_review"
_PLAIN_MARK = " AI clause review "


def _stored_ai_status(conn, review_run_id: str) -> dict:
    row = conn.execute(
        "SELECT ai_check_status FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    try:
        data = json.loads(row[0]) if row and row[0] else {}
    except (TypeError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _store_status(review_run_id: str, status: dict) -> None:
    """Keep the outcome under `ai_check_status[STATUS_KEY]` and its plain sentence
    at the end of that status' `plain` (so every screen that prints it shows it).
    When the AI engineering check did not run, the record says so (it is true)."""
    conn = connect()
    data = _stored_ai_status(conn, review_run_id)
    if not data:
        data = {
            "ran": False,
            "reason": "the AI engineering check was not run on this review",
        }
    base = str(data.get("plain") or "").split(_PLAIN_MARK)[0].strip()
    data[STATUS_KEY] = status
    data["plain"] = (base + " " + status["plain"]).strip()
    with conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data), _now(), review_run_id),
        )


def write_ai_status(review_run_id: str, status: dict) -> None:
    """The ONE way the AI engineering check (and its failure record) writes
    `ai_check_status`: it keeps an existing clause review entry and its sentence,
    so a later /ai-check re-run never makes the sheet look fully read."""
    conn = connect()
    clause = _stored_ai_status(conn, review_run_id).get(STATUS_KEY)
    if clause:
        base = str(status.get("plain") or "").split(_PLAIN_MARK)[0].strip()
        status = {
            **status,
            STATUS_KEY: clause,
            "plain": (base + " " + clause["plain"]).strip(),
        }
    with conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(status), _now(), review_run_id),
        )


def status_of(review_run_id: str) -> dict | None:
    """The run's stored clause review outcome (counts and names, never text); None if it never ran."""
    return _stored_ai_status(connect(), review_run_id).get(STATUS_KEY)


def without_rows(findings: list[dict]) -> list[dict]:
    """The findings with this review's rows left out: they are suggestions for the
    engineer, never counted in a headline (tiers, sheet counts, per-status counts)."""
    return [f for f in findings if f.get("origin") not in (ORIGIN, "spec_kit")]


# ------------------------------------------------------------------- the run


def eligible(submittal_id: str) -> tuple[str | None, str | None]:
    """(kind, state) of a qualifying router kind, else (None, why-not)."""
    from . import document_kind

    stored = document_kind.stored_kind(submittal_id)
    if stored is None or stored[0] not in KINDS:
        return None, "its document kind is not a procedure or a specification"
    if not examples(stored[0]):
        return None, f"there are no decision examples for a {stored[0]}"
    return stored[0], stored[1]


def for_review(review_run_id: str, scope: frozenset[str]) -> None:
    """The review job's call: after the comparison, only with the switch on and a
    qualifying kind. A failure never fails the review: it is logged by kind (never
    text) and recorded on the run."""
    if not settings.clause_review_enabled:
        return
    from . import clause_review_claude

    try:
        # The Claude lane, only when its own engine setting says so and its gates are open.
        started, claude_note = clause_review_claude.for_review(review_run_id, scope)
        if started:
            return
        if local_engine_bar.refuses(
            STEP
        ):  # the local path, in a Claude-lane run: said, not run
            plain = f"AI clause review {local_engine_bar.NOTE}"
            if claude_note:
                plain += f" ({claude_note})"
            _store_status(review_run_id, {"ran": False, "plain": plain})
            return
        run(review_run_id, allowed_document_ids=scope, claude_note=claude_note)
    except Exception as exc:  # noqa: BLE001 - suggestions are optional; the review stands
        log.warning("clause review skipped: %s", type(exc).__name__)
        with contextlib.suppress(Exception):
            rows = (
                connect()
                .execute(
                    "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ? AND origin = ?",
                    (review_run_id, ORIGIN),
                )
                .fetchone()[0]
            )
            plain = (
                f"AI clause review stopped by an error ({type(exc).__name__}) after "
                f"{rows} clause(s) got a row; the rest were not reviewed"
            )
            _store_status(
                review_run_id,
                {
                    "ran": False,
                    "stopped_by_error": True,
                    "rows_before_stop": rows,
                    "plain": plain,
                },
            )


_FAILED = object()
_SKIPPED = object()


def _answer(provider, kind, req, passages, status, submittal, model, cache_only=False):
    """(the parsed answer or None, was it stored, the engine) for one requirement.
    A stored answer makes no model call; a cut-off or schema-breaking reply is no answer."""
    from . import reasoning_provider as rp

    state = status["kind_state"]
    key = cache_key(passages, req, cache_model(model, kind, state))
    conn = connect()
    ensure_schema(conn)
    stored = conn.execute(
        "SELECT answer FROM clause_review_cache WHERE key = ?", (key,)
    ).fetchone()
    if stored is not None:
        status["cache_hits"] += 1
        return _parse(stored["answer"]), True, None
    if (
        cache_only
    ):  # whole-document mode, budget spent: a stored answer costs no model time
        return _SKIPPED, False, None
    packet = rp.Packet(
        prompt=build_prompt(kind, req, passages),
        num_ctx=int(settings.local_num_ctx),
        num_predict=int(settings.clause_review_num_predict),
        step=STEP,
        think=True,
        timeout_s=float(settings.clause_review_call_timeout_s),
        **ask_fields(SYSTEM, SCHEMA, PROMPT_VERSION, kind, status["kind_state"]),
    )
    status["calls"] += 1
    try:
        response = provider.reason(packet)
    except rp.ProviderRefused:
        return _FAILED, False, None
    engine = f"{response.provider}:{response.model_tag}"
    answer = (
        None if response.truncated or response.schema_errors else _parse(response.text)
    )
    if answer is not None:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO clause_review_cache (key, document_id, answer, model, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, submittal, json.dumps(answer), model, _now()),
            )
    return answer, False, engine


def _start_status(
    kind: str, state: str, model: str, pages: int, budget_s: float, wanted: int
) -> dict:
    invented = any(e.get("label") == INVENTED_MARK for e in examples(kind))
    return {
        "ran": True, "kind": kind, "kind_state": state, "model": model,
        "prompt_version": PROMPT_VERSION, "examples": "invented" if invented else "engineer",
        "pages": pages, "budget_seconds": round(budget_s, 1), "requirements": wanted,
        "calls": 0, "cache_hits": 0, "failed": [], "not_reviewed": [], "stopped": None,
        **dict.fromkeys(("verified", "no_evidence", "unverified", "unreadable"), 0),
    }  # fmt: skip


def _finish_status(review_run_id: str, status: dict, elapsed: float) -> dict:
    clause_review_status.fill(status, elapsed)
    _store_status(review_run_id, status)
    return status


def _label(req: dict) -> str:
    return req.get("clause") or req["id"]


def _row_or_line(
    review_run_id, submittal, req, answer, pages, status, engine, cached
) -> None:
    """Code classifies; a requirement not for this document kind is counted for the one line, with no row."""
    outcome, page, quote = _classify(answer, pages)
    if not_for_kind(answer, outcome, req, status["kind"], status["kind_state"]):
        status.setdefault("not_for_kind", []).append(_label(req))
        return
    status[outcome] += 1
    _store_row(review_run_id, submittal, req, outcome, page, quote, engine, cached)


def run(review_run_id: str, *, allowed_document_ids: frozenset[str], provider=None,
        clock=time.monotonic, claude_note: str | None = None) -> dict:  # fmt: skip
    """Review one run's submittal clause by clause. Returns the counts (never text)
    and stores them on the run. Does nothing, and records nothing, when the switch
    is off or the kind does not qualify."""
    from . import reasoning_provider as rp
    from . import submittal_review

    if not settings.clause_review_enabled:
        return {"ran": False, "reason": "off"}
    run_row = submittal_review.get_review_run(
        review_run_id, allowed_document_ids=allowed_document_ids
    )
    if run_row is None:
        return {"ran": False, "reason": "no review run with that id"}
    submittal = run_row["submittal_document_id"]
    kind, state = eligible(submittal)
    if kind is None:
        return {"ran": False, "reason": state}
    if provider is None:
        # This path is local: never `get_provider`, which may return Claude.
        provider = rp.OllamaProvider(
            timeout=float(settings.clause_review_call_timeout_s)
        )
    model = str(getattr(provider, "requested_model", None) or "local")
    pages = page_texts(submittal)
    readable = [p for p, t in pages.items() if t.strip()]
    whole = bool(settings.clause_review_whole_document_enabled)
    budget_s = max(1, len(readable)) * float(settings.clause_review_seconds_per_page)
    if whole:
        # Whole-document mode: ONE time budget for the run replaces the count cap.
        budget_s = float(settings.clause_review_time_budget_s)
    wanted = requirements_for(review_run_id, allowed_document_ids)
    cap = int(settings.clause_review_max_requirements)
    if whole or cap <= 0:
        cap = len(wanted)  # no count cap; the time budget is the bound
    status = _start_status(kind, state, model, len(readable), budget_s, len(wanted))
    clause_review_status.note_run(status, whole, cap, len(wanted), claude_note)
    started, engine = clock(), model
    total = min(len(wanted), cap)
    for index, req in enumerate(wanted[:cap]):
        spent = clock() - started >= budget_s
        if spent and not whole:
            status["not_reviewed"] = [_label(r) for r in wanted[index:cap]]
            status["stopped"] = "the time budget for this document was spent"
            break
        if spent:
            status["stopped"] = f"time budget of {round(budget_s)} s reached"
        # #1494: display only, "checking clause N of M"
        job_progress.clause(index + 1, total)
        passages = retrieve(submittal, req["requirement_text"], pages)
        answer, cached, called_engine = _answer(
            provider,
            kind,
            req,
            passages,
            status,
            submittal,
            model,
            cache_only=spent,
        )
        if answer is _SKIPPED:  # budget spent and nothing stored: not reviewed
            status["not_reviewed"].append(_label(req))
            continue
        if answer is _FAILED:
            status["failed"].append(_label(req))
            continue
        engine = called_engine or engine
        _row_or_line(
            review_run_id, submittal, req, answer, pages, status, engine, cached
        )
    if len(wanted) > cap:
        status["not_reviewed"] += [_label(r) for r in wanted[cap:]]
        status["stopped"] = (
            status["stopped"]
            or f"only the first {cap} requirements are reviewed per run"
        )
    return _finish_status(review_run_id, status, clock() - started)
