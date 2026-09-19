"""Explorer is read-only, injection-proof, and states its denominators."""
import sqlite3

import pytest

from app.admin_explorer import MAX_ROWS, list_tables, read_rows, table_info


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE docs (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    c.execute("CREATE TABLE empty_t (x INTEGER)")
    c.executemany("INSERT INTO docs VALUES (?, ?)",
                  [(f"d{i}", f"n{i}") for i in range(300)])
    return c


def test_lists_tables_with_row_counts(conn):
    tables = {x["name"]: x["row_count"] for x in list_tables(conn)}
    assert tables == {"docs": 300, "empty_t": 0}


def test_sqlite_internals_are_hidden(conn):
    conn.execute("CREATE INDEX i ON docs(name)")
    assert all(not x["name"].startswith("sqlite_")
               for x in list_tables(conn))


def test_unknown_table_reads_as_none_not_error(conn):
    assert table_info(conn, "nope") is None
    assert read_rows(conn, "nope") is None


def test_injection_shaped_name_is_just_unknown(conn):
    assert read_rows(conn, 'docs"; DROP TABLE docs; --') is None
    assert table_info(conn, "docs")["row_count"] == 300


def test_columns_carry_type_null_pk(conn):
    cols = {c["name"]: c for c in table_info(conn, "docs")["columns"]}
    assert cols["id"]["pk"] and cols["name"]["notnull"]


def test_rows_page_with_real_denominator(conn):
    page = read_rows(conn, "docs", limit=10, offset=20)
    assert len(page["rows"]) == 10 and page["total"] == 300
    assert page["rows"][0][0] == "d20"


def test_the_cap_holds_whatever_is_asked(conn):
    page = read_rows(conn, "docs", limit=999999)
    assert len(page["rows"]) == MAX_ROWS <= 200


def test_negative_inputs_are_clamped(conn):
    page = read_rows(conn, "docs", limit=-5, offset=-9)
    assert page["offset"] == 0 and len(page["rows"]) == 1
