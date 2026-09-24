"""Extraction tripwire: field-by-field precision, recall and F1 against a gold sheet.

WHY THIS EXISTS. Phase 0.1 of the master order, and Feature 1 section 6.5 is
built on it. Nothing in this repo currently measures what the extractor gets
right on a datasheet - only that it produced rows. This harness records what
extraction does TODAY and fails the build when a later run does worse on the
same gold sheet. It does not improve extraction and must never be used to tune
it.

WHAT IS SCORED. Either the system's stored extraction (`submittal_facts`, read
ONLY, keyed by `submittal_document_id`) or a model's raw output before it is
ever stored (`--rows <path>`, a JSON list of `ExtractedRow` objects as
`backend/app/extraction_schema.py` defines them: label, column_header, value,
unit, is_blank, page, source_text). Section 6.5 needs the second one, because
by the time a row reaches the database it has already survived a filter.

GOLD SHEETS, TWO SHAPES, DETECTED FROM THE HEADER - never from a flag the
caller has to remember getting right:

    page,field_name,value,unit,blank_marker,equipment_tag,note   (M03-FIELDS)
    submittal,equipment_tag,field,value,unit,page,standard,...   (PAIRS-*)

Lines beginning `#` are the sheet's own provenance and counting rules and are
skipped.

THE SCORING RULES BELOW ARE OWNER DECISIONS (register 10.09), not defaults.

  1. BOTH DENOMINATORS, ALWAYS, NEVER ONE ALONE.

       filled    - gold rows that carry a value. This is the HEADLINE F1: can
                   the extractor read the values that are printed?
       all_slots - every gold row, filled and blank. This measures something
                   different and equally real: whether a blank slot is
                   recognised AS a blank rather than invented or skipped.

     A filled-only figure flatters an extractor that ignores blanks; an
     all-slots figure flatters one that calls everything blank. Quoting either
     alone is the defect this rule exists to prevent, so both are computed,
     both are printed, and the regression gate fails on a drop in EITHER.

  2. NOTES PAGES ARE NOT FIELD PAGES. A page of prose notes prints no
     label/value slots, so scoring it as fields measures the wrong thing. Those
     rows are EXCLUDED from both field denominators and reported separately as
     `notes`, with their own precision/recall/F1 that nothing gates on.

     Which pages those are is read FROM THE SHEET, not hard-coded per document:
     a gold row is a notes row when its `note` column says so in the sheet's
     own words (`NOTES page`). `--notes-pages` overrides for a sheet that does
     not say. For `gold/M03-FIELDS.csv` this selects page 7 - all 35 rows - and
     it selects them because the sheet declares it, not because this script
     knows about that document.

  3. FIELD NAMES ARE MATCHED TYPO-TOLERANTLY, and the normalisation is
     deterministic, documented here and document-independent. NO word lists, no
     per-document rules:

       NFKD, casefold, every character that is not a letter or a digit becomes
       a space, runs of space collapse, ends stripped.

     That alone absorbs case, punctuation, colons, spacing and unicode dashes.
     The sheet preserves the document's own typos verbatim, so an extractor
     that corrects them must not be scored wrong; for the rest a similarity
     fallback applies:

       * an exact match on the normalised form ALWAYS wins, and is tried for
         every row before any fuzzy match is considered;
       * otherwise `difflib.SequenceMatcher` ratio >= 0.93 (SIMILARITY);
       * AND the best candidate must beat the runner-up by >= 0.03 (MARGIN).

     WHY A MARGIN AND NOT JUST A HIGHER THRESHOLD. Measured on this sheet's 385
     distinct names, genuinely DIFFERENT fields reach 0.974 similarity
     ("number per thrust bearing ACTIVE side" vs "... INACTIVE side"), 0.946,
     0.939, and 39 pairs sit above 0.85. No threshold can both admit a typo and
     reject those. A one-character typo in a name of this length scores ~0.96,
     so 0.93 is permissive for typos; what stops "active" being scored as
     "inactive" is that an exact match wins first, and that a name sitting
     near-equally close to two gold names is left UNMATCHED and reported as
     `ambiguous_name` rather than resolved by a coin toss. Every fuzzy match
     made is listed in the output so a reader can overrule it.

     Matching is ONE-TO-ONE WITHIN A PAGE, greedy by descending score. Within a
     page because a gold sheet that names the page is asking for the field to
     be found there; one-to-one because a multi-column field prints the same
     label several times and one extracted row may not satisfy two slots.

  4. VALUES MATCH EXACTLY, after the PROJECT'S OWN unit normalisation - this
     script does not carry a second unit parser. `backend/app/claims.py`
     `normalise(value, unit)` gives a Measurement; when both sides yield a
     `normalized_value` in the same `normalized_unit` they are compared
     numerically (1e-9 relative, float noise and nothing else). When either
     side has no known unit, the folded value strings must be identical, with
     `parse_value` allowing "2.0" to equal "2". Two KNOWN but DIFFERENT
     dimensions never match.

  5. A BLANK SLOT IS MATCHED ON is_blank / blank_marker, NEVER ON VALUE. Both
     sides blank is a match. A differing printed marker is recorded as
     `blank_marker_mismatch` and reported, but is NOT scored as a failure: the
     marker is what the sheet drew in an empty cell, and the claim under test
     is that the slot is empty.

  6. UNSURE ROWS ARE COUNTED IN, AND TAGGED. 51 rows of `M03-FIELDS.csv` carry
     UNSURE in `note` - the preparer's own doubt about whether an engineer
     would call it a field. They are NOT dropped: dropping the hard rows makes
     the score a statement about the easy ones. They are INCLUDED in the
     headline denominators, every miss or false extraction touching one is
     tagged `unsure: true`, and a second set of figures EXCLUDING them is
     reported beside the headline so the owner can see how much of the result
     rests on rows the preparer was unsure of. Nothing gates on the
     UNSURE-excluded figures.

TP / FP / FN. A true positive is a matched pair whose VALUE also agrees (or
both blank). A matched pair whose value disagrees is BOTH a miss and a false
extraction - it is counted once in each, because the extractor both failed to
produce the gold value and produced one that is not it.

    precision = TP / extracted rows in scope     recall = TP / gold rows in scope

With zero extracted rows precision is UNDEFINED; it is reported as 0.0 with the
denominator printed beside it, never as a silent 1.0.

REGRESSION. Compared against the newest previous
`.cowork/eval/extraction-<doc>-*.json` by mtime, and ONLY against one whose
`gold_sha256` matches. A different gold set is INCOMPARABLE, not a regression:
the script says so and exits 0. Otherwise any real decrease in `filled` F1 or
`all_slots` F1 - beyond 1e-9 - exits 1 naming the metric and the drop.

PRIVACY. Read-only throughout: `file:...?mode=ro`. Output goes to
`.cowork/eval/` (or `--out-dir`, which must be another gitignored place such
as the main checkout's `.cowork/eval/`) and nowhere else, because it carries
verbatim client field names and values. No network.

    python scripts/eval_extraction.py --doc doc_da3fcc0aaacc --gold gold/M03-FIELDS.csv
    python scripts/eval_extraction.py --doc <pressure-vessel-datasheet-doc-id> --gold gold/PAIRS-TEMPLATE.csv
    python scripts/eval_extraction.py --doc X --gold Y --rows model_output.json
    python scripts/eval_extraction.py --doc X --gold Y --db <copy.sqlite> --out-dir <dir>

BREAKDOWN (#179). Beside the P/R/F1 the output carries `breakdown`: filled
slots recovered / wrong value / not extracted, blank-by-design slots, and
extracted rows split into matched / DUPLICATE / SPURIOUS - never one number.
AN EMPTY DENOMINATOR IS A HARNESS FAILURE: no gold rows in scope, no filled
gold rows, or (unless --allow-empty-extraction) no extracted rows exits 2 and
writes nothing.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import getpass
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app.claims import normalise, parse_value, unit_dimension  # noqa: E402
from app.config import settings  # noqa: E402

#: Gitignored (`.cowork/*`). Client-derived output lives here and nowhere else.
OUT_DIR = REPO / ".cowork" / "eval"

HEADER = "owner-reviewed, internally measured, NOT engineer-verified"

#: Rule 3. Not a knob to be widened when a run scores badly.
SIMILARITY = 0.93
MARGIN = 0.03

#: Rule 4 / regression. Float comparison noise only.
TOLERANCE = 1e-9

#: Rule 2. The phrase the gold sheet uses about itself.
NOTES_PHRASE = re.compile(r"\bnotes page\b", re.IGNORECASE)

#: Rule 6.
UNSURE_PHRASE = re.compile(r"\bUNSURE\b")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def git_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip() or "unknown"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_name(text: str) -> str:
    """Rule 3's normalisation, in full. Deterministic, no lists, no per-document
    knowledge: NFKD, casefold, non-alphanumeric -> space, collapse, strip."""
    folded = unicodedata.normalize("NFKD", text or "").casefold()
    return " ".join(_NON_ALNUM.sub(" ", folded).split())


def fold_value(text: str) -> str:
    """For the string fallback in rule 4. Case and spacing only - NOT the
    name normalisation: punctuation carries meaning in a value ("1.114",
    "A/B", "6.2.3") and must not be dissolved into spaces."""
    return " ".join((text or "").casefold().split())


# ------------------------------------------------------------------ gold sheets
def _rows_of_csv(path: Path) -> list[dict]:
    """Data rows. A `#` line is the sheet's provenance or its counting rules and
    is not a row; it is dropped before the reader sees it so a comment can never
    be scored as a field."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        body = [line for line in fh if not line.lstrip().startswith("#")]
    return list(csv.DictReader(body))


