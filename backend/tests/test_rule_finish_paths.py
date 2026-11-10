"""The rule finishing line's database opens: read only means read only whatever the path's spelling, the one write
connection is opened only on a marked copy, and the rulebook reads filter by standard, rule key and version.
Every text here is INVENTED."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from app import rule_finish_guard as guard
from app import rule_finish_store as st
from app import rulebook_v2_schema as schema
from tests.test_rule_finish_kit import make_copy, marker_key  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def _scripts():
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_coverage_run as coverage
    import rule_finish_run as run

    return run, coverage


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Spy:
    """Records every sqlite3.connect call (arguments and the connection it returned)."""

    def __init__(self, monkeypatch):
        self.calls: list[tuple[tuple, dict, sqlite3.Connection]] = []
        real = sqlite3.connect

        def spy(*args, **kwargs):
            conn = real(*args, **kwargs)
            self.calls.append((args, kwargs, conn))
            return conn

        monkeypatch.setattr(guard.sqlite3, "connect", spy)


# ------------------------------------------------------------------------------------------------ read only is read only


@pytest.mark.parametrize(
    "suffix", ["?mode=rw&x=", "#frag", "%3Fmode=rw&x=", "?mode=rwc#x%"]
)
def test_a_read_only_open_stays_read_only_and_on_the_named_file_whatever_the_path_holds(
    tmp_path, suffix
):
    target = tmp_path / "t.sqlite"
    make_copy(target).close()  # marked, so a read of the WRONG file would say "marked"
    before = _digest(target)
    decoy = Path(str(target) + suffix)
    sqlite3.connect(str(decoy)).close()  # a plain file of that literal name
    run, coverage = _scripts()
    for opener in (guard.open_read_only, run.open_ro, coverage.ro):
        conn = opener(decoy)
        try:
            assert guard.db_file(conn) == str(decoy.resolve())
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("CREATE TABLE z (a)")
        finally:
            conn.close()
    assert guard.is_marked(target) and not guard.is_marked(decoy)
    assert _digest(target) == before


def test_every_read_only_open_of_the_finishing_line_goes_through_the_one_helper():
    files = [
        ROOT / "backend/app/rule_finish_guard.py",
        ROOT / "backend/app/rule_finish_record.py",
        ROOT / "scripts/rule_finish_run.py",
        ROOT / "scripts/rule_coverage_run.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert 'f"file:{' not in text, path.name
        assert text.count("mode=ro") <= 1, path.name  # only the helper itself spells it
    assert "open_read_only(pages_db)" in files[1].read_text(encoding="utf-8")


def test_is_marked_opens_read_only(tmp_path, monkeypatch):
    make_copy(tmp_path / "w.sqlite").close()
    spy = _Spy(monkeypatch)
    assert guard.is_marked(tmp_path / "w.sqlite")
    assert spy.calls, "is_marked opened nothing"
    for args, kwargs, _conn in spy.calls:
        assert kwargs.get("uri") is True and str(args[0]).endswith("?mode=ro")


# ------------------------------------------------------------------------------------------------ the one write connection


def _live(tmp_path: Path) -> Path:
    live = tmp_path / "other-checkout" / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    return live


def test_open_work_copy_never_opens_a_live_database_not_even_to_refuse_it(
    tmp_path, monkeypatch
):
    live = _live(tmp_path)
    make_copy(live).close()  # even with a signed marker naming it
    spy = _Spy(monkeypatch)
    with pytest.raises(guard.NotAWorkCopy, match="live"):
        guard.open_work_copy(live)
    with pytest.raises(guard.NotAWorkCopy, match="live"):
        guard.is_marked(live)
    assert spy.calls == []


def test_a_refused_work_connection_is_closed(tmp_path, monkeypatch):
    make_copy(tmp_path / "plain.sqlite", marked=False).close()
    spy = _Spy(monkeypatch)
    with pytest.raises(guard.NotAWorkCopy, match="no work-copy marker"):
        guard.open_work_copy(tmp_path / "plain.sqlite")
    [(_args, _kwargs, conn)] = spy.calls
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_a_marker_naming_this_file_as_its_own_source_is_refused(tmp_path):
    path = tmp_path / "self.sqlite"
    conn = make_copy(path, marked=False)
    guard._write_marker(conn, guard._real(path), guard._real(path))
    with pytest.raises(guard.NotAWorkCopy, match="protected"):
        guard.require_work_copy(conn)


def test_the_runner_refuses_a_live_path_before_it_opens_it(tmp_path, monkeypatch):
    run, _ = _scripts()
    source = tmp_path / "src.sqlite"
    make_copy(source, marked=False).close()
    live = _live(tmp_path)
    live.write_bytes(source.read_bytes())

    def opened(_path):
        raise AssertionError("the runner opened a live database")

    monkeypatch.setattr(guard, "is_marked", opened)
    with pytest.raises(SystemExit, match="live"):
        run.prepare_work_db(source, tmp_path / "pages.sqlite", live)


def test_the_runner_never_re_signs_a_copy_whose_marker_is_invalid(
    tmp_path, monkeypatch
):
    run, _ = _scripts()
    source = tmp_path / "src.sqlite"
    make_copy(source, marked=False).close()
    work = tmp_path / "work.sqlite"
    work.write_bytes(source.read_bytes())
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(tmp_path / "another.key"))
    conn = sqlite3.connect(work)
    guard._write_marker(conn, guard._real(work), guard._real(source))
    conn.close()
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(tmp_path / "marker.key"))
    before = _digest(work)
    with pytest.raises(SystemExit, match="not signed"):
        run.prepare_work_db(source, tmp_path / "pages.sqlite", work)
    assert _digest(work) == before


# ------------------------------------------------------------------------------------------------ the marker key


def test_a_marker_key_must_be_exactly_64_hex_characters(tmp_path, monkeypatch):
    key = tmp_path / "k.key"
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(key))
    first = guard._key()
    assert len(first) == 64 and guard._key() == first
    for bad in ("a" * 40, "a" * 63, "a" * 65, "g" * 64, "A" * 64 + "\nmore"):
        key.write_text(
            bad
        )  # e.g. a file read while the winner of the creation race was still writing it
        with pytest.raises(guard.NotAWorkCopy, match="64 hex"):
            guard._key()
    key.write_text("0123456789abcdef" * 4 + "\n")
    assert guard._key() == ("0123456789abcdef" * 4).encode()


# ------------------------------------------------------------------------------------------------ the rulebook reads


def _book(path: Path) -> sqlite3.Connection:
    """Three rules in two standards; one rule has two versions; one rule key is a prefix of another."""
    conn = make_copy(path, marked=False)  # r1 'keyabc12345' in X.pdf, version v1
    conn.executemany(
        "INSERT INTO rulebook_rule VALUES (?,?,?)",
        [("r2", "keyabc123456", "Y.pdf"), ("r3", "zz9", "X.pdf")],
    )
    for vid, rid, no, field in (
        ("v2a", "r2", 1, "old reading"),
        ("v2b", "r2", 2, "flange rating"),
        ("v3", "r3", 1, "design pressure"),
    ):
        conn.execute(
            "INSERT INTO rulebook_version (id, rule_id, version_no, kind, field) VALUES (?,?,?,?,?)",
            (vid, rid, no, "limit", field),
        )
        conn.execute(
            "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote)"
            " VALUES (?,?,?,?,?)",
            (vid, "d" + rid, "5." + vid, 2, "Invented quote for " + vid + "."),
        )
    conn.executemany(
        "INSERT INTO rulebook_applicability (rule_version_id, key_type, value) VALUES (?,?,?)",
        [
            ("v2b", "equipment_type", "pump"),
            ("v2b", "service", "sour"),
            ("v2a", "equipment_type", "vessel"),
        ],
    )
    conn.commit()
    return conn


def test_the_rulebook_reads_filter_by_standard_key_and_version(tmp_path):
    conn = _book(tmp_path / "book.sqlite")
    assert [r["rule_key"] for r in st.load_rules(conn, standard="X.pdf")] == [
        "keyabc12345",
        "zz9",
    ]
    assert [r["rule_key"] for r in st.load_rules(conn, standard="Y.pdf")] == [
        "keyabc123456"
    ]
    by_prefix = st.load_rules(conn, key_prefix="keyabc12345")
    assert [(r["rule_key"], r["version_id"]) for r in by_prefix] == [
        ("keyabc12345", "v1"),
        ("keyabc123456", "v2b"),  # the latest version only
    ]
    assert schema.rule_key_of_version(conn, "v2a") == "keyabc123456"
    assert schema.rule_key_of_version(conn, "v3") == "zz9"
    assert schema.rule_key_of_version(conn, "v1") == "keyabc12345"
    assert schema.rule_key_of_version(conn, "nope") is None
    [one] = st.load_rules_by_version(conn, "v1")
    assert one["version_id"] == "v1" and one["standard"] == "X.pdf"
    [latest] = st.load_rules_by_version(conn, "v2b")
    assert latest["version_no"] == 2 and latest["field"] == "flange rating"
    assert latest["clause"] == "5.v2b"
    assert latest["applicability"] == [("equipment_type", "pump"), ("service", "sour")]
    assert (
        st.load_rules_by_version(conn, "v2a") == []
    )  # an older version is not the rule in force
