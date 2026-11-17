"""Order 14 LPV, V1 (the lead's decision after three review rounds): no grammar, the agreed data decides. A rule's point moves to
the tick section "does not apply? (code, engineer to confirm)" only when the rule names a thing the paper names on no page AND the
rule's AGREED equipment tag (the AI reviewer's own `equipment_decision`) names another equipment type than the paper's. A rule
tagged for the paper's equipment stays asked even when the paper lacks the part (that is the finding). Nothing is removed.

INVENTED texts only: an invented book has a part for "quartzite" frames (a class the tests pass in their own catalogue)."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_equipment as eqmod
from app import rule_equipment
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
OTHER = {"other": True, "rule": "pressure_vessel", "paper": "heat_exchanger"}


def _d(
    text: str,
    passage: str = "",
    paper: str | None = STEEL,
    heading: str = "",
    tag=OTHER,
):
    return fit.decide({"source_text": text}, passage, paper, CAT, heading, tag)


# ---- both conditions ------------------------------------------------------------------------------------------------------------


def test_a_rule_tagged_for_other_equipment_naming_a_thing_the_paper_lacks_moves_with_its_reason():
    assert _d("(3) The rated pressure shall not exceed 70 units.", PASSAGE) == (
        "its agreed equipment tag is pressure vessel, this paper is heat exchanger, and the paper names no quartzite on any page"
    )  # the thing read from its list's lead-in; no grammar
    assert (
        _d(
            "If the flow is not given, it shall be taken as 5 units.",
            heading="6.7 Extra tests for quartzite",
        )
        is not None
    )


@pytest.mark.parametrize(
    "rule",
    [
        "For each frame, a peep hole shall be provided.",  # round 3's invented obligations: tagged for the paper's equipment
        "When a frame exceeds 5 units, a peep hole shall be fitted.",
        "A minimum of two peep holes shall be installed.",
        "(4) The service life of the quartzite pane shall be 4 years.",
    ],
)
def test_a_rule_tagged_for_this_papers_equipment_or_not_agreed_never_moves(rule):
    assert (
        _d(rule, tag=None) is None
    )  # the missing part is the finding: the rule stays asked


def test_the_paper_naming_the_thing_keeps_the_rule_in_any_case_or_punctuation():
    rule = "(4) The service life of the quartzite pane shall be 4 years."
    for paper in (
        "Window: QUARTZITE",
        "Window: Q.U.A.R.T.Z.I.T.E",
        "Window : quartzite pane",
    ):
        assert _d(rule, paper=paper * 5) is None
    assert _d(rule, paper=None) is None  # a page not readable as text
    assert _d("(a) Every frame shall carry a tag.", PASSAGE) is None  # names no thing


def test_the_real_list_keeps_a_rule_when_the_paper_names_a_wider_word():
    rule = {
        "source_text": "Where sight glasses are fitted, they shall be cleaned weekly."
    }
    assert (
        fit.decide(rule, "", "Level gauge: REFLEX GLASS " * 5, None, "", OTHER) is None
    )
    assert (
        fit.decide(rule, "", "Level gauge: magnetic " * 5, None, "", OTHER) is not None
    )
    pump = {"source_text": "For main fire water pumps, the margin shall be 5 %."}
    assert fit.decide(pump, "", "Service: FIREWATER " * 5, None, "", OTHER) is None
    names = {w: n for n, ws, *_p in fit.things() for w in ws}
    for spelling, thing in (("perspex", "acrylic"), ("sightglass", "a viewport or sight glass"), ("gre", "fibre-reinforced plastic"),
                            ("firefightingpump", "a fire-water pump")):  # fmt: skip
        assert names[spelling] == thing


def test_a_lead_in_is_never_inherited_across_lists():
    other = (
        PASSAGE
        + " (c) Gaskets shall be listed: (1) The list shall be dated. (3) The rated pressure shall be 9 units."
    )
    assert fit.lead_in("(3) The rated pressure shall be 9 units.", other) == ""
    assert "quartzite panes" in fit.lead_in(
        "(3) The rated pressure shall not exceed 70 units.", PASSAGE
    )


def test_a_worked_example_moves_whatever_the_tag_but_a_list_or_clause_number_is_no_figure():
    passage = (
        "The valve must reclose above the operating pressure. For example, if the valve is set at 100 psig with a 7% blowdown,"
        " it will close at 93 psig. The operating pressure must be kept below 93 psig to avoid a leak. Other text."
    )
    assert (
        _d(
            "The operating pressure must be kept below 93 psig to avoid a leak.",
            passage,
            tag=None,
        )
        == fit.EXAMPLE_WORDS
    )
    numbers = "For example, see item (3) of clause 4.2. (3) The frame shall be marked as in 4.2."
    assert not fit.is_example(
        {"source_text": "(3) The frame shall be marked as in 4.2."}, numbers
    )


# ---- the agreed tag, judged by the AI reviewer's own function ---------------------------------------------------------------------


def _tag_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    rule_equipment.create_tables(con)
    con.execute("CREATE TABLE rule_label (source TEXT, rule_ref TEXT, field TEXT)")
    sha = "a" * 64
    rows = [
        ("r-vessel", "static", "pressure_vessel", 0, "agreed"),
        ("r-pump", "rotating", "pump", 0, "agreed"),
        ("r-general", None, None, 1, "agreed"),
    ]
    for ref, fam, typ, gen, state in rows:
        con.execute(
            "INSERT INTO rule_equipment_label (source, rule_ref, equip_family, equip_type, equip_general, equip_state, model_a, model_b,"
            " prompt_version, list_sha, labelled_at) VALUES ('requirement', ?, ?, ?, ?, ?, 'ma', 'mb', 'p1', ?, 'now')",
            (ref, fam, typ, gen, state, sha),
        )
    con.execute(
        "INSERT INTO rule_equipment_label (source, rule_ref, equip_type, equip_state, equip_disagreement, labelled_at)"
        " VALUES ('requirement', 'r-unsure', 'pressure_vessel', 'needs_human', 'type', 'now')"
    )
    return con


def _ctx(types: set[str]):
    tax = rule_equipment.Taxonomy.load()
    eq = eqmod.PaperEquipment(
        frozenset(tax.expand(types)),
        frozenset(tax.type_family[t] for t in types),
        bool(types),
        (),
        "read" if types else "none",
        frozenset(tax.expand(types)),
    )
    return eqmod.EquipmentCtx(eq, tax, {}, "type")


def test_only_an_agreed_tag_for_another_type_counts(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    con, pump = _tag_db(), _ctx({"pump"})
    assert fit.tag_against(con, "r-vessel", pump) == {
        "other": True,
        "rule": "pressure_vessel",
        "paper": "pump",
    }
    assert (
        fit.tag_against(con, "r-pump", pump) is None
    )  # tagged for this paper's equipment
    assert fit.tag_against(con, "r-general", pump) is None
    assert fit.tag_against(con, "r-unsure", pump) is None  # not agreed
    assert fit.tag_against(con, "r-missing", pump) is None  # untagged
    assert (
        fit.tag_against(con, "r-vessel", _ctx(set())) is None
    )  # the paper's equipment is not known: nothing moves
    assert fit.tag_against(con, "r-vessel", None) is None


# ---- the page guard and the points ---------------------------------------------------------------------------------------------


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
    assert fit.paper_text(_paper_db({1: STEEL, 2: "short"}), "p") is None
    assert fit.paper_text(_paper_db({1: STEEL, 3: STEEL}), "p") is None
    assert fit.paper_text(_paper_db({1: STEEL}, {1: ("scan", None)}), "p") is None
    assert fit.paper_text(_paper_db({1: STEEL}, {1: ("text", "pending")}), "p") is None
    assert fit.paper_text(_paper_db({}), "p") is None


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


def test_to_confirm_moves_the_point_with_one_label_and_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(fit, "things", lambda path=None: CAT)
    monkeypatch.setattr(eqmod, "load_equipment", lambda conn, paper, mode: "ctx")
    monkeypatch.setattr(
        fit,
        "tag_against",
        lambda conn, rid, ctx: OTHER if rid in ("r-rated", "r-tag") else None,
    )
    points = [
        {
            "id": "rc:1",
            "rank": 4,
            "tile": "questions",
            "_finding": {"requirement_id": "r-rated"},
            "action": "Clarify.",
        },
        {
            "id": "ai:1",
            "rank": 5,
            "tile": "met",
            "_line": {"item_id": "R-r-rated"},
            "ai_label": "Met (AI, one reader)",
        },
        {
            "id": "ai:2",
            "rank": 4,
            "tile": "questions",
            "_line": {"item_id": "R-r-tag"},
        },  # other tag, names no thing
        {
            "id": "ai:3",
            "rank": 3,
            "tile": "not_met",
            "_line": {"item_id": "R-r-peep"},
        },  # tagged for this paper
        {"id": "added:1", "rank": 4, "tile": "questions"},
        {
            "id": "rc:2",
            "rank": 8,
            "tile": "does_not_apply",
            "_finding": {"requirement_id": "r-rated"},
        },
    ]
    assert fit.to_confirm(_points_db(), points, "p") == 2
    moved = [p for p in points if p["rank"] == 9]
    assert [p["id"] for p in moved] == ["rc:1", "ai:1"]
    for p in moved:
        assert (
            p["tile"] == "na_to_confirm"
            and p["firm"] is None
            and p["ai_label"] == fit.LABEL
        )
        assert p["ai_answer"].startswith(fit.LABEL) and "Met (AI" not in str(p)
        assert p["ai_reasoning"].startswith("Code, not the AI:")
    assert [p["rank"] for p in points if p["rank"] != 9] == [4, 3, 4, 8]


def test_the_team_files_reason_of_a_moved_point_is_its_one_reason():
    from app import crs_one

    point = {
        "source": "ai_review",
        "_line": {"reason_code": "met", "why": "AI thinks met"},
        "_subject_fit": "the reason",
    }
    assert crs_one.reason_of(point) == f"{fit.LABEL}: the reason"


def test_the_points_assembly_runs_it(monkeypatch):
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
