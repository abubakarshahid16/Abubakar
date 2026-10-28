"""Order 270.3: turn the sentences of ONE standard into checks, offline, and keep only what code can prove.

THE ROOT CAUSE this closes (plan change 4, #805): standard rules are stored as sentences the system cannot
test. For every stored requirement of one standard the converter asks Claude Sonnet (the one approved lane:
`reasoning_provider.ClaudeProvider` -> `reader_transport`, every call reserved in `claude_spend` under the
step `standards_convert:<standard>` with its own USD cap) for:

  * does it apply to the equipment type (yes / no / depends, with the condition);
  * ONE field of that type's own form (`rule_roles.form`, i.e. the pump form of #1352 - never a copy of it
    here), a comparator, a limit, a unit, and the exact clause words it rests on.

CODE THEN VERIFIES (`verify`); the model never writes a check:

  1. the quote is in the stored clause text;
  2. the number is inside the quote, as a whole figure, and the unit is inside the quote;
  3. the unit is of the kind the field is (a pressure is not in minutes);
  4. the quote names the field (every content word of its canonical name is in the quote);
  5. the comparator is the one the quote's own words say ("shall not exceed" is <=, "at least" is >=).

Verified = a CHECK. Anything else is UNPROVEN, and an unproven row may only say "engineer, please look":
it carries no limit, no comparator and no verdict - there is no path from it to "meets". A "no" or a
"depends" answer is the model's claim, stored unconfirmed; only a "yes" row is ever read by a review.

WHAT GOES TO THE CLOUD: standards text only. The prompt is built from `standard_requirements` rows of
documents classified COMPANY_STANDARD (clause and sentence), the system block from the type's field names.
No datasheet, procedure, CRS or register text can enter it: `requirements_of` is the only source, and
`claude_approved.carrying` declares exactly the standard being converted, so the owner's approved-documents
list refuses the call when that standard is not on it. Only the families in `ALLOWED_FAMILIES` are ever
sent (owner, 28 Oct: SAES and ISO; API and ASME are on hold until the owner confirms the licence).

WHAT COMES OUT: one draft per standard, JSON + CSV, in a folder OUTSIDE the repository (the files hold clause
quotes - they belong in the mirror, never in git). Every file names the pump form it was read against (the
sha of #1352's head), the model, the prompt version, the USD spent, and whether the run completed or
`stopped at cap`. The review reads only the "yes" + verified rows of those files, only when
`standards_converter_dir` is set (empty by default = off), and only as a field mapping that rides
`comparison.match_by_field_name`: it never carries a verdict by itself (NEEDS_ENGINEER_REVIEW).

Nothing here reads a datasheet, writes the database, or opens a socket: the provider does, behind its gates.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import (
    claude_approved,
    claude_spend,
    field_naming,
    field_vocabulary,
    rule_roles,
)
from .ai.json_reply import unfenced
from .reasoning_provider import ProviderRefused

#: Owner, 28 Oct 2026 (order 271.2): SAES and ISO text may go to the API. API and ASME: HOLD.
ALLOWED_FAMILIES = ("SAES", "ISO")
STEP_PREFIX = claude_spend.STANDARD_STEP_PREFIX
#: Where the model runs. "local" is the Mac's own engine (owner order of 28 Oct, order 277: no Claude API
#: for now); "claude" is the lane behind `claude_spend`, the approved-documents list and the egress flags.
LANE_CLAUDE, LANE_LOCAL = "claude", "local"
LANES = (LANE_LOCAL, LANE_CLAUDE)
PROMPT_VERSION = "o270-convert-v1"
STATUS = "draft"
#: Requirements per call.
BATCH = 12
#: Characters of a clause the model reads (and the quote is verified against).
TEXT_CHARS = 1200
APPLIES = ("yes", "no", "depends")
#: The comparator the model may answer, and the words of a quote that make each one true.
COMPARATORS = ("<=", ">=", "<", ">", "=")
_CUES = {
    "<=": (
        "not exceed",
        "not be more than",
        "not be greater than",
        "at most",
        "maximum",
        "max.",
        "max",
        "up to",
        "not above",
        "not higher than",
        "no more than",
        "not greater than",
        "<=",
        "\u2264",
    ),
    ">=": (
        "at least",
        "not less than",
        "not be less than",
        "minimum",
        "min.",
        "min",
        "no less than",
        "not below",
        "not lower than",
        "not fewer than",
        ">=",
        "\u2265",
    ),
    "<": ("less than", "below", "under", "lower than", "fewer than", "<"),
    ">": ("greater than", "more than", "above", "exceed", "higher than", "over", ">"),
    "=": ("equal", "shall be", "is", "are", "of", "="),
}
_CUE_LIST = sorted(
    ((cue, comp) for comp, cues in _CUES.items() for cue in cues),
    key=lambda c: -len(c[0]),
)
#: The reason an answer stays unproven (counts only; never text).
REASONS = (
    "applies_unreadable",
    "no_field",
    "quote_not_in_clause",
    "number_not_in_quote",
    "unit_not_in_quote",
    "unit_not_of_field",
    "field_not_in_quote",
    "comparator_not_in_quote",
    "condition_after_limit",
    "condition_not_in_clause",
    "reply_unreadable",
    "not_asked",
)
ENGINEER = "engineer, please look"
STOPPED_AT_CAP = "stopped at cap"


class FamilyNotAllowed(RuntimeError):
    """The standard's family is not on the allowed list, so nothing was sent."""


