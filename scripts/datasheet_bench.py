"""Score datasheet readers on the made-up datasheet benchmark.

    python scripts/datasheet_bench.py --reader rules
    python scripts/datasheet_bench.py --reader all-local
    python scripts/datasheet_bench.py --reader hybrid:claude --files ds02_psv_unruled.pdf

ONE ANSWER KEY, THE PRODUCTION PATH. The files and `answer_key.json` are
written by `scripts/make_datasheet_bench.py` into
`backend/tests/fixtures/synthetic/datasheets/`; every value is made up.

Every reader except `ai-only:*` runs `datasheet_offline.read_file`: the stages
a real upload runs (upload validation, extract, chunk, OCR when the project's
engine is here, `datasheets.extract_facts`) in a private throwaway database,
with the two switches set for the run and restored afterwards:

  rules           DATASHEET_OFFICE_INPUT off, DATASHEET_AI_READER off -
                  today's production. A workbook is stored and not indexed,
                  a Word file is refused at upload, exactly as production does.
  rules+office    office input on, AI off.
  hybrid:ollama   office input on, AI reader "ollama": rules and the local
                  model both read every page and `datasheet_ai.merge_readings`
                  merges them (agree / conflict for an engineer / AI-only kept
                  only on a quote proved on the page).
  hybrid:claude   the same with "claude": production's engine
                  (`datasheet_ai.model_call_for`), every call through
                  `claude_spend` (USD 5 per step / USD 20 total, checked before
                  a call leaves), charged to production's step. USD reported.
  ai-only:ollama  DIAGNOSIS ONLY: the AI page reader alone over
  ai-only:claude  `datasheet_inputs.page_texts` of every file type, no rules;
                  charged to the benchmark's own step `STEP`.
  hybrid:oracle   NOT AN AI. An upper-bound sanity check: the hybrid path with
                  a scripted stand-in that proposes exactly the key's facts,
                  quoted from the page text. Shows the ceiling the merge and
                  the gates allow, and that the pipes carry AI facts to storage.

  --reader all-local = rules, rules+office, hybrid:ollama, ai-only:ollama: no
  Claude call is ever built, nothing is spent.

WHAT A READER CANNOT READ IS A MISS, NOT A CRASH. A file refused at upload,
stored and never indexed, or a scan whose pages need OCR where the OCR engine
is not available (`ocr_unavailable`, never a silent 0) is reported with its
reason and every expected value on it counts against recall.
`read_file_with(reader, path)` is the one entry point.

Per reader the report gives recall, precision, wrong values, forbidden values
reported, conflicts flagged for an engineer (stored facts in state
`conflict`), model calls and USD (Claude); then one side-by-side table.

HOW A READING IS SCORED (`score_file`), per file:

  * Only VALUES are scored. A fact the reader marked blank ("By Vendor",
    "TBA", a drawn rule) states no value and is neither right nor wrong.
  * A reported value is CORRECT when its field names an expected field (case,
    punctuation and spacing folded; a table reader's "<row> - <column>" label
    read as the row; stop words, unit tokens and row numbers
    dropped; a few abbreviations expanded - `SYNONYMS`; or one of the key's
    `aliases`) AND its value is that field's: numbers equal after unit
    normalisation by `claims.normalise` (0.5% tolerance), or equal as printed
    with the same unit; text equal folded. Each expected answer is matched
    once; a second reading of an answer already matched is a DUPLICATE and
    not scored.
  * FORBIDDEN: a value reported for a field the key lists as printed with no
    value. WRONG VALUE: an expected field with a value that is not any of its
    answers. EXTRA: a field the key does not know. IGNORED: title-block
    fields (the key's `ignore`).
  * recall = correct / expected; precision = correct / reported, where
    reported = correct + wrong + forbidden + extra. A zero denominator gives
    None, printed "n/a" - never a percentage of nothing.

Reports go to `--out`, by default under `benchmarks/local/` (git-ignored):
they are measurements of one run, not source.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BENCH = BACKEND / "tests" / "fixtures" / "synthetic" / "datasheets"
KEY_PATH = BENCH / "answer_key.json"
DEFAULT_OUT_DIR = REPO / "benchmarks" / "local" / "datasheet_bench"
READERS = ("rules", "rules+office", "hybrid:ollama", "hybrid:claude",
           "ai-only:ollama", "ai-only:claude")
#: The `claude_spend` step the benchmark's Claude calls are charged to - its
#: own, so the per-step cap applies to the benchmark and the total cap still
#: sees every dollar.
STEP = "datasheet-bench"
UNSUPPORTED = "unsupported"

# ------------------------------------------------------------ the answer key


def load_key(path: Path = KEY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_text(path: Path) -> str:
    """The words a file carries, for the key-honesty check: a PDF's text
    layer, a workbook's cell values, a Word document's text runs."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf
        with pymupdf.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc)
    if suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        cells = [_cell_text(c) for ws in wb.worksheets for r in ws.iter_rows(values_only=True)
                 for c in r if c is not None]
        wb.close()
        return "\n".join(cells)
    if suffix == ".docx":
        from xml.etree import ElementTree
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
        return "\n".join("".join(t.text or "" for t in p.iter(f"{w}t")) for p in root.iter(f"{w}p"))
    return ""


