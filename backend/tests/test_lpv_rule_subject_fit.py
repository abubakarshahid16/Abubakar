"""Order 14 LPV, V1 (the lead's decision after review): a rule about something the paper does not have is never dropped by words;
its point moves to the engineer's tick section "AI thinks these do not apply, tick to confirm" with the reason "the paper names no
<thing> on any page". Never for a rule that REQUIRES the thing; any doubt keeps the point as it is.

INVENTED texts only: an invented book has a part for "quartzite" frames (a class the tests pass in their own catalogue)."""

from __future__ import annotations

import sqlite3

import pytest

from app import rule_subject_fit as fit

CAT = (("quartzite", ("quartzite",)), ("a peep hole", ("peep hole", "peep holes")))
PASSAGE = (
    "Z-1 SCOPE (a) This part covers frames with quartzite windows. (b) Frames built to this part shall be limited to the following"
    " limits for both the quartzite panes and all steel parts: (1) The inner design pressure shall equal the rated pressure."
    " (2) The outer design pressure shall not exceed 7 units. (3) The rated pressure shall not exceed 70 units."
    " (4) The service life of the quartzite pane shall be 4 years. Z-2 OTHER (a) Every frame shall carry a tag."
)
STEEL = (
    "Invented frame data sheet. Design pressure 3 units. Outer design pressure 5 units. Service life 20 years. "
    * 3
)


def _d(text: str, passage: str = "", paper: str | None = STEEL, heading: str = ""):
    return fit.decide({"source_text": text}, passage, paper, CAT, heading)


# ---- what moves -----------------------------------------------------------------------------------------------------------------


def test_a_list_item_inherits_its_own_lists_lead_in_and_moves_with_the_reason():
    item = "(3) The rated pressure shall not exceed 70 units."
    assert "quartzite panes" in fit.lead_in(item, PASSAGE)
    assert (
        _d(item, PASSAGE)
        == "the list it sits in is about quartzite; the paper names no quartzite on any page"
    )  # the reason says where the thing was read (honesty rule 4)
    assert _d("(4) The service life of the quartzite pane shall be 4 years.") == (
        "its own words are about quartzite; the paper names no quartzite on any page"
    )  # its own subject, the thing only qualifying it ("of the quartzite pane")


def test_a_lead_in_is_never_inherited_across_lists():
    other = (
        PASSAGE
        + " (c) Gaskets shall be listed: (1) The list shall be dated. (3) The rated pressure shall be 9 units."
    )
    assert (
        fit.lead_in("(3) The rated pressure shall be 9 units.", other) == ""
    )  # items 1, 3: not this list's 1 .. 2
    assert (
        fit.lead_in("(a) Every frame shall carry a tag.", PASSAGE) == ""
    )  # another style


def test_a_section_title_counts_only_with_the_thing_as_its_head_and_no_second_group():
    rule = "If the flow is not given, it shall be taken as 5 units."
    assert (
        _d(rule, heading="6.7 Extra tests for quartzite frames and quartzite") is None
    )  # joins a second group
    assert _d(rule, heading="6.7 Extra tests for main quartzite") == (
        "its section is about quartzite; the paper names no quartzite on any page"
    )  # the thing is the title's head
    assert (
        _d(rule, heading="6.7 Seal core with quartzite liner gaskets") is None
    )  # a part of something else
    assert _d(rule, heading="6.7 Nozzles, manways and quartzite") is None
    assert (
        _d(rule, heading="6.7 Quartzite frames shall be tested twice") is None
    )  # a sentence stored as a heading


# ---- what never moves -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule",
    [
        "A peep hole shall be provided on every housing.",  # requires the thing
        "Peep holes shall be fitted at each end of the frame.",
        "One peep hole shall be located at each end of the frame.",
        "The following shall be installed on every housing: a level peep hole and a drain plug.",  # named after the verb
        "Every housing shall have a peep hole.",
        "A peep hole shall be available on every housing.",  # an obligation on the thing: never a closed verb list
        "A peep hole shall be part of the package.",
        "Peep holes must exist on each frame.",
        "A peep hole is required on each frame.",
        "Quartzite frames shall comply with the frame code.",  # the thing is the subject's head
    ],
)
def test_a_rule_that_requires_the_thing_never_moves(rule):
    assert _d(rule) is None  # a paper without it is exactly the finding


@pytest.mark.parametrize(
    "rule",
    [
        "Frames without quartzite panes shall carry a tag.",
        "Frames not fitted with quartzite panes shall carry a tag.",
        "Unless quartzite is used, the frame shall carry a tag.",
        "Frames other than quartzite frames shall carry a tag.",
        "For all frames except main quartzite frames, the rated pressure shall be 3 units.",
        "Non-quartzite panes shall be marked.",
        "Steel instead of quartzite frames shall be marked.",
        "Low grade frames such as quartzite frames shall be marked.",  # an example of something else
        "Frames including quartzite panes shall be marked.",
        "For low grade frames such as quartzite frames, the margin shall be 3 units.",  # the rule is about the class
    ],
)
def test_a_negation_keeps_the_rule(rule):
    assert _d(rule) is None


