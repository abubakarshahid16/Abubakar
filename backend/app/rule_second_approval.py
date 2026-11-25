"""The second-model approval pass over `needs_human` rules (planner, 25 Nov 2026 18:55, item A): the standing order replaces a
missing human input with a MEASURED AI method. Nothing here runs by itself; `scripts/run_rule_second.py` runs it on a COPY.

WHAT IT DOES, per rule the two label passes left `needs_human` for a READING difference (kind, field, comparator, values, unit,
strength, numbers; never an OCR, prompt-version or model guard: `ELIGIBLE`):
  1. CODE finds the rule's quote word for word on its page again (`rule_label_job.quote_found`); not found -> never sent.
  2. A model of a THIRD family (neither pass a's nor pass b's) is asked the SAME blind question as the label passes (rule-book
     text only: clause and quote; `rule_label_prompt`): it never sees the two earlier answers or any paper.
  3. CODE (`rule_labels.decide`) compares its answer with pass a and with pass b. The rule is `second_approved` only when it
     agrees with one of them on the paper kind, the field and the reading (comparator, numbers, unit, strength): two
     different models agree on its wording and scope, and code found its quote. Else `second_refused`, with the reasons.
  Every row stores the approver ("second-model pass"), the model, the prompt version, the answer hash, the agreeing pass, the
  quote hash and page, and the date. Rows are never deleted, replaced or changed (triggers).

THE SAMPLE JUDGE. `draw_sample` picks N approvals at random (a seed, stored); `judge_sample` asks a model of a FOURTH family
(none of the three) whether the approved reading is right for the clause, shown the clause, the quote and the reading only
(blind: not who approved it or why). `measure` stores the count: wrong of judged, with the denominator, and the time up to
which the sampled approvals were made.

THE GATE (`gate`). Reviews use a second-model approval only when the latest measure judged at least `GATE_MIN_JUDGED`
approvals with at most `GATE_MAX_WRONG` of them wrong, and only approvals made up to that measure's time (a later batch is
not measured yet). `library` reads it; with no measure, nothing changes for any review.

MONEY AND PRIVACY: the same lane as the label job (`rule_label_lane.Lane`: reader_transport + claude_spend.metered + the
injected order ledger) and the same rule-book families (`rule_label_job.ALLOWED_FAMILIES`); behind the same switch
(`agent_review_enabled`). Only rule-book text is sent.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Sequence

from . import rule_labels
from .rule_label_job import (
    ALLOWED_FAMILIES,
    PageText,
    Rule,
    _batches,
    _pass_from_row,
    _text_of,
    family_of,
    quote_found,
    require_copy,
)
from .rule_label_lane import OrderStopReached
from .rule_label_prompt import (
    build_parts,
    field_list,
    max_tokens_for,
    parse_answers,
    system_text,
)
from .rule_label_schema import NEEDS_HUMAN, create_tables, require_on

log = logging.getLogger(__name__)

APPROVER = "second-model pass"
APPROVED, REFUSED = "second_approved", "second_refused"
#: A disagreement the second model may settle: a difference of READING. A guard (OCR confidence, prompt version, model naming)
#: stays with a person.
NOT_ELIGIBLE = ("ocr_low_confidence", "prompt_version", "model_not_named", "same_model")
#: The gate: at least this many approvals judged, at most this share of them wrong.
GATE_MIN_JUDGED = 100
GATE_MAX_WRONG = 0.05
SAMPLE_N = 200
JUDGE_PROMPT_VERSION = "rule-second-judge-v1"
JUDGE_BATCH = 20

_TABLES = (
    f"""CREATE TABLE IF NOT EXISTS rule_second_approval (
        source TEXT NOT NULL, rule_ref TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('{APPROVED}', '{REFUSED}')),
        approver TEXT NOT NULL CHECK (approver = '{APPROVER}'),
        model TEXT NOT NULL CHECK (length(trim(model)) > 0), prompt TEXT NOT NULL,
        answer_sha256 TEXT NOT NULL, answer_json TEXT NOT NULL,
        agrees_with TEXT CHECK (agrees_with IS NULL OR agrees_with IN ('a', 'b')),
        paper_kind TEXT, field TEXT, reading_json TEXT, refused_because TEXT,
        quote_sha256 TEXT NOT NULL, quote_page INTEGER NOT NULL, approved_at TEXT NOT NULL,
        PRIMARY KEY (source, rule_ref),
        CHECK (state <> '{APPROVED}' OR (agrees_with IS NOT NULL AND paper_kind IS NOT NULL AND reading_json IS NOT NULL
                                        AND refused_because IS NULL)),
        CHECK (state <> '{REFUSED}' OR refused_because IS NOT NULL))""",
    """CREATE TABLE IF NOT EXISTS rule_second_sample (
        sample_id TEXT NOT NULL, source TEXT NOT NULL, rule_ref TEXT NOT NULL, drawn_at TEXT NOT NULL, seed INTEGER NOT NULL,
        judge_model TEXT, judge_prompt TEXT, verdict TEXT CHECK (verdict IS NULL OR verdict IN ('right', 'wrong')),
        reason TEXT, judged_at TEXT, PRIMARY KEY (sample_id, source, rule_ref))""",
    """CREATE TABLE IF NOT EXISTS rule_second_measure (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sample_id TEXT NOT NULL, measured_at TEXT NOT NULL, covers_until TEXT NOT NULL,
        judged INTEGER NOT NULL CHECK (judged >= 0), wrong INTEGER NOT NULL CHECK (wrong >= 0 AND wrong <= judged),
        judge_model TEXT NOT NULL)""",
    *(
        f"""CREATE TRIGGER IF NOT EXISTS {t}_no_{op} BEFORE {op.upper()} ON {t}
            BEGIN SELECT RAISE(ABORT, '{t}: rows are never {op}d'); END"""
        for t in ("rule_second_approval", "rule_second_measure")
        for op in ("delete", "update")
    ),
    """CREATE TRIGGER IF NOT EXISTS rule_second_sample_no_delete BEFORE DELETE ON rule_second_sample
        BEGIN SELECT RAISE(ABORT, 'rule_second_sample: rows are never deleted'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_second_sample_judged_once BEFORE UPDATE ON rule_second_sample
        WHEN OLD.verdict IS NOT NULL BEGIN SELECT RAISE(ABORT, 'rule_second_sample: a verdict is never changed'); END""",
)


def create(conn: sqlite3.Connection) -> None:
    """The label tables and these three (CREATE ... IF NOT EXISTS only). Switch off: raises, creates nothing."""
    create_tables(conn)
    for statement in _TABLES:
        conn.execute(statement)
    conn.commit()


def has_tables(conn) -> bool:
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return {"rule_second_approval", "rule_second_measure"} <= held


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------------------------------------ the second-model pass


def eligible(
    conn: sqlite3.Connection, rules: Sequence[Rule], pages: PageText
) -> tuple[list[tuple], Counter]:
    """[(rule, pass a, pass b)] of the rules the second model may settle, and the count of why the others are not asked."""
    counts: Counter = Counter()
    out = []
    for r in rules:
        row = conn.execute(
            "SELECT * FROM rule_label WHERE source = ? AND rule_ref = ?",
            (r.source, r.ref),
        ).fetchone()
        done = conn.execute(
            "SELECT 1 FROM rule_second_approval WHERE source = ? AND rule_ref = ?",
            (r.source, r.ref),
        ).fetchone()
        a, b = (
            (_pass_from_row(row, "a"), _pass_from_row(row, "b"))
            if row is not None
            else (None, None)
        )
        why = (
            "already_done" if done
            else "not_needs_human" if row is None or row["state"] != NEEDS_HUMAN
            else "a_guard_not_a_reading" if any(x in str(row["disagreement"] or "") for x in NOT_ELIGIBLE)
            else "not_sent_family_not_allowed" if family_of(r.standard) not in ALLOWED_FAMILIES
            else "passes_not_stored_whole" if a is None or b is None
            else "quote_changed" if row["quote_sha256"] != rule_labels.quote_hash(r.quote) or not quote_found(r, pages)
            else ""
        )  # fmt: skip
        if why:
            counts[why] += 1
        else:
            out.append((r, a, b))
    return out, counts


def check_third(model: str, conn: sqlite3.Connection) -> None:
    """The second model is of neither label pass's family on ANY eligible rule (so an agreement is two different models)."""
    used = {
        rule_labels.family(m)
        for (m,) in conn.execute(
            "SELECT a_model FROM rule_label WHERE a_model IS NOT NULL"
        )
    }
    used |= {
        rule_labels.family(m)
        for (m,) in conn.execute(
            "SELECT b_model FROM rule_label WHERE b_model IS NOT NULL"
        )
    }
    if rule_labels.family(model) in used:
        raise ValueError("the second model must be of a family neither label pass used")


def settle_one(conn, r: Rule, a, b, third, pages: PageText) -> str:
    """CODE decides, by `rule_labels.decide` against pass a, then pass b: the first agreement approves. Writes one row."""
    low = pages.low_confidence_ocr(r.sdid, r.page, r.quote)
    reasons, agreed = [], None
    for name, earlier in (("a", a), ("b", b)):
        d = rule_labels.decide(
            earlier, third, quote_found=True, quote_text=r.quote, quote_ocr_low=low
        )
        if d is not None and d.state == rule_labels.AI_APPROVED:
            agreed = (name, d)
            break
        reasons.append(f"{name}: {d.disagreement if d else 'no decision'}")
    content = {
        "paper_kind": third.paper_kind,
        "field": third.field,
        "reading": dict(third.reading),
        "valid": third.valid,
    }
    d = agreed[1] if agreed else None
    conn.execute(
        "INSERT INTO rule_second_approval (source, rule_ref, state, approver, model, prompt, answer_sha256, answer_json,"
        " agrees_with, paper_kind, field, reading_json, refused_because, quote_sha256, quote_page, approved_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (r.source, r.ref, APPROVED if agreed else REFUSED, APPROVER, third.model, third.prompt, third.answer_sha256,
         json.dumps(content, sort_keys=True), agreed[0] if agreed else None, d.paper_kind if d else None,
         d.field if d else None, json.dumps(dict(d.reading), sort_keys=True) if d and d.reading is not None else None,
         None if agreed else "; ".join(reasons), rule_labels.quote_hash(r.quote), int(r.page), _now()),
    )  # fmt: skip
    return APPROVED if agreed else REFUSED


