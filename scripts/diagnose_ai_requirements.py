"""Where do the model's requirement items go? (#645 diagnosis)

For chosen labelled sections and a model, runs the extraction task, SAVES the
model's raw JSON replies (to --raw-dir, which must be outside the repository),
and counts per section: items the model returned, items rejected by each
code check, items kept. A COPY of the database only (the runner's cache
writes go to it). Prints ids, labels, counts and short reasons - never
document text.

    python scripts/diagnose_ai_requirements.py --db <copy> --labels <labels.json> \\
        --raw-dir <outside the repo> --model qwen3.5:2b --section "doc_prefix|label" ...
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))


class Recording:
    """Wraps a provider and keeps every raw reply."""

    def __init__(self, inner):
        self.inner = inner
        self.requested_model = inner.requested_model
        self.replies: list[str] = []

    def reason(self, packet):
        response = self.inner.reason(packet)
        self.replies.append(response.text or "")
        return response


def categorise(reply_text: str, passage: str) -> Counter:
    from app import ai_requirements as air
    from app import ai_task_runner as runner
    from app.reasoning_provider import schema_errors

    counts: Counter = Counter()
    kept: list[dict] = []
    try:
        data = json.loads(reply_text)
    except ValueError:
        counts["reply not JSON"] += 1
        return counts, kept
    if schema_errors(reply_text, air.SCHEMA):
        counts["schema invalid"] += 1
        return counts, kept
    for item in data.get("requirements") or []:
        counts["returned"] += 1
        reason = air.check_item(item, passage)
        if reason:
            counts["rejected: " + reason] += 1
            continue
        counts["kept"] += 1
        figures = air.read_figures(item["quote"])
        if figures:
            counts["kept with figure"] += 1
        if not air._hints_agree(item, figures):
            counts["flag: " + air.MODEL_VALUE_DISAGREED] += 1
        if not air._standard_hint_agrees(item, air.read_standards(item["quote"])):
            counts["flag: " + air.MODEL_STANDARD_DISAGREED] += 1
        kept.append({**item, "figures": figures})
    return counts, kept


def main(argv: list[str] | None = None) -> int:
    import pilot_ai_requirements as pilot
    from app import access, ai_requirements as air, ai_task_runner as runner, db, model_transport
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--labels", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--section", action="append", required=True,
                    help='"<document id prefix>|<section label>"')
    ap.add_argument("--from-raw", action="store_true",
                    help="score the raw replies already saved in --raw-dir; no model call")
    args = ap.parse_args(argv)
    raw_dir = args.raw_dir.resolve()
    if REPO in raw_dir.parents or raw_dir == REPO:
        raise SystemExit("refusing: raw model replies must not be written inside the repository")
    raw_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path = pilot.refuse_live(args.db)
    settings.auth_mode = access.AUTH_DISABLED
    db.reset_connection()
    runner.ensure_schema()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    conn = db.connect()
    provider = Recording(runner.make_provider(args.model))
    import contextlib
    with (contextlib.nullcontext() if args.from_raw
          else model_transport.keep_alive_override(settings.ai_task_batch_keep_alive)):
        for spec in args.section:
            prefix, label = spec.split("|", 1)
            std = next(s for s in labels["standards"] if s["document_id"].startswith(prefix))
            section = next(s for s in std["sections"] if s["label"] == label)
            marks = ",".join("?" * len(section["chunk_ids"]))
            text = "\n".join(r[0] for r in conn.execute(
                f"SELECT text FROM chunks WHERE id IN ({marks}) ORDER BY ordinal", section["chunk_ids"]))
            passages = air.split_passages(text)
            raw_file = raw_dir / f"{args.model.replace(':', '_')}__{prefix}__{label.split()[0]}.json"
            if section.get("type") == "table":
                found = pilot.table_items(conn, section["chunk_ids"])
                scored = pilot.score(found, section["true"])
                print(json.dumps({"model": "existing table extraction", "section": f"{std['kind']} {label}",
                                  "type": "table", "true": len(section["true"]),
                                  "rows_for_these_chunks": len(found), **scored}), flush=True)
                continue
            if args.from_raw:
                saved = json.loads(raw_file.read_text(encoding="utf-8"))["raw_replies"]
                total, kept_items = Counter(), []
                for reply, passage in zip(saved[-len(passages):], passages):
                    counts, kept = categorise(reply, passage)
                    total += counts
                    kept_items += kept
                scored = pilot.score(kept_items, section["true"])
                print(json.dumps({"model": args.model, "section": f"{std['kind']} {label}", "type": "prose",
                                  "true": len(section["true"]), "passages": len(passages),
                                  "true_found": scored["true_found"], "found_figures": scored["found"],
                                  "found_correct": scored["found_correct"], "counts": dict(total),
                                  "raw": raw_file.name, "scored_from": "saved raw replies"}), flush=True)
                continue
            provider.replies.clear()
            total: Counter = Counter()
            kept_items: list[dict] = []
            unread = 0
            for passage in passages:
                before = len(provider.replies)
                result = runner.run_task(air.TASK, passage, provider=provider, use_cache=False)
                replies = provider.replies[before:]
                if result.state != runner.STATE_OK:
                    unread += 1
                # what code does with the reply the runner accepted (or the last one it saw)
                if replies:
                    counts, kept = categorise(replies[-1], passage)
                    total += counts
                    kept_items += kept
                    if len(replies) > 1:
                        total["runner retries"] += len(replies) - 1
            out = raw_dir / f"{args.model.replace(':', '_')}__{prefix}__{label.split()[0]}.json"
            out.write_text(json.dumps({"model": args.model, "document_id": std["document_id"],
                                       "section": label, "passages": len(passages),
                                       "raw_replies": provider.replies}, indent=1), encoding="utf-8")
            scored = pilot.score(kept_items, section["true"])
            print(json.dumps({"model": args.model, "section": f"{std['kind']} {label}",
                              "true": len(section["true"]), "passages": len(passages),
                              "true_found": scored["true_found"], "found_figures": scored["found"],
                              "found_correct": scored["found_correct"],
                              "passages_could_not_read": unread, "counts": dict(total),
                              "raw": out.name}), flush=True)
    if not args.from_raw:
        runner._unload(provider.inner)
    db.reset_connection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
