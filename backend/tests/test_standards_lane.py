"""The standards converter lane at the Claude gate (CLAUDE.md rule 1): rule-book text of a held company standard of an
allowed family goes by its own named lane, never by the chat's per-request consent. Invented documents; no network."""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from app import (
    claude_approved,
    claude_auto_approve,
    contract_yes,
    review_engine,
    rule_second_approval,
    standards_lane,
)
from app.config import settings


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    c.execute(
        "CREATE TABLE document_classification (document_id TEXT PRIMARY KEY, document_role TEXT)"
    )
    for d, name, role in (("std", "SAES-X-100.pdf", "COMPANY_STANDARD"), ("other_family", "ZZZ-X-100.pdf", "COMPANY_STANDARD"),
                          ("sheet", "SAES-X-100 datasheet.pdf", "CONTRACTOR_SUBMITTAL"), ("spec", "ISO-X-1.pdf", "SPECIFICATION")):  # fmt: skip
        c.execute("INSERT INTO documents VALUES (?, ?)", (d, name))
        c.execute("INSERT INTO document_classification VALUES (?, ?)", (d, role))
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture(autouse=True)
def _list_enforced(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(
        settings, "data_dir", tmp_path
    )  # an empty owner list: nothing is approved by it


def test_a_non_standard_document_is_refused_even_inside_the_standards_lane(
    conn, monkeypatch
):
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids)
    )  # the owner's list path: an empty library
    monkeypatch.setattr(claude_approved, "_in_library", lambda ids: frozenset())
    monkeypatch.setattr(
        claude_approved, "_block_stop", lambda ids: None
    )  # no block here (the next test has one)
    for ids in (
        ["sheet"],
        ["spec"],
        ["other_family"],
        ["std", "sheet"],
        ["unknown_doc"],
        [],
    ):
        with (
            pytest.raises(standards_lane.NotStandardsLane),
            standards_lane.open_for(conn, ids, user="rule approval"),
        ):
            pytest.fail("nothing may be declared")
        assert claude_approved.carried() is None  # nothing was declared
    with standards_lane.open_for(conn, ["std"], user="rule approval"):
        assert (
            claude_approved.refusal() is None
        )  # a held standard of an allowed family goes by the lane
        with claude_approved.carrying(
            ["sheet"]
        ):  # anything else added inside is not the lane's
            assert claude_approved.refusal() is not None


def test_a_block_still_wins_inside_the_lane(conn, monkeypatch):
    monkeypatch.setattr(
        claude_approved, "_block_stop", lambda ids: ("not_approved", "blocked")
    )
    with standards_lane.open_for(conn, ["std"], user="rule approval"):
        assert claude_approved.refusal() == ("not_approved", "blocked")


def test_the_second_model_pass_never_uses_the_chats_per_request_consent():
    src = inspect.getsource(rule_second_approval)
    assert (
        "per_request_consent(" not in src and src.count("standards_lane.open_for(") == 2
    )


def _gate_open_past_the_list(monkeypatch):
    """The owner's list path reached with nothing on it, no block, every id in the library, no contract yes."""
    monkeypatch.setattr(claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids))
    monkeypatch.setattr(claude_approved, "_in_library", lambda ids: frozenset(ids))
    monkeypatch.setattr(claude_approved, "_block_stop", lambda ids: None)
    monkeypatch.setattr(claude_approved, "_consented", lambda ids: frozenset())
    monkeypatch.setattr(contract_yes, "has_yes", lambda d: False)


def test_a_company_standard_the_kind_decision_reads_as_a_contract_is_refused_inside_the_lane(conn, monkeypatch):
    """Review u8 B1: the lane's "may go" came before the contract question. A held standard whose own kind decision reads
    contract (or cannot be read, the safe side) is refused like on every other route except chat."""
    _gate_open_past_the_list(monkeypatch)
    monkeypatch.setattr(claude_auto_approve, "is_contract_paper", lambda d: d == "std")  # a forged contract-kind book
    with standards_lane.open_for(conn, ["std"], user="rule approval"):
        code, why = claude_approved.refusal()
        assert code == claude_approved.NOT_APPROVED and "contract" in why and "std" in why
    monkeypatch.setattr(claude_auto_approve, "is_contract_paper", lambda d: False)
    with standards_lane.open_for(conn, ["std"], user="rule approval"):
        assert claude_approved.refusal() is None


def test_the_local_only_bar_wins_inside_the_lane(conn, monkeypatch):
    _gate_open_past_the_list(monkeypatch)
    monkeypatch.setattr(claude_auto_approve, "is_contract_paper", lambda d: False)
    monkeypatch.setattr(review_engine, "claude_barred", lambda: True)
    with standards_lane.open_for(conn, ["std"], user="rule approval"):
        assert claude_approved.refusal()[0] == review_engine.BARRED_CODE


