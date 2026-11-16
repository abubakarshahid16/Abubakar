"""Order 14 lane E: the contracts sort (`scripts/contract_sort.py`): each contract into ONE part group by its opening headings,
the reason verified on its page, local only. Every paper here is invented text."""

from __future__ import annotations

import importlib.util
import json
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "contract_sort", REPO / "scripts" / "contract_sort.py"
)
cs = importlib.util.module_from_spec(_SPEC)
sys.modules["contract_sort"] = cs
_SPEC.loader.exec_module(cs)  # type: ignore[union-attr]

BODY = "The supplier shall deliver the widgets to the store named by the buyer within the agreed time."


def _group(*lines: str, more: str = BODY) -> int:
    return cs.sort_pages("doc_test", [(1, "\n".join(lines) + "\n" + more)]).group


# ------------------------------------------------------------------------------------------------ one group each


@pytest.mark.parametrize(
    ("lines", "group"),
    [
        (("ORDER NO. 9001", "AGREEMENT FOR THE SUPPLY OF WIDGETS", "between"), 1),
        (("FORM OF AGREEMENT", "Widget Supply Works"), 1),
        (("Gamma Trading", "GENERAL CONDITIONS OF PURCHASE"), 2),
        (("PARTICULAR CONDITIONS", "Widget Supply Works"), 3),
        (("ORDER NO. 9001", "SCHEDULE Q", "SCOPE OF SUPPLY"), 4),
        (("Appendix 7", "Delivery Programme"), 4),
        (("SCHEDULE Q", "ATTACHMENT IV", "List of spares"), 5),
        (("Form of Advance Payment Guarantee",), 5),
        (("ADDENDUM NO. 3 TO THE ORDER",), 6),
        (("MINUTES OF MEETING", "Widget Supply Works"), 7),
    ],
)
def test_each_group_from_a_general_heading(lines, group):
    assert _group(*lines) == group


def test_the_signed_bodys_opening_words_name_the_agreement():
    text = "Widget Supply Works\nTHIS AGREEMENT is made on the second day of June between Gamma Trading and Delta Works."
    s = cs.sort_pages("doc_test", [(1, text)])
    assert (s.group, s.reason.name, s.reason.verified) == (
        1,
        "agreement opening words",
        True,
    )


def test_an_amendment_about_a_part_is_an_amendment_not_that_part():
    assert _group("AMENDMENT NO. 2 TO THE GENERAL CONDITIONS") == 6


def test_a_part_name_beats_its_label_and_a_label_beats_the_word_agreement():
    assert _group("SCHEDULE C - GENERAL CONDITIONS") == 2
    assert _group("SCHEDULE C TO THE AGREEMENT", "Price") == 4


def test_the_longest_cue_owns_its_words():
    # "terms and conditions" alone would be general conditions; inside "special terms and conditions" it is not
    assert _group("SPECIAL TERMS AND CONDITIONS") == 3


def test_the_cue_that_starts_its_line_settles_two_names_of_one_rank():
    assert _group("SPECIAL CONDITIONS", "SUPPLEMENTING THE GENERAL CONDITIONS") == 3


# ------------------------------------------------------------------------------------------------ group 8, engineer to decide


def test_two_part_names_of_one_rank_are_a_conflict_for_the_engineer():
    s = cs.sort_pages(
        "doc_test", [(1, "GENERAL CONDITIONS\nSPECIAL CONDITIONS\n" + BODY)]
    )
    assert (s.group, s.reason) == (cs.ENGINEER, None)
    assert "different parts" in s.why


def test_no_cue_is_group_8():
    assert _group("Notes on widgets", "Blue and green") == cs.ENGINEER