def test_a_subject_joining_another_group_or_two_glued_sentences_keep_the_rule():
    assert (
        _d("For heavy frames and for quartzite frames, all tests shall be witnessed.")
        is None
    )
    assert _d("Heavy frames, quartzite frames shall be witnessed.") is None
    assert (
        _d(
            "Quartzite frames are not allowed 5.2.17 Steel frames shall be painted twice."
        )
        is None
    )  # split at the clause number
    assert (
        _d("Quartzite frames rated 5 units 5.2.17 Steel frames shall be painted twice.")
        is None
    )  # two rules, one stored
    assert (
        _d(
            "Quartzite frame work does not require a rail Posts shall be set at 45 degrees."
        )
        is None
    )  # a verb in the subject
    assert (
        _d("The quartzite pane shall be clean. Every frame shall carry a tag.") is None
    )  # one sentence is general


def test_the_paper_naming_the_thing_or_an_unreadable_paper_keeps_the_rule():
    rule = "(4) The service life of the quartzite pane shall be 4 years."
    assert _d(rule, paper=STEEL + " Window: quartzite.") is None
    assert _d(rule, paper=None) is None


# ---- the worked example ---------------------------------------------------------------------------------------------------------


def test_a_worked_example_moves_but_a_list_or_clause_number_is_no_figure():
    passage = (
        "The valve must reclose above the operating pressure. For example, if the valve is set at 100 psig with a 7% blowdown,"
        " it will close at 93 psig. The operating pressure must be kept below 93 psig to avoid a leak. Other text."
    )
    assert fit.is_example(
        {
            "source_text": "The operating pressure must be kept below 93 psig to avoid a leak."
        },
        passage,
    )
    assert not fit.is_example(
        {"source_text": "The valve must reclose above the operating pressure."}, passage
    )
    numbers = "For example, see item (3) of clause 4.2. (3) The frame shall be marked as in 4.2."
    assert not fit.is_example(
        {"source_text": "(3) The frame shall be marked as in 4.2."}, numbers
    )
    assert (
        _d(
            "The operating pressure must be kept below 93 psig to avoid a leak.",
            passage,
        )
        == fit.EXAMPLE_WORDS
    )


# ---- the data list and the page guard -------------------------------------------------------------------------------------------


def test_the_data_list_holds_the_spellings():
    names = {w: n for n, ws, *_paper in fit.things() for w in ws}
    for spelling, thing in (("perspex", "acrylic"), ("sightglass", "a viewport or sight glass"), ("gauge glass", "a viewport or sight glass"),
                            ("gre", "fibre-reinforced plastic"), ("fiberglass", "fibre-reinforced plastic"),
                            ("fire fighting pump", "a fire-water pump"), ("firewater pumps", "a fire-water pump")):  # fmt: skip
        assert names[spelling] == thing


def _paper_db(
    texts: dict[int, str], ledger: dict[int, tuple] | None = None
) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT, needs_ocr INTEGER)"
    )
    con.executemany(
        "INSERT INTO pages VALUES ('p', ?, ?, ?)", [(n, t, 0) for n, t in texts.items()]
    )
    if ledger is not None:
        con.execute(
            "CREATE TABLE page_ledger (document_id TEXT, page_no INTEGER, native_status TEXT, ocr_status TEXT)"
        )
        con.executemany(
            "INSERT INTO page_ledger VALUES ('p', ?, ?, ?)",
            [(n, *v) for n, v in ledger.items()],
        )
    return con


def test_the_unreadable_page_guard():
    assert fit.paper_text(_paper_db({1: STEEL, 2: STEEL}), "p") is not None
    assert (
        fit.paper_text(_paper_db({1: STEEL, 2: "short"}), "p") is None
    )  # a page with no real text
    assert (
        fit.paper_text(_paper_db({1: STEEL, 3: STEEL}), "p") is None
    )  # page 2 missing
    assert (
        fit.paper_text(_paper_db({1: STEEL}, {1: ("scan", None)}), "p") is None
    )  # not a text page by the ledger
    assert fit.paper_text(_paper_db({1: STEEL}, {1: ("text", "pending")}), "p") is None
    assert fit.paper_text(_paper_db({}), "p") is None


# ---- the points: moved to the tick section, never removed ------------------------------------------------------------------------


def _points_db() -> sqlite3.Connection:
    con = _paper_db({1: STEEL})
    con.executescript(
        "CREATE TABLE standard_requirements (id TEXT, source_text TEXT, requirement_text TEXT, chunk_id TEXT);"
        "CREATE TABLE chunks (id TEXT, text TEXT, section TEXT);"
    )
    con.execute("INSERT INTO chunks VALUES ('c1', ?, 'Z-1 Scope')", (PASSAGE,))
    con.executemany(
        "INSERT INTO standard_requirements VALUES (?, ?, ?, 'c1')",
        [("r-rated", "(3) The rated pressure shall not exceed 70 units.", None),
         ("r-tag", "(a) Every frame shall carry a tag.", None),
         ("r-peep", "A peep hole shall be provided on every housing.", None)],
    )  # fmt: skip
    return con


