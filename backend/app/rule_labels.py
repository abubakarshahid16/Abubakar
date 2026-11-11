"""Rule labels, the read side and the decision (owner decision 1, 11 Nov 2026). Pure functions plus read-only lookups.

WHAT A LABEL SAYS. Per rule: its paper kind (datasheet, procedure, drawing, calculation, contract, other), for a
datasheet rule its field, and a state: `labelled_a` (one model answered), `ai_approved` (two DIFFERENT models agree on
kind, field and reading under ONE prompt version, and code found the quote word for word on the rule-book page),
`needs_human` (they differ, or code cannot prove a reading), `quote_not_found` (never sent to a model).

`decide` is THE decision and it holds every guard itself (no caller's flag is trusted: the readings and the field are checked again here): the quote was found; both
passes answered; the two models are not one family; both passes ran the SAME prompt version, the current one; each
reading is valid by code (every number it writes stands in the quote, its unit is written in the quote); a quote that
states a quantity is not approved on two readings that hold no number; the kind, field and reading agree by code.
Nothing here asks a model anything and no AI word decides a state.

THE TIER (`usable_tier`): a rule is usable by the reviewer when a PERSON approved that exact rule-book version
(`rulebook_approval`, owner or engineer tier, read only here, never written) or when its label is `ai_approved`. A
person's refusal of the exact version is never overridden by an AI label. A rule that is not usable comes back with ONE
reason word. This replaces the engineer sample for now (owner decision 1); an engineer who comes later reviews the
`needs_human` list and a sample.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import claims, numparse
from .rule_label_quantity import quote_states_a_quantity
from .rule_label_schema import (
    AI_APPROVED,
    LABELLED_A,
    NEEDS_HUMAN,
    PAPER_KINDS,
    QUOTE_NOT_FOUND,
    STATES,
)

#: Changes when the prompt text or the answer shape changes. A row is approved only when BOTH passes ran this one.
PROMPT_VERSION = "rule-label-v3"
#: What an import accepts. Never a version this code does not know how to check.
ACCEPTED_PROMPTS = (PROMPT_VERSION,)
#: The lab labeller's prompt of 11 Nov 2026 (no first-words echo). Accepted ONLY from a label file whose rows say
#: `origin: "lab-order12"` (`rule_label_convert`, `rule_label_import`) and then read by `usable_tier` from the table.
LAB_PROMPTS = ("rule-label-v2",)
LAB_ORIGIN = "lab-order12"

OWNER, ENGINEER, AI_TIER = "owner", "engineer", "AI approved"

COMPARATORS = (
    "eq",
    "le",
    "ge",
    "lt",
    "gt",
    "range",
    "one_of",
    "required",
    "prohibited",
    "statement",
)
STRENGTHS = ("shall", "should", "may")
NO_NUMBER = ("required", "prohibited", "statement")
ONE_NUMBER = ("eq", "le", "ge", "lt", "gt")

#: Why a rule is not usable (one word each; the Rules used page says them as they are).
NOT_LABELLED = "not_labelled"
NO_LABEL_TABLE = "no_label_table"
ONE_PASS_ONLY = "one_pass_only"
NEEDS_A_HUMAN = "needs_a_human"
QUOTE_NOT_ON_PAGE = "quote_not_found"
PERSON_DECLINED = "person_declined"
LABEL_REFUSED = "label_refused"


# ------------------------------------------------------------------------------------------------ small pure helpers


def quote_hash(text: str | None) -> str:
    """sha256 of a quote with its whitespace runs folded to one space (the form every check here compares)."""
    return hashlib.sha256(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()


def answer_hash(answer: Mapping) -> str:
    """sha256 of one rule's answer as a model gave it (canonical JSON): the proof of WHICH answer a pass holds."""
    return hashlib.sha256(
        json.dumps(answer, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def family(model: str | None) -> str:
    """A model id without its date suffix, lower case: one model under any spelling is one family."""
    return re.sub(r"-\d{8}$", "", (model or "").strip().lower())


def first_words(quote: str | None, n: int = 3) -> str:
    """The first words of a quote, lower case: a model echoes them so code can tell the answer belongs to THIS rule."""
    return " ".join(str(quote or "").split()[:n]).casefold()


def subject_clip(text: Any) -> str:
    return " ".join(str(text or "").split()[:6])


def page_is_low_confidence_ocr(origin: Mapping | None) -> bool:
    """The page's text was recognised (OCR) and its lowest confidence is unknown or under the app's own low-confidence
    threshold (`settings.ocr_low_conf_threshold`): a quote found there may carry a misread digit that the rule book
    shares, so it is never approved on this word alone. `origin` is one page's entry of `page_origin`."""
    from .config import settings

    if not origin or origin.get("page_source") != "recognised":
        return False
    conf = origin.get("page_min_conf")
    return conf is None or float(conf) < float(settings.ocr_low_conf_threshold)


# ------------------------------------------------------------------------------------------------ readings (code)


def _number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        return numparse.as_number(v)
    return None


def shape_ok(raw: Mapping) -> bool:
    """The answer has a reading's parts in the right TYPES (else it is unreadable: asked again, never guessed)."""
    unit = raw.get("unit")
    return (
        raw.get("comparator") in COMPARATORS
        and raw.get("strength") in STRENGTHS
        and isinstance(raw.get("values"), list)
        and (unit is None or isinstance(unit, str))
    )


def check_reading(raw: Mapping, quote: str | None) -> tuple[bool, dict]:
    """(valid, the reading with its values as floats). Invalid: a value that is no number, a value the quote does not
    state, a count of values that does not fit the comparator, or a unit the quote does not write (case matters: mPa
    is not MPa). Only `shape_ok` answers come here."""
    comparator, raw_values = raw["comparator"], raw["values"]
    unit = str(raw["unit"]).strip() if raw.get("unit") else ""
    reading = {
        "comparator": comparator,
        "values": [],
        "unit": unit or None,
        "strength": raw["strength"],
        "subject": subject_clip(raw.get("subject")),
    }
    nums = [_number(v) for v in raw_values]
    if any(n is None for n in nums):
        return False, reading
    reading["values"] = [float(n) for n in nums]
    count = len(nums)
    fits = (
        (comparator in NO_NUMBER and count == 0)
        or (comparator in ONE_NUMBER and count == 1)
        or (comparator == "range" and count == 2)
        or (comparator == "one_of" and count >= 2)
    )
    if not fits:
        return False, reading
    # `numbers_unread` is a finding of `decide` (it names it), not an invalid reading
    return reading_problem(reading, quote) in (None, "numbers_unread"), reading


def reading_problem(reading: Mapping, quote: str | None) -> str | None:
    """Why a reading cannot stand beside this quote, or None. Checked by code on the quote's own words:
    `value_not_in_quote`, `unit_not_in_quote`, `numbers_unread` (the quote states a quantity and the reading holds no
    number: a bare "statement" of a numeric rule is not a reading of it)."""
    text = " ".join(str(quote or "").split())
    values = list(reading.get("values") or [])
    if not all(numparse.value_in_text(v, text) for v in values):
        return "value_not_in_quote"
    unit = str(reading.get("unit") or "").strip()
    if values and unit and unit not in text:
        return "unit_not_in_quote"
    if not values and quote_states_a_quantity(text):
        return "numbers_unread"
    return None


def _same_numbers(a: Sequence[float], b: Sequence[float]) -> bool:
    if len(a) != len(b):
        return False
    return all(
        math.isclose(x, y, rel_tol=1e-9, abs_tol=0.0)
        for x, y in zip(sorted(a), sorted(b), strict=True)
    )


def units_agree(a: str | None, b: str | None) -> bool:
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return not a and not b
    if a == b:
        return True
    if claims.same_unit(
        claims.Measurement("", a, None, None, None),
        claims.Measurement("", b, None, None, None),
    ):
        return True
    if claims.unit_dimension(a) and claims.unit_dimension(
        b
    ):  # two units the project knows: they differ
        return False
    return a.casefold() == b.casefold()


def readings_agree(a: Mapping, b: Mapping) -> list[str]:
    """The parts that differ, in a fixed order (empty list: the two readings agree). Both readings are valid."""
    out = []
    if a["comparator"] != b["comparator"]:
        out.append("comparator")
    if not _same_numbers(a["values"], b["values"]):
        out.append("values")
    if (a["values"] or b["values"]) and not units_agree(a.get("unit"), b.get("unit")):
        out.append("unit")
    if a["strength"] != b["strength"]:
        out.append("strength")
    return out


# ------------------------------------------------------------------------------------------------ the decision


@dataclass(frozen=True)
class PassAnswer:
    """One pass's answer for one rule, after code read it. `valid` is `check_reading`'s verdict."""

    model: str
    prompt: str
    paper_kind: str
    field: str | None
    reading: Mapping
    valid: bool
    answer_sha256: str


@dataclass(frozen=True)
class Decision:
    state: str
    paper_kind: str | None = None
    field: str | None = None
    disagreement: str | None = None
    reading: Mapping | None = None


@functools.cache
def field_list() -> dict[str, str]:
    """{role: kind}: every role any equipment type's checklist wants (the app's fixed field lists, as data). The one list a
    datasheet rule's field must be on, for the prompt and for `decide`."""
    from . import datasheet_checks, datasheet_roles

    rules = datasheet_checks.load_rules()
    roles = rules.get("roles") or {}
    out: dict[str, str] = {}
    for equipment_type in rules.get("checklists") or {}:
        if str(equipment_type).startswith("_"):
            continue
        for role in datasheet_roles.wanted_roles(equipment_type, rules):
            if role in roles:
                out[role] = str(roles[role].get("kind") or "text")
    return dict(sorted(out.items()))


def _valid_here(p: PassAnswer, quote_text: str | None) -> bool:
    """A pass's reading is valid by code HERE: the caller's `valid` flag must say so AND the reading has the right shape,
    a count of numbers that fits its comparator, every number and the unit in the quote."""
    return (
        bool(p.valid)
        and shape_ok(p.reading)
        and check_reading(p.reading, quote_text)[0]
    )


def decide(
    a: PassAnswer | None,
    b: PassAnswer | None,
    *,
    quote_found: bool,
    quote_text: str | None,
    quote_ocr_low: bool = False,
    prompt_version: str = PROMPT_VERSION,
    fields: Collection[str] | None = None,
) -> Decision | None:
    """THE state of a rule, by code only. None when no pass answered and the quote was found (no row to write yet).

    Order: quote not found -> quote_not_found; one pass -> labelled_a; two passes: any guard or difference below ->
    needs_human naming it (`disagreement`, comma separated, fixed order), else ai_approved.
      model_not_named / same_model   the two answering models are not two named, different families
      prompt_version                 either pass ran a prompt version other than `prompt_version`, or the two differ
      invalid_reading                a model's numbers or unit are not in the quote, or its count does not fit
      numbers_unread                 the quote states a quantity and a reading holds no number
      ocr_low_confidence             the quote stands on a recognised (OCR) page of low or unknown confidence
      kind / field                   the paper kinds differ; a datasheet's two fields differ
      field_not_listed               a datasheet field is named that is not on the fixed field list (`fields`, default
                                     `field_list()`): never approved, whoever supplied the answer
      (`valid` of a PassAnswer is NOT trusted: each reading is checked again here against the quote)
      comparator / values / unit / strength   the two readings differ (numbers compared by code)"""
    if not quote_found:
        return Decision(QUOTE_NOT_FOUND)
    if a is None and b is None:
        return None
    if a is None:
        raise ValueError("pass b answered without pass a")
    if b is None:
        return Decision(LABELLED_A)
    diff: list[str] = []
    if not a.model.strip() or not b.model.strip():
        diff.append("model_not_named")
    elif family(a.model) == family(b.model):
        diff.append("same_model")
    if not (a.prompt == b.prompt == prompt_version):
        diff.append("prompt_version")
    if quote_ocr_low:
        diff.append("ocr_low_confidence")
    if not all(_valid_here(p, quote_text) for p in (a, b)):
        diff.append("invalid_reading")
    else:
        for p in (a, b):
            if (
                reading_problem(p.reading, quote_text) == "numbers_unread"
                and "numbers_unread" not in diff
            ):
                diff.append("numbers_unread")
        if a.paper_kind != b.paper_kind:
            diff.append("kind")
        elif a.paper_kind == "datasheet" and a.field != b.field:
            diff.append("field")
        listed = set(field_list() if fields is None else fields)
        if any(
            p.paper_kind == "datasheet"
            and p.field is not None
            and p.field not in listed
            for p in (a, b)
        ):
            diff.append("field_not_listed")
        diff += readings_agree(a.reading, b.reading)
    kind = a.paper_kind if a.paper_kind == b.paper_kind else None
    field = a.field if kind == "datasheet" and a.field == b.field else None
    if "field_not_listed" in diff:
        field = None
    # the agreed reading is kept whenever the two readings agree, also when only the kind or field is in doubt
    agreed = "invalid_reading" not in diff and not readings_agree(a.reading, b.reading)
    reading = {**a.reading, "subject_b": b.reading.get("subject")} if agreed else None
    return Decision(
        NEEDS_HUMAN if diff else AI_APPROVED,
        kind,
        field,
        ",".join(dict.fromkeys(diff)) or None,
        reading,
    )


def approval_guard(
    row: Mapping,
    quote_text: str | None = None,
    *,
    accepted: Sequence[str] = ACCEPTED_PROMPTS,
) -> str | None:
    """Why a row that CLAIMS `ai_approved` may not be trusted, or None. For rows that arrive (an import) and for a read
    (`usable_tier`): the same conditions `decide` and the table's CHECK hold, from the row's own columns. With the
    rule's current quote text it also re-proves the reading against it."""
    a, b = row.get("a_model"), row.get("b_model")
    if not str(a or "").strip() or not str(b or "").strip():
        return "model_not_named"
    if family(a) == family(b):
        return "same_model"
    if not (
        row.get("a_prompt") == row.get("b_prompt") and row.get("a_prompt") in accepted
    ):
        return "prompt_version"
    hexed = re.compile(r"^[0-9a-f]{64}$")
    if not all(
        hexed.match(str(row.get(k) or ""))
        for k in ("a_answer_sha256", "b_answer_sha256", "quote_sha256")
    ):
        return "hash_missing"
    kind, field = row.get("paper_kind"), row.get("field")
    if kind not in PAPER_KINDS or (field is not None and kind != "datasheet"):
        return "kind_or_field"
    if field is not None and field not in field_list():
        return "field_not_listed"
    if not isinstance(row.get("quote_page"), int) or isinstance(
        row.get("quote_page"), bool
    ):
        return "quote_page_missing"
    try:
        reading = json.loads(row.get("reading_json") or "")
    except ValueError:
        return "reading_missing"
    if not isinstance(reading, dict) or reading.get("comparator") not in COMPARATORS:
        return "reading_missing"
    for which in ("a", "b"):  # the answer a pass holds is the answer its hash names
        raw = row.get(f"{which}_answer_json")
        if raw:
            try:
                if answer_hash(json.loads(raw)) != row.get(f"{which}_answer_sha256"):
                    return "answer_hash_differs"
            except ValueError:
                return "answer_hash_differs"
    if quote_text is not None:
        if quote_hash(quote_text) != row.get("quote_sha256"):
            return "quote_changed"
        problem = reading_problem(reading, quote_text)
        if problem:
            return problem
    return None


# ------------------------------------------------------------------------------------------------ read side (read only)


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def label_for(
    conn, *, requirement_id: str | None = None, rule_version_id: str | None = None
) -> dict | None:
    """The label of one rule as a dict, or None (no row, or no table). By the reviewer's rule (a
    `standard_requirements` id) or by a rule-book version id; a requirement whose quote was bridged to a version is
    found by either. Read only."""
    if not requirement_id and not rule_version_id:
        raise ValueError("a requirement id or a rule version id is needed")
    if not _has(conn, "rule_label"):
        return None
    cursor = conn.execute
    if requirement_id:
        row = cursor(
            "SELECT * FROM rule_label WHERE source = 'requirement' AND rule_ref = ?",
            (requirement_id,),
        ).fetchone()
        if row is not None:
            return _as_dict(conn, row)
    if rule_version_id:
        row = cursor(
            "SELECT * FROM rule_label WHERE (source = 'rulebook' AND rule_ref = ?) OR rule_version_id = ?"
            " ORDER BY (source = 'rulebook') DESC LIMIT 1",
            (rule_version_id, rule_version_id),
        ).fetchone()
        if row is not None:
            return _as_dict(conn, row)
    return None


def _as_dict(conn, row) -> dict:
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}  # noqa: SIM118 - sqlite3.Row has no dict protocol
    names = [d[0] for d in conn.execute("SELECT * FROM rule_label LIMIT 0").description]
    return dict(zip(names, row, strict=True))


@dataclass(frozen=True)
class Tier:
    """`tier` is 'owner', 'engineer', 'AI approved' or None; with None, `reason` is one word of why the rule is not
    usable. `label` is the rule's label row when it has one."""

    tier: str | None
    reason: str | None = None
    label: Mapping | None = None


def _person_decisions(
    conn, version_id: str, equipment_type: str | None
) -> tuple[str | None, bool]:
    """(tier a person's approval gives this exact version, whether a person's decision refuses it). READ ONLY: nothing
    in this module writes `rulebook_approval`. Per equipment type the LAST decision counts; a decision that names no
    type (a retirement) ends every approval before it (the rule book's own reading of its rows)."""
    if not _has(conn, "rulebook_approval"):
        return None, False
    columns = {r[1] for r in conn.execute("PRAGMA table_info(rulebook_approval)")}
    tier_col = "tier" if "tier" in columns else "NULL"
    type_col = "equipment_type" if "equipment_type" in columns else "NULL"
    standing: dict[str, str | None] = {}
    declined = False
    for decision, etype, tier in conn.execute(
        f"SELECT decision, {type_col}, {tier_col} FROM rulebook_approval WHERE rule_version_id = ? ORDER BY rowid",
        (version_id,),
    ):
        kind = " ".join(str(etype or "").casefold().split())
        if not kind:
            standing.clear()
            declined = True
        elif decision == "approve":
            standing[kind] = tier
        else:
            standing.pop(kind, None)
            declined = True
    wanted = " ".join(str(equipment_type or "").casefold().split())
    tiers = (
        [standing[wanted]]
        if wanted and wanted in standing
        else ([] if wanted else list(standing.values()))
    )
    if tiers:
        return (OWNER if OWNER in tiers else ENGINEER), False
    return None, declined


def usable_tier(
    conn,
    *,
    requirement_id: str | None = None,
    rule_version_id: str | None = None,
    equipment_type: str | None = None,
) -> Tier:
    """Whether the reviewer may ask this rule, and on whose word. In order:
      1. a person approved this exact rule-book version (for `equipment_type` when given): 'owner' (wins) or 'engineer';
      2. a person's later decision refused it: not usable, `person_declined`, whatever the label says;
      3. its label is `ai_approved` and still passes `approval_guard`: 'AI approved';
      4. otherwise None with the reason: `not_labelled`, `no_label_table`, `one_pass_only`, `needs_a_human`,
         `quote_not_found` or `label_refused`.
    Read only on any connection."""
    label = label_for(
        conn, requirement_id=requirement_id, rule_version_id=rule_version_id
    )
    version_id = rule_version_id or (label or {}).get("rule_version_id")
    if version_id:
        person, declined = _person_decisions(conn, version_id, equipment_type)
        if person:
            return Tier(person, None, label)
        if declined:
            return Tier(None, PERSON_DECLINED, label)
    if label is None:
        return Tier(
            None, NOT_LABELLED if _has(conn, "rule_label") else NO_LABEL_TABLE, None
        )
    state = label.get("state")
    if state == AI_APPROVED:
        cause = approval_guard(label, accepted=ACCEPTED_PROMPTS + LAB_PROMPTS)
        return (
            Tier(AI_TIER, None, label)
            if cause is None
            else Tier(None, LABEL_REFUSED, label)
        )
    reason = {
        LABELLED_A: ONE_PASS_ONLY,
        NEEDS_HUMAN: NEEDS_A_HUMAN,
        QUOTE_NOT_FOUND: QUOTE_NOT_ON_PAGE,
    }.get(state, LABEL_REFUSED)
    return Tier(None, reason, label)


def paper_kind_of(label: Mapping | None) -> str | None:
    """The agreed paper kind of a label, or None (not agreed, or no label)."""
    kind = (label or {}).get("paper_kind")
    return (
        kind if kind in PAPER_KINDS and (label or {}).get("state") in STATES else None
    )


def bridge_map(conn) -> dict[tuple, str]:
    """{(document id, page, quote with spaces folded): rule_version_id} for the latest rule-book versions, so a
    requirement with the same quote on the same document and page also carries its rule-book version id. Empty when the
    rule book has no tables here. Read only."""
    if not (_has(conn, "rulebook_version") and _has(conn, "rulebook_provenance")):
        return {}
    out: dict[tuple, str] = {}
    for r in conn.execute(
        "SELECT p.rule_version_id, p.standard_document_id, p.page, p.quote FROM rulebook_provenance p"
        " JOIN rulebook_version v ON v.id = p.rule_version_id WHERE v.version_no = ("
        "SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
    ):
        out.setdefault((r[1], r[2], " ".join(str(r[3] or "").split())), r[0])
    return out