def run_second(
    conn: sqlite3.Connection,
    rules: Sequence[Rule],
    *,
    model: str,
    lane,
    pages: PageText | None = None,
    batch_size: int = 20,
    out: Callable[[str], None] = print,
) -> dict:
    """The pass over `rules` (on a COPY); counts only. A cap or the ledger's stop ends the run; nothing is approved on an
    error, an unreadable answer or an answer from a label pass's family."""
    from . import agent_claude, claude_approved, claude_spend

    require_on()
    require_copy(conn)
    create(conn)
    check_third(model, conn)
    pages = pages or PageText(conn)
    todo, counts = eligible(conn, rules, pages)
    counts.update(rules=len(rules), sent=len(todo))
    system = system_text(field_list())
    for batch in _batches(todo, batch_size):
        reps = [r for r, _a, _b in batch]
        try:
            with (
                claude_approved.per_request_consent(sorted({r.sdid for r in reps})),
                claude_spend.for_run("rule-second"),
            ):
                answer = lane.call(
                    model,
                    build_parts(reps, system),
                    max_tokens_for(len(reps), model),
                    len(reps),
                )[0]
        except Exception as exc:  # noqa: BLE001 - counted by type, never its text
            counts["errors:" + str(getattr(exc, "code", type(exc).__name__))] += 1
            if isinstance(
                exc,
                (
                    agent_claude.AgentBudgetStop,
                    agent_claude.AgentGateClosed,
                    OrderStopReached,
                ),
            ):
                counts["stopped"] = str(getattr(exc, "code", type(exc).__name__))
                break
            continue
        used = agent_claude._answered_model(answer)
        used = model if used == "unknown" else used
        got = parse_answers(_text_of(answer), reps, used)
        for n, (r, a, b) in enumerate(batch, 1):
            third = got.get(n)
            if third is None or rule_labels.family(used) in {
                rule_labels.family(a.model),
                rule_labels.family(b.model),
            }:
                counts["not_settled_unreadable_or_same_family"] += 1
                continue
            counts["state:" + settle_one(conn, r, a, b, third, pages)] += 1
        conn.commit()
        out(f"BATCH {len(batch)} rules | order USD {lane.ledger.run_usd:.4f}")
    counts.setdefault("stopped", "")
    return dict(counts)


