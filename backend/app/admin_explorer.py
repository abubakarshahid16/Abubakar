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

#: CREDENTIAL MATERIAL IS NEVER RENDERED, whoever is looking.
#:
#: A rule on COLUMN NAMES, not a list of tables. A hardcoded table list is a
#: claim about the schema as it is today, and the next migration is what
#: breaks it: a new table with a `password_hash` column would be browsable in
#: full while the list still looked complete. This asks the only question that
#: stays true - does this column's name say it holds a credential.
#:
#: Matched as a SUBSTRING of the lowercased name, so `password_hash`,
#: `setup_token_sha256` and `ollama_api_key` are all caught without anybody
#: enumerating them.
SENSITIVE_NAME_PARTS = ("password", "hash", "secret", "token", "api_key")

#: What a masked value renders as. The COLUMN NAME IS NEVER HIDDEN: an admin
#: looking at a schema needs to know the column is there, and hiding it would
#: make the explorer lie about the shape of the table. Only the value goes.
MASK = "•••"

#: The one exception, and it is a judgement stated rather than hidden.
#:
#: `token_count` contains a NUMBER OF TOKENS - a length, not a credential -
#: and the substring rule catches it because "token" is in its name. Masking
#: it would teach a reader that the mask means nothing in particular, which is
#: worse than the narrow risk of showing it: a mask nobody believes is not a
#: control. The exemption is by EXACT column name, never by substring, so a
#: column called `token_count_secret` is still masked.
#:
#: Anything added here is a decision somebody has to defend in review. The
#: default for a name that matches is to mask.
NOT_CREDENTIALS = ("token_count", "token_counts", "hash_algorithm")


def is_sensitive(column_name: str) -> bool:
    """Does this column's NAME say it holds credential material?

    Name-based and deliberately over-broad: a false positive costs an admin
    one unreadable value, a false negative puts a password hash on a screen.
    """
    name = (column_name or "").strip().lower()
    if name in NOT_CREDENTIALS:
        return False
    return any(part in name for part in SENSITIVE_NAME_PARTS)


def mask_row(columns: list[str], row: list) -> list:
    """One row with every credential-shaped column's VALUE replaced.

    A NULL stays NULL rather than becoming a mask: null renders as nothing
    (CLAUDE.md rule 4), and a masked empty would claim a secret is stored
    where none is - which is itself a disclosure about the row.
    """
    return [
        MASK if (is_sensitive(name) and value is not None) else value
        for name, value in zip(columns, row, strict=False)
    ]


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
             "pk": bool(r[5]), "sensitive": is_sensitive(r[1])}
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
    # MASKED HERE, at the only place rows leave this module. Doing it in the
    # route would leave `read_rows` returning hashes to any future caller who
    # forgot; doing it in the UI would put them on the wire, where a browser's
    # network tab renders them perfectly well.
    rows = [mask_row(columns, list(r)) for r in cur.fetchall()]
    total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return {"name": table, "columns": columns, "rows": rows,
            "offset": offset, "limit": limit, "total": total,
            # Which columns were masked, so the UI can mark them without
            # re-deriving the rule and drifting from it.
            "masked_columns": [c for c in columns if is_sensitive(c)]}
