"""The done-gate for the general review (DONE-MEANS checks 0, 1, 2 and 3). It reads; it never reviews and never scores.

    python scripts/aim_done_gate.py switches --base-url http://127.0.0.1:<port> --token-file <file> --datasheet-id <doc id>
    python scripts/aim_done_gate.py found --score BUILD/score/new/SCORE.txt --old BUILD/score/old/SCORE.txt [--old-runs-dir BUILD/score/old]
    python scripts/aim_done_gate.py alarms --score-dir BUILD/score/new --judge-dir BUILD/score/judge
    python scripts/aim_done_gate.py report --score BUILD/score/new/SCORE.txt --score-dir BUILD/score/new --judge-dir BUILD/score/judge \
        --old BUILD/score/old/SCORE.txt [--old-runs-dir BUILD/score/old]

report (DONE-MEANS "How every result is shown, below target included"): one table per paper, the same every run: copies A, B, C
  (found of 10 by code, chance hits, net, comments, WRONG n of N, the saved sheet's path) and the original (comments, sheet), then
  the mean, the target 7.0, the old engine's number and false alarms as n of N, and ONE verdict word:
  PASS; BELOW TARGET naming each missed check and the gap in numbers, never rounded in the method's favour ("valve: mean 6.66
  (20/3) of 10, target 7.0, short by 0.34"; "pump: 2 WRONG of 14 comments = 14.2%, limit 10%"); or NOT MEASURED naming the
  blocking step and the app's own sentence from the driver's run file ("valve-B: upload: HTTP 422 (<sentence>)"). Exit 0 only
  when every paper is PASS.

Each prints ONE table and exits 0 only on PASS. A number that could not be read is NOT MEASURED, and NOT MEASURED fails (never 0,
never a pass).

switches (check 0): GET /api/reviews/method answers method "general", old_engine false, local_available false, and the plan of a
  datasheet says method "general". HTTP to this machine only; the bearer token is read from a file and never printed.
found (checks 1 and 2): reads the score command's output (the `--all` table, or one-copy reports). Per paper: each of copies
  A, B, C gives "found (proven by code)" minus its chance hits (the original paper's review against that copy's key); the mean of
  the three must be >= 7.0. A copy with 0 comments, no row or no chance-hit count is NOT MEASURED. Then the new mean must be
  strictly above the old engine's mean on the same paper (the copies the old engine was measured on; an old score with no chance
  count is taken as found, which can only raise the bar). An old review the app refused counts as 0 when its run file in
  --old-runs-dir says so, with the app's sentence.
alarms (check 3): per paper, WRONG marks over all comments of its copies A, B, C must be at most 1 in 10. The judge file
  <paper>-<copy>.json ({"1": "KEEP", ...} or {"marks": {...}}) must mark every comment of <paper>-<copy>-comments.json, else NOT
  MEASURED.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aim_app_score as driver

PAPERS = driver.PAPERS
SCORED_COPIES = ("A", "B", "C")
MIN_FOUND = 7.0
MAX_WRONG_SHARE = (1, 10)  # at most 1 WRONG in 10 comments
NM = "NOT MEASURED"
MARKS = ("KEEP", "WEAK", "WRONG")

_COUNT = r"(NOT MEASURED|\d+ of \d+)"
#: one row of the score command's --all table: paper copy found +confirmed possible chance comments ...
_TABLE_ROW = re.compile(
    rf"^\s*([a-z]+)\s+([ABC])\s+{_COUNT}\s+{_COUNT}\s+(\d+)\s+{_COUNT}\s+(\d+)\b"
)
_REPORT_KEY = re.compile(r"^key:\s*([a-z]+)-([ABC])\b.*comments read:\s*(\d+)")
_REPORT_FOUND = re.compile(r"^found \(proven by code\):\s*(\d+) of \d+")
_REPORT_FOUND_NM = re.compile(r"^found: NOT MEASURED")
_REPORT_CHANCE = re.compile(
    r"^chance hits \(original paper's review against this key\):\s*(NOT MEASURED|\d+ of \d+)"
)


def _num(s: str | None) -> int | None:
    return None if s is None or s.startswith(NM) else int(s.split()[0])


def _show(v) -> str:
    return NM if v is None else str(v)


def table(head: tuple, rows: list[tuple]) -> str:
    body = [tuple("" if c is None else str(c) for c in r) for r in rows]
    widths = [max(len(str(x[i])) for x in (head, *body)) for i in range(len(head))]
    return "\n".join(
        "  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
        for r in (head, *body)
    )


# ------------------------------------------------------------------------------------------------ score files


def parse_score(text: str) -> dict[tuple[str, str], dict]:
    """{(paper, copy): {"found": int|None, "chance": int|None, "comments": int|None}} from the score command's output. Both
    layouts: the --all table and the one-copy report. A later line for the same copy replaces an earlier one."""
    out: dict[tuple[str, str], dict] = {}
    current = None
    for line in text.splitlines():
        m = _TABLE_ROW.match(line)
        if m:
            paper, copy, found, _conf, _pos, chance, comments = m.groups()
            out[(paper, copy)] = {
                "found": _num(found) if int(comments) > 0 else None,
                "chance": _num(chance),
                "comments": int(comments),
            }
            continue
        m = _REPORT_KEY.match(line)
        if m:
            current = (m.group(1), m.group(2))
            out[current] = {"found": None, "chance": None, "comments": int(m.group(3))}
            continue
        if current is None:
            continue
        m = _REPORT_FOUND.match(line)
        if m and out[current]["comments"]:
            out[current]["found"] = int(m.group(1))
        elif _REPORT_FOUND_NM.match(line):
            out[current]["found"] = None
        m = _REPORT_CHANCE.match(line)
        if m:
            out[current]["chance"] = _num(m.group(1))
    return out


def read_scores(paths: list[str]) -> dict[tuple[str, str], dict]:
    """Score files, or folders of *score*.txt / SCORE.txt files; later files win."""
    out: dict[tuple[str, str], dict] = {}
    for p in paths or []:
        path = Path(p)
        files = (
            sorted(path.glob("*score*.txt")) + sorted(path.glob("SCORE*.txt"))
            if path.is_dir()
            else [path]
        )
        for f in dict.fromkeys(files):
            out.update(parse_score(f.read_text(encoding="utf-8")))
    return out


def old_refusals(runs_dir: str | None) -> dict[tuple[str, str], str]:
    """{(paper, copy): the app's sentence} for old reviews the app refused (the driver's run files say status "refused")."""
    out: dict[tuple[str, str], str] = {}
    if not runs_dir:
        return out
    for f in sorted(Path(runs_dir).glob("*-run.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(rec, dict)
            and rec.get("status") == "refused"
            and rec.get("paper")
            and rec.get("copy")
        ):
            out[(rec["paper"], rec["copy"])] = (
                rec.get("words") or "refused (no sentence given)"
            )
    return out


def net_found(row: dict | None) -> int | None:
    """found minus chance hits; None when either is NOT MEASURED."""
    if not row or row.get("found") is None or row.get("chance") is None:
        return None
    return row["found"] - row["chance"]


def old_value(row: dict | None) -> int | None:
    """The old engine's found: minus chance hits when measured, else found as it is (only raises the bar for the new method)."""
    if not row or row.get("found") is None:
        return None
    return row["found"] - (row["chance"] or 0)