def load_gold(path: Path) -> tuple[list[dict], str]:
    """(rows, shape). The shape is read off the header, not passed in."""
    raw = _rows_of_csv(path)
    if not raw:
        return [], "empty"
    columns = set(raw[0].keys())
    if "field_name" in columns:
        shape = "fields"
        key_name, key_note = "field_name", "note"
    elif "field" in columns:
        shape = "pairs"
        key_name, key_note = "field", "notes"
    else:
        raise SystemExit(
            f"{path.name}: header has neither `field_name` nor `field`; "
            "this is not a gold sheet this harness knows how to read."
        )

    rows = []
    for index, row in enumerate(raw):
        page = (row.get("page") or "").strip()
        note = (row.get(key_note) or "").strip()
        rows.append({
            "index": index,
            "page": int(page) if page.isdigit() else None,
            "field_name": (row.get(key_name) or "").strip(),
            "value": (row.get("value") or "").strip(),
            "unit": (row.get("unit") or "").strip(),
            "blank_marker": (row.get("blank_marker") or "").strip(),
            "equipment_tag": (row.get("equipment_tag") or "").strip(),
            "note": note,
            "unsure": bool(UNSURE_PHRASE.search(note)),
            "declares_notes_page": bool(NOTES_PHRASE.search(note)),
        })
    for row in rows:
        row["is_blank"] = not row["value"]
    return rows, shape


