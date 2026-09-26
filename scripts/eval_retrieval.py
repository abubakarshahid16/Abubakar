"""Retrieval tripwire: measure recall@5, recall@10 and MRR on a fixed case set.

WHY THIS EXISTS. Later phases of the master order change answering, review and
export. None of them intend to change retrieval - but retrieval is upstream of
all of them, and a silent degradation there is invisible in every downstream
test. This harness is the tripwire. It does not improve retrieval and must
never be used to tune it: it records what retrieval does today and fails the
build when a later run does worse on the same questions.

THE CASE SET. `gold/R1-SAMPLE-30.csv`, 30 data rows.

    requirement_text  -> the QUERY put to search()
    standard          -> the target DOCUMENT (a filename, resolved to a doc id)
    page              -> the target PAGE
    clause            -> recorded for the reader, NOT scored (see SCORING)

  NOT AN ENGINEER-LABELLED SET. The columns `answerable_from_this_datasheet`,
  `engineer` and `note` are blank in this file. They belong to a different
  exercise - deciding whether a datasheet should have answered a requirement -
  and a retrieval eval neither needs nor uses them. Nobody reading a result
  from this script may describe it as engineer-verified; the output header says
  so in as many words.

SCORING, exactly as implemented.

  A returned hit COUNTS AS CORRECT when both hold:
      hit["document_id"] == the target document's id, and
      hit["page_start"] <= target page <= hit["page_end"]
  Page containment, not clause-string matching. The gold sheet's clause numbers
  are the engineer's reading of the standard and are not guaranteed to appear
  in the chunk text at all, so matching on them would score the chunker's
  heading extraction rather than retrieval.

  recall@k = (resolved cases with at least one correct hit in the first k) /
             (resolved cases). search() is called ONCE per case with limit=10;
             @5 is scored from the first five of that SAME ranking. Calling it
             twice would risk two different rankings and score neither.

  MRR      = mean over resolved cases of 1/(rank of the first correct hit),
             rank counted from 1. A case with no correct hit contributes 0.
             The mean's denominator is the resolved cases, never the cases
             that happened to succeed.

  UNRESOLVED cases - a `standard` filename with no row in `documents` - are
  REPORTED, never dropped. They are excluded from every metric because there is
  no target to score against, and the count is carried in the output so a
  recall figure can never be read without knowing how many questions it left
  out.

TWO TRAPS IN THE SEARCH CONTRACT, both handled here.

  1. `hits` IS TRUNCATED TO `limit`; `total` COUNTS THE WHOLE SURVIVING POOL.
     A correct passage sitting at rank 11 is not in `hits` and is not in
     `shortlist_excluded` either - it was not dropped, only not asked for. This
     script never treats total-minus-hits as a loss, and a miss that could be
     such a passage is classified `possibly_beyond_limit` rather than as a
     ranking failure, because from a limit=10 call it genuinely cannot be told.

  2. `apply_relevance_floor` AND THE DOCUMENT CAP REMOVE PASSAGES BEFORE THE
     CALLER SEES THEM. A correct passage can be retrieved, scored, and then
     cut. That is a DIFFERENT DEFECT from a correct passage that ranked badly,
     and it has a different fix. So for every miss this script looks the target
     page up in `shortlist_excluded` (joining chunk ids back to their page
     range, read-only) and in `document_census`, and reports which of these
     happened:

       filtered:<reason>   a chunk covering the target page was evicted, with
                           search()'s own reason - below_relevance_floor,
                           document_cap, displaced_before_rerank,
                           near_duplicate, not_retrievable, ...
       possibly_beyond_limit
                           the target document survived into the final pool but
                           no correct hit is in the top 10, and the pool is
                           larger than 10 - trap 1, unverifiable from here
       page_never_a_candidate
                           the target document contributed candidates to the
                           fusion pool, but no candidate covered the target
                           page: the chunk was never retrieved
       document_never_retrieved
                           the target document contributed nothing at all

     This distinction is the most useful thing the harness produces. A drop in
     recall whose misses are `filtered:below_relevance_floor` points at the
     floor; the same drop with `page_never_a_candidate` points at the index.

REGRESSION. The run is compared against the most recent previous
`.cowork/eval/retrieval-*.json` BY FILE MTIME, and only against one whose
`gold_sha256` matches this run's. A different case set is INCOMPARABLE, not a
regression: the script says so and exits 0. Otherwise any real decrease in
recall@5, recall@10 or MRR - beyond 1e-9, which is float noise and nothing
else - exits 1 naming the metric and the drop. That tolerance is not a knob.

PRIVACY AND SAFETY. Read-only throughout: the database is opened
`file:...?mode=ro`. Nothing is written anywhere but `.cowork/eval/`, which is
gitignored, because the queries are verbatim client standard text and the
results carry client document filenames. No network, no model download.

    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --previous <a specific earlier json>
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import hashlib
import json
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import live_guard  # noqa: E402
from app import search as search_mod  # noqa: E402
from app.config import settings  # noqa: E402

#: The one case set this tripwire is defined over. A different file is a
#: different measurement and is not comparable to a recorded run of this one.
GOLD = REPO / "gold" / "R1-SAMPLE-30.csv"

#: Gitignored (`.cowork/*` in .gitignore). Client-derived output lives here and
#: nowhere else.
OUT_DIR = REPO / ".cowork" / "eval"

LIMIT = 10
CUTOFFS = (5, 10)

#: Any real decrease fails. Float comparison noise only - NEVER widened to
#: absorb a genuine drop.
TOLERANCE = 1e-9

HEADER = "owner-reviewed, internally measured, NOT engineer-verified"

#: B6 / ADR-0022: questions the corpus should NOT answer. Generic engineering
#: topics outside a submittal-review library, never client text. A healthy
#: pipeline flags these low-confidence and scores them below the answered
#: cases; `--negatives FILE` (one query per line) replaces the list.
NEGATIVES = (
    "helicopter deck lighting levels",
    "cathodic protection anode spacing",
    "cable tray support spacing",
    "HVAC duct insulation thickness",
    "fire alarm panel battery autonomy",
)


def git_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip() or "unknown"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> list[dict]:
    """The 30 data rows.

    The sheet carries an instruction line for the engineer in place of a row;
    a row is a row only when `n` is a number, so a comment can never be scored
    as a question.
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cases = []
    for row in rows:
        n = (row.get("n") or "").strip()
        page = (row.get("page") or "").strip()
        if not n.isdigit():
            continue
        cases.append({
            "n": int(n),
            "query": (row.get("requirement_text") or "").strip(),
            "standard": (row.get("standard") or "").strip(),
            "clause": (row.get("clause") or "").strip(),
            "page": int(page) if page.isdigit() else None,
        })
    return cases