def paper_verdict(
    nets: list[int | None], olds: list[int], min_found: float
) -> tuple[bool, list[str]]:
    """(passes, why) for one paper: every copy measured, mean >= min_found, mean strictly above the old engine's mean."""
    why = []
    if not nets or any(v is None for v in nets):
        why.append(
            f"{NM}: "
            + (
                ", ".join(f"copy {i + 1}" for i, v in enumerate(nets) if v is None)
                or "no copy"
            )
        )
        mean = None
    else:
        mean = sum(nets) / len(nets)
        if mean < min_found:
            why.append(f"mean below {min_found}")
    old_mean = sum(olds) / len(olds) if olds else None
    if old_mean is None:
        why.append(f"old engine {NM}")
    elif mean is not None and not mean > old_mean:
        why.append("not strictly better than the old engine")
    return not why, why


def cmd_found(a) -> int:
    new = read_scores([a.score])
    old = read_scores(a.old)
    refused = old_refusals(a.old_runs_dir)
    rows, ok_all = [], True
    for paper in a.papers:
        nets = [net_found(new.get((paper, c))) for c in a.copies]
        mean = None if any(v is None for v in nets) else sum(nets) / len(nets)
        olds, notes = [], []
        for c in ("A", "B", "C"):
            if (paper, c) in old and old_value(old[(paper, c)]) is not None:
                olds.append(old_value(old[(paper, c)]))
            elif (paper, c) in refused:
                olds.append(0)
                notes.append(f"old {c} refused: {refused[(paper, c)]}")
        old_mean = sum(olds) / len(olds) if olds else None
        ok, why = paper_verdict(nets, olds, a.min_found)
        ok_all &= ok
        rows.append(
            (
                paper,
                *(NM if v is None else v for v in nets),
                NM if mean is None else f"{mean:.2f}",
                NM if old_mean is None else f"{old_mean:.2f} ({len(olds)} copies)",
                "PASS" if ok else "FAIL",
                "; ".join(why + notes) or "-",
            )
        )
    print(
        table(
            (
                "paper",
                *[f"net {c}" for c in a.copies],
                "new mean",
                "old mean",
                "result",
                "why",
            ),
            rows,
        )
    )
    print(
        "net = found (proven by code) minus chance hits on that copy's key; pass: new mean >= "
        f"{a.min_found} AND new mean > old mean, every paper."
    )
    print(f"FOUND GATE: {'PASS' if ok_all and rows else 'FAIL'}")
    return 0 if ok_all and rows else 1


