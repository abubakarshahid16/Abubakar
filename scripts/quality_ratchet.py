"""A14 / #928: the code-quality bar enforced in CI with a RATCHET, not an
opinion. CI records today's number for each of the 9 rules the owner's audit
set; this script never lets a PR make one worse, and it never fabricates a
number for a rule nothing here can measure yet.

A METRIC WITH NO READER IS NOT A METRIC. Every one of the 9 rules gets an
entry in the report. A rule this script cannot measure (no tool installed, or
no automated check written yet) reports `"value": null` and a `note` saying
why - never a 0, never silently skipped, never counted as passing. `check`
only compares rules where BOTH the baseline and today's run produced a real
number; everything else is printed as "not measured" and is not ratcheted.

EVERY NUMBER HERE IS "LOWER IS BETTER" (a count, a line length, a complexity
score). A PR regresses the gate the moment ANY one of them rises above the
stored baseline for that rule - not an average, not a sum: the worst single
file or function is what the audit graded.

    python scripts/quality_ratchet.py measure                                   # print today's numbers
    python scripts/quality_ratchet.py check --baseline eval/quality/baseline.json
    python scripts/quality_ratchet.py record-baseline --out eval/quality/baseline.json

`check` exits 1 the moment one measured rule is worse than its baseline.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND_APP = REPO / "backend" / "app"
FRONTEND_SRC = REPO / "frontend" / "src"
DEFAULT_BASELINE = REPO / "eval" / "quality" / "baseline.json"

FORMAT = "quality-ratchet/1"

#: The owner's 9 rules (#928), in order. Each key here is the metric this
#: script measures for that rule, or None with a reason when nothing here
#: measures it yet - never a fabricated number standing in for the rule.
RULES = {
    1: "file and function length (no file over 800 lines, no function over 80)",
    2: "cyclomatic complexity per function (<= 15)",
    3: "zero duplicated logic in the danger zone (one vocabulary, one parser, ...)",
    4: "zero dead code",
    5: "no broad except that returns empty with no named, counted reason",
    6: "typed: mypy/pyright strict on the danger zone, then everything",
    7: "measured coverage: >= 90% on the review path",
    8: "one README, one SETUP, no doc contradicting the code",
    9: "frontend: one wording per concept, no component over 400 lines, axe green",
}


def _entry(value: int | None, *, note: str | None = None) -> dict:
    if value is None and not note:
        raise ValueError("a null metric must say why (never a silent skip)")
    return {"value": value, "note": note}


# ---------------------------------------------------------- rule 1: length

def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py")
                  if "__pycache__" not in p.parts and p.is_file())


def _tsx_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.tsx")
                  if "node_modules" not in p.parts and p.is_file()
                  and not p.name.endswith((".test.tsx", ".spec.tsx")))


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _function_lengths(path: Path) -> list[tuple[str, int]]:
    """(qualified name, line count) for every function/method AST finds in a
    backend module. A file that cannot be parsed contributes nothing (never
    guessed); `measure()`'s own file-length count still sees it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None)
            if end is not None:
                out.append((node.name, end - node.lineno + 1))
    return out


def rule_1_length() -> dict:
    backend = _py_files(BACKEND_APP)
    frontend = _tsx_files(FRONTEND_SRC) if FRONTEND_SRC.is_dir() else []
    max_backend_file = max((_line_count(p) for p in backend), default=0)
    max_frontend_file = max((_line_count(p) for p in frontend), default=0)
    func_lengths = [n for p in backend for _name, n in _function_lengths(p)]
    max_func = max(func_lengths, default=0)
    return {
        "max_backend_file_lines": _entry(max_backend_file),
        "max_frontend_component_lines": _entry(max_frontend_file),
        "max_backend_function_lines": _entry(max_func),
    }


# ----------------------------------------------------- rule 2: complexity

_TOO_COMPLEX = re.compile(r"too complex \((\d+) > ")


