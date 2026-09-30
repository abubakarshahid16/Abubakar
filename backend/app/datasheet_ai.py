"""AI READS, CODE CHECKS: the datasheet reader with two interchangeable engines.

WHAT THIS IS. `datasheets.extract_facts` reads label/value pairs with rule
readers (grid, text blocks, table shapes). `claude_datasheet.read_page` reads
a page with a model and keeps a proposal only when code can re-derive it from
the page: the quote is on the page, the value and the label's main word are in
the quote, the unit is one `claims` knows, and two runs agree. Until now that
reader was reachable only by one API route. This module makes it a second,
INDEPENDENT reading inside extraction, behind `settings.datasheet_ai_reader`
("off" by default - off is the old extraction, byte for byte).

TWO ENGINES, ONE CALLABLE SHAPE (prompt -> raw text):

  * "ollama" - the local engine, through `reasoning_provider.OllamaProvider`,
    which reaches the socket only through `model_transport` (the URL is
    re-validated by `config.check_model_url` before every request; it is also
    asked once here first, through `model_transport.endpoint`, so a refused
    host is a reason, not a failure).
  * "claude" - the Claude API, only when `reasoning_provider.claude_unavailable`
    says Claude may be used (REASONING_PROVIDER=claude AND both
    STANDARDS_READER_* egress flags AND a key), through
    `reader_transport.transport()` wrapped in `claude_spend.metered` (the USD
    5 per step / USD 20 total caps are checked BEFORE each call leaves, and
    each call is written to the one ledger) and `claude_budget.Budget` (the
    per-run call cap). It is the `claude_api` routes' exact chain, plus the
    REASONING_PROVIDER check those routes lack. NOT through
    `ClaudeProvider.reason`: that path answers a repeated prompt from its
    response cache, which would make rule 6 of `claude_datasheet.accept` (two
    runs must agree) agree with itself.

NOTHING HERE RAISES INTO INGESTION. An engine that is off, unavailable,
failing, answering malformed JSON, or refused by a budget cap leaves the page
to the rule readers and says why (`model_call_for` returns the reason;
`read_pages` records one per page). A cap refusal stops the calls for the rest
of the document - it would refuse every one of them anyway.

THE MERGE IS PURE. `merge_readings(rule_facts, ai_facts)` takes dicts and
returns decisions; `datasheets._extract_facts` applies them. A benchmark can
call `read_page_text_with_ai` and `merge_readings` without a database.

This module imports no HTTP client and opens no socket
(`tests/test_socket_containment.py`).
"""

from __future__ import annotations

from . import claude_datasheet, datasheets
from .claude_spend import StopRun
from .config import settings

# ---------------------------------------------------------------- vocabulary

OFF = "off"
OLLAMA = "ollama"
CLAUDE = "claude"
ENGINES = (OFF, OLLAMA, CLAUDE)

#: The `claude_spend` step every Claude call from this reader is charged to,
#: so the USD 5 per-step cap applies to this reader's own spend.
STEP = "datasheet-ai-reader"

#: Written into `bbox` provenance (`reader`) on every fact this reader wrote
#: or touched, beside the engine name.
READER = "datasheet_ai"

#: An AI-only fact is written exactly as `claude_datasheet.store_facts` writes
#: one: `extraction_method="model"` (so `comparison.low_trust_reason` holds
#: any verdict resting on it until an engineer confirms it) at confidence 0.5.
#: The ENGINE is recorded in the fact's provenance (`bbox`), not in the method,
#: so every existing reader of "model" keeps working.
EXTRACTION_METHOD = claude_datasheet.EXTRACTION_METHOD
AI_CONFIDENCE = claude_datasheet.CONFIDENCE

#: Rules and AI read the SAME value from the same page, independently. That
#: is more evidence than either alone (rule reader 0.6, model 0.5), so it is
#: written higher than both - and still below `comparison`'s 0.9 ceiling for
#: a deterministic comparison: CLAUDE.md rule 4, confidence is never "high".
AGREED_CONFIDENCE = 0.7

#: Decisions `merge_readings` returns.
AGREED = "agreed"
CONFLICT = "conflict"
AI_ONLY = "ai_only"
RULES_ONLY = "rules_only"

#: Local engine packet sizes. A datasheet page plus the prompt does not fit
#: the answer model's 4096-token window, and a page's JSON answer is longer
#: than a chat answer.
OLLAMA_NUM_CTX = 8192
OLLAMA_NUM_PREDICT = 2048
PROMPT_VERSION = "datasheet-ai-1"

