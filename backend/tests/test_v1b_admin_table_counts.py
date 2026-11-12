"""V1b: the admin table list reuses a table's row count for a short time; names are always fresh. Invented data.

MUTATION: drop the cache (count every call) and the first test fails; never expire it and the second fails.
"""

from __future__ import annotations

import sqlite3

from app import admin_explorer


def _conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "x.sqlite"))
    conn.execute("CREATE TABLE a (v)")
    conn.executemany("INSERT INTO a VALUES (?)", [(1,), (2,)])
    conn.commit()
    return conn


def test_a_count_is_reused_within_the_window_but_a_new_table_shows_at_once(tmp_path):
    admin_explorer._COUNT_CACHE.clear()
    conn = _conn(tmp_path)
    first = admin_explorer.list_tables(conn, now=1000.0)
    conn.execute("INSERT INTO a VALUES (3)")
    conn.execute("CREATE TABLE b (v)")
    conn.commit()
    second = admin_explorer.list_tables(conn, now=1010.0)
    assert first == [{"name": "a", "row_count": 2}]
    assert second == [{"name": "a", "row_count": 2}, {"name": "b", "row_count": 0}]


def test_a_count_older_than_the_window_is_counted_again(tmp_path):
    admin_explorer._COUNT_CACHE.clear()
    conn = _conn(tmp_path)
    admin_explorer.list_tables(conn, now=1000.0)
    conn.execute("INSERT INTO a VALUES (3)")
    conn.commit()
    later = admin_explorer.list_tables(conn, now=1000.0 + admin_explorer.COUNT_CACHE_SECONDS + 1)
    assert later == [{"name": "a", "row_count": 3}]
