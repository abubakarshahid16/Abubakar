"""Score datasheet readers on the made-up datasheet benchmark.

    python scripts/datasheet_bench.py --reader rules
    python scripts/datasheet_bench.py --reader all --out benchmarks/local/ds.json

THREE READERS, ONE ANSWER KEY. The files and `answer_key.json` are written by
`scripts/make_datasheet_bench.py` into
`backend/tests/fixtures/synthetic/datasheets/`; every value is made up.

  rules   the deterministic reader, `datasheets.extract_facts`, unchanged,
          run through `datasheet_offline.read_pdf_rules` (a private
          throwaway database; no ingestion, so no OCR tier).
  ollama  `claude_datasheet.read_page` (two runs + the gate) over each page's
          text, with the model call made by `reasoning_provider.OllamaProvider`
          - the local engine through `model_transport`, the one socket allowed
          to reach it.
  claude  the same page reader with the model call the review routes use:
          `reader_transport.transport()` wrapped in `claude_spend.metered`
          (USD caps checked before each call, the one spend ledger written
          after it) and `claude_budget.Budget` (the call cap), charged to its
          own step `STEP`. Off unless the reader's egress flags are on.

  The AI readers are measured ALONE (no skip-list from the rules reader), so
  the three numbers are three readers, not a reader and its top-up.

WHAT A READER CANNOT READ IS A MISS, NOT A CRASH. The rules reader reads PDFs;
the AI page reader in this branch reads a page's TEXT. A spreadsheet, a Word
file, or a PDF page with no text layer is reported "unsupported by this
reader" and every expected value on it counts against recall. Another branch
adds a path by registering it in `HANDLERS`; `read_file_with(reader, path)`
is the one entry point.

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
READERS = ("rules", "ollama", "claude")
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
    out["files_unsupported"] = sum(1 for r in per_file.values() if r["status"] == UNSUPPORTED)
    out["files"] = len(per_file)
    return out


# -------------------------------------------------------------- the readers


class ReaderUnavailable(RuntimeError):
    """The reader cannot run here at all (flags off, engine not running)."""


def _rules_facts(path: Path) -> dict:
    from app import datasheet_offline
    out = datasheet_offline.read_pdf_rules(path)
    facts = []
    for f in out["facts"]:
        column = (f.get("value_column") or "").strip().lower()
        facts.append({
            "field": f.get("field_label") or f.get("field_name"),
            "value": f.get("field_value"),
            "number": _number(f["raw_value"]) if f.get("raw_value") not in (None, "") else None,
            "unit": f.get("raw_unit") or f.get("unit"),
            "kind": column if column in ("required", "offered", "measured") else None,
            "column": f.get("value_column"),
            "blank": bool(f.get("is_blank")),
            "page": f.get("page"),
        })
    return {"status": "read", "facts": facts, "calls": 0,
            "reader_summary": {k: out["summary"].get(k) for k in
                               ("facts", "blanks", "pages_read", "pages_unparsed")},
            "flags": out["flags"]}


def _page_texts(path: Path) -> list[str]:
    import pymupdf
    with pymupdf.open(str(path)) as doc:
        return [page.get_text("text") or "" for page in doc]


def _ai_facts(path: Path, model_call) -> dict:
    """`claude_datasheet.read_page` over every page's text: two runs and the
    gate, exactly as the review route reads a page."""
    from app import claude_datasheet, claude_spend
    texts = _page_texts(path)
    if not any(t.strip() for t in texts):
        return {"status": UNSUPPORTED, "reason": "no text layer: the AI page reader in this "
                "branch reads page text only", "facts": [], "calls": 0}
    facts: list[dict] = []
    stopped = None
    rejected: dict[str, int] = {}
    for page_no, text in enumerate(texts, start=1):
        if not text.strip():
            continue
        try:
            out = claude_datasheet.read_page(text, page_no, [], model_call)
        except claude_spend.StopRun as exc:
            stopped = exc.count_key
            break
        for reason, n in (out.get("counts") or {}).items():
            rejected[reason] = rejected.get(reason, 0) + n
        if out.get("error"):
            rejected[out["error"]] = rejected.get(out["error"], 0) + 1
        for p in out["accepted"]:
            facts.append({"field": p.get("field"), "value": p.get("value"), "unit": p.get("unit"),
                          "number": None, "kind": p.get("kind"), "blank": False, "page": page_no})
    return {"status": "read" if stopped is None else "stopped", "stopped": stopped,
            "facts": facts, "rejected": rejected}


#: (reader, file suffix) -> handler(path, model_call) -> reading. Anything not
#: here is "unsupported by this reader". Another branch plugs a new path in
#: by adding an entry.
HANDLERS = {
    ("rules", ".pdf"): lambda path, _call: _rules_facts(path),
    ("ollama", ".pdf"): _ai_facts,
    ("claude", ".pdf"): _ai_facts,
}


class _Counted:
    """Counts the calls a reader made through it; `.calls` for the report."""

    def __init__(self, call):
        self._call = call
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return self._call(prompt)


def read_file_with(reader: str, path, *, model_call=None) -> dict:
    """Read one file with one reader. THE PLUG-IN POINT.

    Returns `{"status": "read" | "unsupported" | "stopped" | "error",
    "facts": [{field, value, unit, number, kind, blank, page}], "calls": n,
    ...}`. `model_call(prompt) -> str` is required for the AI readers (tests
    pass a fake; `build_model_call` makes the real one). Never raises for a
    file a reader cannot read - that is a result, not an error.
    """
    if reader not in READERS:
        raise ValueError(f"unknown reader {reader!r}; expected one of {READERS}")
    path = Path(path)
    handler = HANDLERS.get((reader, path.suffix.lower()))
    if handler is None:
        return {"status": UNSUPPORTED, "facts": [], "calls": 0,
                "reason": f"unsupported by this reader: no {reader} path for {path.suffix} files"}
    if reader != "rules" and model_call is None:
        raise ValueError(f"the {reader} reader needs a model_call")
    counted = _Counted(model_call) if model_call is not None else None
    try:
        out = handler(path, counted)
    except Exception as exc:  # noqa: BLE001 - one file's failure is that file's result
        out = {"status": "error", "facts": [], "reason": f"{type(exc).__name__}: {exc}"}
    out.setdefault("calls", counted.calls if counted is not None else 0)
    if counted is not None:
        out["calls"] = counted.calls
    return out


def build_model_call(reader: str):
    """The real `model_call` for an AI reader, through the project's own
    transports and limits. Returns (model_call, usage_fn) where `usage_fn()`
    gives {calls, input_tokens, output_tokens[, estimated_usd, model]}.
    Raises `ReaderUnavailable` when the reader cannot run here."""
    if reader == "ollama":
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
    if reader == "claude":
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


# ---------------------------------------------------------------- the run


def run_reader(reader: str, key: dict, *, bench_dir: Path = BENCH, model_call=None,
               usage_fn=None) -> dict:
    per_file: dict[str, dict] = {}
    for name, entry in key["files"].items():
        reading = read_file_with(reader, Path(bench_dir) / name, model_call=model_call)
        per_file[name] = {"status": reading["status"], "reason": reading.get("reason"),
                          "calls": reading.get("calls", 0),
                          "score": score_file(entry, reading["facts"]),
                          **({"reader_summary": reading["reader_summary"]}
                             if reading.get("reader_summary") else {}),
                          **({"rejected": reading["rejected"]} if reading.get("rejected") else {})}
    report = {"reader": reader, "files": per_file, "total": totals(per_file),
              "calls": sum(r["calls"] for r in per_file.values())}
    if usage_fn is not None:
        report["usage"] = usage_fn()
    if reader == "rules":
        from app import datasheet_offline
        report["flags"] = datasheet_offline.reader_flags()
    return report


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def print_report(report: dict) -> None:
    print(f"\n== reader: {report['reader']} ==")
    if report.get("unavailable"):
        print(f"   unavailable: {report['unavailable']}")
        return
    print(f"{'file':38} {'status':11} {'found/exp':>9} {'recall':>7} {'correct/rep':>11} "
          f"{'prec':>5} {'wrong':>5} {'forb':>4} {'extra':>5}")
    for name, r in report["files"].items():
        s = r["score"]
        print(f"{name:38} {r['status']:11} {s['found']:>4}/{s['expected']:<4} {_pct(s['recall']):>7} "
              f"{s['correct']:>5}/{s['reported']:<5} {_pct(s['precision']):>5} {s['wrong_value']:>5} "
              f"{s['forbidden']:>4} {s['extra']:>5}")
    t = report["total"]
    print(f"{'TOTAL (' + str(t['files']) + ' files, ' + str(t['files_unsupported']) + ' unsupported)':38} "
          f"{'':11} {t['found']:>4}/{t['expected']:<4} {_pct(t['recall']):>7} "
          f"{t['correct']:>5}/{t['reported']:<5} {_pct(t['precision']):>5} {t['wrong_value']:>5} "
          f"{t['forbidden']:>4} {t['extra']:>5}")
    if report["reader"] != "rules":
        print(f"   model calls: {report['calls']}  usage: {report.get('usage')}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reader", choices=[*READERS, "all"], default="rules")
    parser.add_argument("--out", type=Path, default=None,
                        help="JSON report path (default: benchmarks/local/datasheet_bench/, git-ignored)")
    parser.add_argument("--key", type=Path, default=KEY_PATH)
    args = parser.parse_args(argv)
    key = load_key(args.key)
    problems = key_problems(key, args.key.parent)
    if problems:
        print("the answer key is not honest:\n  " + "\n  ".join(problems))
        return 2
    readers = READERS if args.reader == "all" else (args.reader,)
    reports = []
    for reader in readers:
        if reader == "rules":
            report = run_reader(reader, key, bench_dir=args.key.parent)
        else:
            try:
                call, usage_fn = build_model_call(reader)
            except ReaderUnavailable as exc:
                reports.append({"reader": reader, "unavailable": str(exc)})
                print_report(reports[-1])
                continue
            report = run_reader(reader, key, bench_dir=args.key.parent,
                                model_call=call, usage_fn=usage_fn)
        reports.append(report)
        print_report(report)
    out = args.out or DEFAULT_OUT_DIR / f"{args.reader}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"key_version": key.get("version"), "reports": reports},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
