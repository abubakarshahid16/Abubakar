# ruff: noqa: F811
"""Order 14, piece D: saved checklists (a new build never overwrites; only a standards-only build is kept). Invented values only."""

from __future__ import annotations

import pytest

from app import aim_review_store as store
from app import db
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

KEY = "datasheet__inv"


def _checklist(n_items: int = 3, **kw) -> dict:
    base = {
        "key": KEY,
        "built_from": "standards only, no paper",
        "identity": {
            "kind": "datasheet",
            "equipment_type": "invented type",
            "subject": "invented",
            "subject_key": "inv",
        },
        "books": [{"id": "doc_inv_book_1"}, "doc_inv_book_2"],
        "items": [
            {"id": f"C{i:02d}", "text": f"invented item {i}"} for i in range(n_items)
        ],
    }
    return {**base, **kw}


def test_put_then_get_returns_the_same_body_and_the_sha(temp_storage):
    s = store.DbChecklistStore(db.connect())
    assert s.get(KEY) is None
    digest = s.put(KEY, _checklist(), run_id="gen_1", usd=0.79)
    assert len(digest) == 64
    assert s.get(KEY) == {**_checklist(), "sha256": digest}
    row = store.checklists(db.connect())[0]
    assert row["key"] == KEY and row["sha256"] == digest and row["items"] == 3
    assert row["kind"] == "datasheet" and row["equipment_type"] == "invented type"
    assert row["books"] == ["doc_inv_book_1", "doc_inv_book_2"]
    assert row["built_from"] == "standards only, no paper" and row["current"] is True
    assert row["made_by_run"] == "gen_1" and row["usd"] == 0.79


def test_put_is_idempotent_for_the_same_body(temp_storage):
    s = store.DbChecklistStore(db.connect())
    a = s.put(KEY, _checklist(), run_id="gen_1", usd=0.79)
    b = s.put(KEY, _checklist(), run_id="gen_2", usd=0.0)
    assert a == b
    rows = store.checklists(db.connect())
    assert len(rows) == 1 and rows[0]["made_by_run"] == "gen_1"


def test_a_new_build_never_overwrites_the_older_one(temp_storage):
    s = store.DbChecklistStore(db.connect())
    old = s.put(KEY, _checklist(3), run_id="gen_1", usd=0.7)
    new = s.put(KEY, _checklist(5), run_id="gen_2", usd=0.8)
    assert old != new
    assert len(s.get(KEY)["items"]) == 5  # the new one is the current one
    rows = {r["sha256"]: r for r in store.checklists(db.connect())}
    assert rows[old]["current"] is False and rows[new]["current"] is True
    assert rows[old]["items"] == 3  # the older row is whole, not rewritten
    stored = (
        db.connect()
        .execute("SELECT body_json FROM aim_checklists WHERE sha256 = ?", (old,))
        .fetchone()[0]
    )
    assert "invented item 2" in stored and "invented item 3" not in stored


def test_putting_an_older_body_back_makes_it_current_and_keeps_one_current_row(
    temp_storage,
):
    s = store.DbChecklistStore(db.connect())
    old = s.put(KEY, _checklist(3), run_id="gen_1", usd=0.7)
    s.put(KEY, _checklist(5), run_id="gen_2", usd=0.8)
    assert s.put(KEY, _checklist(3), run_id="gen_3", usd=0.0) == old
    assert len(s.get(KEY)["items"]) == 3
    assert sum(1 for r in store.checklists(db.connect()) if r["current"]) == 1


@pytest.mark.parametrize(
    "built_from",
    [
        "built from a paper",
        "",
        None,
        "Standards only, no paper",
        "standards only, no paper ",
    ],
)
def test_a_checklist_not_built_from_standards_alone_is_refused(
    temp_storage, built_from
):
    s = store.DbChecklistStore(db.connect())
    with pytest.raises(ValueError):
        s.put(KEY, _checklist(built_from=built_from), run_id="gen_1", usd=0.1)
    assert s.get(KEY) is None and store.checklists(db.connect()) == []


def test_a_checklist_without_built_from_is_refused(temp_storage):
    body = _checklist()
    del body["built_from"]
    with pytest.raises(ValueError):
        store.DbChecklistStore(db.connect()).put(KEY, body, run_id="gen_1", usd=0.1)


def test_get_ignores_a_row_that_was_not_built_from_standards_alone(temp_storage):
    """A row written by anything else (a hand edit) is not served as a saved checklist."""
    s = store.DbChecklistStore(db.connect())
    s.put(KEY, _checklist(), run_id="gen_1", usd=0.1)
    with db.connect() as conn:
        conn.execute(
            "UPDATE aim_checklists SET built_from = 'a paper' WHERE key = ?", (KEY,)
        )
    assert s.get(KEY) is None


def test_get_of_unreadable_body_is_none(temp_storage):
    s = store.DbChecklistStore(db.connect())
    s.put(KEY, _checklist(), run_id="gen_1", usd=0.1)
    with db.connect() as conn:
        conn.execute(
            "UPDATE aim_checklists SET body_json = 'not json' WHERE key = ?", (KEY,)
        )
    assert s.get(KEY) is None


def test_checklists_lists_current_first_and_never_the_body(temp_storage):
    s = store.DbChecklistStore(db.connect())
    s.put("a__x", _checklist(2, key="a__x"), run_id="r1", usd=0.1)
    s.put("b__y", _checklist(4, key="b__y"), run_id="r2", usd=0.2)
    s.put("b__y", _checklist(5, key="b__y"), run_id="r3", usd=0.2)
    rows = store.checklists(db.connect())
    assert [r["current"] for r in rows] == [True, True, False]
    assert all("body" not in r and "body_json" not in r for r in rows)
    assert {r["key"] for r in rows} == {"a__x", "b__y"}


def test_a_body_got_and_put_back_keeps_its_fingerprint_and_keys_lists_current_keys(
    temp_storage,
):
    """ASK A -> D: `get` carries the current sha256 so a reusing run records it; `put` ignores that key, so the same body
    never becomes a second row; `keys` names the keys with a current checklist."""
    s = store.DbChecklistStore(db.connect())
    assert s.keys() == []
    digest = s.put(KEY, _checklist(), run_id="gen_1", usd=0.5)
    got = s.get(KEY)
    assert got["sha256"] == digest
    assert s.put(KEY, got, run_id="gen_2", usd=0.0) == digest
    assert len(store.checklists(db.connect())) == 1
    s.put("procedure__inv", _checklist(2), run_id="gen_3", usd=0.1)
    assert s.keys() == sorted([KEY, "procedure__inv"])
