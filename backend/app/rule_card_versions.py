"""The engineer's step on a rule card: approve, edit or reject (order 302.4).

A rule card (`rule_cards`) is a checklist item the real code has tested. A TESTED card is not yet an
APPROVED one: an engineer reads it and decides. This module keeps that decision, and the edits that
lead to it, in one append-only table (`rule_card_versions`), and answers one question for the review:
what is this card's state, in one word.

  rejected  an engineer rejected this exact content (shown first: a rejection stands whatever the tests say)
  draft     the real code did not pass it (no cases, a case failed, or it waits for a standard we
            do not hold), whatever anyone approved before
  tested    meets, breaks and unclear all pass; no engineer has decided this exact content
  approved  an engineer approved THIS exact content (its hash), and it still passes

The committed JSON (`reference/datasheet_checks.json`) is version 1 and is never rewritten here.
A decision is written once and never changed. An edit is a NEW version that starts with no decision:
it is tested again at once, and the earlier approval stays in the history but no longer applies.
An approval applies only while the card's content is the content that was approved: the hash
decides, not a flag. Nothing here calls a model or a network.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime

from . import datasheet_checks as dc
from . import rule_cards

APPROVED, REJECTED = "approved", "rejected"
DRAFT, TESTED = "draft", "tested"
STATES = (DRAFT, TESTED, APPROVED, REJECTED)

#: What an edit may change, by kind of rule. Everything else (the kind, the box names of a comparison,
#: the formula) is a new rule, not an edit. A box name must be a role of the checklist data.
EDITABLE = {
    "required": ("field",),
    "allowed": ("field", "values"),
    "compare": ("op", "left", "right"),
    "constant": ("op", "value"),
    "percent_of": ("op", "percent", "left", "right"),
    "above_by": ("percent", "at_least", "left", "right"),
    "calc": ("tolerance_percent",),
}
ROLE_KEYS = ("field", "left", "right")
OPS = (">=", ">", "<=", "<")
SEVERITIES = ("critical", "major", "minor")
#: A clause number: digits with dots, or a letter code with digits ("8.13.1", "UG-22", "A-1").
_CLAUSE = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Za-z]{1,5}-\d+(?:\.\d+)*)$")


#: What "tested" rests on (cloud-3, #1435): cases built from the card itself test the code path, not that the box
#: the card names is the right one; only a person's written cases test the rule's meaning.
BASIS_WRITTEN = "cases written from the rule's meaning, run on the real code"
BASIS_GENERATED = "generated cases only: they check the code path, not that the box named is the right one"


class CardError(ValueError):
    """The decision or edit is refused; the message says why, in plain words."""


class Conflict(CardError):
    """The card changed since the engineer looked at it (the hash or version differs)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def content_hash(item: dict) -> str:
    """The hash an approval is tied to: the card's whole content, canonical."""
    return hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def ensure_schema(conn=None) -> None:
    """Create the table (a write). Reads never call it: `_rows` asks `sqlite_master` first."""
    if conn is None:
        from .db import connect

        conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rule_card_versions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               equipment_type TEXT NOT NULL,
               card_id TEXT NOT NULL,
               version INTEGER NOT NULL,
               content TEXT NOT NULL,
               content_hash TEXT NOT NULL,
               base_hash TEXT NOT NULL,
               created_by TEXT NOT NULL,
               created_at TEXT NOT NULL,
               decision TEXT,
               decided_by TEXT,
               decided_at TEXT,
               tests TEXT,
               UNIQUE (equipment_type, card_id, version))"""
    )


def _baseline(equipment_type: str, card_id: str, rules: dict) -> dict:
    checklist = (rules.get("checklists") or {}).get(equipment_type)
    for item in checklist["items"] if isinstance(checklist, dict) else []:
        if item["id"] == card_id:
            return item
    raise CardError(f"no rule card {card_id!r} for {equipment_type!r}")


def _rows(conn, equipment_type: str, card_id: str) -> list:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rule_card_versions'"
    ).fetchone():
        return []  # nobody has decided or edited anything yet: a read creates nothing
    return conn.execute(
        "SELECT * FROM rule_card_versions WHERE equipment_type = ? AND card_id = ? ORDER BY version",
        (equipment_type, card_id),
    ).fetchall()


def current(conn, equipment_type: str, card_id: str, rules: dict | None = None) -> dict:
    """The card as it stands: its latest version's content and the decision on that exact content.

    Version 1 is the committed item. Stored versions come from the engineer's decisions and edits. When the
    committed item changed after an engineer decided on it (git moved the baseline), a decision on an unedited
    card no longer applies and an edited card keeps the engineer's content, with `baseline_changed` set."""
    rules = rules or dc.load_rules()
    baseline = _baseline(equipment_type, card_id, rules)
    rows = _rows(conn, equipment_type, card_id)
    base_hash = content_hash(baseline)
    out = {
        "card_id": card_id,
        "equipment_type": equipment_type,
        "version": 1,
        "item": baseline,
        "content_hash": base_hash,
        "decision": None,
        "decided_by": None,
        "decided_at": None,
        "baseline_changed": False,
        "versions": len(rows) or 1,
    }
    if not rows:
        return out
    last = rows[-1]
    moved = last["base_hash"] != base_hash
    if moved and last["version"] == 1:
        return out
    stored = json.loads(last["content"])
    out.update(
        version=last["version"],
        item=stored,
        content_hash=last["content_hash"],
        baseline_changed=moved,
    )
    if last["decision"] and not moved:
        out.update(
            decision=last["decision"],
            decided_by=last["decided_by"],
            decided_at=last["decided_at"],
        )
    return out


