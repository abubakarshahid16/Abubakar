# ruff: noqa: F811
"""Order 14, piece D: the general review's stored runs, lines and `shown_label` (invented values only)."""

from __future__ import annotations

import hashlib
import json

import pytest

from app import aim_review_store as store
from app import db, review_points_service
from tests.test_p3_review_jobs import _doc, temp_storage  # noqa: F401 - fixture

PAPER = "doc_inv_paper"
NOW = "2026-11-18T10:00:00Z"


def _review_run(run_id: str, started: str = NOW) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at)"
            " VALUES (?, ?, 'running', ?, ?, ?)",
            (run_id, PAPER, started, started, started),
        )


def _started(run_id: str = "gen_1", started: str = NOW):
    _doc(
        PAPER, "CONTRACTOR_SUBMITTAL", "invented paper text"
    ) if not _has_paper() else None
    _review_run(run_id, started)
    with db.connect() as conn:
        store.start_run(conn, run_id, PAPER, started)
    return run_id


def _has_paper() -> bool:
    return (
        db.connect()
        .execute("SELECT 1 FROM documents WHERE id = ?", (PAPER,))
        .fetchone()
        is not None
    )


def _line(**kw) -> dict:
    base = {
        "item_id": "C01",
        "label": "Question",
        "field": "invented field",
        "page": 2,
        "quote": "invented quote",
        "comment": "invented comment",
        "standard": "Invented Std 1",
        "book_document_id": "doc_inv_book",
        "clause": "4.1",
        "source": "held standard",
        "topic": "invented topic",
    }
    return {**base, **kw}


def _result(lines, **kw) -> dict:
    base = {
        "status": "done",
        "stop_reason": "",
        "identity": {
            "kind": "datasheet",
            "equipment_type": None,
            "subject": "invented",
            "subject_key": "inv",
            "service": None,
        },
        "checklist_key": "datasheet__inv",
        "checklist_sha256": "abc",
        "checklist_reused": True,
        "books": ["doc_inv_book"],
        "not_held": [{"name": "Invented Std 2", "why": "not in the library"}],
        "unlisted_books": ["doc_inv_other"],
        "unlisted_count": 1,
        "lines": lines,
        "calls": [{"step": "aim_judge", "model": "m", "usd": 0.5, "ok": True}],
        "usd": 0.5,
        "seconds": 12.5,
    }
    return {**base, **kw}


# ---- shown_label: the one table of section 4 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "compare", "deferred", "shown"),
    [
        ("Not met", {"result": "fail"}, False, "Fail, compared by code"),
        ("Met", {"result": "pass"}, False, "Pass, compared by code"),
        ("Not met", None, False, "AI opinion: not met"),
        ("Met", None, False, "AI opinion: met"),
        ("Does not apply", None, False, "AI opinion: does not apply"),
        ("AI opinion", None, False, "AI opinion"),
        ("Question", None, False, "Question"),
        # a result of code that is not pass or fail is not "compared by code"
        ("Met", {"result": "unknown"}, False, "AI opinion: met"),
        ("Not met", {"result": "n/a"}, False, "AI opinion: not met"),
        # the code result and the label must agree: never a "Pass" shown on a Not met line
        ("Not met", {"result": "pass"}, False, "AI opinion: not met"),
        ("Met", {"result": "fail"}, False, "AI opinion: met"),
        # a vendor-deferred value is always a Question, even with a code result
        ("Met", {"result": "pass"}, True, "Question"),
        ("Not met", {"result": "fail"}, True, "Question"),
        ("Not met", None, True, "Question"),
        # an unknown word is never a verdict
        ("Complies", None, False, "Question"),
    ],
)
def test_shown_label_table(label, compare, deferred, shown):
    assert store.shown_label(label, compare, deferred) == shown


def test_shown_label_reads_the_stored_json_text():
    assert (
        store.shown_label("Not met", json.dumps({"result": "fail"}))
        == "Fail, compared by code"
    )
    assert store.shown_label("Met", "not json") == "AI opinion: met"


