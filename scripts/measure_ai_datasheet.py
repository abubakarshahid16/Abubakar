"""Measure the AI datasheet readers (#646) on one review run, on a COPY.

Two readers exist; both are measured on the run's datasheet, page by page:

  * locate - `ai_datasheet.read_page` ("AI locates, code reads", #645/#689):
    the model names each field's label and value text; code checks both are
    on the page and reads the figure and unit itself;
  * extraction lane - `datasheet_ai.read_pages` (DATASHEET_AI_READER, engine
    "ollama"): the model proposes field, value, unit and quote; code checks
    them (`claude_datasheet.accept`).

Then, for the requirements that REACHED the run's comparison, it counts how
many the deterministic pairing (`comparison.match_by_containment`) pairs with
a field that has a value - with the rule readers' fields alone, and with each
reader's fields added. A pairing estimate, not a review re-run: it says which
step loses the requirements, not their verdicts.

Counts and reason codes only - never document text. A live-shaped database
path is refused. The model run takes the shared heavy-job lock and unloads the
model at the end.

    python scripts/measure_ai_datasheet.py --db <copy.sqlite> --model qwen3.5:2b \\
        --run 26fd20bc --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _fact(label: str, value: str, page, source: str, index: int) -> dict:
    """An AI reading in the shape the pairing reads. The number is READ BY
    CODE from the value text (`raw_value`; the pairing only pairs a limit
    with a fact that has one) - text with no figure has none."""
    from app import ai_requirements, datasheets

    figures = ai_requirements.read_figures(value)
    return {"id": f"{source}-{index}", "field_name": datasheets.normalise_field_name(label),
            "field_label": label, "field_value": value, "is_blank": 0, "page": page,
            "raw_value": figures[0]["value"] if figures else None,
            "raw_unit": figures[0]["unit"] if figures else None, "source": source}


def _paired(requirements: list[dict], facts: list[dict]) -> Counter:
    from app import comparison

    out: Counter = Counter()
    for r in requirements:
        if not comparison.is_matchable(r):
            out["not_a_value_requirement"] += 1
            continue
        fact = comparison.match_by_containment(r, facts)["fact"]
        if fact is None:
            out["no_field_paired"] += 1
        elif fact.get("is_blank"):
            out["paired_blank_field"] += 1
        else:
            out[f"paired_with_value:{fact.get('source') or 'rules'}"] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    from app import (access, ai_datasheet, ai_task_runner, datasheet_ai, datasheets, db,
                     heavy_lock, live_guard, submittal_review)
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--run", required=True, help="review run id or prefix")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--matcher-only", action="store_true",
                    help="skip the readers; only ask the model matcher about the unpaired requirements")
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path):
        raise SystemExit(f"refusing: {path} is a live database path. Measure on a copy.")
    settings.db_path = path
    settings.data_dir = path.parent / "s1_data"
    settings.data_dir.mkdir(exist_ok=True)
    settings.auth_mode = access.AUTH_DISABLED
    settings.ai_task_model = args.model
    settings.datasheet_ai_ollama_model = args.model
    settings.answer_model = args.model      # the model matcher's model (`match_by_model`)
    settings.match_enabled = True
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    conn = db.connect()
    every = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    run = conn.execute("SELECT id, submittal_document_id FROM review_runs WHERE id LIKE ?",
                       (args.run + "%",)).fetchone()
    sid = run["submittal_document_id"]
    chunks = [dict(r) for r in conn.execute(
        "SELECT c.page_start, c.page_end, c.text, d.stored_path FROM chunks c"
        " JOIN documents d ON d.id = c.document_id WHERE c.document_id = ?", (sid,))]
    stored_path = chunks[0]["stored_path"] if chunks else None
    pages = conn.execute("SELECT page_count FROM documents WHERE id = ?", (sid,)).fetchone()[0]
    texts = {p: datasheet_ai.page_text(stored_path, p, chunks) for p in range(1, (pages or 0) + 1)}

    rules = datasheets.list_facts(sid, allowed_document_ids=every)
    rule_names = {f["field_name"] for f in rules}
    report: dict = {"run": run["id"][:8], "model": args.model, "pages": pages,
                    "pages_with_text": sum(1 for t in texts.values() if t.strip()),
                    "rules": {"facts": len(rules), "distinct_fields": len(rule_names),
                              "blank": sum(1 for f in rules if f.get("is_blank"))}}

    # the requirements that reached the comparison, as the run stored them
    reached = [dict(r) for r in conn.execute(
        "SELECT q.* FROM review_scope_decisions d JOIN standard_requirements q"
        " ON q.id = d.requirement_id WHERE d.review_run_id = ? AND d.state = 'checked'",
        (run["id"],))]
    from app import comparison
    unpaired = [r for r in reached if comparison.is_matchable(r)
                and comparison.match_by_containment(r, rules)["fact"] is None]

    provider = ai_task_runner.make_provider()
    located, unread, passages = [], Counter(), 0
    lane = {"engine": None, "unavailable": "not run (--matcher-only)", "pages": {}, "reasons": {}}
    matcher: Counter = Counter()
    with heavy_lock.held("ai_batch", owner="s1 #646 measure"):
        try:
            if not args.matcher_only:
                for p, text in texts.items():
                    if not text.strip():
                        continue
                    out = ai_datasheet.read_page(text, page=p, provider=provider)
                    located += out["fields"]
                    passages += out["passages"]
                    unread.update(u["reason"] for u in out["could_not_read"])
                lane = datasheet_ai.read_pages(texts, "ollama")
            # THE MODEL MATCHER on what containment could not pair (two runs
            # must agree; `match_by_model`'s own validation chain)
            cache: dict = {}
            for r in unpaired:
                chosen = comparison.match_by_model(r, rules, cache=cache)
                if chosen["fact"] is None:
                    matcher[f"not_paired:{chosen.get('reason') or 'no_reason'}"] += 1
                elif chosen["fact"].get("is_blank"):
                    matcher["paired_blank_field"] += 1
                else:
                    matcher["paired_with_value"] += 1
        finally:
            ai_task_runner._unload(provider)

    loc_names = {datasheets.normalise_field_name(f["label"]) for f in located}
    report["locate"] = {
        "passages": passages, "fields_verified": len(located), "distinct_fields": len(loc_names),
        "with_figure": sum(1 for f in located if f["figures"]),
        "text_only": sum(1 for f in located if not f["figures"]),
        "fields_the_rules_did_not_read": len(loc_names - rule_names),
        "could_not_read": dict(unread)}
    accepted = [a for page in lane["pages"].values() for a in page.get("accepted", [])]
    rejected = Counter(r.get("reason") for page in lane["pages"].values()
                       for r in page.get("rejected", []))
    lane_names = {datasheets.normalise_field_name(a.get("field") or "") for a in accepted}
    report["extraction_lane"] = {
        "engine": lane["engine"], "unavailable": lane["unavailable"],
        "pages_read": len(lane["pages"]), "page_errors": len(lane["reasons"]),
        "accepted": len(accepted), "distinct_fields": len(lane_names),
        "fields_the_rules_did_not_read": len(lane_names - rule_names),
        "rejected_by_reason": dict(rejected)}

    loc_facts = [_fact(f["label"], f["value_text"], f["page"], "locate", i)
                 for i, f in enumerate(located)]
    lane_facts = [_fact(a.get("field") or "", " ".join(filter(None, (a.get("value"), a.get("unit")))),
                        a.get("page"), "lane", i) for i, a in enumerate(accepted)]
    report["pairing_of_requirements_that_reached_the_comparison"] = {
        "requirements": len(reached),
        "rules_only": dict(_paired(reached, rules)),
        "rules_plus_locate": dict(_paired(reached, rules + loc_facts)),
        "rules_plus_extraction_lane": dict(_paired(reached, rules + lane_facts)),
        "model_matcher_on_the_unpaired": {"asked": len(unpaired), **dict(matcher)}}
    print(json.dumps(report, indent=1))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    db.reset_connection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
