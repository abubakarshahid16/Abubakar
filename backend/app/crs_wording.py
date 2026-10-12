"""R26 step 8 (#763): the AI writes each CRS comment like a senior engineer;
code locks every fact.

AI UNDERSTANDS, CODE VERIFIES, THE ENGINEER DECIDES. The comment text the CRS
prints is a code template (`crs_mapping.engineer_comment_text`): correct, but
mechanical. For every machine row of a finished review this asks the
configured model (`reasoning_provider.get_provider`: the local engine, or the
Claude lane when it is on) to rewrite that template in a reviewing engineer's
voice - and then refuses any rewrite that changes a fact. A rewrite is kept
only when ALL of these hold (`lock`), else the template stays and the reason
is counted:

  1. it is a non-empty comment of at most `MAX_CHARS`;
  2. every NUMBER in it is a number of the template, the standard reference
     or the page/section (`numparse.number_keys`, both sides): no invented
     value, page or clause;
  3. every UNIT in it is a unit the template states (`claims._UNIT_TABLE`);
  4. the template's clause and standard, when it cites them, are still cited,
     and it names no OTHER standard (`standard_ids`);
  5. no sentence carries two or more words that are neither in the template
     nor in the reviewer vocabulary (`reference/crs_comment_vocabulary.json`):
     no cause, material or fault the model brought with it;
  6. it does not reverse the row: a breach or an open question is never
     worded as conformance.

WHERE IT SHOWS. Accepted rewrites are stored per run and row
(`crs_ai_wording`) and printed in the INTERNAL copy's "AI Review Comments"
column beside the template (`main._crs_content`). The issue copy never
carries them: the contractor gets the template until an engineer edits the
comment (the existing edit route, which makes the words theirs).

NEVER BLOCKS A REVIEW. Off with `crs_ai_wording_enabled` (default ON, owner
rule "AI-first", 11 Oct). The local call has its own short timeout; the first
call that fails stops the step for the run (the template stays everywhere)
and the run records why. Every run records what the AI did (`summary`):
model, rows tried, accepted, refused by reason. Logs carry ids and counts only.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from . import claude_approved
from . import claims, numparse, standard_ids
from .config import settings
from .db import connect
from .reader_api import _contains, _fold

log = logging.getLogger(__name__)

STEP = "crs_wording"
PROMPT_VERSION = "crs-wording-v1"
MAX_CHARS = 600
#: Rows per run: a long sheet is worded in its first rows, the rest keep the
#: template (counted as "not tried").
MAX_ROWS = 60
#: CRS rows the AI may reword: the machine's own comments. An engineer's own
#: words, an AI/web check item, a carried-forward comment are never reworded.
WORDED_KINDS = ("non_compliant", "missing_information", "needs_engineer_review",
                "datasheet_check", "standard_not_cited", "standard_not_applicable")
_OPEN_KINDS = ("missing_information", "needs_engineer_review", "standard_not_cited",
               "standard_not_applicable")

#: The reasons a rewrite is refused. Stable strings: a run reports them.
NO_COMMENT, TOO_LONG, MALFORMED = "no_comment", "too_long", "malformed"
NUMBER_CHANGED, UNIT_CHANGED = "number_not_in_template", "unit_not_in_template"
CLAUSE_DROPPED, STANDARD_CHANGED = "clause_dropped", "standard_changed"
CLAIM_ADDED, STATUS_REVERSED = "claim_not_in_template", "status_reversed"

#: Conformance words a breach or an open question may never carry (the
#: deleted claude_crs_comments gate, #450 / #648).
_CONFORMANCE = ("complies", "comply with", "is compliant", "are compliant", "conforms",
                "meets the requirement", "meets requirement", "satisfies", "acceptable",
                "no comment", "no further action", "is adequate", "in accordance with")
_NEGATED = ("not acceptable", "is not acceptable", "does not comply", "not compliant",
            "non compliant", "non-compliant", "not in accordance", "does not conform",
            "not adequate", "does not meet", "not satisfy", "unacceptable")

_VOCABULARY_PATH = Path(__file__).parent / "reference" / "crs_comment_vocabulary.json"
_WORD = re.compile(r"[a-z]{4,}")
_UNIT_TOKEN = re.compile(r"(?<![a-z0-9])([a-zA-Z°µμ%/]{1,8}[a-zA-Z0-9/]*)")

PROMPT = """You are a senior engineer reviewing a contractor's submittal. Rewrite \
the CRS comment below so it reads as a clear, polite comment from a reviewing \
engineer to the contractor.

RULES (a rewrite that breaks one is thrown away):
- Keep EVERY number, unit, clause, page and standard exactly as written. Add none.
- Add no new fact, cause, material or reason. Say only what the comment says.
- Keep its meaning: a non-compliance stays a non-compliance; a missing value or \
an open question stays open. Never say it complies or is acceptable.
- At most 3 short sentences.