def test_a_heading_code_cannot_find_on_its_page_is_group_8():
    page = "GENERAL CONDITIONS\n" + BODY
    lost = cs.Cue(
        2, cs.NAME, "general conditions", 1, "GENERAL CONDITIONS OF HIRE", at_start=True
    )
    s = cs.decide("doc_test", [lost], [(1, page)])
    assert s.group == cs.ENGINEER and "not found on its page" in s.why
    found = cs.Cue(
        2, cs.NAME, "general conditions", 1, "GENERAL CONDITIONS", at_start=True
    )
    assert cs.decide("doc_test", [found], [(1, page)]).group == 2


def test_a_quote_too_short_for_the_quote_check_is_group_8():
    short = cs.Cue(4, cs.LABEL, "label: annex", 1, "ANNEX 2", at_start=True, depth=1)
    assert (
        cs.decide("doc_test", [short], [(1, "ANNEX 2\n" + BODY)]).group == cs.ENGINEER
    )


# ------------------------------------------------------------------------------------------------ only the opening's headings


def test_a_list_of_parts_names_them_it_is_none_of_them():
    assert (
        _group("AGREEMENT", "Schedule A Scope", "Schedule B Price", "Schedule C Time")
        == 1
    )


def test_numbered_list_lines_are_not_headings():
    assert _group("Widget Supply Works", "1. General Conditions") == cs.ENGINEER
    assert _group("Widget Supply Works", "(b) General Conditions") == cs.ENGINEER


def test_a_part_name_inside_a_plain_line_is_not_a_heading():
    # not capitals, not capitalised words, and the cue does not start the line
    assert (
        _group("Widget Supply Works", "read with the general conditions") == cs.ENGINEER
    )


def test_a_heading_below_the_top_lines_does_not_name_the_paper():
    top = [f"Line {i} of the cover" for i in range(cs.TOP_LINES)]
    assert _group(*top, "GENERAL CONDITIONS") == cs.ENGINEER
    assert _group(*top[:-1], "GENERAL CONDITIONS") == 2


def test_a_sentence_naming_a_part_is_not_a_heading():
    assert (
        _group(
            "Widget Supply Works",
            "The general conditions apply to this order, as agreed by both of the parties.",
        )
        == 8
    )


# ------------------------------------------------------------------------------------------------ the command, on an invented copy

PAPERS = {
    "doc_aaaaaaaaaaa1": "ORDER NO. 9001\nAGREEMENT FOR WIDGETS\n" + BODY,
    "doc_aaaaaaaaaaa2": "GENERAL CONDITIONS OF PURCHASE\n" + BODY,
    "doc_aaaaaaaaaaa3": "SCHEDULE Q\nSCOPE OF SUPPLY\n" + BODY,
    "doc_aaaaaaaaaaa4": "GENERAL CONDITIONS\nSPECIAL CONDITIONS\n" + BODY,
    "doc_aaaaaaaaaaa5": "Notes on widgets\n" + BODY,
}


def _copy(tmp_path: Path) -> Path:
    db = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE document_classification (document_id TEXT, document_role TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE document_kinds (document_id TEXT, kind TEXT, state TEXT);"
        "CREATE TABLE contract_yes (document_id TEXT);"
    )
    for doc, text in PAPERS.items():
        conn.execute(
            "INSERT INTO document_classification VALUES (?, 'CONTRACT_DOCUMENT')",
            (doc,),
        )
        conn.execute("INSERT INTO pages VALUES (?, 1, ?)", (doc, text))
    conn.execute(
        "INSERT INTO document_classification VALUES ('doc_bbbbbbbbbbb1', 'CONTRACTOR_SUBMITTAL')"
    )
    conn.execute(
        "INSERT INTO document_kinds VALUES ('doc_aaaaaaaaaaa5', NULL, 'needs_engineer')"
    )
    conn.commit()
    conn.close()
    return db