def open_db_readonly() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def filename_index(conn: sqlite3.Connection) -> dict[str, str]:
    """filename (casefolded) -> document id.

    Casefolded because the corpus holds both `SAES-W-016.PDF` and
    `SAES-A-133.pdf`; an exact-case join would report real documents as
    unresolved.
    """
    return {
        r["filename"].strip().casefold(): r["id"]
        for r in conn.execute("SELECT id, filename FROM documents")
    }


def chunk_pages(conn: sqlite3.Connection, chunk_ids: list[str]) -> dict[str, tuple]:
    """chunk id -> (page_start, page_end), for evicted chunks.

    `shortlist_excluded` carries no page range, so a miss cannot be attributed
    to the floor without this join. Read-only, and in batches so a long
    exclusion list does not blow the SQL variable limit.
    """
    pages: dict[str, tuple] = {}
    for i in range(0, len(chunk_ids), 500):
        batch = chunk_ids[i:i + 500]
        marks = ",".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT id, page_start, page_end FROM chunks WHERE id IN ({marks})",
            batch,
        )
        for r in rows:
            pages[r["id"]] = (r["page_start"], r["page_end"])
    return pages


def covers(page_start, page_end, page: int) -> bool:
    if page_start is None or page_end is None:
        return False
    return page_start <= page <= page_end


