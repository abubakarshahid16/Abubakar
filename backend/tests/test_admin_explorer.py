"""Explorer is read-only, injection-proof, and states its denominators.

AND IT NEVER RENDERS CREDENTIAL MATERIAL. The rule is on COLUMN NAMES, not on
a list of tables: a hardcoded table list is a claim about today's schema, and
the next migration that adds a `password_hash` somewhere new is what breaks
it silently. The name-based tests below are written against invented tables
for exactly that reason - the rule must hold for a table nobody has added yet.

Mutations: M225-M229, `python scripts/mutation_check.py --phase 20`.
"""
import sqlite3

import pytest

from app.admin_explorer import (
    MAX_ROWS,
    is_sensitive,
    list_tables,
    mask_row,
    read_rows,
    table_info,
)


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


# ===================================================== credential masking


@pytest.mark.parametrize("name", [
    "password", "password_hash", "PasswordHash", "user_secret",
    "setup_token_sha256", "api_key", "ollama_api_key", "refresh_token",
    "content_hash",
])
def test_a_credential_shaped_name_is_masked(name):
    """SUBSTRING, NOT EQUALITY, and case-insensitive. Nobody enumerates
    `setup_token_sha256`; the rule has to catch it without being told."""
    assert is_sensitive(name)


@pytest.mark.parametrize("name", [
    "id", "email", "display_name", "filename", "created_at", "page_count",
    "status", "discipline",
])
def test_an_ordinary_name_is_left_alone(name):
    """THE GUARD ON THE RULE. A check that masked everything would satisfy
    every test above and make the explorer useless."""
    assert not is_sensitive(name)


def test_a_bare_sha256_is_a_document_digest_and_is_not_masked():
    """THE ASYMMETRY, STATED RATHER THAN DISCOVERED.

    `documents.sha256` is the CONTENT DIGEST of a file - it is how the upload
    path deduplicates - and it is not credential material. It is not masked
    because the rule keys on the word "hash", which this name does not
    contain.

    `content_hash` WOULD be masked, and it is arguably the same kind of value.
    That is the cost of a name rule and it is the right way round: a false
    positive costs an admin one unreadable value, a false negative puts a
    password digest on a screen. `setup_token_sha256` - which IS credential
    material - is caught anyway, by "token".
    """
    assert not is_sensitive("sha256")
    assert is_sensitive("setup_token_sha256")


def test_token_count_is_a_length_and_is_not_masked():
    """A JUDGEMENT CALL, DECIDED AND WRITTEN DOWN.

    `token_count` holds a NUMBER OF TOKENS - a length, not a credential - and
    the substring rule catches it only because "token" is in the name.
    Masking it would teach a reader that the mask means nothing in
    particular, and a mask nobody believes is not a control. So it is exempt,
    BY EXACT NAME, and the next line is why that exemption cannot spread.
    """
    assert not is_sensitive("token_count")
    assert not is_sensitive("hash_algorithm")


def test_the_exemption_is_by_exact_name_and_does_not_spread():
    """`token_count_secret` is still masked. An exemption matched as a
    substring would be a hole shaped like a naming convention."""
    assert is_sensitive("token_count_secret")
    assert is_sensitive("my_token_count_hash")


def test_a_masked_value_is_replaced_and_its_neighbours_are_not():
    columns = ["id", "email", "password_hash"]
    row = ["u1", "a@b.test", "$argon2id$v=19$real"]

    assert mask_row(columns, row) == ["u1", "a@b.test", "•••"]


def test_a_null_stays_null_rather_than_becoming_a_mask():
    """Null renders as nothing (CLAUDE.md rule 4). A masked empty would claim
    a secret is stored where none is, which is itself a disclosure."""
    assert mask_row(["password_hash"], [None]) == [None]


def test_masking_reaches_rows_through_read_rows(conn):
    """THE RULE HOLDS ON A TABLE THAT DID NOT EXIST WHEN IT WAS WRITTEN,
    which is the whole argument for a name rule over a table list."""
    conn.execute("CREATE TABLE brand_new (id TEXT, api_key TEXT, note TEXT)")
    conn.execute("INSERT INTO brand_new VALUES ('1', 'sk-live-REAL', 'keep')")

    page = read_rows(conn, "brand_new")

    assert page["rows"] == [["1", "•••", "keep"]]
    assert page["masked_columns"] == ["api_key"]


def test_table_info_marks_the_column_without_hiding_it(conn):
    conn.execute("CREATE TABLE creds (id TEXT, secret TEXT)")

    columns = {c["name"]: c["sensitive"] for c in table_info(conn, "creds")["columns"]}

    assert columns == {"id": False, "secret": True}
