"""The standards converter lane at the Claude gate (CLAUDE.md rule 1): rule-book text of a held company standard of an
allowed family goes by its own named lane, never by the chat's per-request consent. Invented documents; no network."""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from app import claude_approved, rule_second_approval, standards_lane
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
            standards_lane.open_for(conn, ids),
        ):
            pytest.fail("nothing may be declared")
        assert claude_approved.carried() is None  # nothing was declared
    with standards_lane.open_for(conn, ["std"]):
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
    with standards_lane.open_for(conn, ["std"]):
        assert claude_approved.refusal() == ("not_approved", "blocked")


def test_the_second_model_pass_never_uses_the_chats_per_request_consent():
    src = inspect.getsource(rule_second_approval)
    assert (
        "per_request_consent(" not in src and src.count("standards_lane.open_for(") == 2
    )
