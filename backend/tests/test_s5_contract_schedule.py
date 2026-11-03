"""STEP 5 (#805), a contract schedule as a rule source: invented contract, invented clauses and wording, a temporary
database copy. The template in git holds placeholders only."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import load_contract_schedule as lcs

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "scripts" / "contract_schedule_template.json"
)
ITEMS = [
    {
        "id": "A1",
        "clause": "9.1",
        "kind": "calculations_with_datasheets",
        "text": "Invented: calculations come with the sheets.",
    },
    {
        "id": "A2",
        "clause": "9.2",
        "kind": "old_comments_closed",
        "text": "Invented: earlier comments are closed.",
    },
    {
        "id": "A3",
        "clause": "9.3",
        "kind": "holds_listed",
        "text": "Invented: holds are listed.",
    },
    {
        "id": "A4",
        "clause": "9.4",
        "kind": "deviation_waiver_form",
        "text": "Invented: a deviation needs a waiver form.",
    },
]


def _file(tmp_path, items=None, contract="Invented Contract Z", name="schedule.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"contract": contract, "items": ITEMS if items is None else items})
    )
    return path


@pytest.fixture
def conn(tmp_path):
    return sqlite3.connect(tmp_path / "copy.sqlite")


def test_the_template_in_git_holds_placeholders_only_and_cannot_be_loaded():
    data = json.loads(TEMPLATE.read_text())
    assert {i["kind"] for i in data["items"]} == set(lcs.KINDS)
    assert all("<" in i["text"] and "<" in i["id"] for i in data["items"])
    with pytest.raises(lcs.Refused, match="outside the repository"):
        lcs.read_items(TEMPLATE)
    with pytest.raises(lcs.Refused, match="placeholder"):
        lcs.read_items(TEMPLATE, repo=Path("/nonexistent-repo-root"))


def test_a_local_file_loads_into_rules_with_source_contract_schedule(tmp_path, conn):
    contract, items = lcs.read_items(_file(tmp_path))
    assert lcs.load(conn, contract, items, "me") == {
        "new": 4,
        "new_version": 0,
        "unchanged": 0,
    }
    rules = lcs.current_rules(conn)
    assert [r["id"] for r in rules] == ["A1", "A2", "A3", "A4"]
    assert {r["source"] for r in rules} == {"contract schedule"}
    assert {r["kind"] for r in rules} == set(lcs.KINDS)


def test_a_repeat_adds_nothing_and_a_changed_text_adds_a_version_and_keeps_the_old(
    tmp_path, conn
):
    contract, items = lcs.read_items(_file(tmp_path))
    lcs.load(conn, contract, items, "me")
    assert lcs.load(conn, contract, items, "me") == {
        "new": 0,
        "new_version": 0,
        "unchanged": 4,
    }
    changed = [
        {**items[0], "text": "Invented: calculations come with the sheets, signed."},
        *items[1:],
    ]
    assert lcs.load(conn, contract, changed, "me") == {
        "new": 0,
        "new_version": 1,
        "unchanged": 3,
    }
    assert (
        conn.execute("SELECT COUNT(*) FROM contract_schedule_rule").fetchone()[0] == 5
    )
    assert next(r for r in lcs.current_rules(conn) if r["id"] == "A1")["version"] == 2
    for sql in (
        "UPDATE contract_schedule_rule SET text = 'x'",
        "DELETE FROM contract_schedule_rule",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ({"value": 25}, "never an equipment limit"),
        ({"unit": "bar"}, "never an equipment limit"),
        ({"comparator": ">="}, "never an equipment limit"),
        ({"kind": "max_pressure"}, "not a completeness kind"),
        ({"text": ""}, "no text"),
        ({"clause": "<clause>"}, "placeholder"),
    ],
)
def test_an_item_that_is_not_a_completeness_check_is_refused(tmp_path, bad, why):
    with pytest.raises(lcs.Refused, match=why):
        lcs.read_items(_file(tmp_path, [{**ITEMS[0], **bad}]))


def test_a_file_that_is_not_fit_is_refused(tmp_path):
    for bad in ([], [ITEMS[0], ITEMS[0]]):
        with pytest.raises(lcs.Refused):
            lcs.read_items(_file(tmp_path, bad))
    with pytest.raises(lcs.Refused, match="name the contract"):
        lcs.read_items(_file(tmp_path, contract="<contract label>"))
    (tmp_path / "x.json").write_text("not json")
    with pytest.raises(lcs.Refused, match="cannot be read"):
        lcs.read_items(tmp_path / "x.json")


def test_a_live_shaped_database_gets_no_table(tmp_path):
    live = tmp_path / "backend" / "data"
    live.mkdir(parents=True)
    conn = sqlite3.connect(live / "rag_intelligence.sqlite")
    with pytest.raises(lcs.Refused, match="live-shaped"):
        lcs.load(conn, "Invented Contract Z", ITEMS, "me")
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def test_loading_names_who(conn):
    with pytest.raises(lcs.Refused, match="who"):
        lcs.load(conn, "Invented Contract Z", ITEMS, " ")


RULE = {"kind": "holds_listed"}
QUOTE = {"quote": "Holds: none.", "page": 4, "verified": True}


@pytest.mark.parametrize(
    ("evidence", "status"),
    [
        ({"found": [QUOTE]}, lcs.PRESENT),
        ({"found": [QUOTE], "searched_whole": False}, lcs.PRESENT),
        ({"found": [{**QUOTE, "verified": False}]}, lcs.NEEDS_ENGINEER),
        ({"found": [{**QUOTE, "page": None}]}, lcs.NEEDS_ENGINEER),
        ({"found": [{**QUOTE, "quote": " "}]}, lcs.NEEDS_ENGINEER),
        ({"found": [], "searched_whole": True}, lcs.NOT_PRESENT),
        ({"found": [], "searched_whole": False}, lcs.NEEDS_ENGINEER),
        ({"found": []}, lcs.NEEDS_ENGINEER),
        (None, lcs.NEEDS_ENGINEER),
        (
            {"found": [{**QUOTE, "verified": False}], "searched_whole": True},
            lcs.NEEDS_ENGINEER,
        ),
    ],
)
def test_present_needs_a_verified_quote_and_absent_needs_a_whole_search(
    evidence, status
):
    assert lcs.completeness(RULE, evidence)[0] == status


def test_an_item_of_another_kind_is_never_decided():
    assert (
        lcs.completeness({"kind": "max_pressure"}, {"found": [QUOTE]})[0]
        == lcs.NEEDS_ENGINEER
    )


def test_the_script_loads_a_local_file_into_a_copy_and_lists_ids_only(
    tmp_path, monkeypatch, capsys
):
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()
    monkeypatch.setattr(settings, "db_path", copy)
    db.reset_connection()
    assert (
        lcs.main(["--db", str(copy), "--file", str(_file(tmp_path)), "--by", "me"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["new"] == 4
    assert lcs.main(["--db", str(copy), "--list"]) == 0
    listed = capsys.readouterr().out
    assert "A1" in listed and "calculations come" not in listed
    assert (
        lcs.main(["--db", str(copy), "--file", str(TEMPLATE), "--by", "me"])
        == lcs.EXIT_REFUSED
    )
    assert "outside the repository" in capsys.readouterr().out