#: What the local engine is asked to return (enforced in the engine by
#: Ollama's `format`; `claude_datasheet.parse_response` checks it again).
_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"field": {"type": "string"}, "value": {"type": "string"},
                       "unit": {"type": ["string", "null"]}, "quote": {"type": "string"},
                       "kind": {"type": "string"}},
        "required": ["field", "value", "quote", "kind"]}}},
    "required": ["facts"],
}


class EngineFailed(RuntimeError):
    """The engine answered, but not in a way that can be read (truncated)."""


# ------------------------------------------------------------ the engines

def engine_setting() -> str:
    """`settings.datasheet_ai_reader`, folded. Anything unknown is returned as
    written, and `model_call_for` refuses it with a reason."""
    return (str(settings.datasheet_ai_reader or OFF).strip().lower() or OFF)


def _claude_call():
    from . import claude_budget, claude_spend, reader_api, reader_transport
    from .reasoning_provider import claude_unavailable

    code, why = claude_unavailable()
    if code is not None:
        return None, f"claude engine unavailable ({code}: {why})"
    transport = reader_transport.transport()
    if transport is None:
        return None, "claude engine unavailable (EGRESS_OFF: no transport)"
    call = claude_budget.Budget(reader_api.model_call_via(claude_spend.metered(
        transport, STEP, unbilled=reader_transport.unbilled)))
    call.engine = CLAUDE
    call.step = STEP
    return call, None


def _ollama_call():
    from . import model_transport
    from .reasoning_provider import OllamaProvider, Packet

    # The same gate every request passes (`model_transport.endpoint` ->
    # `config.check_model_url`), asked once up front so a refused host is a
    # reason for the whole document rather than a failure on every page.
    try:
        model_transport.endpoint("/api/generate")
    except Exception as exc:  # noqa: BLE001 - a refused host is a reason, not a crash
        return None, f"ollama engine unavailable ({type(exc).__name__})"
    provider = OllamaProvider(settings.datasheet_ai_ollama_model or settings.answer_model)

    def call(prompt: str) -> str:
        response = provider.reason(Packet(
            prompt=prompt, num_ctx=OLLAMA_NUM_CTX, num_predict=OLLAMA_NUM_PREDICT,
            temperature=0.0, json_schema=_SCHEMA, step=STEP,
            prompt_version=PROMPT_VERSION))
        if response.truncated:
            # A cut-off JSON answer is not an answer; never parsed as one.
            raise EngineFailed("the answer was truncated")
        return response.text

    call.engine = OLLAMA
    return call, None


def model_call_for(engine: str | None = None):
    """`(model_call, None)` for the engine, or `(None, reason)`.

    `engine` defaults to the configured one. NEVER RAISES: an engine that is
    off, unknown or unavailable is a reason the caller records, and the page
    stays with the rule readers. The callable carries `.engine`.
    """
    name = (engine if engine is not None else engine_setting()).strip().lower()
    if name == OFF:
        return None, "DATASHEET_AI_READER is off"
    try:
        if name == OLLAMA:
            return _ollama_call()
        if name == CLAUDE:
            return _claude_call()
    except Exception as exc:  # noqa: BLE001 - never into ingestion
        return None, f"{name} engine unavailable ({type(exc).__name__})"
    return None, f"DATASHEET_AI_READER={name!r} is not one of {', '.join(ENGINES)}"


# ------------------------------------------------------------ one page

def _empty(page_no: int, engine: str | None, **extra) -> dict:
    return {"page": page_no, "engine": engine, "accepted": [], "rejected": [],
            "counts": {}, **extra}


def _read(page_text: str, page_no: int, model_call, engine: str | None) -> dict:
    """`claude_datasheet.read_page` for one page, WITHOUT the rule readers'
    fields as `known_fields`: this is a second, independent reading, and a
    field the rules also read is exactly what agreement is measured on.

    Returns the read_page shape plus `engine`; `error` when the page could
    not be read (engine failure, malformed answer) and `stopped` (the limit's
    count key) when a budget cap refused a call. Only the exception's TYPE is
    kept - a message could carry a URL, never a page's words, but the type is
    all a reader of the result needs."""
    try:
        out = claude_datasheet.read_page(page_text, page_no, None, model_call)
    except StopRun as exc:
        return _empty(page_no, engine, error=f"stopped by a limit ({exc.count_key})",
                      stopped=exc.count_key)
    except Exception as exc:  # noqa: BLE001 - never into ingestion
        return _empty(page_no, engine, error=f"engine failed ({type(exc).__name__})")
    if out.get("error"):
        out["error"] = f"engine answer unusable ({out['error']})"
    out["engine"] = engine
    out["accepted"] = [{**p, "page": page_no} for p in out["accepted"]]
    return out


