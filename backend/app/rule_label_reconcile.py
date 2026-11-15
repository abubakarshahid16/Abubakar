"""Labels two readers differ on only in a word code can reconcile (16 Nov 2026, owner's question on "needs a human").

WHAT. A `needs_human` label whose two readers differ ONLY in comparator ("required" against "statement") or ONLY in strength
(shall / should / may) while kind, field, quote, models and prompt agree, for a rule that carries no number and whose quote holds no
negation, exception or "only" word, is a rule read two harmless ways: the label's comparator and strength are read by nothing but
`rule_labels.decide` (proved in `docs`, see the proof file of the PR); what makes a line mandatory is the stored rule's own type.
The label then reads `ai_approved` through the label code's OWN `decide`, with the differing attribute treated as one reading
("required" for A; the weaker word for B).

NOTHING IS LOST. The change is one UPDATE of the label through its documented re-label path (the existing trigger appends a
`relabel` event) PLUS one row in `rule_label_reconciled`, an append-only table of its own (the schema forbids a new kind in
`rule_label_event`, and no existing table is altered): the kind `code_reconciled`, the state, disagreement and reading BEFORE, BOTH
readers' readings, the reconciled reading, the quote hash and the reason. `undo` puts the label back from that row and appends `undone`.

NOT A MODEL. Code only: no request, no model. The two readers' answers come from the lab copy ONLY when their hash equals the hash the
label stores (a different answer is held), and `decide` run again must reproduce the stored disagreement before anything is treated as
one reading. Read-only functions here take any connection; `apply` and `undo` write, and the script that calls them refuses a
live-shaped database unless it went through `live_guard.prepare_live_write`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from . import rule_label_convert, rule_label_import, rule_labels

CODE_RECONCILED, UNDONE = "code_reconciled", "undone"
REASON_COMPARATOR = "comparator_required_statement"
REASON_STRENGTH = "strength_weaker_word"
CODE_VERSION = "reconcile-1"
WEAKER = {"may": 0, "should": 1, "shall": 2}

#: A quote that holds one of these is never reconciled by code: it may be a prohibition, a condition or an exception.
NEGATION = re.compile(
    r"\b(shall not|must not|may not|should not|cannot|can not|prohibit\w*|not (?:be )?(?:permitted|allowed|used|acceptable|required)"
    r"|never|no \w+ (?:shall|may|is|are)|do not|does not|are not|is not|forbidden|unacceptable|not exceed|except|unless|only)\b",
    re.I,
)
#: The quote must say something of obligation, permission or advice for a strength to be read at all.
MODAL = re.compile(
    r"\b(shall|must|should|may|can|will|required|requires?|is to|are to)\b", re.I
)

_DDL = (
    f"""CREATE TABLE IF NOT EXISTS rule_label_reconciled (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL, rule_ref TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('{CODE_RECONCILED}', '{UNDONE}')),
        reason TEXT NOT NULL,
        previous_state TEXT NOT NULL, previous_disagreement TEXT, previous_reading_json TEXT,
        new_state TEXT NOT NULL, new_reading_json TEXT,
        a_reading_json TEXT, b_reading_json TEXT,
        quote_sha256 TEXT, code_version TEXT NOT NULL, at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS rule_label_reconciled_rule ON rule_label_reconciled (source, rule_ref)",
    """CREATE TRIGGER IF NOT EXISTS rule_label_reconciled_no_update BEFORE UPDATE ON rule_label_reconciled
        BEGIN SELECT RAISE(ABORT, 'rule_label_reconciled is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_label_reconciled_no_delete BEFORE DELETE ON rule_label_reconciled
        BEGIN SELECT RAISE(ABORT, 'rule_label_reconciled is append-only'); END""",
)


@dataclass(frozen=True)
class Plan:
    """One label code would reconcile: ids, the reason, both readings and the reconciled reading. No quote text."""

    source: str
    rule_ref: str
    reason: str
    previous_disagreement: str
    previous_reading_json: str | None
    a_reading: Mapping
    b_reading: Mapping
    new_reading: Mapping
    quote_sha256: str


def create_table(conn: sqlite3.Connection) -> None:
    for statement in _DDL:
        conn.execute(statement)


