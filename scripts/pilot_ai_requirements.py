"""#645 pilot: AI requirement extraction, scored against hand labels.

A BASELINE PER MODEL, NOT A MODEL DECISION (owner, #683): the small models on
the 16 GB PC are development models; the final model is chosen by running
this same pilot, unchanged, on the Mac Studio. Nothing here is tuned to a
model; the model is the only thing that changes (--model).

Runs `app.ai_requirements.extract` on the hand-labelled sections of a few
standards, for one or more models, and reports per standard and model:
recall (true items found / true items), precision (found items that are true
/ found items), what code rejected ("could not read"), seconds per section,
and memory. Matching a found figure to a true one is value AND unit, through
the shared figure check (#653): equal value or an ordinary rounding, the same
quantity, or a correct conversion (4 psi = 28 kPa).

ON A COPY ONLY. A live-shaped path, or this checkout's live file, is refused
before anything is opened; the runner's cache writes go to the copy. Output
is ids, labels, counts and figures - never document text.

THE LABELS are a git-ignored JSON file (CLAUDE.md rule 1: nothing derived from
a document is committed): {"standards": [{"kind", "document_id", "sections":
[{"label", "chunk_ids", "true": [{"value", "unit"}]}]}]}.

THE MACHINE RULES (#644): one model at a time, keep_alive "10m" during its
batch and 0 after it; a batch starts only when no chat answer, test run or P1
is going AND enough memory is free; between sections it pauses for chat, tests
or P1 (memory is not re-checked mid-batch: the loaded model itself takes it).

    python scripts/pilot_ai_requirements.py --db <copy.sqlite> --labels .cowork/pilot645/labels.json \\
        --model qwen3.5:2b --model qwen3.5:4b --out .cowork/pilot645/result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"


def refuse_live(path: Path) -> Path:
    from app import live_guard

    resolved = path.resolve()
    if live_guard.is_live_shaped(resolved) or (
            LIVE.exists() and resolved.exists() and os.path.samefile(resolved, LIVE)):
        raise SystemExit(f"refusing: {resolved} is a live database. Run the pilot on a copy.")
    if not resolved.exists():
        raise SystemExit(f"no database at {resolved}")
    return resolved


def figures(value: str | None, value_to: str | None, unit: str | None) -> list[dict]:
    """A labelled true item's figure(s), as `answer._figure_occurrences` reads them."""
    from app import answer

    out = []
    for v in (value, value_to):
        if v and str(v).strip():
            found = answer._figure_occurrences(f"{v} {unit or ''}".strip())
            out.extend(found[:1])
    return out


def item_figures(item: dict) -> list[dict]:
    """The figures CODE read for a found item (`ai_requirements.read_figures`),
    never the model's own value fields - AI locates, code reads."""
    return [f for fig in item.get("figures") or []
            for f in figures(fig.get("value"), None, fig.get("unit"))]


def table_items(conn, chunk_ids: list[str]) -> list[dict]:
    """TABLE rows come from the existing table extraction (#594/#595), not the
    AI pass: one item per active table cell stored for these chunks."""
    marks = ",".join("?" * len(chunk_ids))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(standard_requirements)")}
    active = " AND superseded_at IS NULL" if "superseded_at" in cols else ""
    rows = conn.execute(
        f"SELECT raw_value, COALESCE(raw_unit, unit) FROM standard_requirements"
        f" WHERE requirement_type = 'table_value' AND chunk_id IN ({marks}){active}",
        chunk_ids).fetchall()
    return [{"figures": [{"value": r[0], "unit": r[1]}]} for r in rows if r[0]]


def matches(a: dict, b: dict) -> bool:
    from app import answer

    if a["sign"] not in (b["sign"], "?") and b["sign"] not in (a["sign"], "?"):
        return False
    if a["unit"] is None or b["unit"] is None:
        return a["unit"] == b["unit"] and answer._value_matches(a["value"], b["value"])
    return answer._unit_value_matches(a, b) or answer._unit_value_matches(b, a)


def score(found_items: list[dict], truth: list[dict]) -> dict:
    """Recall over true items, precision over found figures; one found figure
    matches at most one true item."""
    true_figs = [figures(t["value"], None, t["unit"])[0] for t in truth]
    found_figs = [f for item in found_items for f in item_figures(item)]
    used: set[int] = set()
    correct = 0
    for f in found_figs:
        hit = next((i for i, t in enumerate(true_figs) if i not in used and matches(f, t)), None)
        if hit is not None:
            used.add(hit)
            correct += 1
        elif any(matches(f, t) for t in true_figs):
            correct += 1          # a second reading of a true item: not wrong, not counted twice
    return {"true": len(true_figs), "found": len(found_figs), "true_found": len(used),
            "found_correct": correct}


def wait_until_clear(*, check_memory: bool) -> None:
    from app import ai_task_runner

    while True:
        reason = ai_task_runner.pause_reason(free_ram=None if check_memory else 10 ** 15)
        if reason is None:
            return
        print(f"  paused: {reason}", flush=True)
        time.sleep(30)


def model_memory_gb(model: str) -> float | None:
    from app import model_transport

    try:
        listing = model_transport.get_json("/api/ps", timeout=5.0, required=False) or {}
    except Exception:  # noqa: BLE001 - a reading, never a failure of the pilot
        return None
    for m in listing.get("models") or []:
        if m.get("name") == model or m.get("model") == model:
            return round((m.get("size") or 0) / 1e9, 2)
    return None