def test_only_code_earns_compared_by_code(temp_storage):
    """Across every label x every code result, `compared by code` appears only when the code result is fail/pass and agrees."""
    for label in ("Met", "Not met", "Question", "Does not apply", "AI opinion"):
        for result in (None, "fail", "pass", "unknown"):
            shown = store.shown_label(label, {"result": result} if result else None)
            earned = (label, result) in {("Not met", "fail"), ("Met", "pass")}
            assert ("compared by code" in shown) == earned


def test_finish_stores_shown_label_computed_here_not_taken_from_the_caller(
    temp_storage,
):
    run_id = _started()
    lie = _line(
        label="Met", shown_label="Pass, compared by code"
    )  # a caller's own words are ignored
    deferred = _line(
        item_id="C02", label="Not met", code_compare={"result": "fail"}, deferred=True
    )
    fail = _line(
        item_id="C03",
        label="Not met",
        code_compare={"result": "fail", "why": "invented"},
    )
    conn = db.connect()
    store.finish_run(conn, run_id, _result([lie, deferred, fail]), NOW)
    shown = [x["shown_label"] for x in store.lines(conn, run_id)]
    assert shown == ["AI opinion: met", "Question", "Fail, compared by code"]


def test_a_deferred_flag_inside_the_numbers_also_makes_a_question(temp_storage):
    run_id = _started()
    conn = db.connect()
    store.finish_run(
        conn,
        run_id,
        _result(
            [
                _line(
                    label="Met",
                    numbers={"deferred": True},
                    code_compare={"result": "pass"},
                )
            ]
        ),
        NOW,
    )
    assert store.lines(conn, run_id)[0]["shown_label"] == "Question"


# ---- finish_run ----------------------------------------------------------------------------------------------------------------


def test_finish_run_stores_the_run_and_every_line_in_order(temp_storage):
    run_id = _started()
    conn = db.connect()
    lines = [_line(item_id=f"C{i:02d}", comment=f"c{i}", page=i) for i in range(1, 5)]
    store.finish_run(conn, run_id, _result(lines), "2026-11-18T10:05:00Z")
    row = store.run(conn, run_id)
    assert row["status"] == "done"
    assert row["finished_at"] == "2026-11-18T10:05:00Z"
    assert row["usd"] == 0.5 and row["seconds"] == 12.5
    assert row["identity"]["kind"] == "datasheet"
    assert row["books"] == ["doc_inv_book"]
    assert row["unlisted"] == ["doc_inv_other"]
    assert row["checklist_reused"] is True
    assert row["method_version"] == "aim-1"
    got = store.lines(conn, run_id)
    assert [x["line_no"] for x in got] == [1, 2, 3, 4]
    assert [x["item_id"] for x in got] == ["C01", "C02", "C03", "C04"]
    assert got[2]["page"] == 3 and got[2]["comment"] == "c3"


def test_a_finished_run_can_be_finished_again_without_doubling_lines(temp_storage):
    run_id = _started()
    conn = db.connect()
    store.finish_run(conn, run_id, _result([_line(), _line(item_id="C02")]), NOW)
    store.finish_run(conn, run_id, _result([_line()]), NOW)
    assert len(store.lines(conn, run_id)) == 1


def test_finish_run_is_all_or_nothing_on_a_bad_line(temp_storage):
    """The third line has no method label: nothing of the run is stored, and the run row stays as it was (queued)."""
    run_id = _started()
    conn = db.connect()
    with pytest.raises(ValueError):
        store.finish_run(
            conn,
            run_id,
            _result(
                [_line(), _line(item_id="C02"), _line(item_id="C03", label="Complies")]
            ),
            NOW,
        )
    assert store.lines(conn, run_id) == []
    row = store.run(conn, run_id)
    assert row["status"] == "queued" and row["finished_at"] is None


