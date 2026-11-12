"""Owner order 12 Nov 2026 afternoon (#1584): approval is automatic and needs no block file; the register is blocked by its
file name, and the owner can mark more files by name or checksum. Invented names, no Claude call."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app import absence, classification, claude_approved, claude_auto_approve, db
from app.config import settings
from tests.test_1584_claude_auto_approve import (  # noqa: F401  (the autouse world is the one of #1584's tests)
    SHA_A,
    SHA_B,
    SHA_C,
    STANDARD,
    SUBMITTAL,
    _doc,
    _refused_code,
    _rows_for,
    _set_list,
    world,
)

_K = claude_approved.REGISTER_NAME_KEY
_A, _B = (
    _K[:11].title(),
    _K[11:].title(),
)  # the two words of the register's name, built from the one list
REG = f"{_A} {_B}.pdf"
MARKED = "Invented Marked Sheet.pdf"
# a document with the submittal role is approved by route 1 (a paper uploaded for review), not by citation
ROLES_NOT_RULE_BOOKS = [
    r
    for r in classification.ROLES
    if r not in ("COMPANY_STANDARD", "CONTRACTOR_SUBMITTAL")
] + [None]

_spec = importlib.util.spec_from_file_location(
    "write_block_file_c7",
    Path(__file__).resolve().parents[2] / "scripts" / "write_block_file.py",
)
cli = importlib.util.module_from_spec(_spec)
sys.modules["write_block_file_c7"] = cli
_spec.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def _scope(monkeypatch):
    monkeypatch.setattr(
        claude_auto_approve,
        "_scope_of_run",
        lambda _rid: frozenset(
            r["id"] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )


def _mark(*names, hashes=()):
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": list(hashes), "blocked_names": list(names)}),
        encoding="utf-8",
    )


# ------------------------------------------------------------ the name-match table


@pytest.mark.parametrize(
    "name",
    [
        MARKED,
        "invented marked sheet.pdf",
        "INVENTED MARKED SHEET.PDF",
        "  Invented   Marked   Sheet  .pdf",
        "Invented_Marked-Sheet.pdf",
        "InventedMarkedSheet",
        "Invented Marked Sheet.docx",
        "Invented Marked Sheet (1).pdf",
        "Invented Marked Sheet copy.pdf",
        "Invented Marked Sheet - Copy.pdf",
        "Invented Marked Sheet 2026-11-12.pdf",
        "Invented Marked Sheet rev C.pdf",
        "Copy of Invented Marked Sheet.pdf",
        # decided: a longer name that merely CONTAINS the marked name is blocked (the safer error)
        "Annex to the Invented Marked Sheet of unit 4.pdf",
    ],
)
def test_a_marked_name_matches_every_spelling(name):
    keys = frozenset({claude_approved.name_key(MARKED)})
    assert claude_approved.name_is_blocked(name, keys)


@pytest.mark.parametrize(
    "name",
    [
        "Invented Marked.pdf",
        "Sheet Marked Invented.pdf",
        "invented submittal.pdf",
        "",
        None,
    ],
)
def test_other_names_are_not_matched(name):
    keys = frozenset({claude_approved.name_key(MARKED)})
    assert not claude_approved.name_is_blocked(name, keys)


@pytest.mark.parametrize(
    "name",
    [
        REG,
        f"{_A}_{_B}.PDF".lower(),
        f"{_A}   {_B} (2).pdf",
        f"{_A} {_B}.xlsx",
        f"{_A} {_B} rev 3 2026-11-01.pdf",
        f"Unrelated prefix {_A} {_B} suffix.pdf",  # contains the register's words: blocked
    ],
)
def test_the_register_name_is_built_in_and_needs_no_file(name):
    assert claude_approved.name_is_blocked(name)
    assert claude_approved.is_register_name(name)


def test_a_marked_name_that_is_too_short_makes_the_block_file_unreadable():
    _mark("ab.pdf")
    with pytest.raises(claude_approved.BlockListUnreadable):
        claude_approved.marked_name_keys()


# ------------------------------------------------------- switch on, no block file


def test_no_block_file_paper_and_asked_books_are_approved_the_register_is_not():
    claude_approved.block_file_path().unlink()
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    register = _doc("doc_reg", SHA_C, role=SUBMITTAL, filename=REG)
    claude_auto_approve.on_agent_standards(paper, [book])
    approved = {r["sha256"] for r in _rows_for(SHA_A) + _rows_for(SHA_B)}
    assert approved == {SHA_A, SHA_B}
    with claude_approved.carrying([paper, book]):
        assert claude_approved.refusal() is None
    claude_auto_approve.on_upload(register)
    assert [r["status"] for r in _rows_for(SHA_C)] == ["blocked"]
    code = _refused_code([register])
    assert code == claude_approved.NOT_APPROVED
    with claude_approved.carrying([register]):
        code, reason = claude_approved.refusal()
    assert "blocked" in reason and "file name" in reason and REG not in reason


def test_a_register_named_row_is_refused_even_on_the_approved_list_with_no_block_file():
    claude_approved.block_file_path().unlink()
    register = _doc("doc_reg", SHA_C, filename=REG)
    _set_list((SHA_C, "approved"))
    assert _refused_code([register]) == claude_approved.NOT_APPROVED


# ------------------------------------------------------------ marked files


def test_a_marked_name_is_never_approved_and_is_refused_even_when_already_approved():
    _mark(MARKED)
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    marked = _doc(
        "doc_marked", SHA_B, role=STANDARD, filename="invented marked sheet (3).pdf"
    )
    _set_list((SHA_B, "approved"))  # it was already on the approved list
    assert (
        _refused_code([marked]) == claude_approved.NOT_APPROVED
    )  # the send-time check refuses it
    claude_auto_approve.on_agent_standards(paper, [marked])
    assert [r["status"] for r in _rows_for(SHA_B)] == ["approved", "blocked"]
    assert claude_approved.approved_hashes() == frozenset()
    claude_auto_approve.on_upload(paper)
    with claude_approved.carrying([paper]):
        assert claude_approved.refusal() is None  # the paper itself is not affected


def test_a_marked_hash_is_refused_even_when_already_approved():
    _mark(hashes=[SHA_B])
    marked = _doc("doc_marked", SHA_B, filename="another name.pdf")
    _set_list((SHA_B, "approved"))
    assert _refused_code([marked]) == claude_approved.NOT_APPROVED


def test_a_marked_name_in_a_broken_block_file_is_off_not_empty():
    claude_approved.block_file_path().write_text(
        '{"blocked_names": "x"}', encoding="utf-8"
    )
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    claude_auto_approve.on_upload(paper)
    assert _rows_for(SHA_A) == []
    assert _refused_code([paper]) == claude_approved.NOT_APPROVED


def test_the_switch_off_leaves_the_stored_list_exactly_as_it_was(monkeypatch):
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    _mark(MARKED)
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    _set_list((SHA_C, "approved"))
    before = claude_approved.list_path().read_bytes()
    claude_auto_approve.on_upload(paper)
    claude_auto_approve.on_agent_standards(paper, [book])
    assert claude_approved.list_path().read_bytes() == before
    # a marked name still blocks with the switch off
    marked = _doc("doc_m", SHA_C, filename=MARKED)
    assert _refused_code([marked]) == claude_approved.NOT_APPROVED


# ------------------------------------------------------------ the owner's script


def test_the_script_marks_by_name_and_by_hash_appends_and_prints_no_name(
    tmp_path, capsys
):
    claude_approved.block_file_path().unlink()
    assert cli.main(["--data-dir", str(tmp_path), "--name", MARKED]) == 0
    assert cli.main(["--data-dir", str(tmp_path), "--sha256", SHA_A]) == 0
    assert (
        cli.main(
            [
                "--data-dir",
                str(tmp_path),
                "--name",
                "invented_marked_sheet.PDF",
                "--name",
                "Second Marked Name.pdf",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Marked" not in out and SHA_A not in out
    data = json.loads((tmp_path / claude_approved.BLOCK_FILE_NAME).read_text())
    assert data["blocked_sha256"] == [SHA_A]
    assert data["blocked_names"] == [
        MARKED,
        "Second Marked Name.pdf",
    ]  # same name not added twice, none dropped
    assert claude_approved.marked_name_keys() == frozenset(
        {
            claude_approved.name_key(MARKED),
            claude_approved.name_key("Second Marked Name"),
        }
    )


def test_the_script_refuses_a_short_name_and_does_not_overwrite_a_damaged_file(
    tmp_path, capsys
):
    tmp_path = tmp_path / "fresh"
    tmp_path.mkdir()
    assert cli.main(["--data-dir", str(tmp_path), "--name", "ab"]) == 1
    assert not (tmp_path / claude_approved.BLOCK_FILE_NAME).exists()
    (tmp_path / claude_approved.BLOCK_FILE_NAME).write_text("{broken", encoding="utf-8")
    assert cli.main(["--data-dir", str(tmp_path), "--name", MARKED]) == 1
    assert (tmp_path / claude_approved.BLOCK_FILE_NAME).read_text() == "{broken"
    assert "REFUSED" in capsys.readouterr().out


# ------------------------------------------------ B1: only rule books are approved when cited


@pytest.mark.parametrize(
    "role",
    ROLES_NOT_RULE_BOOKS,
)
@pytest.mark.parametrize("method", ["referenced", "governing_standard"])
def test_a_cited_document_that_is_not_a_rule_book_is_not_approved_and_the_review_says_so(
    role, method
):
    from tests.test_1584_claude_auto_approve import (
        _cite,
        _outcome,
        _start_review,
        _store_outcome,
    )

    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    other = _doc("doc_other", SHA_B)
    if role:
        classification.set_role(other, role)
    book = _doc("doc_book", SHA_C, role=STANDARD)
    run_id = _start_review(paper)
    _cite(run_id, other, method=method)
    _cite(run_id, book, method=method)
    claude_auto_approve.on_review_start(run_id)
    assert _rows_for(SHA_B) == []  # left for the owner
    assert [r["status"] for r in _rows_for(SHA_C)] == [
        "approved"
    ]  # the rule book it cites is
    assert _refused_code([paper, other]) == claude_approved.NOT_APPROVED
    _store_outcome(run_id, {})
    claude_auto_approve.record_on_run(run_id)
    parts = absence.unchecked_parts(run_status="completed", outcome=_outcome(run_id))
    lines = [p["line"] for p in parts if p["part"] == "claude_unlisted_standards"]
    assert any(
        "Not sent: 1 document(s)" in x
        and "not rule books" in x
        and "owner approves" in x
        for x in lines
    )


# ------------------------------------------------ smaller items of the review


def test_an_os_refusal_on_the_block_file_is_the_plain_refusal_not_a_crash(monkeypatch):
    doc = _doc("doc_x", SHA_A)
    _set_list((SHA_A, "approved"))
    real = Path.exists

    def refuse(self):
        if self.name == claude_approved.BLOCK_FILE_NAME:
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "exists", refuse)
    assert _refused_code([doc]) == claude_approved.NOT_APPROVED
    assert claude_approved.approved_hashes() == frozenset()
    assert claude_approved.blocked_by_name("any name.pdf") is True


def test_a_too_short_marked_name_gets_its_own_reason_and_still_refuses():
    _mark("ab.pdf")
    doc = _doc("doc_x", SHA_A)
    _set_list((SHA_A, "approved"))
    with claude_approved.carrying([doc]):
        code, reason = claude_approved.refusal()
    assert code == claude_approved.NOT_APPROVED
    assert "too short" in reason and "fail closed" in reason


def test_an_unreadable_block_file_blocks_every_name_at_the_precheck():
    claude_approved.block_file_path().write_text("{broken", encoding="utf-8")
    assert claude_approved.blocked_by_name("an invented ordinary name.pdf") is True
