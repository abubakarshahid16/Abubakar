"""Read-only database explorer for the Administration page. Phase 8.

Every function takes an open connection and is READ ONLY by construction:
table names are validated against sqlite_master before use (never
interpolated from caller input unchecked), queries are SELECT-only, and
row caps are enforced. No db import: the caller owns the connection, so
this tests standalone against an in-memory database.

Pre-built and pre-tested by Cowork (8 standalone tests, including the
injection-shaped-name case) on branch cowork/phase-8-admin-explorer.
Integration (admin-gated endpoints + the Administration page UI) is the
merge task's job.
"""

MAX_ROWS = 200


def list_tables(conn) -> list[dict]:
    """Every user table with its row count. sqlite internals excluded."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    out = []
    for name in names:
        count = conn.execute(
            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        out.append({"name": name, "row_count": count})
    return out


def _known_table(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
        " AND name NOT LIKE 'sqlite_%'", (table,)).fetchone() is not None


def table_info(conn, table: str) -> dict | None:
    """Columns with type and nullability, or None for an unknown table.
    None, not an error: unknown and forbidden must read alike upstream."""
    if not _known_table(conn, table):
        return None
    cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]),
             "pk": bool(r[5])}
            for r in conn.execute(f'PRAGMA table_info("{table}")')]
    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return {"name": table, "columns": cols, "row_count": count}


def read_rows(conn, table: str, limit: int = 50,
              offset: int = 0) -> dict | None:
    """A page of rows. Caps at MAX_ROWS whatever the caller asks; the cap is
    stated in the result so the UI can say 'showing 200 of 6,805' with a
    real denominator instead of implying completeness."""
    if not _known_table(conn, table):
        return None
    limit = max(1, min(int(limit), MAX_ROWS))
    offset = max(0, int(offset))
    cur = conn.execute(f'SELECT * FROM "{table}" LIMIT ? OFFSET ?',
                       (limit, offset))
    columns = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return {"name": table, "columns": columns, "rows": rows,
            "offset": offset, "limit": limit, "total": total}