def notes_pages(gold: list[dict], override: list[int] | None) -> set[int]:
    """Rule 2: which pages are prose, read from the sheet's own `note` text."""
    if override is not None:
        return set(override)
    return {r["page"] for r in gold if r["declares_notes_page"] and r["page"] is not None}


# ------------------------------------------------------------------ extraction
def open_db_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else settings.db_path
    if not path.exists():
        # sqlite would CREATE an empty file here and the run would then score
        # zero rows - an empty denominator dressed as a result.
        raise HarnessFailure(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def facts_from_db(conn: sqlite3.Connection, doc_id: str) -> list[dict]:
    # CURRENT FACTS ONLY (#193, honesty audit 52): a re-read supersedes old
    # rows (ADR-0024) instead of deleting them; scoring them too would count
    # every re-read field twice. A copy made before the column existed has
    # no superseded rows to skip.
    current = (" AND superseded_at IS NULL"
               if "superseded_at" in {r[1] for r in conn.execute(
                   "PRAGMA table_info(submittal_facts)")} else "")
    rows = conn.execute(
        "SELECT field_name, field_label, field_value, unit, page, raw_value, "
        "       raw_unit, is_blank, blank_marker, equipment_tag "
        "FROM submittal_facts WHERE submittal_document_id = ? " + current +
        " ORDER BY page, field_name",
        (doc_id,),
    ).fetchall()
    out = []
    for index, r in enumerate(rows):
        # raw_value/raw_unit are what was printed; field_value/unit are the
        # pipeline's tidied copy. Prefer the raw pair - the gold sheet records
        # the page as printed, so that is the like-for-like comparison.
        out.append({
            "index": index,
            # THE PRINTED LABEL, like for like with a key that records each
            # field as printed (B4). The product's `field_name` drops clause
            # references ("casing type"), so scoring it against the printed
            # "CASING TYPE: (6.3.10)" counted a correctly read field as missed.
            "field_name": (r["field_label"] or r["field_name"] or "").strip(),
            "value": (r["raw_value"] or r["field_value"] or "").strip(),
            "unit": (r["raw_unit"] or r["unit"] or "").strip(),
            "page": r["page"],
            "is_blank": bool(r["is_blank"]),
            "blank_marker": (r["blank_marker"] or "").strip(),
            "equipment_tag": (r["equipment_tag"] or "").strip(),
            "source_text": "",
        })
    return out


def rows_from_json(path: Path) -> list[dict]:
    """A model's raw output, before anything stores it - section 6.5's case.

    Field names are `ExtractedRow`'s: label, column_header, value, unit,
    is_blank, page, source_text. `column_header` is the scoping column and is
    appended to the label, because on a multi-column datasheet "Rated flow" and
    "Normal flow" are different slots and the gold sheet records them as
    different field names.
    """
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict):
        parsed = parsed.get("rows", parsed.get("values", parsed))
    if not isinstance(parsed, list):
        raise SystemExit(f"{path.name}: expected a JSON list of ExtractedRow objects.")
    out = []
    for index, row in enumerate(parsed):
        if not isinstance(row, dict):
            raise SystemExit(f"{path.name}: row {index} is not an object.")
        label = (row.get("label") or "").strip()
        column = (row.get("column_header") or "").strip()
        is_blank = bool(row.get("is_blank"))
        value = (row.get("value") or "").strip()
        out.append({
            "index": index,
            "field_name": f"{label} {column}".strip() if column else label,
            # An ExtractedRow has no blank_marker field: when it says the slot
            # is blank, the marker IS what it read there.
            "value": "" if is_blank else value,
            "unit": (row.get("unit") or "").strip(),
            "page": row.get("page"),
            "is_blank": is_blank,
            "blank_marker": value if is_blank else "",
            "equipment_tag": "",
            "source_text": (row.get("source_text") or "").strip(),
        })
    return out


