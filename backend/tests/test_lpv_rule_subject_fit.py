"""Order 14 LPV, V1: a rule is asked only when the thing its own words are about fits the paper, never by a shared word alone.

INVENTED texts only (no standard or paper text). The invented book has a part for "quartzite" windows (a material class the data file
does not hold, so the tests pass their own catalogue) and the data file's own words are checked on invented sentences too."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_items as it
from app import agent_review_rules as rules_mod
from app import ai_task_runner, scope_ledger
from app import rule_label_schema as schema
from app import rule_subject_fit as fit
from app.config import settings
from tests import rule_label_support as s
from tests.test_141_division_scope import temp_storage  # noqa: F401  (fixture)
from tests.test_agent_review_items import _label

CAT = (
    ("a quartzite window", ("quartzite",)),
    ("a peep hole", ("peep hole", "peep holes")),
)

#: an invented book passage: a lead-in that names the quartzite window, then a numbered list whose items do not name it
PASSAGE = (
    "Z-1 SCOPE (a) This part covers frames with quartzite windows. (b) Frames built to this part shall be limited to the following"
    " limits for both the quartzite panes and all steel parts: (1) The inner design pressure shall equal the rated pressure."
    " (2) The outer design pressure shall not exceed 7 units. (3) The rated pressure shall not exceed 70 units."
    " (4) The service life of the quartzite pane shall be 4 years. Z-2 OTHER (a) Every frame shall carry a tag."
)
STEEL_PAPER = (
    "Invented frame data sheet. Design pressure 3 units. Outer design pressure 5 units. Service life 20 years. "
    * 3
)


def _req(source: str, chunk: str = "c1", rid: str = "r1") -> dict:
    return {"id": rid, "source_text": source, "chunk_id": chunk}


def test_a_list_item_inherits_the_thing_its_lead_in_names_and_is_not_asked_of_a_paper_without_it():
    item = "(3) The rated pressure shall not exceed 70 units."
    assert "quartzite panes" in fit.lead_in(item, PASSAGE)
    got = fit.decide(_req(item), PASSAGE, STEEL_PAPER, CAT)
    assert got == {
        "thing": "a quartzite window",
        "detail": "its own words are about a quartzite window; this paper names none on any page",
    }


def test_the_rule_sentence_subject_names_the_thing():
    item = "(4) The service life of the quartzite pane shall be 4 years."
    assert fit.decide(_req(item), "", STEEL_PAPER, CAT)["thing"] == "a quartzite window"


def test_a_shared_field_word_alone_never_makes_a_rule_fit_but_an_unrelated_rule_is_asked():
    """The steel paper has 'Outer design pressure' and 'Service life': the quartzite items are still not asked; a rule about
    nothing on the list is asked."""
    for item in (
        "(2) The outer design pressure shall not exceed 7 units.",
        "(4) The service life of the quartzite pane shall be 4 years.",
    ):
        assert fit.decide(_req(item), PASSAGE, STEEL_PAPER, CAT) is not None
    assert (
        fit.decide(
            _req("(a) Every frame shall carry a tag."), PASSAGE, STEEL_PAPER, CAT
        )
        is None
    )


def test_a_thing_the_rule_asks_for_after_its_verb_does_not_make_it_unfit():
    """'... shall be installed: a peep hole' asks the paper to HAVE one: a paper without it is exactly what the rule checks."""
    rule = "The following shall be installed on every housing: a level peep hole and a drain plug."
    assert fit.decide(_req(rule), "", STEEL_PAPER, CAT) is None


def test_a_paper_that_names_the_thing_asks_the_rule():
    paper = STEEL_PAPER + " Window: quartzite, two panes."
    assert (
        fit.decide(
            _req("(3) The rated pressure shall not exceed 70 units."),
            PASSAGE,
            paper,
            CAT,
        )
        is None
    )


def test_a_negated_thing_does_not_count():
    rule = "Frames other than quartzite frames shall carry a tag."
    assert fit.decide(_req(rule), "", STEEL_PAPER, CAT) is None
    assert (
        fit.decide(_req("Non-quartzite panes shall be marked."), "", STEEL_PAPER, CAT)
        is None
    )


def test_an_unreadable_paper_leaves_nothing_out():
    assert (
        fit.decide(
            _req("(4) The service life of the quartzite pane shall be 4 years."),
            "",
            None,
            CAT,
        )
        is None
    )


def test_a_section_title_names_the_thing_but_a_sentence_stored_as_the_section_does_not():
    rule = "If the flow is not given, it shall be taken as 5 units."
    assert (
        fit.decide(
            _req(rule),
            "",
            STEEL_PAPER,
            CAT,
            heading="6.7 Extra tests for quartzite frames",
        )["thing"]
        == "a quartzite window"
    )
    assert (
        fit.decide(
            _req(rule),
            "",
            STEEL_PAPER,
            CAT,
            heading="6.7 Quartzite frames shall be tested twice",
        )
        is None
    )


def test_an_exception_a_few_words_before_the_thing_or_a_subject_joining_another_group_keeps_the_rule():
    assert (
        fit.decide(
            _req(
                "For all frames except main quartzite frames, the rated pressure shall be 3 units."
            ),
            "",
            STEEL_PAPER,
            CAT,
        )
        is None
    )
    assert (
        fit.decide(
            _req(
                "With the exception of main quartzite frames, frames shall carry a tag."
            ),
            "",
            STEEL_PAPER,
            CAT,
        )
        is None
    )
    assert (
        fit.decide(
            _req(
                "For heavy frames and for quartzite frames, all tests shall be witnessed."
            ),
            "",
            STEEL_PAPER,
            CAT,
        )
        is None
    )


def test_a_sentence_that_carries_on_a_worked_example_is_not_a_requirement():
    passage = (
        "The valve must reclose above the operating pressure. For example, if the valve is set at 100 units with a 7% margin,"
        " it will close at 93 units. The operating pressure must be kept below 93 units to avoid a leak. Other text."
    )
    assert fit.is_example(
        _req("The operating pressure must be kept below 93 units to avoid a leak."),
        passage,
    )
    assert not fit.is_example(
        _req("The valve must reclose above the operating pressure."), passage
    )  # no figure of the example
    assert not fit.is_example(
        _req("The operating pressure must be kept below 80 units."),
        passage.replace("below 93", "below 80"),
    )


def test_no_lead_in_for_a_sentence_that_is_not_a_list_item_or_of_another_marker_style():
    assert fit.lead_in("The rated pressure shall not exceed 70 units.", PASSAGE) == ""
    assert (
        fit.lead_in("(c) The rated pressure shall not exceed 70 units.", PASSAGE) == ""
    )  # letters: the list counts in digits


def test_the_data_file_names_non_metal_windows_and_the_reason_is_a_ledger_reason():
    names = dict(fit.things())
    assert any(
        "acrylic" in w for w in names[next(n for n in names if n.startswith("acrylic"))]
    )
    assert fit.named_things("The design life of the acrylic window") == [
        next(n for n in names if n.startswith("acrylic"))
    ]
    state, words = scope_ledger.REASONS[fit.REASON]
    assert state == scope_ledger.DOES_NOT_APPLY and words == fit.REASON_WORDS
    assert rules_mod.REASON_WORDS[rules_mod.SUBJECT_NOT_ON_PAPER] == fit.REASON_WORDS


# ---- the AI reviewer's rule choice ----------------------------------------------------------------------------------------

PAPER, STD = "doc_paper", "doc_std"


@pytest.fixture()
def con(monkeypatch):
    s.switch(monkeypatch)
    monkeypatch.setattr(fit, "things", lambda path=None: CAT)
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);
        CREATE TABLE chunks (id TEXT PRIMARY KEY, text TEXT);
        CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, clause TEXT, page INTEGER,
            requirement_text TEXT, source_text TEXT, requirement_type TEXT, field TEXT, operator TEXT, value REAL, unit TEXT,
            value_low REAL, value_high REAL, table_row INTEGER, chunk_id TEXT);
        CREATE TABLE review_runs (id TEXT PRIMARY KEY, submittal_document_id TEXT, status TEXT, created_at TEXT);
        CREATE TABLE review_scope_decisions (review_run_id TEXT, requirement_id TEXT, state TEXT, reason_code TEXT,
            PRIMARY KEY (review_run_id, requirement_id));
        """
    )
    c.execute(
        "INSERT INTO documents VALUES (?, 'INV-STD-9.pdf'), (?, 'paper.pdf')",
        (STD, PAPER),
    )
    c.execute("INSERT INTO pages VALUES (?, 1, ?)", (STD, PASSAGE))
    c.execute("INSERT INTO pages VALUES (?, 1, ?)", (PAPER, STEEL_PAPER))
    c.execute("INSERT INTO chunks VALUES ('c1', ?)", (PASSAGE,))
    for rid, text in (
        ("r-rated", "(3) The rated pressure shall not exceed 70 units."),
        ("r-tag", "(a) Every frame shall carry a tag."),
    ):
        c.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
            " requirement_type, chunk_id) VALUES (?, ?, 'Z-1', 1, ?, ?, 'statement', 'c1')",
            (rid, STD, text, text),
        )
    c.execute(
        "INSERT INTO review_runs VALUES ('run-1', ?, 'completed', '2026-01-01')",
        (PAPER,),
    )
    for rid in ("r-rated", "r-tag"):
        c.execute(
            "INSERT INTO review_scope_decisions VALUES ('run-1', ?, 'applies_not_checked', 'needs_engineer')",
            (rid,),
        )
    schema.create_tables(c)
    for rid in ("r-rated", "r-tag"):
        _label(c, rid)
    c.commit()
    return c