Answer ONLY with JSON: {"comment": "<the rewritten comment>"}

Standard reference: {standard}
Page/section: {where}
Comment: {comment}
"""

SCHEMA = {"type": "object", "properties": {"comment": {"type": "string"}},
          "required": ["comment"]}


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_ai_wording (
            review_run_id TEXT NOT NULL, row_key TEXT NOT NULL, ai_text TEXT NOT NULL,
            model TEXT, prompt_version TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY (review_run_id, row_key))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crs_ai_wording_runs (
            review_run_id TEXT PRIMARY KEY, summary TEXT NOT NULL, created_at TEXT NOT NULL)""")


@lru_cache(maxsize=2)
def _vocabulary(mtime: float) -> frozenset[str]:
    data = json.loads(_VOCABULARY_PATH.read_text(encoding="utf-8"))
    return frozenset(w.lower() for w in data.get("words", []))


def _stems(word: str) -> set[str]:
    out = {word}
    for suffix in ("es", "s", "ed", "ing", "d", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            out.add(word[: -len(suffix)])
    return out


def _units(text: str) -> set[str]:
    found = set()
    for token in _UNIT_TOKEN.findall(text or ""):
        key = token.lower().replace("°", "").replace("µ", "u").replace("μ", "u")
        if key in claims._UNIT_TABLE:
            found.add(claims._UNIT_TABLE[key][1] + "|" + key)
    return {u.split("|")[1] for u in found}


def _clause_of(standard_reference: str) -> str:
    match = re.search(r"\bcl\.\s*([A-Za-z0-9.\-]+)", standard_reference or "")
    return match.group(1).rstrip(".") if match else ""


def _strip_named(folded: str, names: list[str]) -> str:
    for name in names:
        piece = _fold(name)
        if piece:
            folded = re.sub(r"(?<![\w.,])" + re.escape(piece) + r"(?![\w]|[.,]\d)", " ", folded)
    return folded


def _reversed(row_kind: str, text: str) -> bool:
    if row_kind not in ("non_compliant", *_OPEN_KINDS, "datasheet_check"):
        return False
    folded = _fold(text)
    for negated in _NEGATED:
        folded = folded.replace(_fold(negated), " ")
    return any(_contains(folded, _fold(word)) for word in _CONFORMANCE)


def lock(ai_text: str, row: dict) -> str | None:
    """None when the rewrite keeps every fact of the row; else the reason."""
    text = (ai_text or "").strip()
    if not text:
        return NO_COMMENT
    if len(text) > MAX_CHARS:
        return TOO_LONG
    template = str(row.get("comment") or "")
    standard = str(row.get("standard_reference") or "")
    where = str(row.get("page_section") or "")
    given = " ".join((template, standard, where))
    names = standard_ids.cited_standards(given)
    allowed = numparse.number_keys(_strip_named(_fold(given), names) + " " + _fold(given))
    # A standard's own digits are not a value: the text's named standards are
    # stripped too, and a NEW standard is refused by the standard check below.
    said = standard_ids.cited_standards(text)
    if not numparse.number_keys(_strip_named(_fold(text), names + said)) <= allowed:
        return NUMBER_CHANGED
    if not _units(text) <= _units(given):
        return UNIT_CHANGED
    clause = _clause_of(standard)
    if clause and clause in template and not _contains(_fold(text), _fold(clause)):
        return CLAUSE_DROPPED
    for raw in said:
        if not any(standard_ids.same_standard(raw, known) for known in names):
            return STANDARD_CHANGED
    for name in names:
        if name and _contains(_fold(template), _fold(name)) and not any(
                standard_ids.same_standard(raw, name) for raw in said):
            return STANDARD_CHANGED
    vocabulary = _vocabulary(_VOCABULARY_PATH.stat().st_mtime)
    known = set(_WORD.findall(_fold(given)))
    known |= {w for k in known for w in _stems(k)}
    for sentence in re.split(r"(?<=[.!?;])\s+", _strip_named(_fold(text), names)):
        extra = {w for w in _WORD.findall(sentence)
                 if not (_stems(w) & known) and not (_stems(w) & vocabulary)}
        if len(extra) > 1:
            return CLAIM_ADDED
    if _reversed(str(row.get("row_kind") or ""), text):
        return STATUS_REVERSED
    return None


def _provider():
    from . import reasoning_provider as rp
    provider = rp.get_provider("labelling", step=STEP)
    if isinstance(provider, rp.OllamaProvider):
        provider = rp.OllamaProvider(timeout=float(settings.crs_ai_wording_timeout_s))
    return provider


def _provider_for_this_review():
    """`(provider, local_instead)`. #838: when the review's documents are not
    approved for the cloud model, the local model words the rows - nothing
    leaves the machine - and the run's summary says so. Any other refusal (a
    budget cap) is not replaced: it stops the run, as before."""
    from . import reasoning_provider as rp
    provider = _provider()
    if isinstance(provider, rp.ClaudeProvider):
        note = claude_approved.local_instead()
        if note:
            return rp.OllamaProvider(timeout=float(settings.crs_ai_wording_timeout_s)), note
    return provider, None


def _ask(provider, row: dict) -> tuple[str | None, str | None, str]:
    """(ai_text, refusal reason, model). A transport failure raises."""
    from . import reasoning_provider as rp
    prompt = PROMPT.replace("{standard}", str(row.get("standard_reference") or "")) \
        .replace("{where}", str(row.get("page_section") or "")) \
        .replace("{comment}", str(row.get("comment") or ""))
    response = provider.reason(rp.Packet(
        prompt=prompt, num_ctx=4096, num_predict=300, json_schema=SCHEMA, step=STEP,
        prompt_version=PROMPT_VERSION, timeout_s=float(settings.crs_ai_wording_timeout_s)))
    model = f"{response.provider}:{response.model_tag}"
    try:
        text = json.loads(response.text).get("comment")
    except (TypeError, ValueError, AttributeError):
        return None, MALFORMED, model
    if response.schema_errors or not isinstance(text, str):
        return None, MALFORMED, model
    return text, lock(text, row), model


@claude_approved.for_review      # #806 S3: a CRS row is the review's submittal and standards
def word_run(review_run_id: str, rows: list[dict], *, provider=None) -> dict:
    """Ask the model to reword each machine row of a finished run; keep the
    rewrites that pass `lock`. Returns and stores the run's summary."""
    ensure_schema()
    summary = {"enabled": bool(settings.crs_ai_wording_enabled), "model": None, "tried": 0,
               "accepted": 0, "refused": {}, "not_tried": 0, "stopped": None,
               # #838: None, or why the local model ran in the cloud model's place.
               "local_instead": None}
    if not summary["enabled"]:
        summary["stopped"] = "off (CRS_AI_WORDING_ENABLED=false)"
        return _store_summary(review_run_id, summary)
    candidates = [r for r in rows if r.get("row_kind") in WORDED_KINDS and r.get("crs_row_key")
                  and str(r.get("comment") or "").strip()
                  and not str(r.get("comment_by") or "").startswith(("Edited", "Engineer"))]
    summary["not_tried"] = max(0, len(candidates) - MAX_ROWS)
    try:
        if provider is None:
            provider, summary["local_instead"] = _provider_for_this_review()
    except Exception as exc:  # noqa: BLE001 - no model: the template stays
        summary["stopped"] = f"no model available ({type(exc).__name__})"
        return _store_summary(review_run_id, summary)
    kept: list[tuple[str, str]] = []
    for row in candidates[:MAX_ROWS]:
        try:
            text, refused, model = _ask(provider, row)
        except Exception as exc:  # noqa: BLE001 - timeout or model down: stop, keep templates
            summary["stopped"] = f"the model call failed ({type(exc).__name__}); templates kept"
            break
        summary["tried"] += 1
        summary["model"] = model
        if refused:
            summary["refused"][refused] = summary["refused"].get(refused, 0) + 1
        else:
            kept.append((row["crs_row_key"], text.strip()))
    summary["accepted"] = len(kept)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("DELETE FROM crs_ai_wording WHERE review_run_id = ?", (review_run_id,))
        conn.executemany(
            "INSERT INTO crs_ai_wording (review_run_id, row_key, ai_text, model, prompt_version,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(review_run_id, key, text, summary["model"], PROMPT_VERSION, now) for key, text in kept])
    log.info("crs wording: run %s tried %d accepted %d refused %s stopped %s", review_run_id,
             summary["tried"], summary["accepted"], summary["refused"], bool(summary["stopped"]))
    return _store_summary(review_run_id, summary)


def _store_summary(review_run_id: str, summary: dict) -> dict:
    ensure_schema()
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO crs_ai_wording_runs (review_run_id, summary, created_at)"
                     " VALUES (?, ?, ?)", (review_run_id, json.dumps(summary),
                                           datetime.now(UTC).isoformat(timespec="seconds")))
    return summary


def stored(review_run_id: str) -> dict[str, str]:
    """{row_key: accepted AI wording} for a run. Read only."""
    ensure_schema()
    return {r["row_key"]: r["ai_text"] for r in connect().execute(
        "SELECT row_key, ai_text FROM crs_ai_wording WHERE review_run_id = ?", (review_run_id,))}


def summary_of(review_run_id: str) -> dict | None:
    ensure_schema()
    row = connect().execute("SELECT summary FROM crs_ai_wording_runs WHERE review_run_id = ?",
                            (review_run_id,)).fetchone()
    return json.loads(row["summary"]) if row else None