# ------------------------------------------------------------------ matching
def match_page(gold: list[dict], got: list[dict]) -> tuple[list[tuple], list[dict], list[dict], list[dict]]:
    """One-to-one within one page. Exact normalised names first, then fuzzy.

    Returns (pairs, unmatched_gold, unmatched_got, fuzzy_log). An extracted row
    that is near-equally close to two gold names is left unmatched and logged
    as `ambiguous_name` - see rule 3.
    """
    gold_left = list(gold)
    got_left = list(got)
    pairs: list[tuple] = []
    fuzzy_log: list[dict] = []

    # Pass 1: exact on the normalised form, in order, one-to-one.
    by_name: dict[str, list[dict]] = {}
    for g in gold_left:
        by_name.setdefault(norm_name(g["field_name"]), []).append(g)
    still: list[dict] = []
    for e in got_left:
        bucket = by_name.get(norm_name(e["field_name"]))
        if bucket:
            g = bucket.pop(0)
            pairs.append((g, e, 1.0))
        else:
            still.append(e)
    gold_left = [g for bucket in by_name.values() for g in bucket]
    got_left = still

    # Pass 2: fuzzy, greedy by descending score, with the ambiguity margin.
    scored = []
    for e in got_left:
        en = norm_name(e["field_name"])
        ranked = sorted(
            ((difflib.SequenceMatcher(None, en, norm_name(g["field_name"])).ratio(), g)
             for g in gold_left),
            key=lambda pair: pair[0], reverse=True,
        )
        if not ranked:
            continue
        best, g = ranked[0]
        runner = ranked[1][0] if len(ranked) > 1 else 0.0
        if best < SIMILARITY:
            continue
        if best - runner < MARGIN:
            fuzzy_log.append({
                "outcome": "ambiguous_name",
                "extracted": e["field_name"], "page": e["page"],
                "best": g["field_name"], "score": round(best, 4),
                "runner_up": round(runner, 4),
            })
            continue
        scored.append((best, e, g))

    scored.sort(key=lambda t: t[0], reverse=True)
    taken_gold: set[int] = set()
    taken_got: set[int] = set()
    for score, e, g in scored:
        if id(g) in taken_gold or id(e) in taken_got:
            continue
        taken_gold.add(id(g))
        taken_got.add(id(e))
        pairs.append((g, e, score))
        fuzzy_log.append({
            "outcome": "fuzzy_name_match",
            "extracted": e["field_name"], "gold": g["field_name"],
            "page": e["page"], "score": round(score, 4),
        })

    return (
        pairs,
        [g for g in gold_left if id(g) not in taken_gold],
        [e for e in got_left if id(e) not in taken_got],
        fuzzy_log,
    )


def match_all(gold: list[dict], got: list[dict]) -> tuple[list[tuple], list[dict], list[dict], list[dict]]:
    pages = sorted({r["page"] for r in gold} | {r["page"] for r in got}, key=lambda p: (p is None, p))
    pairs, miss_gold, extra_got, fuzzy = [], [], [], []
    for page in pages:
        p, mg, eg, fz = match_page(
            [g for g in gold if g["page"] == page],
            [e for e in got if e["page"] == page],
        )
        pairs += p
        miss_gold += mg
        extra_got += eg
        fuzzy += fz
    return pairs, miss_gold, extra_got, fuzzy