def rule_2_complexity() -> dict:
    """The real complexity ruff computed for every function, by asking it to
    flag everything (max-complexity=1) and reading the number back out of
    each message - never ruff's own pass/fail at some chosen threshold,
    which would hide exactly the number a ratchet needs."""
    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    if not Path(ruff).exists() and shutil.which("ruff") is None:
        return {"max_cyclomatic_complexity":
                _entry(None, note="not measured: ruff is not on PATH")}
    proc = subprocess.run(
        [ruff, "check", str(BACKEND_APP), "--select", "C901",
         "--config", "lint.mccabe.max-complexity=1", "--no-cache"],
        capture_output=True, text=True, cwd=REPO)
    scores = [int(m.group(1)) for m in _TOO_COMPLEX.finditer(proc.stdout)]
    if not scores and proc.returncode not in (0, 1):
        return {"max_cyclomatic_complexity":
                _entry(None, note=f"not measured: ruff exited {proc.returncode} unexpectedly")}
    return {"max_cyclomatic_complexity": _entry(max(scores, default=0))}


# --------------------------------------------------- rule 3: duplication

def duplicate_definitions(path: Path) -> int:
    """How many top-level (or one-class) names are defined more than once in
    this module - exactly the #197/#922 shape (is_comprehensive/_synthesise
    twice in analysis.py; three Settings fields twice in config.py). Python
    keeps only the last one, so every extra copy is dead, silently
    divergeable text. Counts EXTRA copies (a name seen 3 times counts 2), so
    the metric is 0 when every name is unique."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return 0

    def names_in(body: list[ast.stmt]) -> list[str]:
        out = []
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append(node.name)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                # a class-body field with a type annotation (a Settings field)
                out.append(node.target.id)
        return out

    extra = 0
    scopes = [tree.body] + [n.body for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for body in scopes:
        seen: dict[str, int] = {}
        for name in names_in(body):
            seen[name] = seen.get(name, 0) + 1
        extra += sum(n - 1 for n in seen.values() if n > 1)
    return extra


def rule_3_duplication() -> dict:
    total = sum(duplicate_definitions(p) for p in _py_files(BACKEND_APP))
    return {"duplicate_definitions_in_backend_app": _entry(total),
           "one_unit_table_one_comparator_one_applicability_path": _entry(
               None, note="not measured: needs a semantic check, not a line count "
                          "(see #197/#736's own tracked list for the manual audit)")}


# -------------------------------------------------------- rule 4: dead code

def rule_4_dead_code() -> dict:
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import check_unused_modules as cum
        count = len(cum.unused())
    except Exception as exc:  # noqa: BLE001 - reported as an unmeasured rule, not raised
        return {"unused_backend_modules": _entry(None, note=f"not measured: {type(exc).__name__}")}
    vulture = shutil.which("vulture")
    out = {"unused_backend_modules": _entry(count)}
    if vulture is None:
        out["vulture_findings"] = _entry(None, note="not measured: vulture is not installed here")
    else:
        # The same whitelist CI's own "Find dead code" step already gates on
        # (#661): a name that only LOOKS unused, with the reason beside it.
        # Without it this count would double-report what that step already
        # names and accepts, as if it were new.
        whitelist = REPO / "scripts" / "vulture_whitelist.py"
        args = [vulture, str(BACKEND_APP)] + ([str(whitelist)] if whitelist.exists() else []) + \
            ["--min-confidence", "80"]
        proc = subprocess.run(args, capture_output=True, text=True, cwd=REPO)
        out["vulture_findings"] = _entry(len([ln for ln in proc.stdout.splitlines() if ln.strip()]))
    return out


# --------------------------------------------------------- rule 5: broad except

def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = [handler.type] if isinstance(handler.type, ast.Name) else (
        handler.type.elts if isinstance(handler.type, ast.Tuple) else [])
    return any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names)


#: A handler body that names a reason somewhere counts as accounted for -
#: logged, counted, or re-raised. A heuristic (it reads the body's own
#: source), stated as one: `note` on the metric says so.
_ACCOUNTED_FOR = re.compile(r"\b(log|logger|logging|record|count|raise|warn)\w*\b", re.IGNORECASE)


def broad_unaccounted_excepts(path: Path) -> int:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    lines = source.splitlines()
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad(node):
            start = node.lineno - 1
            end = (node.body[-1].end_lineno if node.body and getattr(node.body[-1], "end_lineno", None)
                  else start + 1)
            body_text = "\n".join(lines[start:end])
            if not _ACCOUNTED_FOR.search(body_text):
                found += 1
    return found


def rule_5_broad_except() -> dict:
    total = sum(broad_unaccounted_excepts(p) for p in _py_files(BACKEND_APP))
    return {"broad_except_with_no_named_reason": _entry(
        total, note=None if total == 0 else
        "heuristic: a handler is 'accounted for' if its body mentions log/record/count/raise/warn")}


# -------------------------------------------------- rules 6, 7, 8: not yet

def rule_6_typed() -> dict:
    return {"mypy_strict_errors": _entry(None, note="not measured: mypy is not installed here")}


def rule_7_coverage() -> dict:
    return {"review_path_coverage_percent": _entry(
        None, note="not measured: no coverage tool runs in this CI job yet (#928)")}


def rule_8_docs() -> dict:
    return {"docs_contradicting_the_code": _entry(
        None, note="not measured: needs a semantic reading of docs against code, not a line count")}


# -------------------------------------------------------- rule 9: frontend

def rule_9_frontend() -> dict:
    # max_frontend_component_lines is already measured in rule 1; this adds
    # what rule 1 does not cover.
    return {"developer_text_on_screen": _entry(
        None, note="not measured: no automated 'no developer text on screen' check exists yet"),
            "axe_serious_critical": _entry(
        None, note="not measured here: the axe gate runs as its own CI job (pass/fail, not a count)")}


# ------------------------------------------------------------------- all

def measure() -> dict:
    metrics: dict = {}
    for fn in (rule_1_length, rule_2_complexity, rule_3_duplication, rule_4_dead_code,
              rule_5_broad_except, rule_6_typed, rule_7_coverage, rule_8_docs, rule_9_frontend):
        metrics.update(fn())
    return {"format": FORMAT, "rules": RULES, "metrics": metrics}


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"{path}: not a {FORMAT} file")
    return data


def compare(baseline: dict, current: dict) -> list[str]:
    """Every metric that is worse (a higher count) in `current` than in
    `baseline`, as a plain-English line naming both numbers. A metric null on
    either side is never compared - printed separately by the caller as
    'not measured', never treated as pass or fail."""
    regressions = []
    for name, base_entry in baseline.get("metrics", {}).items():
        cur_entry = current.get("metrics", {}).get(name)
        if cur_entry is None:
            continue
        base_v, cur_v = base_entry.get("value"), cur_entry.get("value")
        if base_v is None or cur_v is None:
            continue
        if cur_v > base_v:
            regressions.append(f"{name}: was {base_v}, now {cur_v}")
    return regressions


def _print_report(data: dict) -> None:
    for name, entry in sorted(data["metrics"].items()):
        if entry["value"] is None:
            print(f"  {name}: not measured ({entry['note']})")
        else:
            print(f"  {name}: {entry['value']}" + (f"  ({entry['note']})" if entry.get("note") else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("measure")
    c = sub.add_parser("check")
    c.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    r = sub.add_parser("record-baseline")
    r.add_argument("--out", default=str(DEFAULT_BASELINE))
    args = ap.parse_args(argv)

    current = measure()
    if args.cmd == "measure":
        _print_report(current)
        return 0
    if args.cmd == "record-baseline":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline written to {out}")
        _print_report(current)
        return 0
    # check
    baseline = load(args.baseline)
    regressions = compare(baseline, current)
    _print_report(current)
    if regressions:
        print("\nBLOCKED - this PR makes the quality bar worse:")
        for line in regressions:
            print(f"  - {line}")
        return 1
    print("\nOK: no measured rule is worse than the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