def estimate(rules: Sequence[Rule], model: str, batch_size: int = 20) -> dict:
    """Calls and the app's own WORST-CASE USD for asking `rules` once (the label job's formula; no call is made)."""
    from .rule_label_job import estimate as label_estimate

    return label_estimate(rules, model, batch_size)


# ------------------------------------------------------------------------------------------------ the sample judge and the gate

JUDGE_SYSTEM = (
    "You check how a rule of a technical standard was read. For each rule you get its clause number, its exact words "
    '(the quote) and a reading: "paper_kind" (the kind of paper the rule is checked on), "field" (for a datasheet), '
    '"comparator", "values", "unit" and "strength". Say "right" when the reading states what the quote requires, for the '
    'right kind of paper and field, with its numbers, unit and strength; "wrong" when any part of it does not. Reply with ONE '
    'JSON object only: {"answers": [{"n": n, "verdict": "right" | "wrong", "reason": "at most 20 words"}]}'
)


def draw_sample(
    conn: sqlite3.Connection, n: int = SAMPLE_N, seed: int | None = None
) -> str:
    """N approvals at random (seeded; the seed and the time are stored). Returns the sample id."""
    seed = int(seed if seed is not None else random.SystemRandom().randrange(1, 2**31))
    rows = [tuple(r) for r in conn.execute(
        "SELECT source, rule_ref FROM rule_second_approval WHERE state = ? ORDER BY source, rule_ref", (APPROVED,))]  # fmt: skip
    picked = random.Random(seed).sample(rows, min(int(n), len(rows)))
    sample_id, drawn = f"sample-{seed}", _now()
    conn.executemany(
        "INSERT INTO rule_second_sample (sample_id, source, rule_ref, drawn_at, seed) VALUES (?, ?, ?, ?, ?)",
        [(sample_id, s, ref, drawn, seed) for s, ref in picked],
    )
    conn.commit()
    return sample_id