def _run(tmp_path: Path, capsys, *extra: str) -> tuple[int, str]:
    db = _copy(tmp_path)
    live = tmp_path / "live.sqlite"
    live.write_bytes(b"invented live file")
    ledger = tmp_path / "spend.jsonl"
    ledger.write_text('{"usd": 0}\n{"usd": 0}\n')
    approved = tmp_path / "approved.json"
    approved.write_text(
        json.dumps({"documents": [{"status": "approved"}, {"status": "withdrawn"}]})
    )
    code = cs.main(
        [
            "--db",
            str(db),
            "--live-db",
            str(live),
            "--ledger",
            str(ledger),
            "--approved",
            str(approved),
            *extra,
        ]
    )
    return code, capsys.readouterr().out


def test_the_command_passes_e1_to_e9_and_prints_no_document_words(tmp_path, capsys):
    code, out = _run(tmp_path, capsys, "--engineer-dir", str(tmp_path / "eng"))
    assert code == 0, out
    for e in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"):
        assert f"{e} PASS" in out, out
    assert (
        "contract documents (role CONTRACT_DOCUMENT): 5" in out
        and "doc_bbbbbbbbbbb1" not in out
    )
    assert (
        "group 8 (engineer to decide): 2" in out
        and "E10 accuracy not yet measured" in out
    )
    for words in (
        "WIDGETS",
        "PURCHASE",
        "SCOPE OF SUPPLY",
        "Notes on widgets",
        "ORDER NO",
    ):
        assert words.lower() not in out.lower()
    md = (tmp_path / "eng" / "contract-sort.md").read_text()
    assert "GENERAL CONDITIONS OF PURCHASE" in md and "engineer's group" in md
    assert (tmp_path / "eng" / "contract-sort.xlsx").is_file()


def test_two_runs_give_the_same_group_and_reason(tmp_path):
    db = _copy(tmp_path)
    ids = list(PAPERS)
    one, two = cs.run_once(str(db), ids), cs.run_once(str(db), ids)
    assert [s.engineer() for s in one] == [s.engineer() for s in two]
    assert [s.group for s in one] == [1, 2, 4, 8, 8]


def test_the_live_database_is_refused(tmp_path, capsys):
    db = _copy(tmp_path)
    assert cs.main(["--db", str(db), "--live-db", str(db)]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_a_changed_ledger_list_or_live_file_fails_e4_e7_e8():
    s = cs.Sorted(
        "doc_x",
        2,
        "w",
        cs.Cue(
            2,
            cs.NAME,
            "general conditions",
            1,
            "GENERAL CONDITIONS",
            True,
            verified=True,
        ),
    )
    base = {"ledger_before": 2, "ledger_after": 2, "sockets": 0, "own_imports": [], "approved_before": {"a": 1},
            "approved_after": {"a": 1}, "live_before": ["x"], "live_after": ["x"], "copy_not_live": True}  # fmt: skip
    assert all(
        passed for _code, passed, _t in cs.checks([s], [s], ["doc_x"], set(), base)
    )
    bad = {**base, "ledger_after": 3, "approved_after": {"a": 2}, "live_after": ["y"]}
    failed = {
        code
        for code, passed, _t in cs.checks([s], [s], ["doc_x"], set(), bad)
        if not passed
    }
    assert failed == {"E4", "E7", "E8"}


# ------------------------------------------------------------------------------------------------ nothing leaves the machine


def test_the_tool_imports_no_transport_module():
    assert cs.own_imports() == []


def test_every_connection_attempt_during_the_run_is_refused_and_counted():
    attempts: list = []
    with cs.no_network(
        attempts
    ):  # a local closed port: even without the guard nothing would leave this machine
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        with pytest.raises(OSError):
            probe = socket.socket()
            probe.settimeout(0.2)
            try:
                probe.connect(("127.0.0.1", 9))
            finally:
                probe.close()
    assert len(attempts) == 2


def test_each_group_lists_checks_that_exist_in_the_checklist():
    known = {i["id"] for i in cs.parts.checklist()["items"]}
    assert set(cs.CHECKS) == set(cs.GROUPS)
    assert all(set(codes) <= known for codes, _why in cs.CHECKS.values())
    assert cs.CHECKS[1][0] and cs.CHECKS[cs.ENGINEER][0] == ()