def test_finish_run_is_all_or_nothing_when_the_insert_fails_midway(
    temp_storage, monkeypatch
):
    """Lines are written, then the run row update fails: the lines are rolled back too (the earlier lines stay as they were)."""
    run_id = _started()
    conn = db.connect()
    store.finish_run(conn, run_id, _result([_line(comment="first")]), NOW)
    before = store.lines(conn, run_id)

    class _Boom:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def execute(self, sql, *args):
            if sql.lstrip().startswith("UPDATE aim_runs"):
                raise RuntimeError("disk full")
            return self._inner.execute(sql, *args)

    with pytest.raises(RuntimeError):
        store.finish_run(
            _Boom(conn),
            run_id,
            _result([_line(comment="second"), _line(item_id="C02")], status="stopped"),
            NOW,
        )
    assert store.lines(conn, run_id) == before
    assert store.run(conn, run_id)["status"] == "done"


def test_finish_run_for_an_unknown_run_stores_no_line(temp_storage):
    _started()
    conn = db.connect()
    with pytest.raises(LookupError):
        store.finish_run(conn, "gen_missing", _result([_line()]), NOW)
    assert conn.execute("SELECT COUNT(*) FROM aim_lines").fetchone()[0] == 0


def test_finish_run_refuses_an_unknown_status(temp_storage):
    run_id = _started()
    with pytest.raises(ValueError):
        store.finish_run(db.connect(), run_id, _result([_line()], status="great"), NOW)


def test_a_stopped_run_keeps_its_lines_and_is_not_a_finished_review(temp_storage):
    run_id = _started()
    conn = db.connect()
    store.finish_run(
        conn,
        run_id,
        _result([_line()], status="stopped", stop_reason="CAP: invented words"),
        NOW,
    )
    assert store.run(conn, run_id)["stop_reason"] == "CAP: invented words"
    assert len(store.lines(conn, run_id)) == 1
    assert store.latest_run(conn, PAPER) is None
    assert store.latest_run(conn, PAPER, done_only=False)["run_id"] == run_id


def test_numbers_and_code_compare_round_trip(temp_storage):
    run_id = _started()
    conn = db.connect()
    nums = {
        "paper_value": "95",
        "paper_unit": "dB",
        "operator": "<=",
        "rule_value": "90",
        "rule_unit": "dB",
    }
    cmp_ = {"result": "fail", "why": "95 dB is above 90 dB"}
    store.finish_run(
        conn,
        run_id,
        _result(
            [
                _line(
                    label="Not met",
                    numbers=nums,
                    code_compare=cmp_,
                    code="code compared",
                )
            ]
        ),
        NOW,
    )
    got = store.lines(conn, run_id)[0]
    assert got["numbers"] == nums and got["code_compare"] == cmp_
    assert got["code_note"] == "code compared"
    assert got["quote_unverified"] == ""


def test_quote_unverified_is_kept_as_its_text_apart_from_the_quote(temp_storage):
    run_id = _started()
    conn = db.connect()
    store.finish_run(
        conn,
        run_id,
        _result([_line(quote="", quote_unverified="words not found")]),
        NOW,
    )
    got = store.lines(conn, run_id)[0]
    assert got["quote_unverified"] == "words not found" and got["quote"] == ""


# ---- readers -----------------------------------------------------------------------------------------------------------------


def test_latest_run_and_unlisted_of_last(temp_storage):
    older = _started("gen_a", "2026-11-17T10:00:00Z")
    newer = _started("gen_b", "2026-11-18T10:00:00Z")
    conn = db.connect()
    assert store.latest_run(conn, PAPER) is None  # queued runs are not finished
    store.finish_run(conn, older, _result([_line()], unlisted_books=["doc_x"]), NOW)
    assert store.latest_run(conn, PAPER)["run_id"] == "gen_a"
    assert store.unlisted_of_last(conn, PAPER) == frozenset({"doc_x"})
    store.finish_run(
        conn, newer, _result([_line()], unlisted_books=["doc_y", "doc_z"]), NOW
    )
    assert store.latest_run(conn, PAPER)["run_id"] == "gen_b"
    assert store.unlisted_of_last(conn, PAPER) == frozenset({"doc_y", "doc_z"})
    assert store.latest_run(conn, "doc_other") is None
    assert store.unlisted_of_last(conn, "doc_other") == frozenset()