def classify_miss(conn, result: dict, doc_id: str, page: int) -> str:
    """Why this case has no correct hit in the top 10. See TRAP 2 in the module
    docstring - a filtered miss and a ranking miss are different defects."""
    excluded = result.get("shortlist_excluded") or []
    mine = [e for e in excluded if e.get("document_id") == doc_id]
    if mine:
        pages = chunk_pages(conn, [e["chunk_id"] for e in mine])
        reasons = sorted({
            e["reason"] for e in mine
            if covers(*pages.get(e["chunk_id"], (None, None)), page)
        })
        if reasons:
            return "filtered:" + "+".join(reasons)

    census = (result.get("document_census") or {}).get(doc_id)
    if census and census.get("shortlisted", 0) > 0 and result.get("total", 0) > LIMIT:
        return "possibly_beyond_limit"
    if census and census.get("candidates", 0) > 0:
        return "page_never_a_candidate"
    return "document_never_retrieved"


def run_cases(conn, cases: list[dict], docs: dict[str, str]) -> tuple[list, list]:
    allowed = search_mod.every_document_id()
    scored, unresolved = [], []
    for case in cases:
        doc_id = docs.get(case["standard"].casefold())
        if doc_id is None or case["page"] is None:
            unresolved.append({
                "n": case["n"],
                "standard": case["standard"],
                "page": case["page"],
                "why": "no document row for this filename"
                       if doc_id is None else "no usable page in the gold row",
            })
            continue

        started = time.perf_counter()
        result = search_mod.search(
            case["query"], limit=LIMIT,
            allowed_document_ids=allowed, rerank=True, dense=True,
        )
        latency = time.perf_counter() - started
        hits = result.get("hits") or []
        # B6: EVERY rank that covers the target, for precision@k; the first
        # one is the rank recall and MRR have always used.
        correct = [i for i, hit in enumerate(hits, start=1)
                   if hit.get("document_id") == doc_id
                   and covers(hit.get("page_start"), hit.get("page_end"), case["page"])]
        rank = correct[0] if correct else None

        scored.append({
            "n": case["n"],
            "query": case["query"][:120],
            "target_document": case["standard"],
            "target_document_id": doc_id,
            "target_page": case["page"],
            # Recorded for the reader only; nothing is scored on it.
            "gold_clause": case["clause"],
            "first_correct_rank": rank,
            "correct_ranks": correct,
            "top_rerank_score": hits[0].get("rerank_score") if hits else None,
            "latency_s": round(latency, 4),
            "hits_returned": len(hits),
            # TRAP 1: `total` is the surviving pool, not what came back.
            "pool_total": result.get("total"),
            "miss_cause": None if rank else classify_miss(
                conn, result, doc_id, case["page"]
            ),
        })
    return scored, unresolved


def metrics(scored: list[dict]) -> dict:
    n = len(scored)
    out: dict = {"resolved_cases": n}
    for k in CUTOFFS:
        found = sum(
            1 for c in scored
            if c["first_correct_rank"] is not None and c["first_correct_rank"] <= k
        )
        out[f"recall@{k}"] = (found / n) if n else 0.0
    out["mrr"] = (
        sum(1.0 / c["first_correct_rank"] for c in scored
            if c["first_correct_rank"] is not None) / n
    ) if n else 0.0
    # B6 / ADR-0022: precision@k = correct hits in the first k over k, averaged
    # over resolved cases. With one target page per case it cannot exceed the
    # share of the first k that a single page's chunks can fill - read it
    # beside recall, never alone. None rather than 0 when nothing was scored.
    for k in CUTOFFS:
        out[f"precision@{k}"] = (sum(
            sum(1 for r in c.get("correct_ranks") or [] if r <= k) / k
            for c in scored) / n) if n else None
    out.update(latency_summary([c["latency_s"] for c in scored if "latency_s" in c]))
    return out