def _judge_parts(items: list[dict]) -> dict:
    return {
        "system": [
            {
                "type": "text",
                "text": JUDGE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"rules": items}, ensure_ascii=False),
                    }
                ],
            }
        ],
    }


def _verdicts(text: str, n: int) -> dict[int, tuple[str, str]]:
    try:
        rows = json.loads(text).get("answers")
    except (ValueError, AttributeError):
        return {}
    out = {}
    for row in rows if isinstance(rows, list) else []:
        k = row.get("n") if isinstance(row, dict) else None
        if (
            isinstance(k, int)
            and not isinstance(k, bool)
            and 1 <= k <= n
            and row.get("verdict") in ("right", "wrong")
        ):
            out.setdefault(
                k, (row["verdict"], " ".join(str(row.get("reason") or "").split()))
            )
    return out


def judge_sample(
    conn: sqlite3.Connection,
    sample_id: str,
    *,
    judge_model: str,
    lane,
    rules: dict[str, Rule],
) -> dict:
    """The blind judge on a drawn sample: clause, quote and the approved reading only. Its family is none of the approver's
    nor the two label passes'. Stores each verdict once; an unreadable answer leaves the rule unjudged."""
    from . import claude_approved, claude_spend

    require_copy(conn)
    rows = [tuple(r) for r in conn.execute(
        "SELECT s.rule_ref, a.model, a.paper_kind, a.field, a.reading_json, l.a_model, l.b_model, s.verdict"
        " FROM rule_second_sample s JOIN rule_second_approval a ON a.source = s.source AND a.rule_ref = s.rule_ref"
        " JOIN rule_label l ON l.source = s.source AND l.rule_ref = s.rule_ref WHERE s.sample_id = ? ORDER BY s.rule_ref",
        (sample_id,))]  # fmt: skip
    if any(
        rule_labels.family(judge_model)
        in {rule_labels.family(m) for m in (r[1], r[5], r[6])}
        for r in rows
    ):
        raise ValueError(
            "the judge must be of a family none of the approving models used"
        )
    rows = [r for r in rows if r[7] is None]
    counts: Counter = Counter()
    # standards text only: a sampled rule outside the families open to the Claude lane is never shown to the judge
    rows = [
        r
        for r in rows
        if r[0] in rules and family_of(rules[r[0]].standard) in ALLOWED_FAMILIES
    ]
    for batch in _batches(rows, JUDGE_BATCH):
        items = [{"n": i, "clause": rules[r[0]].clause, "quote": rules[r[0]].quote, "paper_kind": r[2], "field": r[3],
                  **json.loads(r[4])} for i, r in enumerate(batch, 1)]  # fmt: skip
        with (
            claude_approved.per_request_consent(
                sorted({rules[r[0]].sdid for r in batch})
            ),
            claude_spend.for_run("rule-second-judge"),
        ):
            answer = lane.call(
                judge_model, _judge_parts(items), 200 + 60 * len(batch), len(batch)
            )[0]
        got = _verdicts(_text_of(answer), len(batch))
        for i, r in enumerate(batch, 1):
            if i not in got:
                counts["unjudged"] += 1
                continue
            conn.execute(
                "UPDATE rule_second_sample SET judge_model = ?, judge_prompt = ?, verdict = ?, reason = ?, judged_at = ?"
                " WHERE sample_id = ? AND rule_ref = ?", (judge_model, JUDGE_PROMPT_VERSION, *got[i], _now(), sample_id, r[0]))  # fmt: skip
            counts[got[i][0]] += 1
        conn.commit()
    return dict(counts)