class NotStandardsText(RuntimeError):
    """A document that is not a company standard was offered to the converter."""


def family(label: str | None) -> str:
    """The leading letters of a standard's label: SAES-G-005 -> SAES, 'ISO 15156-3' -> ISO."""
    m = re.match(r"\s*([A-Za-z]+)", label or "")
    return m.group(1).upper() if m else ""


def require_family(label: str | None) -> None:
    if family(label) not in ALLOWED_FAMILIES:
        raise FamilyNotAllowed(
            f"{label!r}: the family {family(label) or '(none)'!r} is not on the allowed list "
            f"{ALLOWED_FAMILIES}; nothing was sent"
        )


def step_for(label: str) -> str:
    return f"{STEP_PREFIX}{label}"


# ----------------------------------------------------------------------------------------------- the ask


def system_text(equipment_type: str, dictionary: list[str]) -> str:
    """The stable block (cached): the instructions and the type's own numbered field list."""
    numbered = "\n".join(f"{n}: {name}" for n, name in enumerate(dictionary))
    return (
        f"You read sentences of an engineering STANDARD. For each item decide whether the sentence is a "
        f"requirement on a {equipment_type}, and if it states a numeric limit that a datasheet field of "
        f"a {equipment_type} can be compared with, say which one.\n"
        "Answer per item: i (the item number), applies (yes, no or depends), condition (the words that "
        "say when it applies, or null), field (ONE number from the list below, or null), comparator "
        "(<=, >=, <, > or =), limit (the number exactly as written in the sentence), unit (exactly as "
        "written), quote (the EXACT words of the sentence the check rests on, copied unchanged).\n"
        "Rules: choose a field only from the list; never invent a field, a number or a unit; the quote, "
        "the number and the unit must all appear in the sentence word for word; when the sentence has "
        "no numeric limit for one of these fields answer field null. Unproven is a good answer.\n"
        f"FIELDS OF THE {equipment_type.upper()} FORM:\n{numbered}"
    )


SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "applies": {"type": "string", "enum": list(APPLIES)},
                    "condition": {"type": ["string", "null"]},
                    "field": {"type": ["integer", "null"]},
                    "comparator": {"type": ["string", "null"]},
                    "limit": {"type": ["string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "quote": {"type": ["string", "null"]},
                },
                "required": ["i", "applies"],
            },
        }
    },
    "required": ["checks"],
}