def read_page_text_with_ai(page_text: str, page_no: int, engine_or_callable) -> dict:
    """One page's text through the AI reader; the accepted facts and why the
    rest were dropped. `engine_or_callable` is an engine name ("ollama",
    "claude") or a `prompt -> text` callable (a benchmark's, or a test's
    fake). Never raises; `error` says why nothing was read."""
    if callable(engine_or_callable):
        call, engine = engine_or_callable, getattr(engine_or_callable, "engine", "custom")
    else:
        engine = str(engine_or_callable)
        call, why = model_call_for(engine)
        if call is None:
            return _empty(page_no, engine, error=why)
    if not (page_text or "").strip():
        return _empty(page_no, engine, error="no text on this page")
    return _read(page_text, page_no, call, engine)


def read_pages(page_texts: dict[int, str], engine_or_callable=None) -> dict:
    """Every page of one document through the reader, in page order.

    Returns `{"engine", "unavailable", "pages": {page: read result},
    "reasons": {page: why this page has no AI reading}, "stopped"}`. After a
    budget refusal no further call is made: the remaining pages are recorded
    as not read, with that reason."""
    if engine_or_callable is None or not callable(engine_or_callable):
        engine = (engine_or_callable or engine_setting())
        call, why = model_call_for(engine)
        engine = getattr(call, "engine", engine)
    else:
        call, why = engine_or_callable, None
        engine = getattr(call, "engine", "custom")
    pages: dict[int, dict] = {}
    reasons: dict[int, str] = {}
    stopped = None
    for page_no in sorted(page_texts):
        text = page_texts[page_no] or ""
        if call is None:
            reasons[page_no] = why
            continue
        if stopped is not None:
            reasons[page_no] = f"not read: a limit stopped the AI reader ({stopped})"
            continue
        if not text.strip():
            reasons[page_no] = "no text on this page"
            continue
        out = _read(text, page_no, call, engine)
        pages[page_no] = out
        if out.get("stopped"):
            stopped = out["stopped"]
        if out.get("error"):
            reasons[page_no] = out["error"]
    return {"engine": engine, "unavailable": why, "pages": pages,
            "reasons": reasons, "stopped": stopped}


def page_text(stored_path: str | None, page_no: int, chunks: list) -> str:
    """The text the AI reader reads for one page: the PDF's own text layer
    for THAT page first (a chunk may span several pages, and a quote proved
    against a neighbour's text would be cited to the wrong page), then the
    stored chunk text only when a chunk covers exactly this page (an OCR'd
    scan has no text layer)."""
    text = claude_datasheet._pdf_page_text(stored_path, page_no) if stored_path else ""
    if text.strip():
        return text
    own = [c for c in chunks
           if c["page_start"] == page_no and (c["page_end"] or c["page_start"]) == page_no]
    return "\n".join((c["text"] or "") for c in own).strip()


# ------------------------------------------------------------ the merge

#: Words in a rule fact's column header that say whose value it is - the
#: same three kinds `claude_datasheet.KINDS` names. A column the rules did not
#: name (or named "MIN", "RATED") has no kind, and is compatible with any.
_KIND_WORDS = {
    "required": ("required", "spec", "specified", "purchaser"),
    "offered": ("offered", "vendor", "proposed", "supplier"),
    "measured": ("measured", "test", "actual", "as built"),
}


def rule_kind(fact: dict) -> str | None:
    """Whose value a rule fact is, when its column header says so."""
    column = " ".join(str(fact.get("value_column") or "").lower().split())
    if not column:
        return None
    for kind, words in _KIND_WORDS.items():
        if any(w in column for w in words):
            return kind
    return None


def ai_raw_value(fact: dict) -> str:
    """The AI reading as one cell of text, value then unit."""
    return " ".join(p for p in (fact.get("value"), fact.get("unit")) if p)


def values_agree(rule_fact: dict, ai_fact: dict) -> bool:
    """Do the rules and the AI read the same value? The geometry reader's
    agreement rule (`datasheets._geometry_agrees`): numbers compare as
    numbers (normalised when both normalise), text compares folded."""
    raw = ai_raw_value(ai_fact)
    blank, _marker = datasheets.is_blank_value(raw)
    return datasheets._geometry_agrees(raw, blank, rule_fact)


