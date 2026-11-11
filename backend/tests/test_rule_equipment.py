"""The equipment label of a rule: table, taxonomy data, lab conversion, import and route. Invented data only."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import rule_equipment as eq
from app.db import connect
from tests import r2_security_support as support
from tests import rule_label_support as s

world = support.world
temp_storage = support.temp_storage
h = support.h
SHA = "c" * 64


@pytest.fixture
def conn(monkeypatch):
    s.switch(monkeypatch)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    eq.create_tables(c)
    return c


def row(ref="r1", **over):
    base = {
        "source": "requirement", "rule_ref": ref, "equip_family": None, "equip_type": None, "equip_part": None,
        "equip_general": 1, "equip_state": "agreed", "equip_disagreement": None, "model_a": "claude-sonnet-5-5",
        "model_b": "claude-opus-5-5", "prompt_version": "rule-equip-v1", "list_sha": SHA, "labelled_at": "2026-11-11T00:00:00Z",
    }  # fmt: skip
    base.update(over)
    return base


def first_type():
    tax = eq.Taxonomy.load()
    tid = sorted(tax.type_family)[0]
    return tid, tax.type_family[tid]


def test_the_taxonomy_and_mapping_are_data_files_the_code_reads():
    tax = eq.Taxonomy.load()
    assert tax.families and tax.type_family and tax.names
    tid, fam = first_type()
    assert tax.type_family[tid] == fam and tid in tax.expand({tid})
    assert any(tax.also.values())  # some type also counts as a broader one
    broad = next(a for a, parents in tax.also.items() if parents)
    assert set(tax.also[broad]) <= tax.expand({broad})
    mapping = eq.load_mapping()
    assert mapping["map"] and set(mapping["map"].values()) <= set(tax.type_family)
    assert all(
        t in tax.type_family
        for ts in (mapping.get("related") or {}).values()
        for t in ts
    )


def test_switch_off_creates_no_table_and_on_creates_both(monkeypatch):
    s.switch(monkeypatch, False)
    c = sqlite3.connect(":memory:")
    eq.ensure_schema(c)
    with pytest.raises(eq.SwitchedOff):
        eq.create_tables(c)
    assert not eq.has_tables(c)
    s.switch(monkeypatch, True)
    eq.create_tables(c)
    eq.create_tables(c)  # twice: nothing
    assert eq.has_tables(c)


def test_an_agreed_row_needs_two_different_models_a_prompt_and_a_list_hash_in_the_table_itself(
    conn,
):
    cols = [k for k in row() if k not in ()]
    sql = f"INSERT INTO rule_equipment_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    for bad in (
        {"model_b": "claude-sonnet-5-5"}, {"model_b": None}, {"prompt_version": ""}, {"list_sha": "zz"},
        {"equip_disagreement": "type"}, {"equip_general": 0},  # agreed but names nothing
    ):  # fmt: skip
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, tuple(row(**bad)[c] for c in cols))
    conn.execute(sql, tuple(row()[c] for c in cols))
    assert eq.label_for(conn, "requirement", "r1")["equip_state"] == "agreed"
    assert (
        eq.label_for(conn, "requirement", "nope") is None
        and eq.label_for(sqlite3.connect(":memory:"), "requirement", "r1") is None
    )


def test_rows_are_never_deleted_or_replaced_and_the_history_is_append_only(conn):
    counts = eq.import_rows(conn, [row()])
    assert counts == {"read": 1, "stored": 1, "refused": 0}
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM rule_equipment_label")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE rule_equipment_label SET source = 'rulebook'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM rule_equipment_label_event")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE rule_equipment_label_event SET state = 'x'")
    assert (
        conn.execute("SELECT COUNT(*) FROM rule_equipment_label_event").fetchone()[0]
        == 1
    )
    tid, fam = first_type()
    eq.import_rows(
        conn, [row(equip_general=0, equip_type=tid, equip_family=fam)]
    )  # a change updates and appends an event
    assert conn.execute("SELECT COUNT(*) FROM rule_equipment_label").fetchone()[0] == 1
    assert [
        r[0]
        for r in conn.execute(
            "SELECT event_type FROM rule_equipment_label_event ORDER BY id"
        )
    ] == ["insert", "relabel"]
    before = conn.execute("SELECT COUNT(*) FROM rule_equipment_label_event").fetchone()[
        0
    ]
    eq.import_rows(
        conn, [row(equip_general=0, equip_type=tid, equip_family=fam)]
    )  # identical: no new event
    assert (
        conn.execute("SELECT COUNT(*) FROM rule_equipment_label_event").fetchone()[0]
        == before
    )


@pytest.mark.parametrize(
    "bad,why",
    [
        ({"source": "elsewhere"}, "key"), ({"rule_ref": ""}, "key"), ({"equip_state": "maybe"}, "state"),
        ({"equip_type": "an_invented_type", "equip_general": 0}, "not_on_the_list"),
        ({"equip_family": "an_invented_family", "equip_general": 0}, "not_on_the_list"),
        ({"model_b": "claude-sonnet-5-5-20261101"}, "models"),  # the same family under a dated name
        ({"model_a": " "}, "models"), ({"prompt_version": None}, "prompt_version"), ({"list_sha": None}, "list_sha"),
        ({"equip_disagreement": "type"}, "disagreement"), ({"equip_general": 0}, "names_nothing"),
    ],
)  # fmt: skip
def test_a_row_that_fails_a_check_is_refused_and_never_stored_as_agreed(conn, bad, why):
    tax = eq.Taxonomy.load()
    assert eq.problem(row(**bad), tax) == why
    counts = eq.import_rows(conn, [row(**bad)])
    assert counts == {"read": 1, "stored": 0, "refused": 1}
    assert conn.execute("SELECT COUNT(*) FROM rule_equipment_label").fetchone()[0] == 0


def test_a_type_must_belong_to_the_family_it_names(conn):
    tid, fam = first_type()
    other = next(f for f in eq.Taxonomy.load().families if f != fam)
    assert (
        eq.problem(
            row(equip_general=0, equip_type=tid, equip_family=other), eq.Taxonomy.load()
        )
        == "family_does_not_hold_the_type"
    )
    assert (
        eq.problem(
            row(equip_general=0, equip_type=tid, equip_family=fam), eq.Taxonomy.load()
        )
        is None
    )


def test_a_needs_human_or_unlabelled_row_is_stored_as_it_says_and_approves_nothing(
    conn,
):
    rows = [row("h", equip_state="needs_human", equip_general=0, equip_disagreement="type", model_b=None),
            row("u", equip_state="unlabelled", equip_general=0, model_a=None, model_b=None, prompt_version=None, list_sha=None)]  # fmt: skip
    assert eq.import_rows(conn, rows) == {"read": 2, "stored": 2, "refused": 0}
    assert eq.label_for(conn, "requirement", "h")["equip_state"] == "needs_human"


def test_import_with_the_switch_off_writes_nothing(monkeypatch):
    s.switch(monkeypatch, False)
    c = sqlite3.connect(":memory:")
    with pytest.raises(eq.SwitchedOff):
        eq.import_rows(c, [row()])
    assert not eq.has_tables(c)


def lab_table(c, rows):
    c.execute(
        "CREATE TABLE rule_label (source TEXT, rule_ref TEXT, labelled_at TEXT, equip_family TEXT, equip_type TEXT,"
        " equip_part TEXT, equip_general INTEGER, equip_state TEXT, equip_disagreement TEXT, ea_model TEXT, ea_prompt_version TEXT,"
        " ea_list_sha TEXT, eb_model TEXT, eb_prompt_version TEXT, eb_list_sha TEXT)"
    )
    for r in rows:
        c.execute("INSERT INTO rule_label VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)


def test_the_lab_table_converts_to_a_file_the_import_accepts(conn, tmp_path):
    tid, fam = first_type()
    lab = sqlite3.connect(":memory:")
    lab_table(lab, [
        ("requirement", "a", "t", None, None, None, 1, "agreed", None, "claude-sonnet-5-5", "v1", SHA, "claude-opus-5-5", "v1", SHA),
        ("requirement", "b", "t", fam, tid, None, 0, "agreed", None, "claude-sonnet-5-5", "v1", SHA, "claude-opus-5-5", "v1", SHA),
        ("requirement", "c", "t", None, None, None, 0, "needs_human", "type", "claude-sonnet-5-5", "v1", SHA, "claude-opus-5-5", "v1", SHA),
        ("requirement", "d", "t", None, None, None, 0, None, None, None, None, None, None, None, None),  # not asked
        ("requirement", "e", "t", None, None, None, 1, "agreed", None, "claude-sonnet-5-5", "v1", SHA, "claude-opus-5-5", "v2", SHA),
    ])  # fmt: skip
    rows = eq.convert_lab(lab)
    assert [r["rule_ref"] for r in rows] == ["a", "b", "c", "e"]
    assert (
        next(r for r in rows if r["rule_ref"] == "e")["prompt_version"] is None
    )  # the two passes disagree on the prompt
    assert not any(
        "text" in k or "quote" in k for r in rows for k in r
    )  # ids and answers only
    path = tmp_path / "eq.json"
    eq.write_file(rows, path)
    counts = eq.import_rows(conn, eq.read_file(path))
    assert counts == {
        "read": 4,
        "stored": 3,
        "refused": 1,
    }  # "e": agreed without one prompt version: refused
    bare = sqlite3.connect(":memory:")
    bare.execute("CREATE TABLE rule_label (source TEXT, rule_ref TEXT)")
    assert eq.convert_lab(bare) == []  # a lab table with no equipment columns


def test_a_file_that_is_not_an_equipment_label_file_is_refused(tmp_path):
    for body in (
        "not json",
        json.dumps({"format": "rule-labels-v1", "rows": []}),
        json.dumps([1]),
        json.dumps({"format": eq.EXPORT_FORMAT}),
    ):
        (tmp_path / "x.json").write_text(body)
        with pytest.raises(ValueError):
            eq.read_file(tmp_path / "x.json")


def test_the_route_is_admin_only_404_when_off_and_the_server_writes(
    world, tmp_path, monkeypatch
):
    f = settings_file(tmp_path, monkeypatch)
    url = "/api/admin/rule-equipment/import"
    body = {"path": f.name}
    s.switch(monkeypatch, False)
    off = world.post(url, json=body, headers=h("u_admin"))
    assert off.status_code == 404 and "feature_off" in off.text
    assert "rule_equipment_label" not in {
        r[0] for r in connect().execute("SELECT name FROM sqlite_master")
    }
    s.switch(monkeypatch, True)
    assert world.post(url, json=body, headers=h("u_sub")).status_code == 404
    assert world.post(url, json=body).status_code == 404
    assert (
        world.post(url, json={"path": "../x.json"}, headers=h("u_admin")).status_code
        == 422
    )
    assert (
        world.post(url, json={"path": "missing.json"}, headers=h("u_admin")).status_code
        == 422
    )
    ok = world.post(url, json=body, headers=h("u_admin"))
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"read": 2, "stored": 1, "refused": 1}
    assert (
        world.post(url, json=body, headers=h("u_admin")).json() == ok.json()
    )  # idempotent


def settings_file(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    path = tmp_path / "eq-labels.json"
    eq.write_file([row("good"), row("bad", model_b="claude-sonnet-5-5")], path)
    return path