def run(db: Path, labels: dict, models: list[str]) -> dict:
    from app import access, ai_requirements, ai_task_runner, db as db_mod, model_transport
    from app.config import settings

    settings.db_path = refuse_live(db)
    settings.auth_mode = access.AUTH_DISABLED
    db_mod.reset_connection()
    ai_task_runner.ensure_schema()
    conn = db_mod.connect()
    report: dict = {"database": str(settings.db_path), "models": {}}
    for model in models:
        wait_until_clear(check_memory=True)
        provider = ai_task_runner.make_provider(model)
        free_before = ai_task_runner.free_ram_bytes()
        per_standard = []
        peak_model_gb = None
        with model_transport.keep_alive_override(settings.ai_task_batch_keep_alive):
            for std in labels["standards"]:
                row = {"model": model, "kind": std["kind"], "document_id": std["document_id"],
                       "sections": [],
                       "true": 0, "found": 0, "true_found": 0, "found_correct": 0,
                       "could_not_read": 0, "seconds": 0.0}
                for section in std["sections"]:
                    wait_until_clear(check_memory=False)
                    marks = ",".join("?" * len(section["chunk_ids"]))
                    text = "\n".join(r[0] for r in conn.execute(
                        f"SELECT text FROM chunks WHERE id IN ({marks}) ORDER BY ordinal",
                        section["chunk_ids"]))
                    started = time.time()
                    if section.get("type") == "table":
                        result = {"requirements": table_items(conn, section["chunk_ids"]),
                                  "could_not_read": [], "passages": 0}
                    else:
                        result = ai_requirements.extract(text, provider=provider, use_cache=False)
                    seconds = round(time.time() - started, 1)
                    s = score(result["requirements"], section["true"])
                    reasons: dict[str, int] = {}
                    for u in result["could_not_read"]:
                        reasons[u["reason"]] = reasons.get(u["reason"], 0) + 1
                    row["sections"].append({"label": section["label"],
                                            "type": section.get("type", "prose"), **s, "seconds": seconds,
                                            "passages": result["passages"],
                                            "could_not_read": reasons})
                    for k in ("true", "found", "true_found", "found_correct"):
                        row[k] += s[k]
                    row["could_not_read"] += len(result["could_not_read"])
                    row["seconds"] += seconds
                    gb = model_memory_gb(model)
                    if gb is not None:
                        peak_model_gb = max(peak_model_gb or 0, gb)
                    print(f"  {model} {std['kind']} {section['label']}: {s} {seconds}s", flush=True)
                n = len(std["sections"])
                row["recall"] = round(row["true_found"] / row["true"], 3) if row["true"] else None
                row["precision"] = round(row["found_correct"] / row["found"], 3) if row["found"] else None
                row["seconds_per_section"] = round(row["seconds"] / n, 1) if n else None
                per_standard.append(row)
        ai_task_runner._unload(provider)
        totals = {k: sum(r[k] for r in per_standard)
                  for k in ("true", "found", "true_found", "found_correct", "could_not_read")}
        # PROSE (the AI pass) and TABLE rows (the existing table extraction)
        # are reported apart: they are different readers.
        for kind in ("prose", "table"):
            secs = [x for r in per_standard for x in r["sections"] if x["type"] == kind]
            t = {k: sum(x[k] for x in secs) for k in ("true", "found", "true_found", "found_correct")}
            t["recall"] = round(t["true_found"] / t["true"], 3) if t["true"] else None
            t["precision"] = round(t["found_correct"] / t["found"], 3) if t["found"] else None
            totals[kind] = t
        sections = sum(len(r["sections"]) for r in per_standard)
        totals["recall"] = round(totals["true_found"] / totals["true"], 3) if totals["true"] else None
        totals["precision"] = (round(totals["found_correct"] / totals["found"], 3)
                               if totals["found"] else None)
        totals["seconds_per_section"] = round(sum(r["seconds"] for r in per_standard) / sections, 1)
        # #683: the model is a setting and every result names it, so the same
        # pilot runs unchanged on another machine and results never mix.
        report["models"][model] = {"model": model, "per_standard": per_standard, "totals": totals,
                                   "model_memory_gb": peak_model_gb,
                                   "free_ram_gb_before": round(free_before / 1e9, 2)}
    db_mod.reset_connection()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path, help="a COPY of the database")
    ap.add_argument("--labels", required=True, type=Path)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    report = run(args.db, labels, args.model)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{'model':12} {'standard':13} {'true':>4} {'found':>5} {'recall':>6} {'precision':>9} {'s/section':>9}")
    for model, m in report["models"].items():
        for r in m["per_standard"]:
            print(f"{model:12} {r['kind']:13} {r['true']:>4} {r['found']:>5} "
                  f"{str(r['recall']):>6} {str(r['precision']):>9} {str(r['seconds_per_section']):>9}")
        t = m["totals"]
        print(f"{model:12} {'ALL':13} {t['true']:>4} {t['found']:>5} {str(t['recall']):>6} "
              f"{str(t['precision']):>9} {str(t['seconds_per_section']):>9}  model RAM {m['model_memory_gb']} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
