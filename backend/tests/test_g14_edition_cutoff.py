"""Order 14 lane G: a contract's edition cutoff as DATA (a month, its clause and page), what it says of a held book, and
the issue date a book prints. Invented books and dates only: the real cutoff lives in a local file outside git."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_edition as ae
from app import standard_editions as se

MONTH = {
    "rule": "in_effect_on",
    "date": "2011-06",
    "feed_conflict": "strictest",
    "always_latest_families": [],
}


def test_a_month_cutoff_with_its_source_loads_from_a_local_file_and_the_repo_holds_only_the_template(
    tmp_path, monkeypatch
):
    mine = tmp_path / "local.json"
    mine.write_text(
        '{"contracts": {"k": {"rule": "in_effect_on", "date": "2001-02", "feed_conflict": "strictest",'
        ' "source": {"clause": "9.9", "pages": [3], "held_in_app": false, "statement": "invented"}}}}'
    )
    monkeypatch.setenv("EDITION_CUTOFF_FILE", str(mine))
    entry = se.load_policies()["k"]
    assert entry["date"] == "2001-02" and entry["source"]["pages"] == [3]
    monkeypatch.delenv("EDITION_CUTOFF_FILE")
    assert all(
        name.startswith("example-") for name in se.load_policies()
    )  # no real contract in git


def test_a_month_cutoff_takes_an_edition_issued_before_the_month_and_asks_about_one_inside_it():
    before = [
        {"edition": "A", "date": "2009-03-01"},
        {"edition": "B", "date": "2011-05-31"},
    ]
    assert se.pick(before, MONTH, "ZZ-1").editions == ("B",)
    assert se.pick(
        [*before, {"edition": "C", "date": "2011-06-01"}], MONTH, "ZZ-1"
    ).editions == ("C",)  # the month's first day
    inside = se.pick([*before, {"edition": "C", "date": "2011-06-10"}], MONTH, "ZZ-1")
    assert inside.status == se.NEEDS_ENGINEER and "too coarse" in inside.reason
    year = se.pick([*before, {"edition": "C", "date": "2011"}], MONTH, "ZZ-1")
    assert year.status == se.NEEDS_ENGINEER
    assert se.pick(
        [*before, {"edition": "D", "date": "2011-07-01"}], MONTH, "ZZ-1"
    ).editions == ("B",)  # later: not picked


def test_a_day_cutoff_still_works_as_before():
    day = {**MONTH, "date": "2011-06-15"}
    eds = [
        {"edition": "B", "date": "2011-05-31"},
        {"edition": "C", "date": "2011-06-10"},
    ]
    assert se.pick(eds, day, "ZZ-1").editions == ("C",)


def test_a_cutoff_of_a_year_alone_is_refused(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text('{"contracts": {"y": {"rule": "in_effect_on", "date": "2019"}}}')
    with pytest.raises(se.BadPolicy, match="y"):
        se.load_policies(bad)


def test_the_held_book_against_the_cutoff_binds_is_later_cannot_tell_or_not_known():
    binds = se.against_cutoff({"edition": "2009", "date": "2009-05-23"}, MONTH, "ZZ-1")
    assert binds["status"] == se.BINDING and binds["binding"] == "2009"
    assert "none is on file" in binds["caveat"]
    on_file = [{"edition": "2010", "date": "2010-07-01"}]
    later = se.against_cutoff(
        {"edition": "2012", "date": "2012-02-01"}, MONTH, "ZZ-1", register=on_file
    )
    assert later["status"] == se.LATER and later["binding"] == "2010"
    alone = se.against_cutoff({"edition": "2012", "date": "2012-02-01"}, MONTH, "ZZ-1")
    assert alone["status"] == se.LATER and alone["binding"] is None
    year = se.against_cutoff({"edition": "2011", "date": "2011"}, MONTH, "ZZ-1")
    assert year["status"] == se.CANNOT_TELL
    unknown = se.against_cutoff({"edition": None, "date": None}, MONTH, "ZZ-1")
    assert unknown["status"] == se.NOT_KNOWN


def test_an_older_held_edition_names_the_one_that_binds():
    on_file = [
        {"edition": "2006", "date": "2006-01-01"},
        {"edition": "2010", "date": "2010-07-01"},
    ]
    got = se.against_cutoff(
        {"edition": "2006", "date": "2006-01-01"}, MONTH, "ZZ-1", register=on_file
    )
    assert got["status"] == se.EARLIER and got["binding"] == "2010"


@pytest.mark.parametrize(
    ("text", "iso"),
    [("14 March 2007", "2007-03-14"), ("March 14, 2007", "2007-03-14"), ("2005-11", "2005-11"), ("March 2007", "2007-03"),
     ("2007", "2007"), ("2 September 2007.", "2007-09-02"), ("next year", None), ("14 March 2007 draft 2", None)],
)  # fmt: skip
def test_a_printed_date_is_read_whole_or_not_at_all(text, iso):
    assert ae.as_iso_date(text) == iso


def _book(tmp_path, filename, pages):
    c = sqlite3.connect(tmp_path / "b.sqlite")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE documents (id TEXT, filename TEXT)")
    c.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    c.execute("INSERT INTO documents VALUES ('d', ?)", (filename,))
    c.executemany("INSERT INTO pages VALUES ('d', ?, ?)", list(enumerate(pages, 1)))
    return c


def test_the_issue_date_is_the_printed_labelled_line_with_its_page(tmp_path):
    c = _book(tmp_path, "ZZ-STD-9.pdf", ["Contents", "Previous Issue: 1 January 2004\nIssue Date:   14 March 2007\n",
                                          "Issue Date: 14 March 2007"])  # fmt: skip
    got = ae.issue_date(c, "d")
    assert (got["date"], got["page"], got["source"]) == (
        "2007-03-14",
        2,
        "printed issue date",
    )
    assert got["quote"] == "Issue Date:   14 March 2007"


def test_two_printed_dates_or_none_are_not_a_date(tmp_path):
    c = _book(
        tmp_path,
        "ZZ-STD-9.pdf",
        ["Issue Date: 14 March 2007", "Issue Date: 4 July 2008"],
    )
    assert ae.issue_date(c, "d")["date"] is None
    other = tmp_path / "other"
    other.mkdir()
    c2 = _book(other, "ZZ-STD-9.pdf", ["no date here"])
    assert ae.issue_date(c2, "d") == {
        "date": None,
        "page": None,
        "quote": None,
        "source": "no issue date printed",
    }


def test_without_a_printed_date_the_file_names_edition_year_is_used(tmp_path):
    c = _book(tmp_path, "ZZ-STD-9-2020.pdf", ["text"])
    assert (
        ae.issue_date(c, "d")["date"] == "2020"
        and ae.issue_date(c, "d")["source"] == "edition year in the file name"
    )