# ------------------------------------------------------------------------------------------------ alarms


def comment_count(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("comments") if "comments" in data else data.get("points")
    return len(data) if isinstance(data, list) else None


def judge_marks(path: Path) -> dict[int, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("marks"), dict):
        data = data["marks"]
    if not isinstance(data, dict):
        return None
    out = {}
    for k, v in data.items():
        if str(k).isdigit() and str(v).upper() in MARKS:
            out[int(k)] = str(v).upper()
    return out


def cmd_alarms(a) -> int:
    score_dir, judge_dir = Path(a.score_dir), Path(a.judge_dir)
    rows, ok_all = [], True
    num, den = MAX_WRONG_SHARE
    for paper in a.papers:
        wrong = total = 0
        missing = []
        for c in a.copies:
            n = comment_count(score_dir / f"{paper}-{c}-comments.json")
            marks = judge_marks(judge_dir / f"{paper}-{c}.json")
            if not n:
                missing.append(f"{c}: no comments read")
                continue
            if marks is None or any(i not in marks for i in range(1, n + 1)):
                judged = (
                    0
                    if marks is None
                    else sum(1 for i in range(1, n + 1) if i in marks)
                )
                missing.append(f"{c}: judged {judged} of {n}")
                continue
            wrong += sum(1 for i in range(1, n + 1) if marks[i] == "WRONG")
            total += n
        ok = not missing and total > 0 and wrong * den <= num * total
        ok_all &= ok
        share = NM if missing else f"{wrong} of {total}"
        why = (
            f"{NM}: " + "; ".join(missing)
            if missing
            else ("-" if ok else f"more than {num} in {den}")
        )
        rows.append((paper, share, "PASS" if ok else "FAIL", why))
    print(table(("paper", "WRONG of comments (A, B, C)", "result", "why"), rows))
    print(f"ALARMS GATE: {'PASS' if ok_all and rows else 'FAIL'}")
    return 0 if ok_all and rows else 1


# ------------------------------------------------------------------------------------------------ report (every result shown)

PASS, BELOW, NOT_MEASURED = "PASS", "BELOW TARGET", "NOT MEASURED"
DONE_STATUSES = ("completed", "done")


def floor2(x: float) -> str:
    """Two decimals, never rounded up (6.666 -> 6.66)."""
    return f"{math.floor(x * 100 + 1e-9) / 100:.2f}"


def ceil2(x: float) -> str:
    """Two decimals, never rounded down: a shortfall is never shown smaller than it is (0.333 -> 0.34)."""
    return f"{math.ceil(x * 100 - 1e-9) / 100:.2f}"


def share_words(n: int, total: int) -> str:
    pct = math.floor(n * 1000 / total) / 10 if total else 0.0
    return f"{n} WRONG of {total} comments = {pct:.1f}%"


def run_record(score_dir: Path, paper: str, copy: str) -> dict | None:
    f = score_dir / f"{paper}-{copy}-run.json"
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def blocking_words(label: str, rec: dict | None) -> str | None:
    """Why a copy's review is not there: the driver's own record (the step and the app's sentence)."""
    if rec is None:
        return f"{label}: no review in the score folder (no run file)"
    status = rec.get("status")
    if status in DONE_STATUSES:
        return None
    return (
        f"{label}: {rec.get('words') or 'the review did not finish'} (status {status})"
    )


def paper_report(
    a, paper: str, new: dict, old: dict, refused: dict
) -> tuple[str, list[str], list[tuple]]:
    """(verdict, reasons, table rows) for one paper."""
    score_dir, judge_dir = Path(a.score_dir), Path(a.judge_dir)
    blocked, below, rows = [], [], []
    nets, wrong, total = [], 0, 0
    for copy in (*a.copies, "orig"):
        label = f"{paper}-{copy}"
        rec = run_record(score_dir, paper, copy)
        sheet = score_dir / f"{label}-sheet.xlsx"
        sheet_words = str(sheet) if sheet.is_file() else "no sheet saved"
        block = blocking_words(label, rec)
        if copy == "orig":
            if block:
                blocked.append(block + "; chance hits cannot be counted without it")
            rows.append(
                (
                    copy,
                    "-",
                    "-",
                    "-",
                    _show(rec and rec.get("comments")),
                    "-",
                    sheet_words,
                )
            )
            continue
        row = new.get((paper, copy))
        if block:
            blocked.append(block)
        elif row is None:
            blocked.append(
                f"{label}: no row in the score output (the test owner's score step has not run on it)"
            )
        elif row.get("found") is None:
            blocked.append(f"{label}: found {NM} (0 comments read)")
        elif row.get("chance") is None:
            blocked.append(
                f"{label}: chance hits {NM} (no scored review of the original)"
            )
        net = net_found(row)
        nets.append(net)
        n = comment_count(score_dir / f"{label}-comments.json")
        marks = judge_marks(judge_dir / f"{label}.json")
        w = None
        if n:
            if marks is None or any(i not in marks for i in range(1, n + 1)):
                judged = (
                    0
                    if marks is None
                    else sum(1 for i in range(1, n + 1) if i in marks)
                )
                blocked.append(
                    f"{label}: false alarms {NM} (the reader judged {judged} of {n} comments)"
                )
            else:
                w = sum(1 for i in range(1, n + 1) if marks[i] == "WRONG")
                wrong, total = wrong + w, total + n
        rows.append(
            (
                copy,
                _show(row and row.get("found")),
                _show(row and row.get("chance")),
                _show(net),
                _show(n),
                "-" if w is None else f"{w} of {n}",
                sheet_words,
            )
        )
    olds, old_notes = [], []
    for c in ("A", "B", "C"):
        if (paper, c) in old and old_value(old[(paper, c)]) is not None:
            olds.append(old_value(old[(paper, c)]))
        elif (paper, c) in refused:
            olds.append(0)
            old_notes.append(f"old {c} refused, counted 0: {refused[(paper, c)]}")
    if not olds:
        blocked.append(f"{paper}: the old engine's number {NM} (no old score)")
    mean = sum(nets) / len(nets) if nets and all(v is not None for v in nets) else None
    old_mean = sum(olds) / len(olds) if olds else None
    if mean is not None:
        if mean < a.min_found:
            below.append(
                f"{paper}: mean {floor2(mean)} ({sum(nets)}/{len(nets)}) of 10, target {a.min_found:.1f}, "
                f"short by {ceil2(a.min_found - mean)}"
            )
        if old_mean is not None and not mean > old_mean:
            below.append(
                f"{paper}: not above the old engine: new mean {floor2(mean)}, old {floor2(old_mean)}"
            )
    num, den = MAX_WRONG_SHARE
    if total and wrong * den > num * total:
        below.append(f"{paper}: {share_words(wrong, total)}, limit {num * 100 // den}%")
    verdict = NOT_MEASURED if blocked else BELOW if below else PASS
    summary = (
        f"mean {NM if mean is None else floor2(mean)} of 10 | target {a.min_found:.1f} | old engine "
        f"{NM if old_mean is None else floor2(old_mean) + f' ({len(olds)} copies)'} | false alarms "
        f"{share_words(wrong, total) + ' (limit 10%)' if total and not blocked else NM if blocked else '0 comments'}"
    )
    rows.append(("", "", "", "", "", "", ""))
    rows.append((summary, "", "", "", "", "", ""))
    return verdict, blocked + below + old_notes, rows


def cmd_report(a) -> int:
    new = read_scores([a.score]) if a.score else {}
    old = read_scores(a.old)
    refused = old_refusals(a.old_runs_dir)
    verdicts = {}
    for paper in a.papers:
        verdict, reasons, rows = paper_report(a, paper, new, old, refused)
        verdicts[paper] = verdict
        print(f"== {paper}: {verdict}")
        print(
            table(
                (
                    "copy",
                    "found (code) of 10",
                    "chance hits",
                    "net",
                    "comments",
                    "WRONG",
                    "sheet",
                ),
                rows[:-2],
            )
        )
        print(rows[-1][0])
        for r in reasons:
            print(f"  - {r}")
        print()
    print(table(("paper", "verdict"), list(verdicts.items())))
    ok = bool(verdicts) and all(v == PASS for v in verdicts.values())
    print(
        f"DONE GATE: {'PASS' if ok else 'NOT PASSED'} ({sum(v == PASS for v in verdicts.values())} of {len(verdicts)} papers PASS)"
    )
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ switches


def _unscored(words) -> bool:
    """The Local-only words mark it as not scored (the app's own phrases: "rough draft", "not yet scored")."""
    said = str(words or "").lower()
    return "rough draft" in said or "not yet scored" in said


def cmd_switches(a) -> int:
    c = driver.Client(a.base_url, driver.read_token(a.token_file))
    code, m = c.json("GET", "/api/reviews/method")
    m = m if code == 200 and isinstance(m, dict) else {}
    checks = [
        ("method route answers", code == 200, f"HTTP {code}"),
        ("method is general", m.get("method") == "general", repr(m.get("method", NM))),
        ("old engine off", m.get("old_engine") is False, repr(m.get("old_engine", NM))),
        # today's rule (since update 9; the planner's 26 Nov order): Local only is OFFERED and labelled as unscored (a rough
        # draft); the rule before update 9 was "Local only not available"
        (
            "Local only offered, labelled a rough draft",
            m.get("local_available") is True and _unscored(m.get("local_words")),
            f"{m.get('local_available', NM)!r}, words {'say' if _unscored(m.get('local_words')) else 'do NOT say'} unscored",
        ),
    ]
    code, plan = c.json(
        "GET",
        "/api/reviews/plan",
        params={"submittal_document_id": a.datasheet_id, "engine": "automatic"},
    )
    plan = plan if code == 200 and isinstance(plan, dict) else {}
    checks.append(
        (
            "datasheet plan says general",
            plan.get("method") == "general",
            f"HTTP {code}, method {plan.get('method', NM)!r}",
        )
    )
    print(
        table(
            ("check", "result", "seen"),
            [(n, "PASS" if ok else "FAIL", seen) for n, ok, seen in checks],
        )
    )
    ok = all(x[1] for x in checks)
    print(f"SWITCHES GATE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("switches", help="check 0: the app runs the general review")
    s.add_argument("--base-url", required=True)
    s.add_argument("--token-file", required=True)
    s.add_argument("--datasheet-id", required=True)
    f = sub.add_parser(
        "found", help="checks 1 and 2: found >= 7 of 10 and better than the old engine"
    )
    f.add_argument("--score", required=True)
    f.add_argument(
        "--old", nargs="+", default=[], help="old engine score files or folders"
    )
    f.add_argument(
        "--old-runs-dir",
        default=None,
        help="the driver's --old-engine out folder (refused runs count as 0)",
    )
    f.add_argument("--papers", nargs="+", default=list(PAPERS))
    f.add_argument("--copies", nargs="+", default=list(SCORED_COPIES))
    f.add_argument("--min-found", type=float, default=MIN_FOUND)
    rp = sub.add_parser(
        "report",
        help="one table per paper, every result shown: PASS, BELOW TARGET or NOT MEASURED",
    )
    rp.add_argument(
        "--score",
        default=None,
        help="the score command's output for the new method (missing: NOT MEASURED)",
    )
    rp.add_argument(
        "--score-dir",
        required=True,
        help="the driver's --out folder (run files, comments, sheets)",
    )
    rp.add_argument("--judge-dir", required=True)
    rp.add_argument(
        "--old", nargs="+", default=[], help="old engine score files or folders"
    )
    rp.add_argument("--old-runs-dir", default=None)
    rp.add_argument("--papers", nargs="+", default=list(PAPERS))
    rp.add_argument("--copies", nargs="+", default=list(SCORED_COPIES))
    rp.add_argument("--min-found", type=float, default=MIN_FOUND)
    al = sub.add_parser("alarms", help="check 3: at most 1 WRONG in 10 comments")
    al.add_argument("--score-dir", required=True)
    al.add_argument("--judge-dir", required=True)
    al.add_argument("--papers", nargs="+", default=list(PAPERS))
    al.add_argument("--copies", nargs="+", default=list(SCORED_COPIES))
    a = ap.parse_args(argv)
    try:
        return {
            "switches": cmd_switches,
            "found": cmd_found,
            "alarms": cmd_alarms,
            "report": cmd_report,
        }[a.cmd](a)
    except driver.Refused as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
