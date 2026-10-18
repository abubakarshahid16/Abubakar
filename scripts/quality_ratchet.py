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
    python scripts/quality_ratchet.py format-check --base <commit>             # order 79d, PRs only

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


#: Rule 1's limits, per file and per function (order 71c on #692). The two
#: max_* numbers below only bound the single longest file and function, so a
#: NEW 1,000-line file passed. `long_code.json` lists every file and function
#: over its limit today; `check` fails one that is new or longer than listed.
FILE_LIMIT, FUNCTION_LIMIT = 800, 80
DEFAULT_LONG_CODE = REPO / "eval" / "quality" / "long_code.json"


def _qualified_lengths(path: Path) -> dict[str, int]:
    """{"Class.method" / "outer.inner": line count} for one module; the
    longest wins when one name is defined twice. A file that cannot be parsed
    contributes nothing (never guessed)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    out: dict[str, int] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = ".".join([*stack, child.name])
                if not isinstance(child, ast.ClassDef) and child.end_lineno is not None:
                    out[name] = max(out.get(name, 0), child.end_lineno - child.lineno + 1)
                walk(child, [*stack, child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return out


def long_code(root: Path = BACKEND_APP) -> dict[str, dict[str, int]]:
    """Every backend file over FILE_LIMIT lines and function over FUNCTION_LIMIT."""
    files, functions = {}, {}
    for path in _py_files(root):
        rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name
        if (n := _line_count(path)) > FILE_LIMIT:
            files[rel] = n
        for name, n in _qualified_lengths(path).items():
            if n > FUNCTION_LIMIT:
                functions[f"{rel}::{name}"] = n
    return {"files": dict(sorted(files.items())), "functions": dict(sorted(functions.items()))}


def compare_long_code(listed: dict, current: dict) -> tuple[list[str], list[str]]:
    """(blocked, shrunk). Blocked: a file or function over its limit that is
    not listed, or longer than listed. Shrunk: a listed one that is shorter
    or gone - never a failure; `record-long-code` moves the bar down."""
    blocked, shrunk = [], []
    for kind, limit in (("files", FILE_LIMIT), ("functions", FUNCTION_LIMIT)):
        was, now = listed.get(kind, {}), current.get(kind, {})
        for key, n in now.items():
            if key not in was:
                blocked.append(f"NEW: {key} is {n} lines (limit {limit})")
            elif n > was[key]:
                blocked.append(f"GREW: {key} {was[key]} -> {n} lines (listed, may only shrink)")
        shrunk += [f"{key} {n} -> {now.get(key, 'under the limit')}"
                   for key, n in was.items() if now.get(key, 0) < n]
    return blocked, shrunk


# ----------------------------- order 79d: the formatter, changed files only

#: The trees the lint baseline reads (check_lint_baseline.PATHS).
FORMAT_TREES = ("backend/", "scripts/", "eval/")


def format_drift(source: str, path: str) -> int:
    """How many lines `ruff format` would add or remove in `source`. Main is
    far from formatted (958 of 981 files on 18 Oct), so the number is
    ratcheted per file instead of demanding a whole-file reformat."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--diff",
            "--no-cache",
            "--config",
            str(REPO / "ruff.toml"),
            "--stdin-filename",
            path,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
    )
    if proc.returncode not in (0, 1):
        raise SystemExit(
            f"ruff format failed on {path} ({proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    return sum(
        1
        for line in proc.stdout.splitlines()
        if line[:1] in ("+", "-") and not line.startswith(("+++", "---"))
    )


