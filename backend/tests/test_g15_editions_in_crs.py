# ruff: noqa: RUF059
"""Order 14 lane G: the edition check shown in the one CRS (`crs_editions`), through the built file. Invented books, dates and
cutoffs only; the cutoff file is a temporary file (the real one is local and git-ignored)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from openpyxl import load_workbook

from app import crs_completeness, crs_editions, crs_one, db
from app import standard_editions as se
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import rows_after, scope_all


@pytest.fixture(autouse=True)
def on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)
    monkeypatch.setattr(settings, "standard_editions_enabled", False)
    monkeypatch.delenv("EDITION_CUTOFF_FILE", raising=False)
    monkeypatch.setattr(se, "LOCAL_POLICY_FILE", tmp_path / "absent.local.json")


def _cutoff(tmp_path, monkeypatch, date="2011-03", contract=crs_editions.CONTRACT):
    f = tmp_path / "cutoff.json"
    f.write_text(
        json.dumps({"contracts": {contract: {"rule": "in_effect_on", "date": date}}})
    )
    monkeypatch.setenv("EDITION_CUTOFF_FILE", str(f))


def _printed(doc_id: str, line: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, 1, ?, ?, 1)",
            (doc_id, line, len(line)),
        )


def _content(data: bytes) -> dict:
    """The workbook's parts, without the time it was saved (docProps/core.xml)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist() if n != "docProps/core.xml"}


def _files(doc):
    team = crs_one.build_team(doc, scope_all(), exported="FIXED")
    contractor = crs_one.build_contractor(doc, scope_all(), exported="FIXED")
    return team, contractor


def _world(issue="Issue Date: 14 March 2007"):
    doc, rc, ai, client = world_with_both()
    _printed("doc_std", issue)
    return doc


# ------------------------------------------------------------------------------------------------ off: byte-same


def test_off_or_with_no_cutoff_for_the_contract_the_files_are_byte_same(
    tmp_path, monkeypatch
):
    doc = _world()
    off = _files(doc)
    assert crs_editions.SHEET not in load_workbook(io.BytesIO(off[0])).sheetnames
    monkeypatch.setattr(
        settings, "standard_editions_enabled", True
    )  # on, but no cutoff file names the contract
    assert [_content(f) for f in _files(doc)] == [_content(f) for f in off]
    _cutoff(tmp_path, monkeypatch, contract="some-other-contract")
    assert [_content(f) for f in _files(doc)] == [_content(f) for f in off]
    _cutoff(tmp_path, monkeypatch)
    monkeypatch.setattr(
        settings, "standard_editions_enabled", False
    )  # a cutoff on file, the switch off
    assert [_content(f) for f in _files(doc)] == [_content(f) for f in off]


# ------------------------------------------------------------------------------------------------ on: one row per cited held book


def test_on_the_team_file_gets_one_editions_row_per_cited_held_book_and_nothing_else_changes(
    tmp_path, monkeypatch
):
    doc = _world()
    team_off, contractor_off = _files(doc)
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    _cutoff(tmp_path, monkeypatch)
    team, contractor = _files(doc)
    wb = load_workbook(io.BytesIO(team))
    head, rows = rows_after(wb[crs_editions.SHEET], "Rule book")
    assert tuple(head) == crs_editions.COLUMNS and len(rows) == 1
    row = dict(zip(head, rows[0], strict=True))
    assert row["Rule book"] == "STD-A-001" and row["Edition held"] == "2007-03-14"
    assert row["Where the date was read"] == "p.1: printed issue date"
    assert row["Printed line (verified on the page)"] == "Issue Date: 14 March 2007"
    assert row["Status"] == se.BINDING and row["Edition that binds"] == "2007-03-14"
    assert "not on file" in row["Caveat"] and row["Points citing it"] >= 1
    assert "never a Pass or a Fail" in wb[crs_editions.SHEET].cell(1, 1).value
    # G2: the same rows on the sheets CRS and Evidence; the contractor file is untouched (G6)
    old = load_workbook(io.BytesIO(team_off))
    for name, first in (
        (crs_one.TEAM_SHEET, "Comment"),
        (crs_one.EVIDENCE_SHEET, "No"),
    ):
        assert len(rows_after(wb[name], first)[1]) == len(
            rows_after(old[name], first)[1]
        )
    assert _content(contractor) == _content(contractor_off)
    at = (
        old.sheetnames.index(crs_one.HELD_SHEET) + 1
    )  # next to the books not held; no other sheet moves
    assert wb.sheetnames == [
        *old.sheetnames[:at],
        crs_editions.SHEET,
        *old.sheetnames[at:],
    ]