def latency_summary(latencies: list[float]) -> dict:
    """p50 / p95 in milliseconds, or None each when nothing was timed."""
    if not latencies:
        return {"latency_p50_ms": None, "latency_p95_ms": None}
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"latency_p50_ms": round(statistics.median(ordered) * 1000, 1),
            "latency_p95_ms": round(p95 * 1000, 1)}


def run_negatives(queries: list[str]) -> list[dict]:
    """Each negative query's outcome: flagged low-confidence or empty, and the
    best score it still got. Nothing here is a target, so nothing is 'found'."""
    allowed = search_mod.every_document_id()
    out = []
    for query in queries:
        started = time.perf_counter()
        result = search_mod.search(query, limit=LIMIT, allowed_document_ids=allowed,
                                   rerank=True, dense=True)
        hits = result.get("hits") or []
        out.append({"query": query, "latency_s": round(time.perf_counter() - started, 4),
                    "flagged": bool(result.get("low_confidence")) or not hits,
                    "top_rerank_score": hits[0].get("rerank_score") if hits else None})
    return out


def negative_metrics(negatives: list[dict], scored: list[dict]) -> dict:
    """How the negatives separate from the answered cases. `separated` is True
    when every negative's best score is below every answered case's top score
    - None when either side has no scores to compare."""
    neg = [n["top_rerank_score"] for n in negatives if n["top_rerank_score"] is not None]
    pos = [c["top_rerank_score"] for c in scored
           if c.get("first_correct_rank") == 1 and c.get("top_rerank_score") is not None]
    return {
        "negative_queries": len(negatives),
        "negatives_flagged": sum(1 for n in negatives if n["flagged"]),
        "negative_best_score": max(neg) if neg else None,
        "answered_worst_top_score": min(pos) if pos else None,
        "separated": (max(neg) < min(pos)) if neg and pos else None,
    }


def previous_run(out_dir: Path, explicit: Path | None) -> dict | None:
    """The newest recorded run, by file mtime.

    CALLED BEFORE THIS RUN IS WRITTEN, which is what makes "excluding the one
    being written" true: at this moment the output path either does not exist
    or still holds an EARLIER run. Two runs at the same commit share a
    filename, so excluding that path by name instead would make a re-run
    compare against nothing and silently pass - the one case the tripwire is
    most likely to be used for.
    """
    if explicit is not None:
        return json.loads(explicit.read_text(encoding="utf-8"))
    if not out_dir.is_dir():
        return None
    files = list(out_dir.glob("retrieval-*.json"))
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8"))