def test_to_confirm_moves_the_point_with_its_reason_and_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(fit, "things", lambda path=None: CAT)
    points = [
        {
            "id": "rc:1",
            "rank": 4,
            "tile": "questions",
            "_finding": {"requirement_id": "r-rated"},
            "action": "Clarify.",
        },
        {"id": "ai:1", "rank": 5, "tile": "met", "_line": {"item_id": "R-r-rated"}},
        {"id": "ai:2", "rank": 4, "tile": "questions", "_line": {"item_id": "R-r-tag"}},
        {
            "id": "ai:3",
            "rank": 3,
            "tile": "not_met",
            "_line": {"item_id": "R-r-peep"},
        },  # requires the thing: a finding
        {"id": "added:1", "rank": 4, "tile": "questions"},  # an engineer's own point
        {
            "id": "rc:2",
            "rank": 8,
            "tile": "does_not_apply",
            "_finding": {"requirement_id": "r-rated"},
        },  # not reviewed
    ]
    assert fit.to_confirm(_points_db(), points, "p") == 2
    moved = [p for p in points if p["rank"] == 9]
    assert [p["id"] for p in moved] == ["rc:1", "ai:1"]
    for p in moved:
        assert p["tile"] == "na_to_confirm" and p["firm"] is None
        assert (
            p["action"]
            == "Engineer to check whether the rule applies to this paper: the list it sits in is about quartzite; the paper names no quartzite on any page."
        )
        assert p["ai_reasoning"].startswith("Code, not the AI:")
        assert (
            p["ai_label"] == fit.LABEL
        )  # ONE label: never the AI's own answer inside the tick section
    assert [p["rank"] for p in points if p["rank"] != 9] == [4, 3, 4, 8]


def test_to_confirm_moves_nothing_on_an_unreadable_paper(monkeypatch):
    monkeypatch.setattr(fit, "things", lambda path=None: CAT)
    con = _points_db()
    con.execute("UPDATE pages SET text = 'short'")
    points = [
        {
            "id": "rc:1",
            "rank": 4,
            "tile": "questions",
            "_finding": {"requirement_id": "r-rated"},
        }
    ]
    assert fit.to_confirm(con, points, "p") == 0 and points[0]["rank"] == 4


def test_the_points_assembly_runs_it(monkeypatch):
    """`review_points_service._assemble` hands every rule check and AI point to `to_confirm` before the list is built."""
    from app import review_points_service as svc

    seen = []
    monkeypatch.setattr(
        fit, "to_confirm", lambda conn, pts, paper: seen.append((len(pts), paper)) or 0
    )
    monkeypatch.setattr(svc, "runs_of_paper", lambda conn, paper: ("rc", "ai"))
    monkeypatch.setattr(svc.rp, "ai_points_of_run", lambda *a: ([{"id": "ai:x"}], []))
    monkeypatch.setattr(svc, "_rule_points", lambda *a: [{"id": "rc:x"}])
    monkeypatch.setattr(
        svc.rp, "build", lambda ai, rc, add: (_ for _ in ()).throw(StopIteration)
    )
    monkeypatch.setattr(svc.decisions_mod, "people", lambda paper: [])
    monkeypatch.setattr(svc.decisions_mod, "added", lambda paper: [])
    monkeypatch.setattr(svc.rp, "library_of", lambda conn: [])
    monkeypatch.setattr(svc.rp, "books_not_held", lambda *a: [])
    monkeypatch.setattr(svc, "connect", lambda: None)

    class Scope:
        allowed_document_ids = frozenset()

    with pytest.raises(StopIteration):
        svc._assemble("paper-1", Scope())
    assert seen == [(2, "paper-1")]


def test_a_condition_on_the_thing_moves_the_rule():
    assert _d("Where peep holes are fitted, they shall be cleaned weekly.") is not None
    assert _d("For quartzite frames, the rated pressure shall be 3 units.") is not None
    assert _d("If quartzite panes are used, they shall be marked.") is not None


def test_the_paper_side_ignores_case_punctuation_and_spaces_and_wider_words():
    rule = {"source_text": "(9) The design life of the acrylic window shall be 10 yr."}
    for paper in (
        "Window: ACRYLIC",
        "Window: P.M.M.A.",
        "Window : Perspex",
        "Window: plexi glass",
    ):
        assert fit.decide(rule, "", paper * 5, None) is None
    assert fit.decide(rule, "", "Window: steel " * 5, None) is not None
    glass = {
        "source_text": "Where sight glasses are fitted, they shall be cleaned weekly."
    }
    assert (
        fit.decide(glass, "", "Level gauge: REFLEX GLASS " * 5, None) is None
    )  # a paper word keeps it
    pump = {"source_text": "For main fire water pumps, the margin shall be 5 %."}
    assert fit.decide(pump, "", "Service: FIREWATER " * 5, None) is None
    assert fit.decide(pump, "", "Service: brine " * 5, None) is not None
