"""STEP 5 (#805), editions: every edition kept with its date, the contract's cutoff rule picks one, the CRS prints it.
Invented standards, invented dates, no real contract."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import crs_mapping, crs_reference, db
from app import standard_editions as se
from app.config import settings

ED = [
    {"edition": "2019", "date": "2019-03-01"},
    {"edition": "2021", "date": "2021-05-10"},
    {"edition": "2023", "date": "2023-09-01"},
]
IN_EFFECT = {
    "rule": "in_effect_on",
    "date": "2022-01-15",
    "feed_conflict": "strictest",
    "always_latest_families": [],
}
AWARD = {
    "rule": "latest_at_award",
    "date": "2022-01-15",
    "feed_conflict": "none",
    "always_latest_families": ["ZZ-B"],
}


def test_in_effect_on_picks_the_latest_edition_issued_by_the_date():
    got = se.pick(ED, IN_EFFECT, "ZZ-A-001")
    assert (got.status, got.editions) == (se.PICKED, ("2021",))


def test_an_edition_issued_exactly_on_the_date_counts():
    assert se.pick(ED, {**IN_EFFECT, "date": "2021-05-10"}, "ZZ-A-001").editions == (
        "2021",
    )
    assert se.pick(ED, {**IN_EFFECT, "date": "2021-05-09"}, "ZZ-A-001").editions == (
        "2019",
    )


def test_a_named_family_always_takes_the_newest_edition_but_others_follow_the_award_date():
    assert se.pick(ED, AWARD, "ZZ-B-014").editions == ("2023",)
    assert se.pick(ED, AWARD, "ZZ-B").editions == ("2023",)
    assert se.pick(ED, AWARD, "ZZ-BX-014").editions == ("2021",)  # not the same family
    assert se.pick(ED, AWARD, "ZZ-A-001").editions == ("2021",)


def test_when_the_feed_names_another_edition_both_are_checked():
    got = se.pick(ED, IN_EFFECT, "ZZ-A-001", feed_edition="2019")
    assert (got.status, got.editions) == (se.BOTH, ("2021", "2019"))
    assert se.pick(ED, IN_EFFECT, "ZZ-A-001", feed_edition="2021").status == se.PICKED
    # a contract that does not ask for the stricter of both ignores the FEED
    assert se.pick(ED, AWARD, "ZZ-A-001", feed_edition="2019").editions == ("2021",)


def test_a_feed_edition_that_is_not_on_file_goes_to_the_engineer():
    got = se.pick(ED, IN_EFFECT, "ZZ-A-001", feed_edition="2015")
    assert got.status == se.NEEDS_ENGINEER and got.editions == ()


def test_nothing_is_guessed_when_dates_do_not_decide():
    assert se.pick([], IN_EFFECT, "ZZ-A").status == se.NEEDS_ENGINEER
    assert (
        se.pick([{"edition": "2020", "date": None}], IN_EFFECT, "ZZ-A").status
        == se.NEEDS_ENGINEER
    )
    assert (
        se.pick(ED, {**IN_EFFECT, "date": "2018-01-01"}, "ZZ-A").status
        == se.NEEDS_ENGINEER
    )
    # a year-only date that straddles the cutoff cannot say whether it came first
    coarse = [
        {"edition": "2022", "date": "2022"},
        {"edition": "2019", "date": "2019-03-01"},
    ]
    assert se.pick(coarse, IN_EFFECT, "ZZ-A").status == se.NEEDS_ENGINEER
    # an edition without a date is named, not used
    mixed = [*ED, {"edition": "X", "date": ""}]
    assert "no readable date" in se.pick(mixed, IN_EFFECT, "ZZ-A").reason


def test_strictest_takes_the_harder_limit_per_comparator():
    assert se.strictest([25, 30], ">=") == 30
    assert se.strictest([25, 30], "<=") == 25
    assert se.strictest([], "<=") is None
    assert se.strictest([25, 30], "=") is None
    assert se.strictest([True, 30], "<=") == 30


def test_the_template_policy_file_loads_and_a_bad_entry_is_named(tmp_path):
    assert set(se.load_policies()) == {"example-contract-a", "example-contract-b"}
    bad = tmp_path / "p.json"
    bad.write_text(
        json.dumps({"contracts": {"c1": {"rule": "whenever", "date": "2020-01-01"}}})
    )
    with pytest.raises(se.BadPolicy, match="c1"):
        se.load_policies(bad)
    bad.write_text(
        json.dumps({"contracts": {"c2": {"rule": "in_effect_on", "date": "2020-01"}}})
    )
    with pytest.raises(se.BadPolicy, match="c2"):
        se.load_policies(bad)


def test_the_owner_edits_the_cutoff_in_data_not_code(tmp_path, monkeypatch):
    mine = tmp_path / "mine.json"
    mine.write_text(
        json.dumps({"contracts": {"k": {**IN_EFFECT, "date": "2019-12-31"}}})
    )
    monkeypatch.setenv("EDITION_CUTOFF_FILE", str(mine))
    assert se.pick(ED, se.load_policies()["k"], "ZZ-A").editions == ("2019",)


# ------------------------------------------------------------------------------------------------ the register


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    c = sqlite3.connect(tmp_path / "copy.sqlite")
    se.ensure_schema(c)
    return c


def test_every_edition_is_kept_with_its_date_and_none_is_rewritten(conn):
    se.add_edition(conn, "ZZ-A-001", "2019", "2019-03-01", "me")
    se.add_edition(conn, "ZZ-A-001", "2021", "2021-05", "me")
    assert [e["edition"] for e in se.editions_of(conn, "ZZ-A-001")] == ["2019", "2021"]
    for sql in (
        "UPDATE standard_edition SET issued_on = '2030'",
        "DELETE FROM standard_edition",
        "INSERT OR REPLACE INTO standard_edition (id, family, edition, issued_on, recorded_by, recorded_at)"
        " SELECT id, family, edition, '2030', 'x', 'x' FROM standard_edition",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="editions"):
            conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        se.add_edition(
            conn, "ZZ-A-001", "2019", "2019-03-01", "me"
        )  # the same edition twice
    assert len(se.editions_of(conn, "ZZ-A-001")) == 2


def test_an_edition_without_a_readable_date_is_not_registered(conn):
    for bad in ("", "March 2019", "2019-13"):
        with pytest.raises(ValueError):
            se.add_edition(conn, "ZZ-A-001", "2019", bad, "me")
    assert se.editions_of(conn, "ZZ-A-001") == []


def test_the_register_is_off_by_default_and_never_on_a_live_shaped_file(
    tmp_path, monkeypatch
):
    c = sqlite3.connect(tmp_path / "copy.sqlite")
    monkeypatch.setattr(settings, "standard_editions_enabled", False)
    with pytest.raises(se.SwitchedOff):
        se.ensure_schema(c)
    assert c.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    live = tmp_path / "backend" / "data"
    live.mkdir(parents=True)
    lc = sqlite3.connect(live / "rag_intelligence.sqlite")
    with pytest.raises(se.RefusedLive):
        se.ensure_schema(lc)
    assert lc.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------------ the CRS cell


def test_a_finding_keeps_its_edition_and_the_standard_reference_prints_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    db.reset_connection()
    db.init_db()
    from app import review

    ref = crs_mapping._standard_reference(
        {
            "standard_name": "ZZ-A-001.pdf",
            "standard_clause": "4.3",
            "standard_page": 2,
            "standard_edition": "2021",
        }
    )
    assert ref == "ZZ-A-001 (2021) cl. 4.3 (p.2)"


def test_a_datasheet_check_source_prints_its_edition_when_known_and_is_unchanged_otherwise():
    base = {
        "origin": "datasheet_check",
        "standard_clause": "ZZ 520-I 3.20",
        "standard_page": 12,
    }
    assert crs_reference.check_reference(base) == "ZZ 520-I 3.20 (p.12)"
    assert (
        crs_reference.check_reference({**base, "standard_edition": "2021"})
        == "ZZ 520-I 3.20 (2021) (p.12)"
    )
    named = {
        **base,
        "standard_clause": "ZZ 520-I 2021 3.20",
        "standard_edition": "2021",
    }
    assert crs_reference.check_reference(named) == "ZZ 520-I 2021 3.20 (p.12)"


def test_a_version_2_finding_stores_the_edition_of_the_rule_it_cites(
    tmp_path, monkeypatch
):
    from app import rulebook_v2_findings as rf

    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    db.reset_connection()
    db.init_db()
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('d1','x.pdf','sha',1,'x.pdf','ready',1,'2026-11-03T00:00:00Z')"
        )
    payload = {
        "document_id": "d1",
        "category": "requirement_deviation",
        "severity": "minor",
        "requirement": "r",
        "finding": "f",
        "required_action": "a",
        "status": "open",
        "approval_status": "pending",
    }
    for edition, expect in (("2021", "2021"), ("", None)):
        made = rf._created(
            conn, {"document_id": "s1", "page": 3, "edition": edition}, payload
        )
        assert made["standard_edition"] == expect


def test_clean_edition_trims_and_blank_is_none():
    assert se.clean_edition(" 2021 ") == "2021"
    assert se.clean_edition("  ") is None and se.clean_edition(None) is None


def test_a_reader_with_no_grant_on_the_standard_is_not_told_its_edition(
    tmp_path, monkeypatch
):
    from app import review

    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    db.reset_connection()
    db.init_db()
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('s1','s.pdf','sha',1,'s.pdf','ready',1,'2026-11-03T00:00:00Z')"
        )
    finding = {"standard_document_id": "s1", "standard_edition": "2021"}
    review.withhold_unreadable_standards([finding], frozenset())
    assert finding["standard_edition"] is None