KIND = {"kind": "datasheet", "known": True, "method": "test", "guess": False}


def _asked(doc) -> set[str]:
    return {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}


def test_the_ai_reviewer_leaves_the_unfit_rule_out_with_its_reason_and_says_so(con):
    rows = [
        dict(zip([d[0] for d in cur.description], r, strict=True))
        for cur in [con.execute("SELECT * FROM standard_requirements")]
        for r in cur
    ]
    doc = it.build_items(con, PAPER, KIND, skills=[], cache={}, requirement_rows=rows)
    assert _asked(doc) == {"r-tag"}
    left = [
        r
        for r in doc["rule_labels"]["left_out"]
        if r["reason"] == rules_mod.SUBJECT_NOT_ON_PAPER
    ]
    assert [r["rule_version_id"] for r in left] == ["r-rated"]
    assert doc["rule_labels"]["counts"][rules_mod.SUBJECT_NOT_ON_PAPER] == 1
    assert any(fit.REASON_WORDS in line for line in doc["rule_labels"]["summary_lines"])


def test_the_ai_reviewer_asks_it_when_the_paper_names_the_thing(con):
    con.execute(
        "UPDATE pages SET text = ? WHERE document_id = ?",
        (STEEL_PAPER + " Window: quartzite.", PAPER),
    )
    rows = [
        dict(zip([d[0] for d in cur.description], r, strict=True))
        for cur in [con.execute("SELECT * FROM standard_requirements")]
        for r in cur
    ]
    doc = it.build_items(con, PAPER, KIND, skills=[], cache={}, requirement_rows=rows)
    assert _asked(doc) == {"r-tag", "r-rated"}
    assert (
        rules_mod.SUBJECT_NOT_ON_PAPER not in doc["rule_labels"]["counts"]
    )  # unused: the counts are as they were