def state_of(card: dict, rules: dict | None = None) -> dict:
    """The card's state in one word and why, from the real tests of its CURRENT content and the decision on it."""
    rules = rules or dc.load_rules()
    ran = rule_cards.run_card(card["item"], card["equipment_type"], rules)
    if card["decision"] == REJECTED:
        state, why = REJECTED, ""
    elif ran["status"] != "tested":
        state, why = DRAFT, ran["why"]
    elif card["decision"] == APPROVED:
        state, why = APPROVED, ""
    else:
        state, why = TESTED, "tested, not yet approved"
    written = sum(r["kind"] == "written" for r in ran["runs"])
    return {
        "state": state,
        "why": why,
        "runs": ran["runs"],
        "weak_source": ran["weak_source"],
        "written_cases": written,
        "basis": BASIS_WRITTEN if written else BASIS_GENERATED,
    }


def whole(conn, equipment_type: str, card_id: str, rules: dict | None = None) -> dict:
    rules = rules or dc.load_rules()
    card = current(conn, equipment_type, card_id, rules)
    return {**card, **state_of(card, rules)}


def clause_is_a_number(item: dict) -> bool:
    return bool(
        _CLAUSE.match(str((item.get("source") or {}).get("clause") or "").strip())
    )


def _check_stale(card: dict, version: int, seen_hash: str) -> None:
    if card["version"] != version or card["content_hash"] != seen_hash:
        raise Conflict(
            "this card changed since you opened it; reload it and decide again"
        )


def _write_decision(conn, card: dict, decision: str, actor: str, counts: dict) -> dict:
    """Write the decision on the card's current version once. Version 1 gets its row now (the committed item)."""
    now = _now()
    base = content_hash(
        _baseline(card["equipment_type"], card["card_id"], dc.load_rules())
    )
    ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO rule_card_versions (equipment_type, card_id, version, content, content_hash,"
            " base_hash, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                card["equipment_type"],
                card["card_id"],
                card["version"],
                json.dumps(card["item"], sort_keys=True),
                card["content_hash"],
                base,
                actor,
                now,
            ),
        )
        done = conn.execute(
            "UPDATE rule_card_versions SET decision = ?, decided_by = ?, decided_at = ?, tests = ?"
            " WHERE equipment_type = ? AND card_id = ? AND version = ? AND content_hash = ? AND decision IS NULL",
            (
                decision,
                actor,
                now,
                json.dumps(counts),
                card["equipment_type"],
                card["card_id"],
                card["version"],
                card["content_hash"],
            ),
        )
        if done.rowcount != 1:
            raise Conflict("this card was already decided")
    return {"decision": decision, "decided_by": actor, "decided_at": now}


def decide(
    conn,
    equipment_type: str,
    card_id: str,
    decision: str,
    *,
    version: int,
    seen_hash: str,
    actor: str,
    rules: dict | None = None,
) -> dict:
    """Approve or reject the card version the engineer saw. Approve needs the card tested NOW and a clause number."""
    if decision not in (APPROVED, REJECTED):
        raise CardError("the decision is approve or reject")
    if not actor:
        raise CardError("nobody is signed in; nothing is written")
    rules = rules or dc.load_rules()
    card = current(conn, equipment_type, card_id, rules)
    _check_stale(card, version, seen_hash)
    if card["decision"]:
        raise Conflict("this card was already decided; edit it to decide again")
    ran = state_of(card, rules)
    if decision == APPROVED:
        if ran["state"] != TESTED:
            raise CardError(
                f"only a tested card can be approved (this one is {ran['state']}: {ran['why']})"
            )
        if not clause_is_a_number(card["item"]):
            raise CardError(
                "the card's source is not a clause number; name the clause before approving"
            )
    counts = {
        "cases": len(ran["runs"]),
        "passed": sum(r["passed"] for r in ran["runs"]),
    }
    return _write_decision(conn, card, decision, actor, counts)