def test_a_general_run_is_invisible_to_the_old_run_list(temp_storage):
    run_id = _started()
    conn = db.connect()
    store.finish_run(conn, run_id, _result([_line()]), NOW)
    assert review_points_service.runs_of_paper(conn, PAPER) == (None, None)
    assert store.is_general(conn, run_id)


def test_the_readers_work_without_the_tables(temp_storage):
    conn = db.connect()
    assert store.run(conn, "x") is None and store.lines(conn, "x") == []
    assert store.latest_run(conn, PAPER) is None
    assert store.unlisted_of_last(conn, PAPER) == frozenset()
    assert store.checklists(conn) == []
    assert store.DbChecklistStore(conn).get("k") is None


# ---- old data is untouched -----------------------------------------------------------------------------------------------------


def _fingerprint(conn) -> str:
    """A hash of every row of every table that is not the general review's own."""
    h = hashlib.sha256()
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if not r[0].startswith("aim_")
        and not r[0].endswith(
            ("_fts", "_data", "_idx", "_content", "_docsize", "_config")
        )
    ]
    for name in names:
        h.update(name.encode())
        for row in conn.execute(f'SELECT * FROM "{name}"'):
            h.update(repr(tuple(row)).encode())
    return h.hexdigest()


def test_old_runs_and_their_files_are_unchanged_by_the_schema_and_a_general_run(
    temp_storage, tmp_path
):
    """Old run rows, findings and AI-run rows, and any stored old file on disk, are byte-identical after `ensure_schema` and after a
    general run is made and finished next to them."""
    _doc(PAPER, "CONTRACTOR_SUBMITTAL", "invented paper text")
    _review_run("rc_old", "2026-11-01T10:00:00Z")
    old_file = tmp_path / "runs" / "rc_old" / "crs-internal.xlsx"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"PK invented old workbook bytes")
    before_file = hashlib.sha256(old_file.read_bytes()).hexdigest()
    conn = db.connect()
    before = _fingerprint(conn)
    store.ensure_schema(conn)
    store.ensure_schema(conn)
    assert _fingerprint(conn) == before
    _review_run("gen_1")
    run_id = "gen_1"
    store.start_run(conn, run_id, PAPER, NOW)
    store.finish_run(conn, run_id, _result([_line()]), NOW)
    after = _fingerprint(conn)
    # only the new review_runs row is new; every old row is the same
    old_only = conn.execute("SELECT * FROM review_runs WHERE id = 'rc_old'").fetchone()
    assert old_only["status"] == "running"
    assert before != after  # the new run's own review_runs row
    assert hashlib.sha256(old_file.read_bytes()).hexdigest() == before_file


def test_a_line_table_made_before_the_named_books_column_is_upgraded_and_still_stores(
    temp_storage,
):
    """A rehearsal or live database whose `aim_lines` was made before `named_books_json`: the start-up's `ensure_schema` adds the
    column at the END (additive), so the positional insert of `finish_run` lands every value in its own column."""
    conn = db.connect()
    old = next(
        c for c in store._SCHEMA if f"TABLE IF NOT EXISTS {store.LINES}" in c
    ).replace("        named_books_json  TEXT,\n", "")
    assert "named_books_json" not in old
    conn.execute(old)
    conn.commit()
    store.ensure_schema(conn)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({store.LINES})")]
    assert cols[-1] == "named_books_json"
    run_id = _started("gen_old_table")
    named = [{"id": "doc_inv_book", "name": "Invented Std 1"}]
    store.finish_run(conn, run_id, _result([_line(named_books=named)]), NOW)
    got = store.lines(conn, run_id)[0]
    assert got["named_books"] == named and got["label"] == _line()["label"]