# ------------------------------------------------------------------ value match
def values_agree(gold: dict, got: dict) -> tuple[bool, str]:
    """Rules 4 and 5. Returns (agree, why) - `why` names the comparison used so
    a disagreement can be read without re-running anything."""
    if gold["is_blank"] or got["is_blank"]:
        if gold["is_blank"] and got["is_blank"]:
            gm, em = fold_value(gold["blank_marker"]), fold_value(got["blank_marker"])
            if gm and em and gm != em:
                return True, f"blank_marker_mismatch:{gold['blank_marker']}|{got['blank_marker']}"
            return True, "both_blank"
        which = "gold" if gold["is_blank"] else "extracted"
        return False, f"blank_disagreement:only_{which}_says_blank"

    g = normalise(gold["value"], gold["unit"])
    e = normalise(got["value"], got["unit"])
    if g.normalized_value is not None and e.normalized_value is not None:
        if g.normalized_unit != e.normalized_unit:
            return False, f"unit_mismatch:{g.normalized_unit}|{e.normalized_unit}"
        scale = max(1.0, abs(g.normalized_value))
        if abs(g.normalized_value - e.normalized_value) <= TOLERANCE * scale:
            return True, f"normalised:{g.normalized_value:g} {g.normalized_unit}"
        return False, (f"value_mismatch:{g.normalized_value:g}|"
                       f"{e.normalized_value:g} {g.normalized_unit}")

    gd, ed = unit_dimension(gold["unit"]), unit_dimension(got["unit"])
    if gd and ed and gd != ed:
        return False, f"dimension_mismatch:{gd}|{ed}"
    if fold_value(gold["unit"]) != fold_value(got["unit"]):
        return False, f"unit_string_mismatch:{gold['unit']}|{got['unit']}"

    gv, ev = parse_value(gold["value"]), parse_value(got["value"])
    if gv is not None and ev is not None and abs(gv - ev) <= TOLERANCE * max(1.0, abs(gv)):
        return True, "numeric_no_unit"
    if fold_value(gold["value"]) == fold_value(got["value"]):
        return True, "string_exact"
    return False, "value_mismatch:string"


# ------------------------------------------------------------------ scoring
def score(gold: list[dict], got: list[dict], label: str) -> dict:
    """One scope: its pairs, its P/R/F1, every miss and every false extraction."""
    pairs, miss_gold, extra_got, fuzzy = match_all(gold, got)

    hits, wrong_value = [], []
    for g, e, name_score in pairs:
        agree, why = values_agree(g, e)
        record = {
            "page": g["page"], "gold_field": g["field_name"],
            "extracted_field": e["field_name"],
            "name_score": round(name_score, 4),
            "gold_value": g["value"], "gold_unit": g["unit"],
            "extracted_value": e["value"], "extracted_unit": e["unit"],
            "gold_blank_marker": g["blank_marker"],
            "extracted_blank_marker": e["blank_marker"],
            "why": why, "unsure": g["unsure"],
            "source_text": e["source_text"][:200],
        }
        (hits if agree else wrong_value).append(record)

    misses = [{
        "kind": "not_extracted", "page": g["page"], "gold_field": g["field_name"],
        "gold_value": g["value"], "gold_unit": g["unit"],
        "gold_blank_marker": g["blank_marker"], "unsure": g["unsure"],
        "source_text": "", "why": "no extracted row matched this slot on this page",
    } for g in miss_gold] + [{
        "kind": "wrong_value", "page": r["page"], "gold_field": r["gold_field"],
        "gold_value": r["gold_value"], "gold_unit": r["gold_unit"],
        "gold_blank_marker": r["gold_blank_marker"], "unsure": r["unsure"],
        "source_text": r["source_text"], "why": r["why"],
    } for r in wrong_value]

    falses = [{
        "kind": "not_in_gold", "page": e["page"], "extracted_field": e["field_name"],
        "extracted_value": e["value"], "extracted_unit": e["unit"],
        "extracted_blank_marker": e["blank_marker"],
        "source_text": e["source_text"][:200],
        "why": "no gold slot matched this row on this page",
    } for e in extra_got] + [{
        "kind": "wrong_value", "page": r["page"], "extracted_field": r["extracted_field"],
        "extracted_value": r["extracted_value"], "extracted_unit": r["extracted_unit"],
        "extracted_blank_marker": r["extracted_blank_marker"],
        "source_text": r["source_text"], "why": r["why"],
    } for r in wrong_value]

    tp = len(hits)
    precision = (tp / len(got)) if got else 0.0
    recall = (tp / len(gold)) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    marker_mismatches = [h for h in hits if h["why"].startswith("blank_marker_mismatch")]

    return {
        "scope": label,
        "gold_rows": len(gold),
        "extracted_rows": len(got),
        "true_positives": tp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "precision_denominator": len(got),
        "recall_denominator": len(gold),
        "precision_undefined": not got,
        "recall_undefined": not gold,
        "unsure_gold_rows": sum(1 for g in gold if g["unsure"]),
        "misses_on_unsure_rows": sum(1 for m in misses if m["unsure"]),
        # Rule 5: recorded, reported, NOT scored as a failure.
        "blank_marker_mismatches": marker_mismatches,
        "name_matching": fuzzy,
        "misses": misses,
        "false_extractions": falses,
    }