def _number(value, name: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardError(f"{name} must be a number")
    return value


def apply_changes(item: dict, changes: dict, rules: dict) -> dict:
    """The edited copy of a card, or a CardError. Only the fields the rule's kind allows; boxes from the data."""
    new = copy.deepcopy(item)
    rule = new["rule"]
    allowed = EDITABLE[rule["kind"]]
    for key, value in changes.items():
        if key == "text":
            if not isinstance(value, str) or not value.strip():
                raise CardError("the card's words cannot be empty")
            new["text"] = value.strip()
        elif key == "severity":
            if value not in SEVERITIES:
                raise CardError("severity is critical, major or minor")
            new["severity"] = value
        elif key in ("standard", "clause"):
            if not isinstance(value, str) or not value.strip():
                raise CardError(f"the source {key} cannot be empty")
            new["source"][key] = value.strip()
        elif key in allowed:
            if key == "op" and value not in OPS:
                raise CardError(f"the comparison is one of {', '.join(OPS)}")
            if key in ROLE_KEYS and value not in rules["roles"]:
                raise CardError(f"{value!r} is not a box this checklist knows")
            if key == "values":
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(isinstance(v, str) and v.strip() for v in value)
                ):
                    raise CardError("values is a list of words")
                value = [v.strip() for v in value]
            if key in ("percent", "at_least", "value", "tolerance_percent"):
                _number(value, key)
            rule[key] = value
        else:
            raise CardError(f"{key!r} cannot be edited on a {rule['kind']} rule")
    if new == item:
        raise CardError("nothing changed")
    return new


def edit(
    conn,
    equipment_type: str,
    card_id: str,
    changes: dict,
    *,
    version: int,
    seen_hash: str,
    actor: str,
    rules: dict | None = None,
) -> dict:
    """A new version of the card: its content changed, no decision, tested again at once. The old one stays."""
    if not actor:
        raise CardError("nobody is signed in; nothing is written")
    rules = rules or dc.load_rules()
    card = current(conn, equipment_type, card_id, rules)
    _check_stale(card, version, seen_hash)
    new = apply_changes(card["item"], changes, rules)
    base = content_hash(_baseline(equipment_type, card_id, rules))
    now = _now()
    ensure_schema(conn)
    with conn:
        if not _rows(conn, equipment_type, card_id):
            conn.execute(
                "INSERT INTO rule_card_versions (equipment_type, card_id, version, content, content_hash,"
                " base_hash, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    equipment_type,
                    card_id,
                    1,
                    json.dumps(card["item"], sort_keys=True),
                    card["content_hash"],
                    base,
                    "committed",
                    now,
                ),
            )
        conn.execute(
            "INSERT INTO rule_card_versions (equipment_type, card_id, version, content, content_hash,"
            " base_hash, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                equipment_type,
                card_id,
                card["version"] + 1,
                json.dumps(new, sort_keys=True),
                content_hash(new),
                base,
                actor,
                now,
            ),
        )
    return whole(conn, equipment_type, card_id, rules)


def listing(conn, rules: dict | None = None) -> dict:
    """Every card with its state, and the counts per equipment type (the denominator is that type's cards)."""
    rules = rules or dc.load_rules()
    out: dict = {}
    for equipment_type, checklist in rules["checklists"].items():
        if not isinstance(checklist, dict):
            continue
        cards = [
            whole(conn, equipment_type, i["id"], rules) for i in checklist["items"]
        ]
        counts = {s: sum(c["state"] == s for c in cards) for s in STATES}
        out[equipment_type] = {
            "cards": [
                {
                    "card_id": c["card_id"],
                    "text": c["item"]["text"],
                    "source": c["item"]["source"],
                    "state": c["state"],
                    "why": c["why"],
                    "version": c["version"],
                    "weak_source": c["weak_source"],
                    "written_cases": c["written_cases"],
                    "decided_by": c["decided_by"],
                    "decided_at": c["decided_at"],
                }
                for c in cards
            ],
            "counts": counts,
            "total": len(cards),
        }
    return out


def in_force(conn, rules: dict) -> dict:
    """The rules the review evaluates when the approval switch is on: every checklist item replaced by the latest
    version of its card (an engineer's edit changes the check itself; its state, not its presence, decides whether
    it may decide). A card nobody edited is the committed item, unchanged."""
    checklists = {}
    for equipment_type, checklist in rules["checklists"].items():
        if not isinstance(checklist, dict):
            checklists[equipment_type] = checklist
            continue
        items = [
            current(conn, equipment_type, i["id"], rules)["item"]
            for i in checklist["items"]
        ]
        checklists[equipment_type] = {**checklist, "items": items}
    return {**rules, "checklists": checklists}