def _cell_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fold_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def key_problems(key: dict, bench_dir: Path = BENCH) -> list[str]:
    """Everything wrong with the key, as sentences. Empty means honest.

    A key that asks for a value the file does not carry scores every reader
    down for the key's mistake, so each expected value (with its unit), each
    expected field and each forbidden field must be IN the file's text - for
    files with a text layer. A file the key says has no text layer must have
    none, or the "scanned" case is not what it claims.
    """
    problems: list[str] = []
    for name, entry in key.get("files", {}).items():
        path = Path(bench_dir) / name
        if not path.is_file():
            problems.append(f"{name}: file missing")
            continue
        for item in entry.get("expected", []):
            for need in ("field", "value", "kind"):
                if not item.get(need):
                    problems.append(f"{name}: an expected item has no {need}")
        text = _fold_text(file_text(path))
        if not entry.get("text_layer", True):
            if text.strip():
                problems.append(f"{name}: marked scanned but has a text layer")
            continue
        for item in entry.get("expected", []):
            wanted = _fold_text(item["value"] + (f" {item['unit']}" if item.get("unit") else ""))
            if wanted not in text and not _value_near_unit(item, text):
                problems.append(f"{name}: expected value {item['field']!r} not in the file")
            if _fold_text(item["field"]) not in text and not any(
                    _fold_text(a) in text for a in item.get("aliases", [])):
                problems.append(f"{name}: expected field {item['field']!r} not in the file")
        for field in entry.get("forbidden", []):
            if _fold_text(field) not in text:
                problems.append(f"{name}: forbidden field {field!r} not in the file")
    return problems


def _value_near_unit(item: dict, text: str) -> bool:
    """A grid or workbook prints the unit in its own cell: the value and the
    unit are then each in the text, not side by side."""
    if not item.get("unit"):
        return False
    value = _fold_text(item["value"])
    return (re.search(r"(?<![\w.])" + re.escape(value) + r"(?![\w])", text) is not None
            and _fold_text(item["unit"]) in text)


# ------------------------------------------------------------- the matcher

STOP_WORDS = frozenset({"of", "at", "the", "and", "a", "an", "for", "to", "in"})
#: Abbreviation -> word. Kept small on purpose: a tolerance for spelling, not
#: a thesaurus that decides "flow" means "capacity".
SYNONYMS = {"temp": "temperature", "press": "pressure", "dia": "diameter",
            "diam": "diameter", "no": "number", "nr": "number", "qty": "quantity",
            "max": "maximum", "min": "minimum", "req": "required", "reqd": "required",
            "eff": "efficiency", "wt": "weight", "od": "outside diameter",
            "cap": "capacity", "matl": "material", "mat": "material", "dp": "pressure drop"}


def field_key(label: str | None) -> frozenset:
    from app import claims, datasheets
    name = datasheets.normalise_field_name(label or "")
    tokens: set[str] = set()
    for token in re.split(r"[^a-z0-9%]+", name.lower()):
        if not token or token in STOP_WORDS or token.isdigit():
            continue
        for word in SYNONYMS.get(token, token).split():
            tokens.add(word)
    units = {t for t in tokens if claims.is_unit(t) and len(tokens) > 1}
    return frozenset(tokens - units) or frozenset(tokens)


def label_forms(label: str | None) -> list[frozenset]:
    """The field keys a reported label is fairly read as: the label itself,
    and - when a table reader named the cell "<row label> - <column header>"
    ("Maximum flow - Offered") - the row label alone."""
    forms = [field_key(label)]
    head, sep, _column = str(label or "").rpartition(" - ")
    if sep and head.strip():
        forms.append(field_key(head))
    return [f for f in forms if f]


