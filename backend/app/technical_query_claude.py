"""The consent record of a technical query's Claude draft (order 14; owner approved the lane on #1584 comment 7170031292).

The engineer chooses which contract documents Claude may read for ONE query's draft; that choice is stored here BEFORE anything is sent:
query id, the chosen document ids, who, when (ids only, no title and no text). It is this lane's own record, never chat's
`per_request_consent`. The send itself goes through the ordinary Claude path (`reader_transport` under the `claude_spend` caps); the
client register block, "Local only" and the money caps still stop it, and the draft's engine setting is local unless the owner changes it.
"""

from __future__ import annotations

import json
import uuid

from .technical_queries import now

TABLE = "query_claude_consent"


def create_table(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, query_id TEXT NOT NULL, document_ids_json TEXT NOT NULL, "
        "user_id TEXT, created_at TEXT NOT NULL)"
    )


def record(conn, query_id: str, document_ids, user_id: str | None) -> str:
    """Store the engineer's choice (ids sorted, no duplicates) and return its id. Called before the Claude call is made."""
    create_table(conn)
    consent_id = str(uuid.uuid4())
    ids = sorted({str(d) for d in document_ids if d})
    conn.execute(
        f"INSERT INTO {TABLE}(id,query_id,document_ids_json,user_id,created_at) VALUES (?,?,?,?,?)",
        (consent_id, query_id, json.dumps(ids), user_id, now()),
    )
    return consent_id


def entries(conn, query_id: str) -> list[dict]:
    create_table(conn)
    return [
        {
            "id": r["id"],
            "document_ids": json.loads(r["document_ids_json"]),
            "user_id": r["user_id"],
            "at": r["created_at"],
        }
        for r in conn.execute(
            f"SELECT * FROM {TABLE} WHERE query_id = ? ORDER BY created_at", (query_id,)
        )
    ]