class HarnessFailure(RuntimeError):
    """A run that cannot produce a score. Never printed as F1 0.0000."""


def require_denominators(gold_fields: list[dict], got_fields: list[dict], *,
                         allow_empty_extraction: bool) -> None:
    """ISSUE #179: AN EMPTY DENOMINATOR IS A HARNESS FAILURE, NOT A SCORE.

    A gold sheet whose header parsed but whose rows did not, a notes-page
    override that swallowed every page, or a document id that matched no
    stored row all used to print `F1 0.0000` - indistinguishable from an
    extractor that genuinely read nothing right. Each is a broken RUN.

    Zero extracted rows CAN be a real result (the live table held no facts
    for one regression datasheet before #175), so that side alone may be
    waived - explicitly, by the caller, never by default.
    """
    # ONE CHECK, deliberately: an empty gold scope also has an empty FILLED
    # scope, so a separate "no rows at all" test was dead code (mutation M401
    # found it - no test could tell the two apart).
    if not any(not g["is_blank"] for g in gold_fields):
        raise HarnessFailure(
            f"filled gold denominator is 0 ({len(gold_fields)} gold field rows "
            "in scope, none filled - empty sheet, or every page excluded as a "
            "notes page). The headline figure would be meaningless.")
    if not got_fields and not allow_empty_extraction:
        raise HarnessFailure(
            "extracted denominator is 0: no extracted rows in scope for this "
            "document (wrong --doc, wrong --db, or an extraction that never "
            "ran). Pass --allow-empty-extraction only if an empty extraction "
            "is the result you mean to record.")


def _row_identity(row: dict) -> tuple:
    """What makes two EXTRACTED rows the same row: page, name, value, unit
    and blankness. Used only to tell a duplicate from a spurious row."""
    return (row["page"], norm_name(row["field_name"]), fold_value(row["value"]),
            fold_value(row["unit"]), bool(row["is_blank"]))


def breakdown(gold_fields: list[dict], got_fields: list[dict]) -> dict:
    """ISSUE #179: every gold slot and every extracted row, counted ONCE, in
    the category it belongs to - never folded into one number.

    Gold side: filled slots recovered / given a wrong value / not extracted;
    blank-by-design slots recovered as blank / given a value / not extracted.

    Extracted side: MATCHED to a gold slot (right or wrong value), a
    DUPLICATE of another extracted row (same page, name, value, unit), or
    SPURIOUS - no gold slot on that page. In a group of identical rows none
    of which matched a slot, one is spurious and the rest are duplicates: the
    extractor invented one thing and then repeated it.

    Name + value + unit + page are scored together - `match_all` pairs within
    a page and `values_agree` compares value and unit.
    """
    pairs, _miss_gold, extra_got, _fuzzy = match_all(gold_fields, got_fields)
    out = {
        "gold_filled": sum(1 for g in gold_fields if not g["is_blank"]),
        "gold_blank_by_design": sum(1 for g in gold_fields if g["is_blank"]),
        "filled_recovered": 0, "filled_wrong_value": 0, "filled_not_extracted": 0,
        "blank_by_design_recovered": 0, "blank_by_design_given_a_value": 0,
        "blank_by_design_not_extracted": 0,
        "extracted_total": len(got_fields),
        "extracted_matched": len(pairs),
        "extracted_matched_wrong_value": 0,
        "extracted_duplicates": 0, "extracted_spurious": 0,
    }
    matched_gold: set[int] = set()
    matched_identities: set[tuple] = set()
    for g, e, _score in pairs:
        matched_gold.add(id(g))
        matched_identities.add(_row_identity(e))
        agree, _why = values_agree(g, e)
        if not agree:
            out["extracted_matched_wrong_value"] += 1
        if g["is_blank"]:
            out["blank_by_design_recovered" if agree else "blank_by_design_given_a_value"] += 1
        else:
            out["filled_recovered" if agree else "filled_wrong_value"] += 1
    for g in gold_fields:
        if id(g) not in matched_gold:
            out["blank_by_design_not_extracted" if g["is_blank"] else "filled_not_extracted"] += 1

    spurious_seen: set[tuple] = set()
    for e in extra_got:
        identity = _row_identity(e)
        if identity in matched_identities or identity in spurious_seen:
            out["extracted_duplicates"] += 1
        else:
            spurious_seen.add(identity)
            out["extracted_spurious"] += 1
    return out