def measure(conn: sqlite3.Connection, sample_id: str) -> dict:
    """Store and return the sample's count: wrong of judged (the denominator), and the time up to which its approvals were made."""
    judged, wrong, models, drawn = conn.execute(
        "SELECT COUNT(verdict), SUM(verdict = 'wrong'), GROUP_CONCAT(DISTINCT judge_model), MIN(drawn_at)"
        " FROM rule_second_sample WHERE sample_id = ?", (sample_id,)).fetchone()  # fmt: skip
    row = {"sample_id": sample_id, "measured_at": _now(), "covers_until": drawn or _now(), "judged": int(judged or 0),
           "wrong": int(wrong or 0), "judge_model": models or "none"}  # fmt: skip
    conn.execute(
        "INSERT INTO rule_second_measure (sample_id, measured_at, covers_until, judged, wrong, judge_model)"
        " VALUES (:sample_id, :measured_at, :covers_until, :judged, :wrong, :judge_model)", row)  # fmt: skip
    conn.commit()
    return row


def gate(conn: sqlite3.Connection) -> dict:
    """The latest measure and whether reviews may use second-model approvals: {"open", "judged", "wrong", "covers_until",
    "sentence"}. No table or no measure: closed, and the sentence says so (never a rate without its denominator)."""
    if not has_tables(conn):
        return {
            "open": False,
            "judged": 0,
            "wrong": 0,
            "covers_until": None,
            "sentence": "Second-model approvals: not measured.",
        }
    row = conn.execute(
        "SELECT judged, wrong, covers_until FROM rule_second_measure ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {
            "open": False,
            "judged": 0,
            "wrong": 0,
            "covers_until": None,
            "sentence": "Second-model approvals: not measured.",
        }
    judged, wrong, until = int(row[0]), int(row[1]), row[2]
    ok = judged >= GATE_MIN_JUDGED and wrong <= GATE_MAX_WRONG * judged
    pct = f" ({100 * wrong / judged:.1f}%)" if judged else ""
    return {"open": ok, "judged": judged, "wrong": wrong, "covers_until": until,
            "sentence": f"Second-model approvals: {wrong} wrong of {judged} judged{pct}; used in reviews only with at most "
                        f"{GATE_MAX_WRONG:.0%} wrong of at least {GATE_MIN_JUDGED} judged: {'open' if ok else 'closed'}."}  # fmt: skip