def field_matches(expected: dict, reported_field: str | None) -> bool:
    names = [field_key(name) for name in [expected["field"], *expected.get("aliases", [])]]
    return any(form in names for form in label_forms(reported_field))


_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _number(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    from app import claims
    found = claims.parse_value(str(text).strip())
    if found is not None:
        return found
    m = _NUMBER.search(str(text))
    return claims.parse_value(m.group(0)) if m else None


def _unit_of(value_text: str | None) -> str | None:
    m = re.match(r"^\s*[<>=~±]*\s*[-+]?\d[\d.,]*\s*([^\d\s.,].*?)\s*$", str(value_text or ""))
    return m.group(1) if m else None


def _normalised(number: float, unit: str | None):
    from app import claims
    if not unit:
        return None
    base, reference = claims.split_reference(unit)
    m = claims.normalise(repr(number), base or unit)
    if m.normalized_value is None:
        return None
    return m.normalized_value, m.normalized_unit, reference


def _fold_unit(unit: str | None) -> str:
    return re.sub(r"[\s.°]", "", str(unit or "")).lower()


def value_matches(expected: dict, reported: dict) -> bool:
    """Numbers: equal after unit normalisation (0.5%), or equal with the same
    printed unit. Text: equal once case, spacing and end punctuation fold."""
    want = _number(expected["value"]) if re.fullmatch(
        r"[-+]?\d+(?:[.,]\d+)?", expected["value"].strip()) else None
    if want is None:
        got = _fold_text(reported.get("value")).strip(" .;")
        return got == _fold_text(expected["value"]).strip(" .;")
    got_number = reported.get("number")
    if got_number is None:
        got_number = _number(reported.get("value"))
    if got_number is None:
        return False
    want_unit = expected.get("unit")
    got_unit = reported.get("unit") or _unit_of(reported.get("value"))
    if not want_unit:
        return math.isclose(got_number, want, rel_tol=0.005, abs_tol=1e-9) and not got_unit
    if not got_unit:
        return False
    a, b = _normalised(want, want_unit), _normalised(got_number, got_unit)
    if a is not None and b is not None and a[1] == b[1] and a[2] == b[2]:
        return math.isclose(a[0], b[0], rel_tol=0.005, abs_tol=1e-9)
    return (math.isclose(got_number, want, rel_tol=0.005, abs_tol=1e-9)
            and _fold_unit(got_unit) == _fold_unit(want_unit))


def score_file(entry: dict, facts: list[dict]) -> dict:
    """Score one reading against one file's key entry (see the module doc)."""
    expected = list(entry.get("expected", []))
    forbidden = [field_key(f) for f in entry.get("forbidden", [])]
    ignore = [field_key(f) for f in entry.get("ignore", [])]
    values = [f for f in facts if not f.get("blank")]
    used = [False] * len(expected)
    outcome: list[str | None] = [None] * len(values)
    detail: list[dict] = []
    # Pass 1: every exact match first, so an early wrong reading of a field
    # cannot take the answer a later right reading deserves.
    for i, fact in enumerate(values):
        for j, item in enumerate(expected):
            if not used[j] and field_matches(item, fact.get("field")) and value_matches(item, fact):
                used[j] = True
                outcome[i] = "correct"
                break
    for i, fact in enumerate(values):
        if outcome[i]:
            continue
        forms = label_forms(fact.get("field"))
        same_field = [j for j, item in enumerate(expected) if field_matches(item, fact.get("field"))]
        if any(value_matches(expected[j], fact) for j in same_field):
            outcome[i] = "duplicate"
        elif any(form in ignore for form in forms):
            outcome[i] = "ignored"
        elif any(form in forbidden for form in forms):
            outcome[i] = "forbidden"
        elif same_field:
            outcome[i] = "wrong_value"
        else:
            outcome[i] = "extra"
    counts = {k: outcome.count(k) for k in
              ("correct", "wrong_value", "forbidden", "extra", "duplicate", "ignored")}
    for fact, what in zip(values, outcome):
        if what not in ("correct", "duplicate", "ignored"):
            detail.append({"outcome": what, "field": fact.get("field"),
                           "value": fact.get("value"), "unit": fact.get("unit")})
    reported = counts["correct"] + counts["wrong_value"] + counts["forbidden"] + counts["extra"]
    return {
        "expected": len(expected),
        "found": counts["correct"],
        "reported": reported,
        **counts,
        "blanks_recorded": len(facts) - len(values),
        "recall": _ratio(counts["correct"], len(expected)),
        "precision": _ratio(counts["correct"], reported),
        "missed": [f"{e['field']} = {e['value']}{' ' + e['unit'] if e.get('unit') else ''}"
                   for e, hit in zip(expected, used) if not hit],
        "errors": detail,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def totals(per_file: dict[str, dict]) -> dict:
    keys = ("expected", "found", "reported", "correct", "wrong_value", "forbidden",
            "extra", "duplicate", "ignored", "blanks_recorded")
    out = {k: sum(r["score"].get(k, 0) for r in per_file.values()) for k in keys}
    out["recall"] = _ratio(out["found"], out["expected"])
    out["precision"] = _ratio(out["correct"], out["reported"])
    # Every file the reader did not fully read: unsupported, refused at
    # upload, stored and not indexed, OCR unavailable, stopped, failed.
    out["files_unsupported"] = sum(1 for r in per_file.values() if r["status"] != "read")
    out["conflicts"] = sum(r.get("conflicts", 0) for r in per_file.values())
    out["files"] = len(per_file)
    return out


# -------------------------------------------------------------- the readers
#
# WHAT EACH READER RUNS. Every reader but `ai-only:*` is THE PRODUCTION PATH:
# `datasheet_offline.read_file` runs a real upload's stages (upload
# validation, extract, chunk, OCR for pages the project routes to it, then
# `datasheets.extract_facts`) in a throwaway database, with two switches set
# for the run and restored afterwards:
#
#   reader           DATASHEET_OFFICE_INPUT  DATASHEET_AI_READER
#   rules            off                     off      (today's production)
#   rules+office     on                      off
#   hybrid:ollama    on                      ollama   (rules + AI, merged)
#   hybrid:claude    on                      claude   (Claude spend, USD caps)
#
# `ai-only:ollama|claude` is a DIAGNOSIS, not a production path: the AI page
# reader alone over `datasheet_inputs.page_texts` of every file type, no
# rules, no merge - what the AI can read by itself.
#
# `hybrid:oracle` is NOT A MEASUREMENT OF ANY AI. It is the hybrid path with
# a deterministic stand-in (`oracle_model_call`) that proposes exactly the
# answer key's facts, quoted from the page text. It proves the pipes carry a
# correct AI reading all the way into stored facts, and shows the CEILING the
# merge and the gates allow. Its numbers are an upper bound, labelled so.

READ = "read"
ALL_LOCAL = ("rules", "rules+office", "hybrid:ollama", "ai-only:ollama")
ORACLE = "hybrid:oracle"
ORACLE_LABEL = "UPPER-BOUND SANITY CHECK - a scripted answer-key oracle, not an AI"


class ReaderUnavailable(RuntimeError):
    """The reader cannot run here at all (flags off, engine not running)."""


def reader_spec(reader: str) -> dict:
    """What a reader name means: `{"mode": "rules"|"hybrid"|"ai-only",
    "office": bool, "engine": str|None}`. Raises ValueError for a name that
    is not a reader."""
    if reader == "rules":
        return {"mode": "rules", "office": False, "engine": None}
    if reader == "rules+office":
        return {"mode": "rules", "office": True, "engine": None}
    mode, _, engine = reader.partition(":")
    if mode == "hybrid" and engine in ("ollama", "claude", "oracle"):
        return {"mode": "hybrid", "office": True, "engine": engine}
    if mode == "ai-only" and engine in ("ollama", "claude"):
        return {"mode": "ai-only", "office": True, "engine": engine}
    raise ValueError(f"unknown reader {reader!r}; expected one of {(*READERS, ORACLE)}")


def _stored_facts(rows: list[dict]) -> list[dict]:
    """Stored `submittal_facts` rows as the scorer reads them. An AI fact's
    kind is in its section (`model:<kind>`); a rule fact's in its column."""
    facts = []
    for f in rows:
        column = (f.get("value_column") or "").strip().lower()
        section = str(f.get("section") or "")
        kind = (section.split(":", 1)[1] if section.startswith("model:")
                else column if column in ("required", "offered", "measured") else None)
        facts.append({
            "field": f.get("field_label") or f.get("field_name"),
            "value": f.get("field_value"),
            "number": _number(f["raw_value"]) if f.get("raw_value") not in (None, "") else None,
            "unit": f.get("raw_unit") or f.get("unit"),
            "kind": kind,
            "column": f.get("value_column"),
            "blank": bool(f.get("is_blank")),
            "page": f.get("page"),
            "method": f.get("extraction_method"),
            "state": f.get("validation_state"),
        })
    return facts


def _production_facts(path: Path, spec: dict, model_call) -> dict:
    """The production path for one file (`datasheet_offline.read_file`)."""
    from app import datasheet_offline, datasheets
    out = datasheet_offline.read_file(path, office_input=spec["office"],
                                      ai_engine=spec["engine"], model_call=model_call)
    summary = out["summary"] or {}
    ai = summary.get("ai_reader") or {}
    reading = {
        "status": out["status"], "reason": out["reason"], "facts": _stored_facts(out["facts"]),
        "conflicts": sum(1 for f in out["facts"]
                         if f.get("validation_state") == datasheets.GEOMETRY_CONFLICT),
        "reader_summary": {k: summary.get(k) for k in
                           ("facts", "blanks", "pages_read", "pages_unparsed")},
        "flags": out["flags"], "stages": out["stages"], "ocr": out["ocr"],
    }
    if ai:
        reading["ai_reader"] = {k: ai.get(k) for k in
                                ("engine", "unavailable", "stopped", "pages_read", "agreed",
                                 "conflicts", "ai_only", "facts_written", "dropped",
                                 "proposals_rejected")}
    return reading


def _ai_facts(path: Path, model_call) -> dict:
    """DIAGNOSIS: `claude_datasheet.read_page` (two runs and the gate, as the
    review route reads a page) over every page of `datasheet_inputs.
    page_texts` - PDF text layer, OCR for a page without one (when the
    project's OCR engine can run here), a workbook's sheets, a Word file's
    pages. No rules, no merge."""
    from app import claude_datasheet, claude_spend, datasheet_inputs, datasheet_offline
    ocr_ok, ocr_why = datasheet_offline.ocr_available()
    pages = datasheet_inputs.page_texts(path, recognise=ocr_ok)
    texts = [p.text or "" for p in pages]
    if not any(t.strip() for t in texts):
        if not ocr_ok and path.suffix.lower() == ".pdf":
            return {"status": datasheet_offline.OCR_UNAVAILABLE, "facts": [], "calls": 0,
                    "reason": f"ocr unavailable: no text layer and {ocr_why}"}
        return {"status": UNSUPPORTED, "reason": "no text on any page", "facts": [], "calls": 0}
    facts: list[dict] = []
    stopped = None
    rejected: dict[str, int] = {}
    for page in pages:
        text = page.text or ""
        if not text.strip():
            continue
        try:
            out = claude_datasheet.read_page(text, page.page_no, [], model_call)
        except claude_spend.StopRun as exc:
            stopped = exc.count_key
            break
        for reason, n in (out.get("counts") or {}).items():
            rejected[reason] = rejected.get(reason, 0) + n
        if out.get("error"):
            rejected[out["error"]] = rejected.get(out["error"], 0) + 1
        for p in out["accepted"]:
            facts.append({"field": p.get("field"), "value": p.get("value"), "unit": p.get("unit"),
                          "number": None, "kind": p.get("kind"), "blank": False,
                          "page": page.page_no})
    return {"status": READ if stopped is None else "stopped", "stopped": stopped,
            "facts": facts, "rejected": rejected}


class _Counted:
    """Counts the calls a reader made through it; `.calls` for the report.
    Carries the wrapped call's `.engine`, so provenance names the engine."""

    def __init__(self, call):
        self._call = call
        self.calls = 0
        self.engine = getattr(call, "engine", "custom")

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return self._call(prompt)


def read_file_with(reader: str, path, *, model_call=None) -> dict:
    """Read one file with one reader. THE PLUG-IN POINT.

    Returns `{"status": "read" | "stored_not_indexed" | "refused_at_upload" |
    "ocr_unavailable" | "unsupported" | "stopped" | "failed" | "error",
    "facts": [{field, value, unit, number, kind, blank, page}], "calls": n,
    "conflicts": n, ...}`. `model_call(prompt) -> str` is required for the AI
    readers (tests pass a fake; `build_model_call` makes the real one). Never
    raises for a file a reader cannot read - that is a result, not an error.
    """
    spec = reader_spec(reader)
    path = Path(path)
    if spec["engine"] is not None and model_call is None:
        raise ValueError(f"the {reader} reader needs a model_call")
    counted = _Counted(model_call) if model_call is not None else None
    try:
        if spec["mode"] == "ai-only":
            out = _ai_facts(path, counted)
        else:
            out = _production_facts(path, spec, counted)
    except Exception as exc:  # noqa: BLE001 - one file's failure is that file's result
        out = {"status": "error", "facts": [], "reason": f"{type(exc).__name__}: {exc}"}
    out["calls"] = counted.calls if counted is not None else 0
    out.setdefault("conflicts", 0)
    return out


def build_model_call(reader: str):
    """The real `model_call` for an AI reader. Returns (model_call, usage_fn)
    where `usage_fn()` gives what the calls used (`estimated_usd` for
    Claude). Raises `ReaderUnavailable` when the reader cannot run here.

    hybrid:*  - PRODUCTION'S engine, `datasheet_ai.model_call_for`: Ollama
                through `model_transport`; Claude only when
                `reasoning_provider.claude_unavailable` allows it, through
                `claude_spend.metered` (USD caps) and `claude_budget`, charged
                to production's step `datasheet_ai.STEP`. USD is that step's
                ledger delta over the run.
    ai-only:* - the benchmark's own lane, charged to `STEP`.
    """
    spec = reader_spec(reader)
    if spec["mode"] == "hybrid":
        if spec["engine"] == "oracle":
            raise ValueError("the oracle is built per file: oracle_model_call(entry)")
        from app import claude_spend, datasheet_ai
        call, why = datasheet_ai.model_call_for(spec["engine"])
        if call is None:
            raise ReaderUnavailable(why)
        if spec["engine"] == "claude":
            before = claude_spend.spent(datasheet_ai.STEP)
            return call, lambda: {"estimated_usd": round(
                claude_spend.spent(datasheet_ai.STEP) - before, 4)}
        return call, None
    engine = spec["engine"]
    if engine == "ollama":
        from app import model_transport
        from app import reasoning_provider as rp
        try:
            if model_transport.get_json("/api/tags", timeout=3.0, required=False) is None:
                raise ReaderUnavailable("the local Ollama engine did not answer /api/tags")
        except ReaderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - not running is a result here
            raise ReaderUnavailable(f"the local Ollama engine is not reachable ({type(exc).__name__})") from exc
        provider = rp.OllamaProvider()
        usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

        def call(prompt: str) -> str:
            response = provider.reason(rp.Packet(
                prompt=prompt, num_ctx=8192, num_predict=2048, temperature=0.0,
                step=STEP, prompt_version="claude_datasheet"))
            usage["calls"] += 1
            usage["input_tokens"] += int(response.tokens_in or 0)
            usage["output_tokens"] += int(response.tokens_out or 0)
            usage["model"] = response.model_tag
            return response.text
        return call, lambda: dict(usage)
    if engine == "claude":
        from app import claude_budget, claude_spend, reader_api, reader_transport
        transport = reader_transport.transport()
        if transport is None:
            raise ReaderUnavailable(
                "the Claude reader is off: STANDARDS_READER_ENABLED and "
                "STANDARDS_READER_ALLOW_PUBLIC_EGRESS are not both on")
        model = reader_api.ReaderSettings.from_env().model
        budget = claude_budget.Budget(reader_api.model_call_via(
            claude_spend.metered(transport, STEP, unbilled=reader_transport.unbilled)))

        def usage_fn() -> dict:
            used = dict(getattr(transport, "usage", None) or {})
            used["model"] = model
            used["estimated_usd"] = round(claude_spend.cost_usd(model, used), 4)
            return used
        return budget, usage_fn
    raise ValueError(f"{reader} has no model call")


# ------------------------------------------- the oracle (NOT a measurement)

_PAGE_MARK = "Answer with JSON and nothing else.\n\nPAGE "


def _prompt_page_text(prompt: str) -> str:
    """The page text `claude_datasheet.build_prompt` put at the end of the prompt."""
    tail = prompt.split(_PAGE_MARK, 1)[1] if _PAGE_MARK in prompt else prompt
    return tail.split("\n", 1)[1] if "\n" in tail else ""


def _loose(text: str) -> str:
    """A regex for `text` with any run of whitespace between its words."""
    return r"\s+".join(re.escape(w) for w in str(text).split())


def _oracle_quote(item: dict, page: str) -> tuple[str, str] | None:
    """(label as printed, quote) for one answer-key item on one page: the
    span of the PAGE TEXT from the label to the nearest following printing of
    the value, copied from the page. None when the page does not carry both."""
    value = re.compile(r"(?<![\w.])" + _loose(item["value"]) + r"(?![\w])", re.IGNORECASE)
    best = None
    for label in [item["field"], *item.get("aliases", [])]:
        for m in re.finditer(r"(?<!\w)" + _loose(label) + r"(?!\w)", page, re.IGNORECASE):
            v = value.search(page, m.end())
            if v is None or v.start() - m.end() > 400:
                continue
            span = (v.end() - m.start(), m.group(0), page[m.start():v.end()])
            if best is None or span[0] < best[0]:
                best = span
    return None if best is None else (best[1], best[2])


def oracle_model_call(entry: dict):
    """UPPER-BOUND SANITY CHECK, NOT A MEASUREMENT OF ANY AI.

    A deterministic `prompt -> JSON` stand-in for one file: on each page it
    proposes exactly the answer key's expected facts that the page carries,
    with the quote COPIED from the page text (`_oracle_quote`) and the key's
    kind. It knows the answers, so its recall is what the pipeline lets
    through when the reading is perfect - the ceiling of the merge and the
    gates, and proof the pipes carry an AI reading into stored facts."""
    def call(prompt: str) -> str:
        page = _prompt_page_text(prompt)
        facts = []
        for item in entry.get("expected", []):
            found = _oracle_quote(item, page)
            if found is None:
                continue
            label, quote = found
            facts.append({"field": " ".join(label.split()), "value": item["value"],
                          "unit": item.get("unit"), "quote": quote, "kind": item["kind"]})
        return json.dumps({"facts": facts})
    call.engine = "oracle"
    return call


# ---------------------------------------------------------------- the run


def run_reader(reader: str, key: dict, *, bench_dir: Path = BENCH, model_call=None,
               usage_fn=None, files: list[str] | None = None) -> dict:
    per_file: dict[str, dict] = {}
    oracle = reader == ORACLE
    for name, entry in key["files"].items():
        if files and name not in files:
            continue
        call = oracle_model_call(entry) if oracle else model_call
        reading = read_file_with(reader, Path(bench_dir) / name, model_call=call)
        per_file[name] = {"status": reading["status"], "reason": reading.get("reason"),
                          "calls": reading.get("calls", 0),
                          "conflicts": reading.get("conflicts", 0),
                          "score": score_file(entry, reading["facts"]),
                          **{k: reading[k] for k in ("reader_summary", "rejected", "ai_reader",
                                                      "ocr", "stages") if reading.get(k)}}
    report = {"reader": reader, "files": per_file, "total": totals(per_file),
              "calls": sum(r["calls"] for r in per_file.values())}
    if oracle:
        report["label"] = ORACLE_LABEL
    if usage_fn is not None:
        report["usage"] = usage_fn()
    from app import datasheet_offline
    report["flags"] = datasheet_offline.reader_flags()
    return report


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def print_report(report: dict) -> None:
    print(f"\n== reader: {report['reader']} ==")
    if report.get("label"):
        print(f"   {report['label']}")
    if report.get("unavailable"):
        print(f"   unavailable: {report['unavailable']}")
        return
    print(f"{'file':34} {'status':18} {'found/exp':>9} {'recall':>7} {'correct/rep':>11} "
          f"{'prec':>5} {'wrong':>5} {'forb':>4} {'extra':>5} {'confl':>5} {'calls':>5}")
    for name, r in report["files"].items():
        s = r["score"]
        print(f"{name:34} {r['status']:18} {s['found']:>4}/{s['expected']:<4} {_pct(s['recall']):>7} "
              f"{s['correct']:>5}/{s['reported']:<5} {_pct(s['precision']):>5} {s['wrong_value']:>5} "
              f"{s['forbidden']:>4} {s['extra']:>5} {r['conflicts']:>5} {r['calls']:>5}")
        if r["status"] != READ and r.get("reason"):
            print(f"{'':34}   {r['reason']}")
    t = report["total"]
    print(f"{'TOTAL (' + str(t['files']) + ' files, ' + str(t['files_unsupported']) + ' not read)':34} "
          f"{'':18} {t['found']:>4}/{t['expected']:<4} {_pct(t['recall']):>7} "
          f"{t['correct']:>5}/{t['reported']:<5} {_pct(t['precision']):>5} {t['wrong_value']:>5} "
          f"{t['forbidden']:>4} {t['extra']:>5} {t['conflicts']:>5} {report['calls']:>5}")
    if report.get("usage"):
        print(f"   usage: {report['usage']}")


def summary_rows(reports: list[dict]) -> list[dict]:
    """One row per reader, side by side: the numbers the owner compares."""
    rows = []
    for r in reports:
        if r.get("unavailable"):
            rows.append({"reader": r["reader"], "unavailable": r["unavailable"]})
            continue
        t = r["total"]
        rows.append({"reader": r["reader"], "found": t["found"], "expected": t["expected"],
                     "recall": t["recall"], "correct": t["correct"], "reported": t["reported"],
                     "precision": t["precision"], "wrong_value": t["wrong_value"],
                     "forbidden": t["forbidden"], "conflicts": t["conflicts"],
                     "files_not_read": t["files_unsupported"], "calls": r["calls"],
                     "usd": (r.get("usage") or {}).get("estimated_usd"),
                     **({"label": r["label"]} if r.get("label") else {})})
    return rows


def print_summary(reports: list[dict]) -> None:
    print("\n== side by side ==")
    print(f"{'reader':15} {'recall':>14} {'precision':>14} {'wrong':>5} {'forb':>4} "
          f"{'conflicts':>9} {'not read':>8} {'calls':>5} {'USD':>7}")
    for row in summary_rows(reports):
        if row.get("unavailable"):
            print(f"{row['reader']:15} unavailable: {row['unavailable']}")
            continue
        recall = f"{row['found']}/{row['expected']} {_pct(row['recall'])}"
        precision = f"{row['correct']}/{row['reported']} {_pct(row['precision'])}"
        usd = "-" if row["usd"] is None else f"{row['usd']:.4f}"
        print(f"{row['reader']:15} {recall:>14} {precision:>14} {row['wrong_value']:>5} "
              f"{row['forbidden']:>4} {row['conflicts']:>9} {row['files_not_read']:>8} "
              f"{row['calls']:>5} {usd:>7}"
              + ("   <- " + ORACLE_LABEL if row.get("label") else ""))


def readers_for(choice: str) -> tuple[str, ...]:
    """The readers a `--reader` choice runs."""
    if choice == "all":
        return READERS
    if choice == "all-local":
        return ALL_LOCAL
    reader_spec(choice)            # refuses an unknown name
    return (choice,)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reader", choices=[*READERS, ORACLE, "all-local", "all"],
                        default="rules",
                        help="all-local = rules, rules+office, hybrid:ollama, ai-only:ollama "
                             "(no Claude, no spend); hybrid:oracle is an upper-bound sanity "
                             "check, not an AI")
    parser.add_argument("--files", nargs="*", default=None,
                        help="only these benchmark files (default: all)")
    parser.add_argument("--out", type=Path, default=None,
                        help="JSON report path (default: benchmarks/local/datasheet_bench/, git-ignored)")
    parser.add_argument("--key", type=Path, default=KEY_PATH)
    args = parser.parse_args(argv)
    key = load_key(args.key)
    problems = key_problems(key, args.key.parent)
    if problems:
        print("the answer key is not honest:\n  " + "\n  ".join(problems))
        return 2
    reports = []
    for reader in readers_for(args.reader):
        spec = reader_spec(reader)
        if spec["engine"] is None or reader == ORACLE:
            report = run_reader(reader, key, bench_dir=args.key.parent, files=args.files)
        else:
            try:
                call, usage_fn = build_model_call(reader)
            except ReaderUnavailable as exc:
                reports.append({"reader": reader, "unavailable": str(exc)})
                print_report(reports[-1])
                continue
            report = run_reader(reader, key, bench_dir=args.key.parent,
                                model_call=call, usage_fn=usage_fn, files=args.files)
        reports.append(report)
        print_report(report)
    print_summary(reports)
    out = args.out or DEFAULT_OUT_DIR / f"{args.reader.replace(':', '-')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"key_version": key.get("version"), "reports": reports,
                               "summary": summary_rows(reports)},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