# ---- the rule check --------------------------------------------------------------------------------------------------------


def test_the_rule_check_gate_says_does_not_apply_with_the_ledger_reason(
    monkeypatch, con
):
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "connect", lambda: con)
    reqs = [{"id": "r-rated", "source_text": "(3) The rated pressure shall not exceed 70 units.", "chunk_id": "c1"},
            {"id": "r-tag", "source_text": "(a) Every frame shall carry a tag.", "chunk_id": "c1"}]  # fmt: skip
    kept, items = fit.gate_for_run(reqs, PAPER)
    assert [r["id"] for r in kept] == ["r-tag"]
    (item,) = items
    assert item["code"] == fit.REASON and item["requirement"]["id"] == "r-rated"
    assert (
        scope_ledger.decision(item["requirement"], item["code"], item["detail"])[
            "state"
        ]
        == scope_ledger.DOES_NOT_APPLY
    )


def test_a_rule_check_review_does_not_apply_the_unfit_rule_and_records_why(
    temp_storage,  # noqa: F811 - the fixture, imported above
    monkeypatch,
):
    """End to end on the rule check (`comparison.run_comparison`): the quartzite list item is recorded as does-not-apply with this
    reason and gets no finding; the general rule of the same passage is still compared. Removing the gate in `comparison` fails."""
    import uuid

    from app import comparison, datasheets, db, standards
    from tests.test_141_division_scope import (  # noqa: F401  (_review: the same set-up shape)
        NOW,
        FakeModel,
        _doc,
        _review,
    )

    monkeypatch.setattr(fit, "things", lambda path=None: CAT)
    monkeypatch.setattr(settings, "ai_division_scope_enabled", False)
    monkeypatch.setattr(
        ai_task_runner, "make_provider", lambda model_name=None: FakeModel()
    )
    _doc(
        "std",
        "XYZ-code.pdf",
        "COMPANY_STANDARD",
        [(1, PASSAGE)],
        document_number="XYZ-9",
    )
    _doc(
        "sub",
        "sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        [(1, STEEL_PAPER)],
        equipment_type="Pressure vessel",
    )
    ids = {}
    for key, text in (
        ("rated", "(3) The rated pressure shall not exceed 70 units."),
        ("tag", "(a) Every frame shall carry a tag."),
    ):
        ids[key] = standards.create_requirement(
            standard_document_id="std",
            chunk_id="std-1",
            clause=None,
            page=1,
            requirement_text=text,
            source_text=text,
            structured={"requirement_type": "statement"},
        )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Design pressure",
        raw_value="3 units",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at) VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_method,included,created_at)"
            " VALUES (?,?,?,'manual',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({"std", "sub"})
    )
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    assert stored[ids["rated"]]["state"] == scope_ledger.DOES_NOT_APPLY
    assert stored[ids["rated"]]["reason_code"] == fit.REASON
    assert "a quartzite window" in stored[ids["rated"]]["reason"]
    assert stored[ids["tag"]]["state"] != scope_ledger.DOES_NOT_APPLY
    assert not [
        f for f in result["findings"] if f.get("requirement_id") == ids["rated"]
    ]


def test_split_leaves_a_worked_example_out_with_its_own_reason(con):
    passage = "For example, if it is set at 100 units, it will close at 93 units. The pressure must be kept below 93 units."
    con.execute("INSERT INTO chunks VALUES ('c2', ?)", (passage,))
    rows = [{"id": "r-ex", "source_text": "The pressure must be kept below 93 units.", "chunk_id": "c2"},
            {"id": "r-tag", "source_text": "(a) Every frame shall carry a tag.", "chunk_id": "c1"}]  # fmt: skip
    kept, left = fit.split(con, rows, PAPER)
    assert [r["id"] for r in kept] == ["r-tag"]
    assert [(i["requirement"]["id"], i["code"]) for i in left] == [
        ("r-ex", fit.EXAMPLE)
    ]
    assert scope_ledger.REASONS[fit.EXAMPLE][0] == scope_ledger.DOES_NOT_APPLY
    assert rules_mod.REASON_WORDS[rules_mod.RULE_BOOK_EXAMPLE] == fit.EXAMPLE_WORDS