def _key(fact: dict) -> tuple:
    return (fact.get("page"),
            fact.get("field_name") or datasheets.normalise_field_name(fact.get("field") or ""))


def merge_readings(rule_facts: list[dict], ai_facts: list[dict]) -> list[dict]:
    """Merge the rule readers' facts and the AI reader's accepted facts.

    PURE: dicts in, decisions out, no database. Facts are matched by page and
    normalised field name, and only across compatible kinds (a rule fact
    whose column names no kind is compatible with any). Per field:

      * AGREED     - a rule fact and an AI fact of a compatible kind read the
                     same value: one fact, `{"rule", "ai"}`.
      * CONFLICT   - they read different values: BOTH kept, `{"rules": [...],
                     "ai": [...]}`, for an engineer. Never silently one. An AI
                     reading of the same kind as a pair that AGREED, with a
                     different value, is a conflict too: the page then states
                     two values where the rules read one, and the agreeing
                     reading is kept on the decision as `agreed_ai`.
      * AI_ONLY    - no rule fact of a compatible kind: `{"ai"}`.
      * RULES_ONLY - no AI reading of a compatible kind: `{"rule"}`.

    Deterministic: input order within a field, fields in (page, name) order.
    """
    groups: dict[tuple, tuple[list, list]] = {}
    for r in rule_facts:
        groups.setdefault(_key(r), ([], []))[0].append(r)
    for a in ai_facts:
        groups.setdefault(_key(a), ([], []))[1].append(a)

    def order(key):
        page, name = key
        return (page if page is not None else -1, name or "")

    out: list[dict] = []
    for key in sorted(groups, key=order):
        page, name = key
        rules, ais = groups[key]
        base = {"page": page, "field_name": name}
        # 1. Agreement, greedily, in input order.
        partner: dict[int, int] = {}          # rule index -> ai index
        used_ai: set[int] = set()
        for ri, r in enumerate(rules):
            rk = rule_kind(r)
            for ai_i, a in enumerate(ais):
                if ai_i in used_ai or (rk is not None and rk != a.get("kind")):
                    continue
                if values_agree(r, a):
                    partner[ri] = ai_i
                    used_ai.add(ai_i)
                    break

        def kind_of(ri: int) -> str | None:
            # A rule fact with no named column takes its partner's kind once
            # an AI reading agreed with it.
            return rule_kind(rules[ri]) or (
                ais[partner[ri]].get("kind") if ri in partner else None)

        # 2. Every AI reading left over contradicts each kind-compatible rule
        #    fact on this field - or, with none, stands alone.
        against: dict[int, list[int]] = {}    # rule index -> contradicting ai indexes
        alone: list[int] = []
        for ai_i, a in enumerate(ais):
            if ai_i in used_ai:
                continue
            hits = [ri for ri in range(len(rules))
                    if kind_of(ri) is None or kind_of(ri) == a.get("kind")]
            for ri in hits:
                against.setdefault(ri, []).append(ai_i)
            if not hits:
                alone.append(ai_i)
        for ri, r in enumerate(rules):
            if ri in against:
                decision = {**base, "outcome": CONFLICT, "rules": [r],
                            "ai": [ais[i] for i in against[ri]]}
                if ri in partner:
                    decision["agreed_ai"] = ais[partner[ri]]
                out.append(decision)
            elif ri in partner:
                out.append({**base, "outcome": AGREED, "rule": r, "ai": ais[partner[ri]]})
            else:
                out.append({**base, "outcome": RULES_ONLY, "rule": r})
        out.extend({**base, "outcome": AI_ONLY, "ai": ais[i]} for i in alone)
    return out


def outcome_counts(decisions: list[dict]) -> dict[str, int]:
    counts = {AGREED: 0, CONFLICT: 0, AI_ONLY: 0, RULES_ONLY: 0}
    for d in decisions:
        counts[d["outcome"]] += 1
    return counts


__all__ = [
    "AGREED",
    "AGREED_CONFIDENCE",
    "AI_CONFIDENCE",
    "AI_ONLY",
    "CLAUDE",
    "CONFLICT",
    "ENGINES",
    "EXTRACTION_METHOD",
    "OFF",
    "OLLAMA",
    "READER",
    "RULES_ONLY",
    "STEP",
    "engine_setting",
    "merge_readings",
    "model_call_for",
    "outcome_counts",
    "page_text",
    "read_page_text_with_ai",
    "read_pages",
    "rule_kind",
    "values_agree",
]