def review_sql(conn, held: set[str], labels: Sequence[str]) -> dict | None:
    """The review's rule pool's part for second-model approvals (`library.rule_pool`), or None when the gate is closed or the
    table is not there: the join (approvals made up to the latest measure's time), the reading column, and the extra kind
    test for a needs_human rule."""
    if "rule_second_approval" not in held:
        return None
    g = gate(conn)
    if not g["open"]:
        return None
    marks = ",".join("?" for _ in labels)
    return {
        "join": " LEFT JOIN rule_second_approval sa ON sa.source = 'requirement' AND sa.rule_ref = sr.id"
        " AND sa.state = 'second_approved' AND sa.approved_at <= ?",
        "join_args": [g["covers_until"]],
        "reading": "CASE WHEN rl.state = 'ai_approved' THEN rl.reading_json ELSE sa.reading_json END AS reading_json",
        "where": f" OR (rl.state = '{NEEDS_HUMAN}' AND sa.paper_kind IN ({marks}))",
        "where_args": list(labels),
    }


# ------------------------------------------------------------------------------------------------ the file to the server

EXPORT_FORMAT = "rule-second-v1"
APPROVAL_COLUMNS = ("source", "rule_ref", "state", "approver", "model", "prompt", "answer_sha256", "answer_json",
                    "agrees_with", "paper_kind", "field", "reading_json", "refused_because", "quote_sha256", "quote_page",
                    "approved_at")  # fmt: skip
SAMPLE_COLUMNS = ("sample_id", "source", "rule_ref", "drawn_at", "seed", "judge_model", "judge_prompt", "verdict", "reason",
                  "judged_at")  # fmt: skip
MEASURE_COLUMNS = (
    "sample_id",
    "measured_at",
    "covers_until",
    "judged",
    "wrong",
    "judge_model",
)


def export(conn: sqlite3.Connection) -> dict:
    """The copy's approvals, samples and measures as one file for the server's import (`rule_second_import`): ids, hashes,
    pages, models, dates, readings; no quote text."""

    def rows(table, cols):
        return [
            dict(zip(cols, r, strict=True))
            for r in conn.execute(
                f"SELECT {', '.join(cols)} FROM {table} ORDER BY 1, 2"
            )
        ]

    return {"format": EXPORT_FORMAT, "approvals": rows("rule_second_approval", APPROVAL_COLUMNS),
            "samples": rows("rule_second_sample", SAMPLE_COLUMNS), "measures": rows("rule_second_measure", MEASURE_COLUMNS)}  # fmt: skip