def requirements_of(conn, document_id: str) -> list[dict]:
    """The stored requirements of ONE company standard: the only text the converter ever sends."""
    role = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not role or role["document_role"] != "COMPANY_STANDARD":
        raise NotStandardsText(
            f"document {document_id} is not classified COMPANY_STANDARD"
        )
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, standard_document_id, clause, requirement_type, requirement_text, raw_value, raw_unit,"
            " unit FROM standard_requirements WHERE standard_document_id = ? AND superseded_at IS NULL"
            " AND requirement_text IS NOT NULL AND TRIM(requirement_text) <> '' ORDER BY id",
            (document_id,),
        )
    ]


def _text(row: dict) -> str:
    return " ".join((row.get("requirement_text") or "").split())[:TEXT_CHARS]


def packet(batch: list[dict], system: str, step: str):
    from .reasoning_provider import Packet

    items = [
        {"i": n, "clause": r.get("clause") or "", "text": _text(r)}
        for n, r in enumerate(batch)
    ]
    return Packet(
        prompt=json.dumps({"items": items}, ensure_ascii=False),
        num_ctx=16384,
        num_predict=250 * len(batch) + 300,
        json_schema=SCHEMA,
        system=system,
        step=step,
        prompt_version=PROMPT_VERSION,
    )


# ------------------------------------------------------------------------------------------ the proof