def headline(result: dict) -> str:
    note = ""
    if result["precision_undefined"]:
        note = "  (precision undefined: 0 extracted rows in scope, reported as 0.0)"
    return (f"{result['scope']:<26} P {result['precision']:.4f} "
            f"({result['true_positives']}/{result['precision_denominator']})  "
            f"R {result['recall']:.4f} "
            f"({result['true_positives']}/{result['recall_denominator']})  "
            f"F1 {result['f1']:.4f}{note}")


# ------------------------------------------------------------------ regression
def previous_run(out_dir: Path, doc_id: str, explicit: Path | None) -> dict | None:
    """The newest recorded run FOR THIS DOCUMENT, by mtime.

    Called before this run is written, so the output path either does not exist
    or still holds an earlier run. Two runs at one commit share a filename, so
    excluding by name would make a re-run compare against nothing.
    """
    if explicit is not None:
        return json.loads(explicit.read_text(encoding="utf-8"))
    if not out_dir.is_dir():
        return None
    files = list(out_dir.glob(f"extraction-{doc_id}-*.json"))
    if not files:
        return None
    return json.loads(max(files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"))


#: The two figures the gate is defined over - rule 1: never one alone.
GATED = ("filled", "all_slots")


def compare(current: dict, prior: dict | None) -> tuple[int, list[str]]:
    if prior is None:
        return 0, ["No previous run recorded for this document. This run is the baseline."]
    if prior.get("gold_sha256") != current["gold_sha256"]:
        return 0, [
            "INCOMPARABLE: the previous run used a different gold set "
            f"({str(prior.get('gold_sha256', '?'))[:12]} vs "
            f"{current['gold_sha256'][:12]}). A different gold set is not a "
            "regression. Exiting 0.",
        ]
    if prior.get("document_id") != current["document_id"]:
        return 0, [
            "INCOMPARABLE: the previous run scored a different document "
            f"({prior.get('document_id')} vs {current['document_id']}). Exiting 0.",
        ]
    lines = [f"Comparing against run {prior.get('git_commit')} of {prior.get('generated_at')}."]
    fell = []
    for scope in GATED:
        now = current["metrics"][scope]["f1"]
        before = (prior.get("metrics", {}).get(scope) or {}).get("f1")
        if before is None:
            lines.append(f"  {scope} F1: {now:.4f} (previous run did not record it)")
            continue
        delta = now - before
        lines.append(f"  {scope} F1: {before:.4f} -> {now:.4f} ({delta:+.4f})")
        if delta < -TOLERANCE:
            fell.append(f"{scope} F1 fell by {abs(delta):.4f} ({before:.4f} -> {now:.4f})")
    if fell:
        lines.append("REGRESSION: " + "; ".join(fell))
        return 1, lines
    lines.append("No regression.")
    return 0, lines


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc", required=True, help="document id, e.g. doc_da3fcc0aaacc")
    ap.add_argument("--gold", required=True, type=Path, help="the gold CSV")
    ap.add_argument(
        "--rows", type=Path, default=None,
        help="score this JSON list of ExtractedRow objects instead of the "
             "stored facts (section 6.5: a model's output before it is stored)",
    )
    ap.add_argument(
        "--previous", type=Path, default=None,
        help="compare against this exact earlier result file instead of the "
             "newest one for this document (for testing the regression gate)",
    )
    ap.add_argument(
        "--notes-pages", type=int, nargs="*", default=None,
        help="override rule 2: treat these pages as prose notes. By default the "
             "pages are read from the gold sheet's own `note` text.",
    )
    ap.add_argument(
        "--db", type=Path, default=None,
        help="score the submittal_facts of THIS database file (opened "
             "read-only) instead of settings.db_path - e.g. a disposable copy "
             "re-extracted by scripts/reextract_on_copy.py",
    )
    ap.add_argument(
        "--out-dir", type=Path, default=OUT_DIR,
        help="where the result JSON is written (default: <repo>/.cowork/eval, "
             "gitignored). From a git worktree, point this at the main "
             "checkout's .cowork/eval so runs are found by the regression gate.",
    )
    ap.add_argument(
        "--label", default="",
        help="appended to the output filename (letters, digits, '-', '_'), so "
             "two runs at one commit do not overwrite each other",
    )
    ap.add_argument(
        "--allow-empty-extraction", action="store_true",
        help="record a run with ZERO extracted rows as a result. Without this "
             "an empty extraction is a harness failure (exit 2).",
    )
    args = ap.parse_args()
    if args.label and not re.fullmatch(r"[A-Za-z0-9_-]+", args.label):
        ap.error("--label may contain only letters, digits, '-' and '_'")

    commit = git_commit()
    gold_sha = sha256_of(args.gold)
    gold, shape = load_gold(args.gold)
    prose = notes_pages(gold, args.notes_pages)

    try:
        if args.rows is not None:
            got = rows_from_json(args.rows)
            source = f"--rows {args.rows.name}"
        else:
            conn = open_db_readonly(args.db)
            try:
                got = facts_from_db(conn, args.doc)
            finally:
                conn.close()
            source = (f"submittal_facts of {args.doc}"
                      + (f" in {args.db.name}" if args.db is not None else ""))

        gold_fields = [g for g in gold if g["page"] not in prose]
        got_fields = [e for e in got if e["page"] not in prose]
        gold_notes = [g for g in gold if g["page"] in prose]
        got_notes = [e for e in got if e["page"] in prose]
        require_denominators(gold_fields, got_fields,
                             allow_empty_extraction=args.allow_empty_extraction)
    except HarnessFailure as exc:
        # Nothing is written: a failed run must not leave a score behind for
        # the regression gate to compare against.
        print(f"HARNESS FAILURE: {exc}", file=sys.stderr)
        return 2

    metrics = {
        # Rule 1, headline: can it read what is printed?
        "filled": score([g for g in gold_fields if not g["is_blank"]],
                        [e for e in got_fields if not e["is_blank"]], "filled"),
        # Rule 1, secondary: are blanks recognised as blanks?
        "all_slots": score(gold_fields, got_fields, "all_slots"),
        # Rule 6: the same two, without the rows the preparer was unsure of.
        "filled_excluding_unsure": score(
            [g for g in gold_fields if not g["is_blank"] and not g["unsure"]],
            [e for e in got_fields if not e["is_blank"]], "filled_excluding_unsure"),
        "all_slots_excluding_unsure": score(
            [g for g in gold_fields if not g["unsure"]], got_fields,
            "all_slots_excluding_unsure"),
        # Rule 2: reported, never gated.
        "notes": score(gold_notes, got_notes, "notes"),
    }

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    # Two runs at one commit (the live copy and a re-extracted copy, say)
    # would otherwise overwrite each other's evidence.
    suffix = f"-{args.label}" if args.label else ""
    out_path = out_dir / f"extraction-{args.doc}-{commit}{suffix}.json"

    payload = {
        "header": HEADER,
        "generated_by": getpass.getuser(),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": commit,
        "document_id": args.doc,
        "scored_source": source,
        "gold_csv": args.gold.name,
        "gold_shape": shape,
        "gold_sha256": gold_sha,
        "rules": {
            "name_normalisation": "NFKD, casefold, non-alphanumeric -> space, collapse",
            "name_similarity_threshold": SIMILARITY,
            "name_ambiguity_margin": MARGIN,
            "value_match": "exact after claims.normalise; 1e-9 relative on the normalised number",
            "blank_match": "is_blank / blank_marker, never value",
            "notes_pages": sorted(prose),
            "notes_pages_source": "gold `note` text" if args.notes_pages is None else "--notes-pages",
            "unsure_rows": "counted IN the headline, tagged, and reported again excluded",
            "gated_metrics": [f"{s} F1" for s in GATED],
        },
        "counts": {
            "gold_rows_total": len(gold),
            "gold_rows_filled": sum(1 for g in gold if not g["is_blank"]),
            "gold_rows_blank": sum(1 for g in gold if g["is_blank"]),
            "gold_rows_unsure": sum(1 for g in gold if g["unsure"]),
            "gold_rows_on_notes_pages": len(gold_notes),
            "extracted_rows_total": len(got),
            "extracted_rows_on_notes_pages": len(got_notes),
        },
        "metrics": metrics,
        # #179: every slot and every extracted row in exactly one category.
        "breakdown": breakdown(gold_fields, got_fields),
    }

    prior = previous_run(out_dir, args.doc, args.previous)
    code, lines = compare(payload, prior)
    payload["comparison"] = lines
    payload["regression"] = code != 0
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(HEADER)
    print(f"generated_by={payload['generated_by']} at={payload['generated_at']} "
          f"commit={commit} gold_sha256={gold_sha}")
    print(f"document={args.doc}  gold={args.gold.name} ({shape})  scored={source}")
    print(f"counts={json.dumps(payload['counts'])}")
    print(f"notes pages (rule 2, from {payload['rules']['notes_pages_source']}): "
          f"{sorted(prose) or 'none'}")
    for key in ("filled", "all_slots", "filled_excluding_unsure",
                "all_slots_excluding_unsure", "notes"):
        print(headline(metrics[key]))
    head = metrics["filled"]
    print(f"misses (filled): {len(head['misses'])}   "
          f"false extractions (filled): {len(head['false_extractions'])}   "
          f"of which on UNSURE gold rows: {head['misses_on_unsure_rows']}")
    print("breakdown (field pages only): " + json.dumps(payload["breakdown"]))
    print(f"written: {out_path}")
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
