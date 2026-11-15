"""Resume and cancellation helpers of the nine-role job (B5): the job's cancel flag, a call seam wrapper that honours it BEFORE every paid call,
and the small hand-over table that lets a restart skip a role that already "ran" and still give the next role what it made.

The hand-over keeps structure and ids only (the context blocks are rows of typed tokens, the reading list is the chosen (book, chapter) pairs);
the fact sheet is already stored by `nine_facts`. No document text is written here. `ctx` is the job's `RoleContext` (duck typed)."""

from __future__ import annotations

import json

from . import nine_call
from .db import connect


def job_cancelled(run_id: str) -> bool:
    row = (
        connect()
        .execute(
            "SELECT cancel_requested FROM jobs WHERE review_run_id = ? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        )
        .fetchone()
    )
    return bool(row and row["cancel_requested"])


def guarded_ask(ctx):
    """`nine_call.ask` that honours the job's cancellation BEFORE every call (a paid call is never started after a cancel)."""

    def ask(*args, **kwargs):
        ctx.check_stop()
        return nine_call.ask(*args, **kwargs)

    return ask


HANDOVER = "agent_review_role_handover"


def handover_save(run_id: str, key: str, value) -> None:
    conn = connect()
    with conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {HANDOVER} (run_id TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, key))"
        )
        conn.execute(
            f"INSERT OR REPLACE INTO {HANDOVER} (run_id, key, payload) VALUES (?,?,?)",
            (run_id, key, json.dumps(value)),
        )


def handover_load(run_id: str, key: str):
    conn = connect()
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (HANDOVER,)
    ).fetchone():
        return None
    row = conn.execute(
        f"SELECT payload FROM {HANDOVER} WHERE run_id = ? AND key = ?", (run_id, key)
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def hand_over(ctx, n: int) -> None:
    """After a role: keep what the next role needs, so a restart that skips this role (it "ran") still hands it over. Ids and structure only: the
    fact sheet is already stored by `nine_facts`; the context blocks are rows of typed tokens; the reading list is the chosen (book, chapter) pairs."""
    if n == 2 and ctx.store.get("context_blocks") is not None:
        handover_save(ctx.run_id, "context_blocks", [
            {"name": b.name, "sources": list(b.sources), "kinds": list(b.kinds or ()) or None, "items": [list(r) for r in b.items]}
            for b in ctx.store["context_blocks"]
        ])  # fmt: skip
    if n == 3 and ctx.store.get("reading") is not None:
        handover_save(
            ctx.run_id,
            "chosen",
            [
                [b.book_id, i.chapter.chapter_id]
                for b in ctx.store["reading"].books
                if b.on_shown_list
                for i in b.items
                if i.chosen
            ],
        )


def reload(ctx, n: int) -> None:
    """A role that ran is skipped on a restart: reload what it handed over."""
    from . import nine_facts

    if n == 1:
        ctx.store["fact_sheet"] = nine_facts.load(connect(), ctx.run_id)
    elif n == 2 and (rows := handover_load(ctx.run_id, "context_blocks")) is not None:
        ctx.store["context_blocks"] = tuple(
            nine_call.Block("review_record", name=r["name"], sources=tuple(r["sources"]), kinds=tuple(r["kinds"]) if r["kinds"] else None, items=tuple(tuple(x) for x in r["items"]))
            for r in rows
        )  # fmt: skip
    elif n == 3 and (chosen := handover_load(ctx.run_id, "chosen")) is not None:
        ctx.store["chosen"] = [tuple(x) for x in chosen]
