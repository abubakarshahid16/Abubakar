"""Read-only, local-model probe of the chat collection summary on real files.

Only aggregate diagnostics are printed. Never print the answer, source text,
filenames, document IDs, prompts, or model completions from client documents.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

from app import analysis, synthesis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--count", type=int, choices=(1, 2, 10, 20), default=10)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit("Database is unavailable.")

    # A separate read-only connection also prevents this worktree from
    # accidentally writing the server-owned live database.
    uri = args.database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT d.id, d.chunk_count_total FROM documents d
               WHERE d.status = 'ready' AND d.page_count IS NOT NULL
                 AND d.chunk_count_total >= 2
                 AND (SELECT COUNT(*) FROM page_ledger p
                      WHERE p.document_id = d.id) = d.page_count
                 AND NOT EXISTS (
                     SELECT 1 FROM page_ledger p WHERE p.document_id = d.id
                       AND p.index_status NOT IN ('retrievable', 'excluded')
                       AND NOT (p.native_status = 'empty'
                                AND p.ocr_status = 'not_required'))
               ORDER BY d.chunk_count_total, d.id LIMIT ? OFFSET ?""",
            (args.count, args.offset),
        ).fetchall()
        if len(rows) != args.count:
            raise SystemExit("Not enough fully indexed, ready documents for this probe.")
        selected = frozenset(row["id"] for row in rows)
        print(f"selected_documents={len(selected)} readable_chunks={sum(row['chunk_count_total'] for row in rows)}")

        calls: dict[str, int] = {}
        failed_stage: str | None = None
        original_summarise = synthesis._summarise_sources

        def measured_summarise(*call_args, **call_kwargs):
            nonlocal failed_stage
            stage = call_kwargs.get("stage", "single")
            calls[stage] = calls.get(stage, 0) + 1
            outcome = original_summarise(*call_args, **call_kwargs)
            if outcome.refusal:
                failed_stage = stage
            print(f"stage_completed={stage} call={sum(calls.values())} refused={bool(outcome.refusal)}",
                  flush=True)
            if outcome.refusal and outcome.raw_completion:
                raw = outcome.raw_completion.strip().upper()
                print(f"refusal_token_exact={raw == synthesis.INSUFFICIENT} "
                      f"refusal_token_present={synthesis.INSUFFICIENT in raw}", flush=True)
            return outcome

        original_connect = analysis.connect
        analysis.connect = lambda: conn
        synthesis._summarise_sources = measured_summarise
        try:
            started = time.monotonic()
            result = analysis.collection_summary(
                f"Summarize these {args.count} documents in one page",
                selected, allowed_document_ids=selected,
            )
        finally:
            analysis.connect = original_connect
            synthesis._summarise_sources = original_summarise

        coverage = result["summary_coverage"]
        print(f"outcome={result['answer_type']} elapsed_seconds={time.monotonic() - started:.1f}")
        print(f"processed={coverage['processed']} cited_documents={coverage['cited_documents']}")
        print(f"target_words={coverage['target_words']} actual_words={coverage['actual_words']}")
        print(f"source_passages={len(result['passages'])}")
        print(f"stage_calls={calls} failed_stage={failed_stage}")
        if result["answer"] is None:
            # Refusal reasons are fixed system wording, never client prose.
            print(f"refusal={result['reason']}")
        else:
            print("all_selected_documents_cited=" + str(coverage["cited_documents"] == args.count))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