def _held_reason(
    row: Mapping, lab: Mapping | None, held, conn
) -> tuple[str | None, tuple | None]:
    """(why code holds this label, or None) and the two passes with the quote when it does not."""
    if lab is None:
        return "no_lab_answers", None
    if not held:
        return "rule_not_stored", None
    quote = held[0]["quote"]
    if rule_labels.quote_hash(quote) != row["quote_sha256"]:
        return "quote_changed", None
    a = rule_label_convert._pass(lab, "a", quote, lab["prompt_version"])
    b = rule_label_convert._pass(lab, "b", quote, lab["prompt_version"])
    if a is None or b is None:
        return "no_lab_answers", None
    if (a.answer_sha256, b.answer_sha256) != (
        row["a_answer_sha256"],
        row["b_answer_sha256"],
    ) or (a.model, b.model) != (
        row["a_model"],
        row["b_model"],
    ):
        return "lab_answer_differs_from_stored_hash", None
    prompt = (
        a.prompt if a.prompt in rule_labels.LAB_PROMPTS else rule_labels.PROMPT_VERSION
    )
    again = rule_labels.decide(
        a, b, quote_found=True, quote_text=quote, prompt_version=prompt
    )
    if again is None or again.disagreement != row["disagreement"]:
        return "redecide_differs_from_stored", None
    return None, (a, b, quote, prompt)


def _own_value(conn, row: Mapping) -> bool:
    r = conn.execute(
        "SELECT value FROM standard_requirements WHERE id = ?", (row["rule_ref"],)
    ).fetchone()
    return bool(r is not None and r[0] is not None)


def candidate(
    conn, row: Mapping, lab: Mapping | None
) -> tuple[Plan | None, str | None]:
    """(the plan, None) when code may reconcile this needs_human label, else (None, why it holds). Read only."""
    if (
        row["source"] != "requirement"
        or row["state"] != "needs_human"
        or row["disagreement"] not in ("comparator", "strength")
    ):
        return None, "not_in_scope"
    held = rule_label_import._stored_rule(conn, row["source"], row["rule_ref"])
    why, passes = _held_reason(row, lab, held, conn)
    if passes is None:
        return None, why
    a, b, quote, prompt = passes
    ra, rb = dict(a.reading), dict(b.reading)
    if row["disagreement"] == "comparator":
        if {ra["comparator"], rb["comparator"]} != {"required", "statement"}:
            return None, "comparator_pair_not_required_statement"
        reason, ra["comparator"], rb["comparator"] = (
            REASON_COMPARATOR,
            "required",
            "required",
        )
    else:
        if not (
            ra["comparator"] in rule_labels.NO_NUMBER
            and rb["comparator"] in rule_labels.NO_NUMBER
        ):
            return None, "strength_with_a_number_comparator"
        weaker = min((ra["strength"], rb["strength"]), key=lambda s: WEAKER[s])
        reason, ra["strength"], rb["strength"] = REASON_STRENGTH, weaker, weaker
    if ra["values"] or rb["values"] or _own_value(conn, row):
        return None, "rule_holds_a_number"
    if NEGATION.search(quote):
        return None, "quote_holds_a_negation_or_exception_word"
    if not MODAL.search(quote):
        return None, "quote_holds_no_modal_word"
    after = rule_labels.decide(
        rule_labels.PassAnswer(
            a.model, a.prompt, a.paper_kind, a.field, ra, a.valid, a.answer_sha256
        ),
        rule_labels.PassAnswer(
            b.model, b.prompt, b.paper_kind, b.field, rb, b.valid, b.answer_sha256
        ),
        quote_found=True,
        quote_text=quote,
        prompt_version=prompt,
    )
    if (
        after is None
        or after.state != rule_labels.AI_APPROVED
        or after.disagreement is not None
        or after.reading is None
    ):
        return None, "decide_still_needs_a_human"
    if (after.paper_kind, after.field) != (row["paper_kind"], row["field"]):
        return None, "kind_or_field_changed"
    plan = Plan(
        row["source"],
        row["rule_ref"],
        reason,
        row["disagreement"],
        row["reading_json"],
        a.reading,
        b.reading,
        after.reading,
        row["quote_sha256"],
    )
    return plan, None