def _fold(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _has_figure(quote: str, figure: str) -> bool:
    return bool(
        re.search(
            r"(?<![\w.])" + re.escape(figure.strip().lower()) + r"(?![\w])",
            _fold(quote),
        )
    )


def _has_unit(quote: str, unit: str) -> bool:
    u = _fold(unit)
    if not u:
        return False
    return bool(
        re.search(r"(?<![a-z0-9])" + re.escape(u) + r"(?![a-z0-9])", _fold(quote))
    )


def _names_field(quote: str, name: str) -> bool:
    """Every content word of the field's canonical name is in the quote (canonical spelling)."""
    wanted = [
        w for w in field_vocabulary._tokens(name) if w not in field_naming._QUALIFIERS
    ]
    have = set(field_vocabulary._tokens(quote))
    return bool(wanted) and all(w in have for w in wanted)


def comparators_said(quote: str) -> set[str]:
    """The comparators a quote's own words say. Longest phrase first, each match blanked out, so
    "shall not exceed" says <= and not also >. A quote that says more than one (a range: "minimum ...
    maximum ...") is ambiguous and proves none."""
    q = " " + _fold(quote) + " "
    said: set[str] = set()
    for cue, comp in _CUE_LIST:
        if cue[0].isalpha():
            pattern = r"(?<![a-z])" + re.escape(cue) + r"(?![a-z])"
        else:
            pattern = re.escape(cue)
        if re.search(pattern, q):
            said.add(comp)
            q = re.sub(pattern, " ", q)
    if said - {"="}:
        said.discard(
            "="
        )  # "is" / "of" are only the weak cue: any real comparator outranks them
    return said


#: What may follow a limit's number and unit and leave it unconditional: nothing, a bracketed unit or
#: conversion, or WHERE it is measured. Anything else ("for services other than sour service", "for pumps
#: of the vertical type") is a scope: the sentence does not state an unconditional limit (s3, #1412).
_LOCATION_STARTS = ("at ", "measured at ")


def limit_closes_sentence(sentence: str, quote: str, limit: str, unit: str) -> bool:
    """Does the sentence end right after the limit's number and unit (a bracketed conversion and a
    measuring location aside)? A condition written AFTER the number is not caught by the leading-condition
    tests of `ai_requirements.verify_proposal`, so a scope that follows the limit must refuse the row here.
    False when the number and unit do not stand together in the quote (nothing to measure the tail from)."""
    s, q = _fold(sentence), _fold(quote)
    at = s.find(q)
    found = re.search(
        r"(?<![\w.])"
        + re.escape(limit.strip().lower())
        + r"\s*"
        + re.escape(unit.strip().lower())
        + r"(?![a-z0-9])",
        q,
    )
    if at < 0 or found is None:
        return False
    tail = re.split(r"[.;](?:\s|$)", s[at + found.end() :], maxsplit=1)[0]
    tail = re.sub(r"\([^)]*\)", " ", tail).strip(" ,:-")
    return not tail or tail.startswith(_LOCATION_STARTS)


def _comparator_says(quote: str, comparator: str) -> bool:
    return comparators_said(quote) == {comparator}


@dataclass
class Check:
    """The verified part of an answer, in the form's own terms."""

    field: str
    comparator: str
    limit: str
    unit: str
    quote: str


def verify(
    answer: dict,
    row: dict,
    dictionary: list[str],
    roles: dict[str, str],
    families: dict[str, tuple[str, ...]],
) -> tuple[str, str | None, Check | None]:
    """(status, reason, check) for ONE answer about ONE stored requirement. Code decides; the answer is a
    claim. status: 'verified' (check set), 'unproven' (reason set) or 'not_applicable' (the model's claim)."""
    applies = str(answer.get("applies") or "").lower()
    if applies not in APPLIES:
        return "unproven", "applies_unreadable", None
    if applies == "no":
        return "not_applicable", None, None
    text = _fold(_text(row))
    condition = (answer.get("condition") or "").strip()
    if applies == "depends" and (not condition or _fold(condition) not in text):
        return "unproven", "condition_not_in_clause", None
    idx = answer.get("field")
    if (
        isinstance(idx, bool)
        or not isinstance(idx, int)
        or not 0 <= idx < len(dictionary)
    ):
        return "unproven", "no_field", None
    name = dictionary[idx]
    quote = " ".join(str(answer.get("quote") or "").split())
    if len(quote) < 8 or _fold(quote) not in text:
        return "unproven", "quote_not_in_clause", None
    limit, unit = (
        str(answer.get("limit") or "").strip(),
        str(answer.get("unit") or "").strip(),
    )
    if not limit or not _has_figure(quote, limit):
        return "unproven", "number_not_in_quote", None
    if not _has_unit(quote, unit):
        return "unproven", "unit_not_in_quote", None
    if not limit_closes_sentence(text, quote, limit, unit):
        return "unproven", "condition_after_limit", None
    if not set(families.get(name, ())) & field_vocabulary._unit_families(unit):
        return "unproven", "unit_not_of_field", None
    if not _names_field(quote, name):
        return "unproven", "field_not_in_quote", None
    comparator = str(answer.get("comparator") or "").strip()
    if comparator not in COMPARATORS or not _comparator_says(quote, comparator):
        return "unproven", "comparator_not_in_quote", None
    return "verified", None, Check(roles[name], comparator, limit, unit, quote)


# ------------------------------------------------------------------------------------------- the run


@dataclass
class Result:
    standard: str
    equipment_type: str
    rows: list[dict] = field(default_factory=list)
    stopped_at_cap: bool = False
    lane: str = LANE_CLAUDE
    #: Why a call was refused (not a USD cap): a code, never text. None = nothing was refused.
    refused: str | None = None
    model: str | None = None
    usd: float = 0.0
    calls: int = 0
    unreadable_batches: int = 0

    def counts(self) -> dict[str, int]:
        out = {
            "requirements": len(self.rows),
            "verified": 0,
            "unproven": 0,
            "not_applicable": 0,
            "not_asked": 0,
        }
        for r in self.rows:
            out[r["status"]] = out.get(r["status"], 0) + 1
        out["applies_yes"] = sum(
            1 for r in self.rows if r["status"] == "verified" and r["applies"] == "yes"
        )
        return out


def _row(
    src: dict,
    status: str,
    reason: str | None,
    applies: str | None,
    condition: str | None,
    check: Check | None,
) -> dict:
    return {
        "clause": src.get("clause"),
        "requirement_type": src.get("requirement_type"),
        "text_sha256": rule_roles.text_hash(src.get("requirement_text")),
        "applies": applies,
        "condition": condition,
        "status": status,
        "reason": reason,
        "field": check.field if check else None,
        "comparator": check.comparator if check else None,
        "limit": check.limit if check else None,
        "unit": check.unit if check else None,
        "quote": check.quote if check else None,
        "note": ENGINEER if status in ("unproven", "not_asked") else None,
    }


def _not_asked(src: dict, why: str) -> dict:
    return _row(src, "not_asked", f"not asked: {why}", None, None, None)


def _stop_reason(exc: BaseException, out: Result) -> str:
    """Why a call stopped the run, recorded on `out` and as the words of every row not asked. A USD cap is
    "stopped at cap"; a refusal before the call left (document not on the list, egress off) and a failed call
    are named, never called a cap. Names only: no prompt text is in any of them."""
    if isinstance(exc, claude_spend.DocumentNotApproved):
        out.refused = exc.code
        return f"refused: {exc.code}"
    if isinstance(exc, claude_spend.BudgetExceeded):
        out.stopped_at_cap = True
        return STOPPED_AT_CAP
    out.refused = type(exc).__name__
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def _read_batch(
    response, chunk: list[dict], dictionary, roles, families, out: Result
) -> list[dict]:
    """The rows of one answered batch: every answer proven by code, an unreadable reply unproven."""
    answers = _answers(response, len(chunk))
    if answers is None:
        out.unreadable_batches += 1
        return [
            _row(r, "unproven", "reply_unreadable", None, None, None) for r in chunk
        ]
    rows = []
    for n, src in enumerate(chunk):
        got = answers.get(n)
        if got is None:
            rows.append(_row(src, "unproven", "applies_unreadable", None, None, None))
            continue
        status, reason, check = verify(got, src, dictionary, roles, families)
        applies = str(got.get("applies") or "").lower() or None
        condition = (got.get("condition") or None) if status != "unproven" else None
        rows.append(_row(src, status, reason, applies, condition, check))
    return rows


def convert(
    conn,
    document_id: str,
    standard: str,
    equipment_type: str,
    provider,
    *,
    limit: int | None = None,
    batch: int | None = None,
    lane: str = LANE_CLAUDE,
) -> Result:
    """Convert every stored requirement of one standard.

    LANE "claude": the family must be allowed (refused BEFORE anything is built), each call declares the
    standard to the approved-documents list and is reserved in `claude_spend`. LANE "local" (owner, 28 Oct:
    no Claude API for now): `provider` is the local engine's; nothing here touches `claude_spend`, the
    approved-documents list or `reader_transport`. Either way a refused, failed or capped call stops the run:
    what was finished is kept, the rest is "not asked: <why>", and the run NEVER retries into another lane."""
    claude = lane == LANE_CLAUDE
    if claude:
        require_family(standard)
    rows = requirements_of(conn, document_id)
    if limit:
        rows = rows[:limit]
    dictionary, roles, families = rule_roles.form(equipment_type)
    step = step_for(standard)
    system = system_text(equipment_type, dictionary)
    out = Result(
        standard,
        equipment_type,
        lane=lane,
        model=getattr(provider, "requested_model", None),
    )
    before = claude_spend.spent(step) if claude else 0.0
    size, why_not = batch or BATCH, None
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        if why_not is not None:
            out.rows += [_not_asked(r, why_not) for r in chunk]
            continue
        try:
            if claude:
                with claude_approved.carrying({document_id}):
                    response = provider.reason(packet(chunk, system, step))
            else:
                response = provider.reason(packet(chunk, system, step))
        except (claude_spend.StopRun, ProviderRefused) as exc:
            why_not = _stop_reason(exc, out)
            out.rows += [_not_asked(r, why_not) for r in chunk]
            continue
        out.calls += 1
        out.model = getattr(response, "model_tag", None) or out.model
        out.rows += _read_batch(response, chunk, dictionary, roles, families, out)
    out.usd = round(claude_spend.spent(step) - before, 6) if claude else 0.0
    return out


def _answers(response, size: int) -> dict[int, dict] | None:
    """{item number: answer} from a reply, or None when the reply cannot be read (truncated, invalid)."""
    if getattr(response, "schema_errors", ()) or getattr(response, "truncated", False):
        return None
    try:
        data = json.loads(unfenced(response.text))
    except (ValueError, TypeError):
        return None
    items = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    out: dict[int, dict] = {}
    for it in items:
        if (
            isinstance(it, dict)
            and isinstance(it.get("i"), int)
            and 0 <= it["i"] < size
        ):
            out.setdefault(it["i"], it)
    return out


# --------------------------------------------------------------------------------------------- the files

#: A short or long hex sha: the pump form's source is pinned in every file.
_SHA = re.compile(r"[0-9a-f]{7,40}")
REPO = Path(__file__).resolve().parents[2]
COLUMNS = (
    "clause",
    "requirement_type",
    "text_sha256",
    "applies",
    "condition",
    "status",
    "reason",
    "field",
    "comparator",
    "limit",
    "unit",
    "quote",
    "note",
)


def refuse_out_dir(out_dir: Path) -> Path:
    """The folder for the drafts: never inside the repository (the files hold clause quotes)."""
    resolved = Path(out_dir).expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise ValueError(
            f"refusing: {resolved} is inside the repository; the drafts belong in the mirror"
        )
    return resolved


def file_stem(result: Result) -> str:
    return f"{rule_roles.slug(result.equipment_type)}.{re.sub(r'[^A-Za-z0-9]+', '_', result.standard).strip('_')}"


def write(
    result: Result, out_dir: Path, *, form_sha: str, form_source: str = "#1352"
) -> dict[str, Path]:
    """Write `<type>.<standard>.json` and `.csv` into `out_dir` (outside the repo). `form_sha` is the
    head of the pump form's PR as read: a later form change then shows up as a different file."""
    sha = (form_sha or "").strip().lower()
    if not _SHA.fullmatch(sha):
        raise ValueError(
            "form_sha must be the hex sha of the form's source (a short or full git sha)"
        )
    folder = refuse_out_dir(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    body = {
        "_about": "Order 270.3: DRAFT checks converted from one standard by the cloud model, each proven by "
        "code against the stored clause. Unproven rows say 'engineer, please look' and carry no limit. "
        "Holds clause quotes: never commit it.",
        "converter": True,
        "status": STATUS,
        "equipment_type": result.equipment_type,
        "standard": result.standard,
        "form_source": {"ref": form_source, "sha": sha},
        "lane": result.lane,
        "model": result.model,
        "prompt_version": PROMPT_VERSION,
        "run": STOPPED_AT_CAP
        if result.stopped_at_cap
        else (f"refused: {result.refused}" if result.refused else "complete"),
        "usd_spent": result.usd,
        "calls": result.calls,
        "counts": result.counts(),
        "entries": result.rows,
    }
    stem = file_stem(result)
    jpath, cpath = folder / f"{stem}.json", folder / f"{stem}.csv"
    jpath.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with cpath.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in result.rows:
            w.writerow({k: r.get(k) for k in COLUMNS})
    return {"json": jpath, "csv": cpath}


# ------------------------------------------------------------------------------- the review's reading


def reviewed_entries(files: list[Path] | None = None) -> list[tuple[str, dict]]:
    """[(equipment type, entry)] of the VERIFIED rows whose answer was 'yes', from the converter's drafts
    in `settings.standards_converter_dir` (or the given files). Nothing when the setting is empty."""
    from .config import settings

    if files is None:
        folder = (settings.standards_converter_dir or "").strip()
        if not folder or not Path(folder).is_dir():
            return []
        files = sorted(Path(folder).glob("*.json"))
    out: list[tuple[str, dict]] = []
    for f in files:
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            not isinstance(data, dict)
            or data.get("converter") is not True
            or data.get("status") != STATUS
        ):
            continue
        for e in data.get("entries", []):
            if (
                e.get("status") == "verified"
                and e.get("applies") == "yes"
                and e.get("field")
                and e.get("text_sha256")
            ):
                out.append(
                    (data["equipment_type"], {**e, "standard": data.get("standard")})
                )
    return out