def _family_db(rows):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    c.execute("CREATE TABLE document_classification (document_id TEXT PRIMARY KEY, document_role TEXT,"
              " standard_family TEXT, document_number TEXT)")  # fmt: skip
    for d, name, fam, number in rows:
        c.execute("INSERT INTO documents VALUES (?, ?)", (d, name))
        c.execute("INSERT INTO document_classification VALUES (?, 'COMPANY_STANDARD', ?, ?)", (d, fam, number))
    c.row_factory = sqlite3.Row
    return c


def test_the_family_is_the_books_own_identifier_never_a_word_inside_its_name():
    """Review u8 M4: the family came from the FIRST family word anywhere in the file name."""
    c = _family_db([("mid", "Notes on API pumps.pdf", None, None), ("start", "API-X-610.pdf", None, None),
                    ("recorded", "Notes on API pumps.pdf", "ISO", None), ("number", "cover.pdf", None, "NACE-X-1"),
                    ("recorded_other", "API-X-610.pdf", "OTHER", None)])  # fmt: skip
    assert standards_lane.not_standards(c, ["mid", "start", "recorded", "number", "recorded_other"]) == [
        "mid", "recorded_other"]  # fmt: skip


def test_a_standard_held_for_an_administrators_confirmation_is_refused(monkeypatch):
    """Review u8 M4: the role alone was asked. A company standard a non-administrator uploaded and no administrator
    confirmed (#620) is not used by reviews, and not by this lane."""
    monkeypatch.setattr(settings, "company_standard_confirm_from", "")
    c = _family_db([("std", "SAES-X-100.pdf", None, None)])
    c.executescript("""
        CREATE TABLE document_role_access (document_id TEXT, granted_by TEXT, granted_at TEXT);
        CREATE TABLE user_roles (user_id TEXT, role_id TEXT); CREATE TABLE roles (id TEXT, name TEXT);
        CREATE TABLE company_standard_confirmations (document_id TEXT);
        INSERT INTO roles VALUES ('r1', 'engineer'); INSERT INTO user_roles VALUES ('u1', 'r1');
        INSERT INTO document_role_access VALUES ('std', 'u1', '2026-11-25T10:00:00');""")
    with pytest.raises(standards_lane.NotStandardsLane):
        standards_lane.check(c, ["std"])
    c.execute("INSERT INTO company_standard_confirmations VALUES ('std')")
    assert standards_lane.check(c, ["std"]) == {"std"}


def test_only_its_named_users_open_the_lane_and_never_inside_a_review_or_another_declaration(conn):
    with pytest.raises(standards_lane.NotStandardsLane), standards_lane.open_for(conn, ["std"], user="chat"):
        pytest.fail("not a user of the lane")
    with claude_approved.reviewing("run-1"), pytest.raises(standards_lane.NotStandardsLane), \
            standards_lane.open_for(conn, ["std"], user="rule approval"):  # fmt: skip
        pytest.fail("never inside a review run")
    with claude_approved.carrying(["sheet"]), pytest.raises(standards_lane.NotStandardsLane), \
            standards_lane.open_for(conn, ["std"], user="rule approval"):  # fmt: skip
        pytest.fail("never inside another declaration")
    import sys
    from pathlib import Path

    from app import rule_label_job

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import standards_figures  # a tool in scripts/ (J2)

    named = [inspect.getsource(m).count(f'user="{u}"') for m, u in (
        (rule_second_approval, "rule approval"), (rule_second_approval, "rule approval judge"),
        (rule_label_job, "standards converter"), (standards_figures, "figure reading"))]  # fmt: skip
    # the figure-reading user: owner, 26 Nov 2026, #1584 7189065710 (J2)
    assert named == [1, 1, 1, 1] and standards_lane.USERS == {"rule approval", "rule approval judge", "standards converter",
                                                              "figure reading"}  # fmt: skip


def test_the_lane_is_never_opened_inside_a_run_named_only_through_the_spend_ledger(conn):
    """Recheck of update 8: the lane asked only the review marker, while the gate also counts a run the spend ledger names.
    Its own users open the lane first and name their spend run inside it."""
    from app import claude_spend

    with claude_spend.for_run("run-1"), pytest.raises(standards_lane.NotStandardsLane), \
            standards_lane.open_for(conn, ["std"], user="rule approval"):  # fmt: skip
        pytest.fail("never inside a run the spend ledger names")
    with standards_lane.open_for(conn, ["std"], user="rule approval"), claude_spend.for_run("rule-second"):
        assert claude_approved.carried() == {"std"}


def test_a_file_name_whose_family_word_is_followed_by_an_underscore_or_a_digit_has_that_family(conn):
    """26 Nov 2026: 'NACE_MR0175_..._2020.pdf' read as no family (the word boundary does not fall before '_'), so a held NACE book
    stood outside the lane. A family word later in a name still never counts."""
    from app.standards_inventory import FAMILY_OTHER

    assert standards_lane.family_of(conn, "no_record", "NACE_MR0175_ISO_15156_2_2020.pdf") == "NACE"
    assert standards_lane.family_of(conn, "no_record", "API650.pdf") == "API"
    assert standards_lane.family_of(conn, "no_record", "Notes on API pumps.pdf") == FAMILY_OTHER
