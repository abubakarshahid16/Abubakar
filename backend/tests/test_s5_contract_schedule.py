"""STEP 5 (#805), a contract schedule as a rule source: invented contract, invented clauses and wording, a temporary
database copy. The template in git holds placeholders only."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import load_contract_schedule as lcs

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "scripts" / "contract_schedule_template.json"
)
ITEMS = [
    {
        "id": "A1",
        "clause": "9.1",
        "kind": "calculations_with_datasheets",
        "text": "Invented: calculations come with the sheets.",
    },
    {
        "id": "A2",
        "clause": "9.2",
        "kind": "old_comments_closed",
        "text": "Invented: earlier comments are closed.",
    },
    {
        "id": "A3",
        "clause": "9.3",
        "kind": "holds_listed",
        "text": "Invented: holds are listed.",
    },
    {
        "id": "A4",
        "clause": "9.4",
        "kind": "deviation_waiver_form",
        "text": "Invented: a deviation needs a waiver form.",
    },
]


def _file(tmp_path, items=None, contract="Invented Contract Z", name="schedule.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"contract": contract, "items": ITEMS if items is None else items})
    )
    return path


@pytest.fixture
def conn(tmp_path):
    return sqlite3.connect(tmp_path / "copy.sqlite")


def test_the_template_in_git_holds_placeholders_only_and_cannot_be_loaded():
    data = json.loads(TEMPLATE.read_text())
    assert {i["kind"] for i in data["items"]} == set(lcs.KINDS)
    assert all("<" in i["text"] and "<" in i["id"] for i in data["items"])
    with pytest.raises(lcs.Refused, match="outside the repository"):
        lcs.read_items(TEMPLATE)
    with pytest.raises(lcs.Refused, match="placeholder"):
        lcs.read_items(TEMPLATE, repo=Path("/nonexistent-repo-root"))


def test_a_local_file_loads_into_rules_with_source_contract_schedule(tmp_path, conn):
    contract, items = lcs.read_items(_file(tmp_path))
    assert lcs.load(conn, contract, items, "me") == {
        "new": 4,
        "new_version": 0,
        "unchanged": 0,
    }
    rules = lcs.current_rules(conn)
    assert [r["id"] for r in rules] == ["A1", "A2", "A3", "A4"]
    assert {r["source"] for r in rules} == {"contract schedule"}
    assert {r["kind"] for r in rules} == set(lcs.KINDS)


def test_a_repeat_adds_nothing_and_a_changed_text_adds_a_version_and_keeps_the_old(
    tmp_path, conn
):
    contract, items = lcs.read_items(_file(tmp_path))
    lcs.load(conn, contract, items, "me")
    assert lcs.load(conn, contract, items, "me") == {
        "new": 0,
        "new_version": 0,
        "unchanged": 4,
    }
    changed = [
        {**items[0], "text": "Invented: calculations come with the sheets, signed."},
        *items[1:],
    ]
    assert lcs.load(conn, contract, changed, "me") == {
        "new": 0,
        "new_version": 1,
        "unchanged": 3,
    }
    assert (
        conn.execute("SELECT COUNT(*) FROM contract_schedule_rule").fetchone()[0] == 5
    )
    assert next(r for r in lcs.current_rules(conn) if r["id"] == "A1")["version"] == 2
    for sql in (
        "UPDATE contract_schedule_rule SET text = 'x'",
        "DELETE FROM contract_schedule_rule",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ({"value": 25}, "never an equipment limit"),
        ({"unit": "bar"}, "never an equipment limit"),
        ({"comparator": ">="}, "never an equipment limit"),
        ({"kind": "max_pressure"}, "not a completeness kind"),
        ({"text": ""}, "no text"),
        ({"clause": "<clause>"}, "placeholder"),
    ],
)
def test_an_item_that_is_not_a_completeness_check_is_refused(tmp_path, bad, why):
    with pytest.raises(lcs.Refused, match=why):
        lcs.read_items(_file(tmp_path, [{**ITEMS[0], **bad}]))


def test_a_file_that_is_not_fit_is_refused(tmp_path):
    for bad in ([], [ITEMS[0], ITEMS[0]]):
        with pytest.raises(lcs.Refused):
            lcs.read_items(_file(tmp_path, bad))
    with pytest.raises(lcs.Refused, match="name the contract"):
        lcs.read_items(_file(tmp_path, contract="<contract label>"))
    (tmp_path / "x.json").write_text("not json")
    with pytest.raises(lcs.Refused, match="cannot be read"):
        lcs.read_items(tmp_path / "x.json")


def test_a_live_shaped_database_gets_no_table(tmp_path):
    live = tmp_path / "backend" / "data"
    live.mkdir(parents=True)
    conn = sqlite3.connect(live / "rag_intelligence.sqlite")
    with pytest.raises(lcs.Refused, match="live-shaped"):
        lcs.load(conn, "Invented Contract Z", ITEMS, "me")
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def test_loading_names_who(conn):
    with pytest.raises(lcs.Refused, match="who"):
        lcs.load(conn, "Invented Contract Z", ITEMS, " ")


RULE = {"kind": "holds_listed"}
QUOTE = "Holds: there are no holds on this submittal."
PAGES = {
    1: "Cover sheet of the invented submittal.",
    2: f"Section 2. {QUOTE} End of section.",
}


def _ev(**over):
    return {"pages": PAGES, "page_count": 2, "terms": ["holds"], "found": [], **over}


@pytest.mark.parametrize(
    ("evidence", "status"),
    [
        (_ev(found=[{"quote": QUOTE, "page": 2}]), lcs.PRESENT),
        # an invented quote, a quote on another page, a bool page, a negative page, a missing page, a short quote
        (
            _ev(
                found=[
                    {
                        "quote": "Holds are fully listed in the invented annex.",
                        "page": 2,
                    }
                ]
            ),
            lcs.NEEDS_ENGINEER,
        ),
        (_ev(found=[{"quote": QUOTE, "page": 1}]), lcs.NEEDS_ENGINEER),
        (_ev(found=[{"quote": QUOTE, "page": True}]), lcs.NEEDS_ENGINEER),
        (_ev(found=[{"quote": QUOTE, "page": -5}]), lcs.NEEDS_ENGINEER),
        (_ev(found=[{"quote": QUOTE, "page": 9}]), lcs.NEEDS_ENGINEER),
        (_ev(found=[{"quote": QUOTE, "page": None}]), lcs.NEEDS_ENGINEER),
        (_ev(found=[{"quote": "Holds", "page": 2}]), lcs.NEEDS_ENGINEER),
        # a caller flag is not evidence
        (
            _ev(
                found=[
                    {
                        "quote": "Invented words not on any page at all.",
                        "page": 2,
                        "verified": True,
                    }
                ]
            ),
            lcs.NEEDS_ENGINEER,
        ),
        # absence: every page read, a term to look for, nothing on any page
        (_ev(pages={1: "Cover.", 2: "Body."}), lcs.NOT_PRESENT),
        (
            _ev(pages={1: "Cover.", 2: "Body."}, searched_whole=True, page_count=3),
            lcs.NEEDS_ENGINEER,
        ),  # partial
        (_ev(pages={1: "Cover."}), lcs.NEEDS_ENGINEER),  # partial read of two pages
        (_ev(pages={}, page_count=0), lcs.NEEDS_ENGINEER),  # an empty submittal
        (_ev(pages={}, page_count=None), lcs.NEEDS_ENGINEER),
        (_ev(pages={1: "Cover.", 2: " "}), lcs.NEEDS_ENGINEER),  # a page with no text
        (_ev(pages={1: "Cover.", 2: "Body."}, page_count=True), lcs.NEEDS_ENGINEER),
        (_ev(pages={1: "Cover.", 2: "Body."}, terms=[]), lcs.NEEDS_ENGINEER),
        (_ev(), lcs.NEEDS_ENGINEER),  # the term is on a page but nobody quoted it
        (
            _ev(pages={1: "Cover.", 2: "Body."}, found=[{"quote": QUOTE, "page": 2}]),
            lcs.NEEDS_ENGINEER,
        ),
        (None, lcs.NEEDS_ENGINEER),
    ],
)
def test_present_needs_a_quote_on_its_own_page_and_absent_needs_every_page_read(
    evidence, status
):
    assert lcs.completeness(RULE, evidence)[0] == status


@pytest.mark.parametrize(
    "text",
    [
        "Invented: pressure of 25 bar",
        "Invented: a value >= x",
        "Invented: at least one copy",
        "Invented: not exceed it",
    ],
)
def test_a_number_unit_or_comparator_in_the_text_is_refused(tmp_path, text):
    with pytest.raises(lcs.Refused, match="never an equipment limit"):
        lcs.read_items(_file(tmp_path, [{**ITEMS[0], "text": text}]))


def test_an_item_of_another_kind_is_never_decided():
    assert (
        lcs.completeness(
            {"kind": "max_pressure"}, _ev(found=[{"quote": QUOTE, "page": 2}])
        )[0]
        == lcs.NEEDS_ENGINEER
    )


def test_the_script_loads_a_local_file_into_a_copy_and_lists_ids_only(
    tmp_path, monkeypatch, capsys
):
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()
    monkeypatch.setattr(settings, "db_path", copy)
    db.reset_connection()
    assert (
        lcs.main(["--db", str(copy), "--file", str(_file(tmp_path)), "--by", "me"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["new"] == 4
    assert lcs.main(["--db", str(copy), "--list"]) == 0
    listed = capsys.readouterr().out
    assert "A1" in listed and "calculations come" not in listed
    assert (
        lcs.main(["--db", str(copy), "--file", str(TEMPLATE), "--by", "me"])
        == lcs.EXIT_REFUSED
    )
    assert "outside the repository" in capsys.readouterr().out


@pytest.mark.parametrize(
    "page",
    [
        "Section 2. We list open holds\nlist here.",
        "Section 2. We list open holds\u00a0list here.",
        "Section 2. We list open hold-\ns list here.",
        "Section 2. We list open HOLDS   LIST here.",
    ],
)
def test_a_term_split_by_a_line_break_or_hyphen_or_no_break_space_is_still_found(page):
    got = lcs.completeness(
        RULE, _ev(pages={1: "Cover.", 2: page}, terms=["holds list"])
    )
    assert got[0] == lcs.NEEDS_ENGINEER, got


def test_ordinary_item_wording_is_still_accepted(tmp_path):
    lcs.read_items(_file(tmp_path))
    lcs.read_items(
        _file(
            tmp_path,
            [
                {
                    **ITEMS[0],
                    "text": "Calculations are submitted in a package with the datasheets as a rule.",
                }
            ],
        )
    )


INVISIBLE = ["\u200b", "\u200d", "\u200e", "\u2060", "\ufeff", "\u00ad"]


@pytest.mark.parametrize("mark", INVISIBLE)
def test_invisible_characters_in_the_term_or_the_page_do_not_hide_a_term(mark):
    page = f"Section 2. We list open ho{mark}lds list here."
    assert (
        lcs.completeness(RULE, _ev(pages={1: "Cover.", 2: page}, terms=["holds list"]))[
            0
        ]
        == lcs.NEEDS_ENGINEER
    )
    page = "Section 2. We list open holds list here."
    assert (
        lcs.completeness(
            RULE, _ev(pages={1: "Cover.", 2: page}, terms=[f"hol{mark}ds list"])
        )[0]
        == lcs.NEEDS_ENGINEER
    )


@pytest.mark.parametrize("dash", ["\u2013", "\u2011", "\u2212", "\u2014", "\uff0d"])
def test_a_look_alike_dash_does_not_hide_a_hyphenated_term(dash):
    page = f"Section 2. A sign{dash}off sheet is attached."
    assert (
        lcs.completeness(RULE, _ev(pages={1: "Cover.", 2: page}, terms=["sign-off"]))[0]
        == lcs.NEEDS_ENGINEER
    )


def test_fullwidth_letters_do_not_hide_a_term():
    page = "Section 2. A \uff53\uff49\uff47\uff4e off sheet."
    assert (
        lcs.completeness(RULE, _ev(pages={1: "Cover.", 2: page}, terms=["sign off"]))[0]
        == lcs.NEEDS_ENGINEER
    )


def test_a_quote_is_checked_with_the_same_normaliser():
    page = "Section 2. Holds:\u200b there are no holds\u2013none listed."
    quote = "Holds: there are no holds-none listed."
    got = lcs.completeness(
        RULE, _ev(pages={1: "Cover.", 2: page}, found=[{"quote": quote, "page": 2}])
    )
    assert got[0] == lcs.PRESENT


@pytest.mark.parametrize(
    "text",
    [
        "Invented: t\u200bhree copies",
        "Invented: fi\u00adve copies",
        "Invented: at le\u200bast one",
        "Invented: m\u200bax of them",
        "Invented: up\u200b to the others",
        "Invented: tw\u2060elve copies",
        "Invented: the p\ufeffsi value",
        "Invented: \uff54\uff48\uff52\uff45\uff45 copies",
    ],
)
def test_invisible_or_look_alike_characters_do_not_get_a_limit_past_the_refusal(
    tmp_path, text
):
    with pytest.raises(lcs.Refused, match="never an equipment limit"):
        lcs.read_items(_file(tmp_path, [{**ITEMS[0], "text": text}]))