def test_on_every_book_reference_in_a_cell_carries_the_status_in_brackets(
    tmp_path, monkeypatch
):
    doc = _world()
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    _cutoff(tmp_path, monkeypatch)
    wb = load_workbook(io.BytesIO(_files(doc)[0]))
    head, ev = rows_after(wb[crs_one.EVIDENCE_SHEET], "No")
    books = {r[head.index("Rule book")] for r in ev if r[head.index("Rule book")]}
    assert "STD-A-001 [edition binds]" in books and not any(
        b == "STD-A-001" for b in books
    )
    head, crs = rows_after(wb[crs_one.TEAM_SHEET], "Comment")
    cells = [str(r[head.index("Rule books and clauses")]) for r in crs]
    assert any("STD-A-001 [edition binds]" in c for c in cells)
    assert not any("STD-A-001 " in c.replace("STD-A-001 [", "") for c in cells)


@pytest.mark.parametrize(
    ("issue", "cutoff", "status", "bracket"),
    [
        ("Issue Date: 14 March 2007", "2011-03", se.BINDING, "edition binds"),
        (
            "Issue Date: 2 May 2015",
            "2011-03",
            se.LATER,
            "later edition: for information only",
        ),
        (
            "Issue Date: 9 March 2011",
            "2011-03",
            se.CANNOT_TELL,
            "edition: engineer to check",
        ),
        ("no date on this page", "2011-03", se.NOT_KNOWN, "edition not known"),
    ],
)
def test_each_status_reaches_the_sheet_and_the_bracket(
    tmp_path, monkeypatch, issue, cutoff, status, bracket
):
    doc = _world(issue)
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    _cutoff(tmp_path, monkeypatch, date=cutoff)
    wb = load_workbook(io.BytesIO(_files(doc)[0]))
    head, rows = rows_after(wb[crs_editions.SHEET], "Rule book")
    assert rows[0][head.index("Status")] == status
    head, ev = rows_after(wb[crs_one.EVIDENCE_SHEET], "No")
    assert f"STD-A-001 [{bracket}]" in {r[head.index("Rule book")] for r in ev}


def test_on_the_completeness_check_still_passes_the_bracketed_file(
    tmp_path, monkeypatch
):
    doc = _world()
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    _cutoff(tmp_path, monkeypatch)
    got = crs_completeness.checked_files(doc, scope_all())
    assert got["team"][1]["ok"] and got["contractor"][1]["ok"], got["team"][1][
        "sentence"
    ]
    assert got["team"][1]["cut_problems"] == 0


def test_a_paper_citing_no_held_book_gets_no_empty_sheet_unless_the_cutoff_is_on_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "standard_editions_enabled", True)
    assert (
        crs_editions.verdicts([{"books": []}]) is None
    )  # no cutoff file: nothing, so the file stays byte-same
    _cutoff(tmp_path, monkeypatch)
    assert (
        crs_editions.verdicts([{"books": []}]) == {}
    )  # on and a cutoff: the sheet says 0 held books
    monkeypatch.setattr(settings, "standard_editions_enabled", False)
    assert (
        crs_editions.verdicts([{"books": []}]) is None
    )  # a cutoff on file, the switch off: nothing


def test_an_unknown_status_is_never_guessed_and_an_unjudged_book_is_unchanged():
    assert (
        crs_editions.mark("BOOK-1", {"BOOK-1": {"status": "something new"}})
        == "BOOK-1 [edition not known]"
    )
    assert crs_editions.mark("BOOK-2", {"BOOK-1": {"status": se.BINDING}}) == "BOOK-2"
    assert crs_editions.mark("BOOK-1", None) == "BOOK-1"


# ------------------------------------------------------------------------------------------------ where the live app reads the cutoff


def test_the_git_ignored_local_cutoff_file_is_read_when_no_env_names_one(
    tmp_path, monkeypatch
):
    local = tmp_path / "edition_cutoff.local.json"
    local.write_text(
        json.dumps(
            {"contracts": {"c-local": {"rule": "in_effect_on", "date": "2001-01"}}}
        )
    )
    assert "c-local" not in se.load_policies()  # no local file: the template
    monkeypatch.setattr(se, "LOCAL_POLICY_FILE", local)
    assert "c-local" in se.load_policies()
    _cutoff(tmp_path, monkeypatch, contract="c-env")
    assert set(se.load_policies()) == {"c-env"}  # the environment's file wins