def compare(current: dict, prior: dict | None) -> tuple[int, list[str]]:
    """Exit code plus the lines explaining it."""
    if prior is None:
        return 0, ["No previous run recorded. Nothing to compare; this run is the baseline."]
    if prior.get("gold_sha256") != current["gold_sha256"]:
        return 0, [
            "INCOMPARABLE: the previous run used a different case set "
            f"({prior.get('gold_sha256', '?')[:12]} vs "
            f"{current['gold_sha256'][:12]}). A different case set is not a "
            "regression. Exiting 0.",
        ]
    lines = [f"Comparing against run {prior.get('git_commit')} of {prior.get('generated_at')}."]
    fell = []
    for key in (*(f"recall@{k}" for k in CUTOFFS), "mrr"):
        now, before = current["metrics"].get(key, 0.0), prior.get("metrics", {}).get(key)
        if before is None:
            lines.append(f"  {key}: {now:.4f} (previous run did not record it)")
            continue
        delta = now - before
        lines.append(f"  {key}: {before:.4f} -> {now:.4f} ({delta:+.4f})")
        if delta < -TOLERANCE:
            fell.append(f"{key} fell by {abs(delta):.4f} ({before:.4f} -> {now:.4f})")
    if fell:
        lines.append("REGRESSION: " + "; ".join(fell))
        return 1, lines
    lines.append("No regression.")
    return 0, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--previous", type=Path, default=None,
        help="compare against this exact earlier result file instead of the "
             "newest one in .cowork/eval (for testing the regression gate)",
    )
    ap.add_argument(
        "--gold", type=Path, default=None,
        help="a different labelled case set (same columns). Its runs carry its "
             "own sha256 and are never compared against the R1 tripwire's")
    ap.add_argument(
        "--negatives", type=Path, default=None,
        help="negative queries, one per line (default: a built-in generic list)")
    args = ap.parse_args()

    gold = args.gold or GOLD
    commit = git_commit()
    gold_sha = sha256_of(gold)
    cases = load_cases(gold)
    negatives_in = (
        [line.strip() for line in args.negatives.read_text(encoding="utf-8").splitlines()
         if line.strip()] if args.negatives else list(NEGATIVES))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / (f"retrieval-{commit}.json" if gold == GOLD
                          else f"retrieval-{gold.stem}-{commit}.json")

    # DIAGNOSTICS RUN ON A COPY. `search` reads through `db.connect()`, which
    # opens a read-WRITE handle and is refused on a live database outside the
    # server (live_guard). A consistent backup-API copy gives the same answers
    # and cannot change the live file.
    if live_guard.is_live_shaped(settings.db_path):
        settings.db_path = live_guard.diagnostic_copy(settings.db_path)
    conn = open_db_readonly()
    try:
        docs = filename_index(conn)
        scored, unresolved = run_cases(conn, cases, docs)
        negatives = run_negatives(negatives_in)
    finally:
        conn.close()

    miss_causes: dict[str, int] = {}
    for case in scored:
        if case["miss_cause"]:
            miss_causes[case["miss_cause"]] = miss_causes.get(case["miss_cause"], 0) + 1

    payload = {
        "header": HEADER,
        "generated_by": getpass.getuser(),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": commit,
        "gold_csv": gold.name,
        "gold_sha256": gold_sha,
        "settings": {
            "limit": LIMIT,
            "rerank": True,
            "dense": True,
            "embed_model_dir": settings.embed_model_dir.name,
            "reranker_model_dir": "reranker",
            "search_candidates": settings.search_candidates,
            "rerank_candidates": settings.rerank_candidates,
            "relevance_floor": search_mod.RELEVANCE_FLOOR,
            "document_cap": search_mod.MAX_PASSAGES_PER_DOCUMENT,
        },
        "cases_in_sheet": len(cases),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "metrics": metrics(scored),
        "negatives": negative_metrics(negatives, scored),
        "negative_cases": negatives,
        "miss_causes": dict(sorted(miss_causes.items())),
        "cases": scored,
    }

    prior = previous_run(OUT_DIR, args.previous)
    code, lines = compare(payload, prior)
    payload["comparison"] = lines
    payload["regression"] = code != 0
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(HEADER)
    print(f"generated_by={payload['generated_by']} at={payload['generated_at']} "
          f"commit={commit} gold_sha256={gold_sha}")
    print(f"settings={json.dumps(payload['settings'])}")
    print(f"cases in sheet: {len(cases)}   resolved: {len(scored)}   "
          f"unresolved: {len(unresolved)}")
    m = payload["metrics"]
    for k in CUTOFFS:
        print(f"recall@{k}: {m[f'recall@{k}']:.4f}")
    print(f"MRR:       {m['mrr']:.4f}")
    for k in CUTOFFS:
        value = m.get(f"precision@{k}")
        print(f"precision@{k}: {'-' if value is None else f'{value:.4f}'}")
    print(f"latency p50/p95: {m['latency_p50_ms']} / {m['latency_p95_ms']} ms")
    neg = payload["negatives"]
    print(f"negatives: {neg['negatives_flagged']} of {neg['negative_queries']} flagged "
          f"low-confidence; best negative score {neg['negative_best_score']}, worst "
          f"answered top score {neg['answered_worst_top_score']}, separated: {neg['separated']}")
    print("miss causes: " + (json.dumps(payload["miss_causes"]) or "{}"))
    print(f"written: {out_path}")
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