def changed_python(base: str) -> list[tuple[str | None, str]]:
    """(path at `base` or None for a new file, path now) for every Python file
    under FORMAT_TREES that differs from `base`. A rename keeps its old path,
    so moving an unformatted file is not a new unformatted file."""
    proc = subprocess.run(
        ["git", "diff", "--name-status", "-M", "--diff-filter=AMR", base, "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git diff against {base} failed: {proc.stderr.strip()[:300]}")
    pairs = []
    for row in proc.stdout.splitlines():
        status, *paths = row.split("\t")
        now = paths[-1]
        if now.endswith(".py") and now.startswith(FORMAT_TREES):
            pairs.append((None if status == "A" else paths[0], now))
    return pairs


def compare_format(
    drifts: list[tuple[str, int | None, int]],
) -> tuple[list[str], list[str]]:
    """(blocked, better) from (path, drift at base or None for a new file,
    drift now). A new file must be formatted; a changed file may not move
    further from the formatter. Closer is reported, never a failure."""
    blocked, better = [], []
    for path, was, now in drifts:
        if was is None and now:
            blocked.append(
                f"NEW FILE NOT FORMATTED: {path} ({now} lines differ; run `ruff format {path}`)"
            )
        elif was is not None and now > was:
            blocked.append(
                f"FORMAT DRIFT GREW: {path} {was} -> {now} lines differ from `ruff format`"
            )
        elif was is not None and now < was:
            better.append(f"{path} {was} -> {now}")
    return blocked, better


#: A new file whose non-blank lines are at least this share of lines the same
#: PR deleted elsewhere is MOVED code (a split out of a long file), not new
#: code: it keeps its old formatting, so a split stays a verbatim move and its
#: mutation anchors still match. The api/ splits measured 92 to 94%.
MOVED_SHARE = 0.8


def _same_line(line: str) -> str:
    # a route moved out of main.py changes only `@app.` to `@router.`
    return re.sub(r"^@router\.", "@app.", line.strip())


def moved_share(source: str, deleted: set[str]) -> float:
    """The share of `source`'s non-blank lines that are lines this PR deleted."""
    lines = [_same_line(line) for line in source.splitlines() if line.strip()]
    return sum(1 for line in lines if line in deleted) / len(lines) if lines else 0.0


def _deleted_lines(base: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "-U0", base, "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        check=True,
    )
    return {
        _same_line(line[1:])
        for line in proc.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---") and line[1:].strip()
    }


def format_check(base: str) -> tuple[list[str], list[str], list[str], int]:
    """(blocked, better, moved, files checked) for the files changed since `base`."""
    drifts, moved = [], []
    deleted = None
    for old, now in changed_python(base):
        source = (REPO / now).read_text(encoding="utf-8")
        drift = format_drift(source, now)
        was = None
        if old is not None:
            shown = subprocess.run(
                ["git", "show", f"{base}:{old}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=REPO,
                check=True,
            )
            was = format_drift(shown.stdout, old)
        elif drift:
            deleted = _deleted_lines(base) if deleted is None else deleted
            share = moved_share(source, deleted)
            if share >= MOVED_SHARE:
                moved.append(
                    f"{now} ({share:.0%} of its lines moved from elsewhere in this PR)"
                )
                was = drift
        drifts.append((now, was, drift))
    return (*compare_format(drifts), moved, len(drifts))


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
    c.add_argument("--long-code", default=str(DEFAULT_LONG_CODE))
    r = sub.add_parser("record-baseline")
    r.add_argument("--out", default=str(DEFAULT_BASELINE))
    rl = sub.add_parser("record-long-code")
    rl.add_argument("--out", default=str(DEFAULT_LONG_CODE))
    fc = sub.add_parser("format-check")
    fc.add_argument(
        "--base", required=True, help="the commit to compare with (CI: the PR's base)"
    )
    args = ap.parse_args(argv)

    if args.cmd == "format-check":
        blocked, better, moved, checked = format_check(args.base)
        print(
            f"  formatter: {checked} changed Python files checked against {args.base}; "
            f"{len(blocked)} further from `ruff format`, {len(better)} closer"
        )
        for line in better:
            print(f"  closer: {line}")
        for line in moved:
            print(f"  moved, kept as it was: {line}")
        if blocked:
            print("\nBLOCKED - format the lines this PR touches, or the new file:")
            for line in blocked:
                print(f"  - {line}")
            return 1
        print("\nOK: no changed file moved further from the formatter.")
        return 0

    if args.cmd == "record-long-code":
        listed = long_code()
        Path(args.out).write_text(json.dumps({"limits": {"file": FILE_LIMIT, "function": FUNCTION_LIMIT},
                                              **listed}, indent=1) + "\n", encoding="utf-8")
        print(f"listed {len(listed['files'])} files over {FILE_LIMIT} lines and "
              f"{len(listed['functions'])} functions over {FUNCTION_LIMIT} in {args.out}")
        return 0
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
    listed = json.loads(Path(args.long_code).read_text(encoding="utf-8"))
    blocked, shrunk = compare_long_code(listed, long_code())
    regressions += blocked
    print(f"\n  long code: {len(listed['files'])} files over {FILE_LIMIT} lines and "
          f"{len(listed['functions'])} functions over {FUNCTION_LIMIT} listed; "
          f"{len(blocked)} new or longer, {len(shrunk)} shorter")
    for line in shrunk:
        print(f"  shorter: {line}")
    if shrunk and not blocked:
        print("  the bar went down: run `python scripts/quality_ratchet.py record-long-code`"
              " in this PR so it cannot come back")
    if regressions:
        print("\nBLOCKED - this PR makes the quality bar worse:")
        for line in regressions:
            print(f"  - {line}")
        return 1
    print("\nOK: no measured rule is worse than the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