def plan_all(
    conn: sqlite3.Connection, lab: sqlite3.Connection
) -> tuple[list[Plan], Counter]:
    """Every label code would reconcile, and the counts of why it held the others in scope. Read only on both."""
    conn.row_factory = lab.row_factory = sqlite3.Row
    plans: list[Plan] = []
    held: Counter = Counter()
    for row in conn.execute(
        "SELECT * FROM rule_label WHERE state = 'needs_human' AND source = 'requirement' AND disagreement IN ('comparator', 'strength')"
        " ORDER BY rule_ref"
    ).fetchall():
        labrow = lab.execute(
            "SELECT * FROM rule_label WHERE source = ? AND rule_ref = ?",
            (row["source"], row["rule_ref"]),
        ).fetchone()
        plan, why = candidate(conn, row, labrow)
        if plan is None:
            held[why] += 1
        else:
            plans.append(plan)
    return plans, held


def _dump(reading: Mapping | None) -> str | None:
    return json.dumps(dict(reading), sort_keys=True) if reading is not None else None


def apply(conn: sqlite3.Connection, plans: list[Plan]) -> int:
    """Write the plans (all or none): the event row, then the label's own re-label. A label that is no longer needs_human with the
    same disagreement is skipped, never overwritten. Returns how many labels changed."""
    create_table(conn)
    done = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for p in plans:
            now = conn.execute(
                "SELECT strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            ).fetchone()[0]
            moved = conn.execute(
                "UPDATE rule_label SET state = 'ai_approved', disagreement = NULL, reading_json = ?"
                " WHERE source = ? AND rule_ref = ? AND state = 'needs_human' AND disagreement = ? AND quote_sha256 = ?",
                (
                    _dump(p.new_reading),
                    p.source,
                    p.rule_ref,
                    p.previous_disagreement,
                    p.quote_sha256,
                ),
            ).rowcount
            if not moved:
                continue
            conn.execute(
                "INSERT INTO rule_label_reconciled (source, rule_ref, kind, reason, previous_state, previous_disagreement,"
                " previous_reading_json, new_state, new_reading_json, a_reading_json, b_reading_json, quote_sha256, code_version, at)"
                " VALUES (?, ?, ?, ?, 'needs_human', ?, ?, 'ai_approved', ?, ?, ?, ?, ?, ?)",
                (
                    p.source,
                    p.rule_ref,
                    CODE_RECONCILED,
                    p.reason,
                    p.previous_disagreement,
                    p.previous_reading_json,
                    _dump(p.new_reading),
                    _dump(p.a_reading),
                    _dump(p.b_reading),
                    p.quote_sha256,
                    CODE_VERSION,
                    now,
                ),
            )
            done += 1
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return done


def undo(conn: sqlite3.Connection) -> int:
    """Put every still-reconciled label back from its `code_reconciled` row and append `undone`. A label that changed since
    (state or reading no longer the reconciled one) is left as it is. Returns how many labels were put back."""
    create_table(conn)
    conn.row_factory = sqlite3.Row
    back = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for ev in conn.execute(
            "SELECT * FROM rule_label_reconciled e WHERE kind = ? AND NOT EXISTS (SELECT 1 FROM rule_label_reconciled u"
            " WHERE u.source = e.source AND u.rule_ref = e.rule_ref AND u.kind = ? AND u.id > e.id) ORDER BY id",
            (CODE_RECONCILED, UNDONE),
        ).fetchall():
            moved = conn.execute(
                "UPDATE rule_label SET state = ?, disagreement = ?, reading_json = ?"
                " WHERE source = ? AND rule_ref = ? AND state = 'ai_approved' AND reading_json IS ? AND quote_sha256 = ?",
                (
                    ev["previous_state"],
                    ev["previous_disagreement"],
                    ev["previous_reading_json"],
                    ev["source"],
                    ev["rule_ref"],
                    ev["new_reading_json"],
                    ev["quote_sha256"],
                ),
            ).rowcount
            if not moved:
                continue
            conn.execute(
                "INSERT INTO rule_label_reconciled (source, rule_ref, kind, reason, previous_state, previous_disagreement,"
                " previous_reading_json, new_state, new_reading_json, a_reading_json, b_reading_json, quote_sha256, code_version, at)"
                " VALUES (?, ?, ?, ?, 'ai_approved', NULL, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                (
                    ev["source"],
                    ev["rule_ref"],
                    UNDONE,
                    ev["reason"],
                    ev["new_reading_json"],
                    ev["previous_state"],
                    ev["previous_reading_json"],
                    ev["a_reading_json"],
                    ev["b_reading_json"],
                    ev["quote_sha256"],
                    CODE_VERSION,
                ),
            )
            back += 1
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return back
