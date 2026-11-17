"""The rehearsal gate for a live update (owner order, 17 Nov 2026). READ ONLY: it reads the app's own routes and two files.

Owner order, word for word: "add the rehearsal gate: no live update if any paper's rules asked or comments drop by more than 30%,
go to zero, or WRONG goes up."

Why: on 17 Nov a live update passed every count check (page = database = file) and the bench, yet the pump review afterwards asked
0 rules and fell from 244 points to 30. Counts that agree with each other do not catch a review that silently stops checking; this
gate compares each paper's review BEFORE the update (live) with the same paper re-reviewed on the rehearsal copy AFTER it.

HOW TO USE IT (the lead, before every live update):

  1. On the LIVE app, before the update (app running), for the papers the update touches:
       python scripts/rehearsal_gate.py snapshot --base-url http://127.0.0.1:<live port> --token-file <file> \\
           --papers PUMP=<doc id> VALVE=<doc id> --out live.json
  2. On the REHEARSAL copy, after installing the update there AND re-running each touched paper's review there:
       python scripts/rehearsal_gate.py snapshot --base-url http://127.0.0.1:<rehearsal port> --token-file <file> \\
           --papers PUMP=<doc id> VALVE=<doc id> --out rehearsal.json
  3. Read every comment of both and write the KEEP/WEAK/WRONG tables (<PAPER>-KWW.md with a line "KEEP n / WEAK n / WRONG n"),
     or a json {"PUMP": {"keep": n, "weak": n, "wrong": n}, ...} for each side. Then:
       python scripts/rehearsal_gate.py compare --live live.json --rehearsal rehearsal.json \\
           --kww-live <dir or json> --kww-rehearsal <dir or json> [--accept PUMP:points:"<why this drop is right>"]
     Exit 0 only when every row passes. The live update script runs the same `compare` in its step 0 and stops on exit 1.

The token file holds a bearer token the caller obtained by signing in; this script never reads, asks for or prints a password,
and never prints the token. The base URL must be this machine (127.0.0.1, localhost or ::1). The snapshot holds ids, counts and
the app's own fixed reason words only, never document text.

What `compare` refuses (exit 1), per paper and per metric (rules asked, comments, points):
  * the rehearsal value is 0 while live was above 0 ("went to zero");
  * the rehearsal value is more than 30% below live;
  * 0 on both sides (a review that checks nothing cannot be told from a broken one);
  * a value that could not be read on either side (NOT MEASURED; missing == missing never passes);
  * WRONG (from the KEEP/WEAK/WRONG tables) is higher in the rehearsal than live, or could not be read;
  * the rehearsal shows the same review run as live (the paper was not re-reviewed on the copy, so nothing was compared).
`--accept <paper>:<metric>:<reason>` turns ONE refusal into ACCEPTED, printed with its reason: the gate is never bypassed silently.

`history` (the general-review update, DONE-MEANS check 5): snapshot live BEFORE the update and the copy AFTER it WITHOUT
re-reviewing, then
       python scripts/rehearsal_gate.py history --live live.json --rehearsal rehearsal.json [--accept PAPER:<row>:"<why>"]
It refuses (exit 1) unless, per paper: the copy shows the SAME old run ids; rules asked, comments and points are EXACTLY equal
(0 on both sides refuses, missing is NOT MEASURED); every old CRS file (team, contractor) has the same page count and rows; and
the copy's GET /api/reviews/papers/{id}/history lists every old run as "earlier version". The snapshot now also keeps the history
route's run list (ids, version and part words, status, points: no text); live, before the update, has no such route and that
error is kept in its `errors`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "rehearsal-gate-snapshot/1"
#: The metrics compared for every paper, in the order the table prints them.
METRICS = ("rules_asked", "comments", "points")
WRONG = "wrong"
FRESH = "fresh_runs"
ALL_ROWS = (*METRICS, WRONG, FRESH)
#: More than this share below live refuses (owner: "drop by more than 30%").
MAX_DROP_PERCENT = 30
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TILES = ("not_met", "questions", "met", "does_not_apply")
_KWW_LINE = re.compile(
    r"KEEP\s+(\d+)\s*/\s*WEAK\s+(\d+)\s*/\s*WRONG\s+(\d+)", re.IGNORECASE
)
_WORD_LIMIT = 300  # a reason the app wrote is kept to this many characters


# ------------------------------------------------------------------ snapshot


class Client:
    """GET the app's own JSON routes with a bearer token; never through a proxy, never to another machine."""

    def __init__(self, base_url: str, token: str, timeout: float = 180.0):
        parts = urllib.parse.urlsplit(base_url)
        if (
            parts.scheme not in ("http", "https")
            or (parts.hostname or "") not in LOCAL_HOSTS
        ):
            raise ValueError(
                "the base URL must be this machine: http://127.0.0.1:<port> (or localhost, ::1)"
            )
        self.base = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str, params: dict | None = None):
        """(json, None) or (None, a short error naming the route and the status: never the token)."""
        url = (
            self.base
            + path
            + (("?" + urllib.parse.urlencode(params)) if params else "")
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as exc:
            return None, f"GET {path}: HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return None, f"GET {path}: {type(exc).__name__}"


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _words(value) -> str | None:
    return value[:_WORD_LIMIT] if isinstance(value, str) and value else None


def _points_part(listing: dict) -> dict:
    """Points, comments, tiles, runs and found-during-review from GET /papers/{doc}/points (counts only)."""
    points = listing.get("points")
    n_points = _int(listing.get("of"))
    if n_points is None and isinstance(points, list):
        n_points = len(points)
    tiles = (listing.get("counts") or {}).get("tiles") or {}
    per_tile = (
        {t: _int((tiles.get(t) or {}).get("total")) for t in TILES} if tiles else None
    )
    runs = listing.get("runs") or {}
    return {
        "runs": {
            "rule_check": runs.get("rule_check"),
            "ai_review": runs.get("ai_review"),
        },
        "points": n_points,
        "comments": _int(listing.get("comment_count")),
        "points_per_tile": per_tile,
        "found_during_review": _int(listing.get("found_during_review")),
    }


def _rules_part(rules: dict) -> dict:
    """Rules asked and left out (with the app's fixed reason words) from GET /runs/{ai}/rules-used: counts only, no quote."""
    asked = rules.get("asked")
    left_out = rules.get("left_out")
    by_reason = {
        str(k): _int(v) for k, v in (rules.get("left_out_counts") or {}).items()
    }
    return {
        "rules_asked": len(asked) if isinstance(asked, list) else None,
        "rules_left_out": {
            "total": len(left_out) if isinstance(left_out, list) else None,
            "by_reason": by_reason,
            "missing_books": len(rules.get("missing_books") or []),
            "stop_reason": _words(rules.get("stop_reason")),
        },
    }


def _summary_part(summary: dict) -> dict:
    by_class = {
        str(k): _int(v) for k, v in (summary.get("counts_by_class") or {}).items()
    }
    return {
        "counts_by_class": by_class,
        "not_reviewed": _int(summary.get("not_reviewed")),
        "stop_reason": _words(summary.get("stop_reason")),
        "mode": _words(summary.get("mode")),
    }


def _not_applied(run: dict) -> int | None:
    """The run's requirements left out as about other equipment: the sum of the grouped counts (no subject words kept)."""
    lines = run.get("requirements_not_applied")
    if not isinstance(lines, list):
        return None
    counts = [
        _int(line.get("count")) if isinstance(line, dict) else None for line in lines
    ]
    return sum(1 if n is None else n for n in counts)


def _crs_part(check: dict) -> dict:
    out = {}
    for copy, report in check.items():
        if isinstance(report, dict):
            out[copy] = {
                "ok": report.get("ok"),
                "page": _int(report.get("page")),
                "rows_in_file": _int(report.get("rows_in_file")),
                "missing": len(report.get("missing") or []),
            }
    return out


def snapshot_paper(client: Client, document_id: str) -> dict:
    """Everything the gate compares for one paper, read through the app's own routes. A route that cannot be read leaves its
    values null (the compare then says NOT MEASURED) and its error in `errors`."""
    doc = urllib.parse.quote(document_id, safe="")
    paper: dict = {"document_id": document_id, "errors": []}
    listing, err = client.get(f"/api/reviews/papers/{doc}/points")
    if err:
        paper["errors"].append(err)
    paper.update(
        _points_part(listing or {})
    )  # an unread listing leaves every count null, never 0
    runs, err = client.get(
        "/api/reviews/runs", {"document_id": document_id, "limit": 5}
    )
    paper["latest_runs"] = [
        {
            "review_run_id": r.get("review_run_id"),
            "status": r.get("status"),
            "created_at": r.get("created_at"),
        }
        for r in (runs or {}).get("runs") or []
    ]
    if err:
        paper["errors"].append(err)
    paper["requirements_not_applied"] = {}
    for kind, run_id in paper["runs"].items():
        if run_id:
            detail, err = client.get(
                f"/api/reviews/runs/{urllib.parse.quote(run_id, safe='')}"
            )
            paper["requirements_not_applied"][kind] = (
                _not_applied(detail) if detail else None
            )
            if err:
                paper["errors"].append(err)
    ai = paper["runs"].get("ai_review")
    paper.update({"rules_asked": None, "rules_left_out": None, "ai_summary": None})
    if ai:
        ai_q = urllib.parse.quote(ai, safe="")
        rules, err = client.get(f"/api/reviews/runs/{ai_q}/rules-used")
        if rules:
            paper.update(_rules_part(rules))
        if err:
            paper["errors"].append(err)
        summary, err = client.get(f"/api/reviews/runs/{ai_q}/agent/summary")
        paper["ai_summary"] = _summary_part(summary) if summary else None
        if err:
            paper["errors"].append(err)
    check, err = client.get(f"/api/reviews/papers/{doc}/crs/check")
    paper["crs_check"] = _crs_part(check) if check else None
    if err:
        paper["errors"].append(err)
    # the history route exists only after the general review lands: before it, the error is kept and `history` uses the other side
    history, err = client.get(f"/api/reviews/papers/{doc}/history")
    paper["history"] = _history_part(history) if isinstance(history, dict) else None
    if err:
        paper["errors"].append(err)
    return paper


def _history_part(history: dict) -> list[dict] | None:
    """The runs GET /papers/{doc}/history lists: ids, the app's version and part words, status and points (no text)."""
    runs = history.get("runs")
    if not isinstance(runs, list):
        return None
    return [
        {
            "run_id": r.get("run_id"),
            "version": _words(r.get("version")),
            "part": _words(r.get("part")),
            "status": _words(r.get("status")),
            "points": _int(r.get("points")),
            "files": len(r.get("files") or []),
        }
        for r in runs
        if isinstance(r, dict)
    ]


def parse_papers(items: list[str]) -> dict[str, str]:
    """`LABEL=doc id` (the label names the KEEP/WEAK/WRONG file) or a bare doc id (then the label is the id)."""
    out: dict[str, str] = {}
    for item in items:
        label, sep, doc = item.partition("=")
        label, doc = (label, doc) if sep else (item, item)
        if not label.strip() or not doc.strip():
            raise ValueError(
                f"a paper must be LABEL=<doc id> or <doc id>, got {item!r}"
            )
        if label.strip() in out:
            raise ValueError(f"the paper label {label.strip()!r} is given twice")
        out[label.strip()] = doc.strip()
    return out


def cmd_snapshot(args) -> int:
    try:
        papers = parse_papers(args.papers)
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("the token file is empty")
        client = Client(args.base_url, token)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    snap = {
        "schema": SCHEMA,
        "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app": urllib.parse.urlsplit(args.base_url).netloc,
        "papers": {label: snapshot_paper(client, doc) for label, doc in papers.items()},
    }
    Path(args.out).write_text(
        json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for label, p in snap["papers"].items():
        print(
            f"{label}: rules asked {_show(p.get('rules_asked'))}, comments {_show(p.get('comments'))}, "
            f"points {_show(p.get('points'))}, errors {len(p['errors'])}"
        )
    print(f"written: {args.out}")
    return 0


# ------------------------------------------------------------------- compare


def _show(value) -> str:
    return "NOT MEASURED" if value is None else str(value)


def read_kww(source: str | None, labels) -> dict[str, int | None]:
    """WRONG per paper label from a directory of <LABEL>-KWW.md files (the first "KEEP n / WEAK n / WRONG n" line) or a json
    {label: {keep, weak, wrong}}. A paper with no readable table is None (NOT MEASURED), never 0."""
    out: dict[str, int | None] = dict.fromkeys(labels)
    if not source:
        return out
    path = Path(source)
    if path.is_dir():
        files = {f.name[: -len("-KWW.md")].lower(): f for f in path.glob("*-KWW.md")}
        for label in labels:
            f = files.get(label.lower())
            m = _KWW_LINE.search(f.read_text(encoding="utf-8")) if f else None
            out[label] = int(m.group(3)) if m else None
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    lowered = (
        {str(k).lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
    )
    for label in labels:
        entry = lowered.get(label.lower())
        out[label] = _int(entry.get("wrong")) if isinstance(entry, dict) else None
    return out


def judge(live, rehearsal) -> tuple[bool, str]:
    """(passes, reason) for one count. Integers only: the 30% line is compared without rounding."""
    if live is None or rehearsal is None:
        side = "live" if live is None else "rehearsal"
        if live is None and rehearsal is None:
            side = "either side"
        return False, f"NOT MEASURED: could not be read on {side}"
    if live > 0 and rehearsal == 0:
        return False, "went to zero"
    if live == 0 and rehearsal == 0:
        return (
            False,
            "0 on both sides: a review that checks nothing cannot be told from a broken one",
        )
    if (live - rehearsal) * 100 > MAX_DROP_PERCENT * live:
        return False, f"dropped by more than {MAX_DROP_PERCENT}%"
    return True, "within the limit" if rehearsal < live else "same or higher"


def judge_wrong(live, rehearsal) -> tuple[bool, str]:
    if live is None or rehearsal is None:
        return False, "NOT MEASURED: no KEEP/WEAK/WRONG table read for " + (
            "live" if live is None else "the rehearsal"
        )
    if rehearsal > live:
        return False, "WRONG went up"
    return True, "not higher"


def judge_fresh(
    live_runs: dict | None, rehearsal_runs: dict | None
) -> tuple[bool, str]:
    """The rehearsal must show a review run that is NOT the live one: the same run on both sides compares nothing."""
    live_runs, rehearsal_runs = live_runs or {}, rehearsal_runs or {}
    present = {k: v for k, v in rehearsal_runs.items() if v}
    if not present:
        return False, "NOT MEASURED: the rehearsal shows no review run"
    same = sorted(k for k, v in present.items() if v == live_runs.get(k))
    if same:
        return (
            False,
            f"the rehearsal shows the live run ({', '.join(same)}): re-run the review on the copy",
        )
    return True, "new runs on the copy"


def change_percent(live, rehearsal) -> str:
    if not isinstance(live, int) or not isinstance(rehearsal, int) or live == 0:
        return "n/a"
    return f"{(rehearsal - live) * 100 / live:+.1f}%"


def parse_accepts(
    items: list[str], allowed: tuple[str, ...] = ALL_ROWS
) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for item in items or []:
        parts = item.split(":", 2)
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise ValueError(
                f"--accept must be <paper>:<metric>:<reason>, got {item!r}"
            )
        paper, metric, reason = (p.strip() for p in parts)
        if metric not in allowed:
            raise ValueError(
                f"--accept metric must be one of {', '.join(allowed)}, got {metric!r}"
            )
        out[(paper.lower(), metric)] = reason
    return out


# ------------------------------------------------------------------- history (check 5: old reviews unchanged)

#: The rows `history` prints per paper, in order.
SAME_RUNS = "old_runs"
CRS_FILES = "crs_files"
LISTED = "history_listed"
HISTORY_ROWS = (SAME_RUNS, *METRICS, CRS_FILES, LISTED)
#: The version word the history route gives an old run (CONTRACT section D).
EARLIER = "earlier version"


def judge_same(live, rehearsal) -> tuple[bool, str]:
    """The old review's count must be EXACTLY the same on the copy (it was not re-reviewed). Missing is NOT MEASURED; 0 on
    both sides is not a pass (a review that checks nothing cannot be told from a broken one)."""
    if live is None or rehearsal is None:
        side = (
            "either side"
            if live is None and rehearsal is None
            else ("live" if live is None else "rehearsal")
        )
        return False, f"NOT MEASURED: could not be read on {side}"
    if live != rehearsal:
        return False, f"changed: live {live}, rehearsal {rehearsal}"
    if live == 0:
        return (
            False,
            "0 on both sides: a review that checks nothing cannot be told from a broken one",
        )
    return True, "same"


def judge_same_runs(
    live_runs: dict | None, rehearsal_runs: dict | None
) -> tuple[bool, str]:
    live = {k: v for k, v in (live_runs or {}).items() if v}
    if not live:
        return False, "NOT MEASURED: live shows no review run"
    differ = sorted(k for k, v in live.items() if (rehearsal_runs or {}).get(k) != v)
    if differ:
        return (
            False,
            f"the copy shows another run for {', '.join(differ)} (re-reviewed, or the old run is gone)",
        )
    return True, "the same run ids"


def judge_crs(live: dict | None, rehearsal: dict | None) -> tuple[bool, str]:
    """Every old CRS file (team, contractor) reads back with the same page count and the same rows on the copy."""
    if not live:
        return False, "NOT MEASURED: live CRS check could not be read"
    if not rehearsal:
        return False, "NOT MEASURED: rehearsal CRS check could not be read"
    team = (live.get("team") or {}).get("rows_in_file")
    if not isinstance(team, int) or team == 0:
        return False, "NOT MEASURED: live team file has no rows"
    bad = []
    for copy, a in sorted(live.items()):
        b = rehearsal.get(copy) or {}
        for key in ("page", "rows_in_file"):
            if a.get(key) is None or a.get(key) != b.get(key):
                bad.append(f"{copy} {key} {_show(a.get(key))} -> {_show(b.get(key))}")
    return (
        (False, "changed: " + "; ".join(bad))
        if bad
        else (True, "same rows in every file")
    )


def judge_listed(live_runs: dict | None, history: list | None) -> tuple[bool, str]:
    if history is None:
        return False, "NOT MEASURED: the rehearsal's history route could not be read"
    live = {k: v for k, v in (live_runs or {}).items() if v}
    if not live:
        return False, "NOT MEASURED: live shows no review run"
    by_id = {h.get("run_id"): h for h in history if isinstance(h, dict)}
    bad = []
    for kind, run_id in sorted(live.items()):
        h = by_id.get(run_id)
        if h is None:
            bad.append(f"{kind} not listed")
        elif (h.get("version") or "").lower() != EARLIER:
            bad.append(f"{kind} listed as {h.get('version')!r}")
    return (
        (False, "; ".join(bad))
        if bad
        else (True, f'every old run listed as "{EARLIER}"')
    )


def history_rows(live: dict, rehearsal: dict, accepts: dict) -> list[dict]:
    lp, rp = live.get("papers") or {}, rehearsal.get("papers") or {}
    rows = []
    for paper in sorted(set(lp) | set(rp)):
        a, b = lp.get(paper) or {}, rp.get(paper) or {}
        checks = [
            (SAME_RUNS, None, None, judge_same_runs(a.get("runs"), b.get("runs")))
        ]
        checks += [
            (m, a.get(m), b.get(m), judge_same(a.get(m), b.get(m))) for m in METRICS
        ]
        checks.append(
            (CRS_FILES, None, None, judge_crs(a.get("crs_check"), b.get("crs_check")))
        )
        checks.append(
            (LISTED, None, None, judge_listed(a.get("runs"), b.get("history")))
        )
        for metric, lv, rv, (ok, reason) in checks:
            outcome = "PASS" if ok else "REFUSE"
            accepted = accepts.get((paper.lower(), metric))
            if not ok and accepted:
                outcome, reason = "ACCEPTED", f"{reason}; accepted: {accepted}"
            rows.append(
                {
                    "paper": paper,
                    "metric": metric,
                    "live": lv,
                    "rehearsal": rv,
                    "change": change_percent(lv, rv) if metric in METRICS else "",
                    "outcome": outcome,
                    "reason": reason,
                }
            )
    return rows


def cmd_history(args) -> int:
    """Check 5 of the general-review update: the copy, NOT re-reviewed, still shows every old review exactly as live did."""
    try:
        live, rehearsal = _load_snapshot(args.live), _load_snapshot(args.rehearsal)
        accepts = parse_accepts(args.accept, HISTORY_ROWS)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    if not (live.get("papers") or rehearsal.get("papers")):
        print("REFUSED: NOT MEASURED: neither snapshot names a paper")
        return 1
    rows = history_rows(live, rehearsal, accepts)
    print(render(rows, blank=(SAME_RUNS, CRS_FILES, LISTED)))
    refused = [r for r in rows if r["outcome"] == "REFUSE"]
    accepted = sum(1 for r in rows if r["outcome"] == "ACCEPTED")
    if refused:
        print(
            f"HISTORY: REFUSED ({len(refused)} of {len(rows)} rows refuse; {accepted} accepted). No live update."
        )
        return 1
    print(f"HISTORY: PASS ({len(rows)} rows; {accepted} accepted with a reason).")
    return 0


def gate_rows(
    live: dict, rehearsal: dict, kww_live: dict, kww_rehearsal: dict, accepts: dict
) -> list[dict]:
    """One row per paper and metric: {paper, metric, live, rehearsal, change, outcome (PASS/REFUSE/ACCEPTED), reason}."""
    lp, rp = live.get("papers") or {}, rehearsal.get("papers") or {}
    rows = []
    for paper in sorted(set(lp) | set(rp)):
        a, b = lp.get(paper) or {}, rp.get(paper) or {}
        checks = [(m, a.get(m), b.get(m), judge(a.get(m), b.get(m))) for m in METRICS]
        checks.append(
            (
                WRONG,
                kww_live.get(paper),
                kww_rehearsal.get(paper),
                judge_wrong(kww_live.get(paper), kww_rehearsal.get(paper)),
            )
        )
        checks.append((FRESH, None, None, judge_fresh(a.get("runs"), b.get("runs"))))
        for metric, lv, rv, (ok, reason) in checks:
            outcome = "PASS" if ok else "REFUSE"
            accepted = accepts.get((paper.lower(), metric))
            if not ok and accepted:
                outcome, reason = "ACCEPTED", f"{reason}; accepted: {accepted}"
            rows.append(
                {
                    "paper": paper,
                    "metric": metric,
                    "live": lv,
                    "rehearsal": rv,
                    "change": change_percent(lv, rv) if metric != FRESH else "",
                    "outcome": outcome,
                    "reason": reason,
                }
            )
    return rows


def render(rows: list[dict], blank: tuple[str, ...] = (FRESH,)) -> str:
    head = ("paper", "metric", "live", "rehearsal", "change %", "result", "reason")
    body = [
        (
            r["paper"],
            r["metric"],
            "" if r["metric"] in blank else _show(r["live"]),
            "" if r["metric"] in blank else _show(r["rehearsal"]),
            r["change"],
            r["outcome"],
            r["reason"],
        )
        for r in rows
    ]
    widths = [max(len(str(x[i])) for x in (head, *body)) for i in range(len(head) - 1)]
    lines = []
    for row in (head, *body):
        lines.append(
            "  ".join(str(c).ljust(w) for c, w in zip(row[:-1], widths, strict=True))
            + "  "
            + row[-1]
        )
    return "\n".join(lines)


def _load_snapshot(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(f"{path} is not a rehearsal gate snapshot ({SCHEMA})")
    return data


def cmd_compare(args) -> int:
    try:
        live, rehearsal = _load_snapshot(args.live), _load_snapshot(args.rehearsal)
        accepts = parse_accepts(args.accept)
        labels = sorted(
            set(live.get("papers") or {}) | set(rehearsal.get("papers") or {})
        )
        kww_live, kww_rehearsal = (
            read_kww(args.kww_live, labels),
            read_kww(args.kww_rehearsal, labels),
        )
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 1
    if not labels:
        print("REFUSED: NOT MEASURED: neither snapshot names a paper")
        return 1
    rows = gate_rows(live, rehearsal, kww_live, kww_rehearsal, accepts)
    print(render(rows))
    used = {
        (r["paper"].lower(), r["metric"]) for r in rows if r["outcome"] == "ACCEPTED"
    }
    for paper, metric in sorted(set(accepts) - used):
        print(f"note: --accept {paper}:{metric} matched no refusal and changed nothing")
    refused = [r for r in rows if r["outcome"] == "REFUSE"]
    accepted = sum(1 for r in rows if r["outcome"] == "ACCEPTED")
    if refused:
        print(
            f"GATE: REFUSED ({len(refused)} of {len(rows)} rows refuse; {accepted} accepted). No live update."
        )
        return 1
    print(f"GATE: PASS ({len(rows)} rows; {accepted} accepted with a reason).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="The rehearsal gate for a live update (see the top of this file)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser(
        "snapshot", help="read each paper's review counts from a running app"
    )
    s.add_argument("--base-url", required=True)
    s.add_argument(
        "--token-file",
        required=True,
        help="a file holding a bearer token (never a password)",
    )
    s.add_argument(
        "--papers",
        nargs="+",
        required=True,
        help="LABEL=<doc id> (label as in <LABEL>-KWW.md) or <doc id>",
    )
    s.add_argument("--out", required=True)
    c = sub.add_parser(
        "compare", help="refuse when a paper's review drops on the rehearsal copy"
    )
    c.add_argument("--live", required=True)
    c.add_argument("--rehearsal", required=True)
    c.add_argument(
        "--kww-live",
        help="directory of <LABEL>-KWW.md files or a json {label: {keep, weak, wrong}}",
    )
    c.add_argument("--kww-rehearsal", help="the same for the rehearsal")
    c.add_argument(
        "--accept",
        action="append",
        default=[],
        help="<paper>:<metric>:<reason>, one refusal accepted",
    )
    h = sub.add_parser(
        "history",
        help="check 5: the copy, not re-reviewed, shows every old review exactly as live",
    )
    h.add_argument("--live", required=True)
    h.add_argument("--rehearsal", required=True)
    h.add_argument(
        "--accept",
        action="append",
        default=[],
        help="<paper>:<row>:<reason>, one refusal accepted",
    )
    args = ap.parse_args(argv)
    return {"snapshot": cmd_snapshot, "compare": cmd_compare, "history": cmd_history}[
        args.cmd
    ](args)


if __name__ == "__main__":
    sys.exit(main())
