"""The label job's prompt and the reading of a model's answers (owner decision 1, 11 Nov 2026).

A model is shown ONLY rule-book text: the clause number and the quote of each rule, with the paper kinds and the app's
fixed field list. It answers per rule, and `parse_answers` keeps an answer only when it is readable, in its closed lists,
and tied to ITS rule by the echo of the quote's first three words (an answer attached to the wrong rule is dropped).
Code reads the numbers and unit of each answer against the quote (`rule_labels.check_reading`); no AI word decides.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from . import agent_claude, claude_spend, rule_labels
from .rule_label_schema import PAPER_KINDS

if TYPE_CHECKING:
    from .rule_label_job import Rule

BATCH_RULES = 20
TOKENS_PER_RULE_OUT = 100
#: Thinking cannot be switched off on these models: room for it, per call, at low effort.
THINKING_ALLOWANCE_TOKENS = 600


field_list = (
    rule_labels.field_list
)  # the one fixed list, also read by `rule_labels.decide`


SYSTEM_HEAD = (
    "You label rules of engineering standards. Each numbered rule gives its clause number and its words copied from the "
    "standard (quote). Work from the QUOTE alone. For each rule answer:\n"
    "- start: the first three words of the quote, exactly as written (so the answer is tied to its rule).\n"
    "- paper_kind: choose the paper on which an engineer would FIRST and most directly check this requirement. One of:\n"
    "  datasheet = a property of the equipment item itself that its datasheet states or selects (type, arrangement, "
    "size, rating, material, design or operating condition, set point, code or stamp, accessory, sealing or flushing "
    "arrangement, connection). If the rule fixes a value or a selection of the item, it is datasheet even if drawings "
    "are also affected.\n"
    "  drawing = where things are placed or how they are connected, routed or arranged (location, orientation, piping "
    "layout, isolation arrangement, supports, clearances; what a piping and instrument diagram, layout or isometric "
    "shows).\n"
    "  calculation = a quantity that must be computed, or a sizing or analysis basis or method, checked in a "
    "calculation report.\n"
    "  procedure = how work is carried out or recorded (fabrication, welding, testing, inspection, installation "
    "steps, operation, maintenance, qualification records).\n"
    "  contract = who must do, approve or submit what (responsibilities, approvals, deviations, waivers, document "
    "deliverables, purchasing terms).\n"
    "  other = definitions, scope or classification statements, none of the above.\n"
    "- field: ONLY when paper_kind is datasheet: the ONE field from THE LIST that the rule limits or asks for, "
    "exactly as named there, or null when none fits. For every other paper_kind: null.\n"
    "- comparator: one of eq (is equal to), le (at most), ge (at least), lt (less than), gt (more than), range "
    "(between two values), one_of (one of several listed values), required (something must be provided, stated or "
    "done; no number), prohibited (something must not be present or used; no number), statement (anything else: a "
    "definition, a description, a rule with no number and no clear obligation).\n"
    "- values: the numbers of the requirement exactly as written in the quote, as plain JSON numbers, in the primary "
    "(first stated) unit system only. eq, le, ge, lt, gt: one number; range: two (low, high); one_of: two or more "
    "numbers, or, when the listed alternatives are words (materials, types, grades), the two or more alternatives as JSON "
    "strings, each copied exactly as written in the quote; required, prohibited, statement: an empty list. Never a "
    "number or word that is not in the quote.\n"
    "- unit: the unit exactly as written in the quote, or null.\n"
    "- strength: shall (shall, must, is required), should (should, is recommended), may (may, is permitted).\n"
    "- subject: what the rule is about, at most 6 words.\n"
    "- reason: at most 12 words.\n"
    'Reply with ONE JSON object and nothing else: {"answers": [{"n": 1, "start": "the item shall", "paper_kind": '
    '"datasheet", "field": null, "comparator": "le", "values": [10], "unit": "bar", "strength": "shall", "subject": '
    '"the item design pressure", "reason": "..."}]}. One answer per rule, with its n. (The example values are '
    "invented; they say nothing about any rule.)"
)


def system_text(fields: dict[str, str]) -> str:
    listed = "\n".join(f"- {role} ({kind})" for role, kind in fields.items())
    return f"{SYSTEM_HEAD}\n\nTHE LIST:\n{listed}"


def user_text(batch: Sequence[Rule]) -> str:
    """ONLY rule-book text: n, clause, quote. Nothing of any other rule, pass or paper."""
    rules = [
        {"n": i, "clause": r.clause, "quote": r.quote} for i, r in enumerate(batch, 1)
    ]
    return json.dumps({"rules": rules}, ensure_ascii=False)


def build_parts(batch: Sequence[Rule], system: str) -> dict:
    """The request body parts: the cached system prefix first, the rules last. Low effort: the lane's lever for
    labelling from a fixed list (thinking itself cannot be switched off)."""
    return {
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": user_text(batch)}]}
        ],
        "output_config": {"effort": "low"},
    }


def max_tokens_for(n_rules: int, model: str | None = None) -> int:
    base = TOKENS_PER_RULE_OUT * n_rules + 300 + 2 * THINKING_ALLOWANCE_TOKENS
    return claude_spend.output_cap(model, base) if model else base


def _start_key(text: Any) -> str:
    return " ".join(re.sub(r"\W+", " ", str(text or "")).casefold().split())


def batch_structure_ok(rows: Any, n_rules: int) -> bool:
    """As many answers as rules in the batch, each a JSON object with an integer n, and the indexes exactly 1..N, each
    once. Anything else (a missing, extra, repeated or out-of-range answer) and the WHOLE batch is unreadable."""
    if not isinstance(rows, list) or len(rows) != n_rules:
        return False
    ns = [a.get("n") if isinstance(a, dict) else None for a in rows]
    return all(isinstance(n, int) and not isinstance(n, bool) for n in ns) and sorted(
        ns
    ) == list(range(1, n_rules + 1))


def parse_answers(
    text: str, batch: Sequence[Rule], model: str
) -> dict[int, rule_labels.PassAnswer]:
    """{n: PassAnswer} for the answers that are readable AND belong to their rule. The WHOLE batch is left out unless the answers are exactly
    n = 1..N, each once (`batch_structure_ok`). Left out (the rule stays unlabelled for this pass): not JSON; an `n` out of range, repeated or not an integer; a paper kind outside its closed list or a field that is no text; a reading of the wrong shape; a `start` that is not the first three words of THAT rule's quote (an answer
    attached to the wrong rule). A readable answer whose numbers or unit the quote does not hold is kept with
    valid=False (code decides: the rule goes to a human)."""
    obj = agent_claude.parse_json_object(text)
    rows = obj.get("answers") if isinstance(obj, dict) else None
    out: dict[int, rule_labels.PassAnswer] = {}
    if not batch_structure_ok(rows, len(batch)):
        return out  # the whole batch is unreadable: nothing attached by guesswork, the rules stay unlabelled
    for a in rows:
        if not isinstance(a, dict):
            continue
        n, kind, fld = a.get("n"), a.get("paper_kind"), a.get("field")
        if (
            isinstance(n, bool)
            or not isinstance(n, int)
            or not 1 <= n <= len(batch)
            or n in out
        ):
            continue
        quote = batch[n - 1].quote
        if kind not in PAPER_KINDS or not rule_labels.shape_ok(a):
            continue
        if _start_key(a.get("start")) != _start_key(rule_labels.first_words(quote)):
            continue
        if kind != "datasheet":
            fld = None
        elif fld is not None and not isinstance(fld, str):
            continue  # a field NOT ON THE LIST is kept: `rule_labels.decide` makes that row needs_human
        valid, reading = rule_labels.check_reading(a, quote)
        content = {"paper_kind": kind, "field": fld, "reading": reading, "valid": valid}
        out[n] = rule_labels.PassAnswer(
            model=model,
            prompt=rule_labels.PROMPT_VERSION,
            paper_kind=kind,
            field=fld,
            reading=reading,
            valid=valid,
            answer_sha256=rule_labels.answer_hash(content),
        )
    return out
