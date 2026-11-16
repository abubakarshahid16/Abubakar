"""Order 14 lane C: (1) a rule a re-extraction superseded is never a candidate of the AI reviewer, by any road; (2) a
re-extraction carries a superseded rule's AI labels to its successor with IDENTICAL text in the same book, never a
person's approval. Invented rows only; no model, no network."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_items as it
from app import rule_equipment, rule_labels, standards
from app import rule_label_schema as schema
from tests import rule_label_support as s
from tests.test_agent_review_items import (  # noqa: F401  (fixture and helpers)
    KIND,
    PAPER,
    _label,
    con,
)

# ---- (1) superseded rules are not candidates ---------------------------------------------------------------------------


def _supersede(c, *ids):
    c.execute("ALTER TABLE standard_requirements ADD COLUMN superseded_at TEXT")
    for rid in ids:
        c.execute(
            "UPDATE standard_requirements SET superseded_at = '2026-11-16' WHERE id = ?",
            (rid,),
        )


def _rules(doc):
    return {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}


def test_a_superseded_rule_from_a_stored_runs_decisions_is_not_asked_and_is_counted(
    con,  # noqa: F811
):
    before = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert "r-limit" in _rules(before)
    _supersede(con, "r-limit")
    after = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert "r-limit" not in _rules(after)
    assert _rules(after) == _rules(before) - {"r-limit"}
    assert after["rules_left_out"]["superseded"] == 1


def test_a_superseded_rule_chosen_by_the_caller_is_not_asked(con):  # noqa: F811
    _supersede(con, "r-coat")
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in cur.execute(
            "SELECT * FROM standard_requirements WHERE id IN ('r-limit', 'r-coat')"
        )
    ]
    doc = it.build_items(
        con, "doc_never_reviewed", KIND, skills=[], cache={}, requirement_rows=rows
    )
    assert _rules(doc) == {"r-limit"} and doc["rules_left_out"]["superseded"] == 1


def test_nothing_superseded_changes_nothing(con):  # noqa: F811
    before = it.build_items(con, PAPER, KIND, skills=[], cache={})
    _supersede(con)  # the column exists, no row is superseded
    after = it.build_items(con, PAPER, KIND, skills=[], cache={})
    assert (
        _rules(after) == _rules(before) and "superseded" not in after["rules_left_out"]
    )


# ---- (2) labels carried to an identical successor ----------------------------------------------------------------------

RUN = "xrun_new"


@pytest.fixture
def book(monkeypatch):
    s.switch(monkeypatch)
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, requirement_text TEXT,"
        " source_text TEXT, superseded_at TEXT, superseded_by_run TEXT, chunk_id TEXT, page INTEGER DEFAULT 1)"
    )
    c.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, section TEXT)")
    c.execute(
        "CREATE TABLE rulebook_version (id TEXT PRIMARY KEY, rule_id TEXT, version_no INTEGER)"
    )
    c.execute(
        "CREATE TABLE rulebook_provenance (rule_version_id TEXT, standard_document_id TEXT, page INTEGER, quote TEXT)"
    )
    c.execute(
        "INSERT INTO chunks VALUES ('ch-head', 'ZZ-12 NUTS AND WASHERS'), ('ch-plain', '4.1 General')"
    )
    c.execute(
        "CREATE TABLE rulebook_approval (id TEXT PRIMARY KEY, rule_version_id TEXT, decision TEXT, approver_id TEXT,"
        " decided_at TEXT, equipment_type TEXT, tier TEXT)"
    )
    schema.create_tables(c)
    rule_equipment.create_tables(c)

    def rule(rid, text, by=None, doc="d-book", chunk="ch-plain", page=1):
        c.execute(
            "INSERT INTO standard_requirements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, doc, text, text, "2026-11-16" if by else None, by, chunk, page),
        )

    rule("old-same", "The relief device shall be set at the stated pressure.", RUN)
    rule(
        "new-same", "The relief  device shall be set at the stated pressure."
    )  # whitespace aside: identical
    rule("old-changed", "The disk shall be marked.", RUN)
    rule("new-changed", "The disk shall be marked with its burst pressure.")
    rule("old-twice", "Each valve shall be tested.", RUN)
    rule("new-twice-a", "Each valve shall be tested.")
    rule("new-twice-b", "Each valve shall be tested.")
    rule("old-taken", "The seat shall be tight.", RUN)
    rule("new-taken", "The seat shall be tight.")
    rule("old-earlier", "Springs shall be marked.", "xrun_older")
    rule("new-earlier", "Springs shall be marked.")
    rule("old-person", "Bonnets shall be vented.", RUN)
    rule("new-person", "Bonnets shall be vented.")
    rule("old-head", "ZZ-12 NUTS AND WASHERS Nuts shall be of the stated grade.", RUN)
    rule(
        "new-head", "Nuts shall be of the stated grade.", chunk="ch-head"
    )  # its heading line, read apart now
    rule("old-head-other", "ZZ-13 BOLTS Washers shall be hardened.", RUN)
    rule(
        "new-head-other", "Washers shall be hardened.", chunk="ch-head"
    )  # another heading: no match
    rule(
        "old-rechunk", "Gaskets shall be replaced.", "xrun_rechunk_1794835902"
    )  # its chunk went at the re-chunk
    rule("new-rechunk", "Gaskets shall be replaced.")
    rule("old-split-1", "Covers shall be bolted.", RUN)
    rule("old-split-2", "Covers  shall be bolted.", RUN)
    rule(
        "new-split", "Covers shall be bolted."
    )  # two old rules, different labels: nothing is carried
    for ref in (
        "old-rechunk",
        "old-same",
        "old-changed",
        "old-twice",
        "old-taken",
        "old-earlier",
        "old-head",
        "old-head-other",
        "old-split-1",
    ):
        _label(c, ref, rule_version_id=None)
    _label(c, "old-split-2", rule_version_id=None, kind="drawing")
    _label(c, "new-taken", state="needs_human", rule_version_id=None)
    _label(c, "old-person")  # rule_version_id v-old-person
    c.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-old-person', 'approve', 'u1', 't', 'relief valve', 'owner')"
    )
    c.execute(
        "INSERT INTO rule_equipment_label (source, rule_ref, equip_state, equip_general, equip_type, labelled_at,"
        " model_a, model_b, prompt_version, list_sha) VALUES ('requirement', 'old-same', 'agreed', 0, 'relief valve',"
        " 't', ?, ?, 'rule-equip-v1', ?)",
        (s.MODEL_A, s.MODEL_B, "c" * 64),
    )
    return c


def _has(c, ref):
    return rule_labels.label_for(c, requirement_id=ref) is not None


def test_an_identical_successor_gets_the_ai_label_and_is_judged_as_before(book):
    got = standards.carry_labels(book, "d-book", RUN)
    new = rule_labels.label_for(book, requirement_id="new-same")
    old = rule_labels.label_for(book, requirement_id="old-same")
    keys = ("state", "paper_kind", "quote_sha256", "a_model", "b_model")
    assert new is not None and {k: new[k] for k in keys} == {k: old[k] for k in keys}
    assert (
        rule_labels.usable_tier(book, requirement_id="new-same").tier
        == rule_labels.AI_TIER
    )
    assert got["carried_equipment"] == 1
    assert (
        rule_equipment.label_for(book, "requirement", "new-same")["equip_type"]
        == "relief valve"
    )


def test_every_identical_successor_gets_the_label(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "new-twice-a") and _has(book, "new-twice-b")
    # new-same, new-twice-a, new-twice-b, new-rechunk
    assert (
        got["carried_identical"] == 4
    )  # new-person is not carried: a person decided the old rule


def test_a_rule_superseded_by_the_rechunk_of_the_book_carries_its_label_too(book):
    standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "new-rechunk")


def test_a_successor_whose_heading_line_was_read_apart_gets_the_label(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "new-head") and got["carried_heading_restored"] == 1
    assert not _has(
        book, "new-head-other"
    )  # the old text names another heading: no exact match


def test_changed_conflicting_already_labelled_and_other_runs_are_not_carried(book):
    got = standards.carry_labels(book, "d-book", RUN)
    assert not _has(book, "new-changed")
    assert not _has(book, "new-split") and got["conflicting"] == 1
    assert (
        rule_labels.label_for(book, requirement_id="new-taken")["state"]
        == "needs_human"
    )  # its own label stays
    assert got["successor_labelled"] == 1
    assert not _has(book, "new-earlier")  # superseded by another run
    # old-changed, old-head-other, old-split-1, old-split-2, old-person (a person decided it)
    assert got["old_rules_not_carried"] == 5


def test_a_rule_a_person_decided_carries_nothing(book):
    """A person's approval is never carried, and neither is the AI label of a rule a person decided (R89 item 3)."""
    got = standards.carry_labels(book, "d-book", RUN)
    assert (
        got["person_decided_not_carried"] == 1
        and got["person_decisions_not_carried"] == 1
    )
    assert rule_labels.usable_tier(book, requirement_id="old-person").tier == "owner"
    assert not _has(book, "new-person")


def test_a_persons_refusal_is_never_bypassed(book):
    book.execute("UPDATE rulebook_approval SET decision = 'reject'")
    standards.carry_labels(book, "d-book", RUN)
    assert (
        rule_labels.usable_tier(book, requirement_id="new-person").tier
        != rule_labels.AI_TIER
    )


def test_a_successor_with_only_an_equipment_label_gets_the_rule_label_and_keeps_its_own(
    book,
):
    """R89 item 2: the equipment-label insert must not replace a successor's own row (the table refuses it)."""
    book.execute(
        "INSERT INTO rule_equipment_label (source, rule_ref, equip_state, equip_general, equip_type, labelled_at,"
        " model_a, model_b, prompt_version, list_sha) VALUES ('requirement', 'new-same', 'agreed', 0, 'pump',"
        " 't', ?, ?, 'rule-equip-v1', ?)",
        (s.MODEL_A, s.MODEL_B, "c" * 64),
    )
    got = standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "new-same") and got["carried_equipment"] == 0
    assert (
        rule_equipment.label_for(book, "requirement", "new-same")["equip_type"]
        == "pump"
    )


def test_carrying_twice_changes_nothing(book):
    first = standards.carry_labels(book, "d-book", RUN)
    again = standards.carry_labels(book, "d-book", RUN)
    assert (
        again["carried"] == 0
        and again["successor_labelled"]
        == first["carried"] + first["successor_labelled"]
    )


def test_a_superseded_rule_never_wins_the_duplicate_check_over_its_identical_successor(
    con,  # noqa: F811
):
    """R89 blocker: the old row and its current successor share the duplicate key; with the old row sorting first, the
    successor was counted as a repeat and the old row then dropped, so the rule vanished."""
    _supersede(con)
    con.execute(
        "INSERT INTO standard_requirements (id, clause, page, requirement_text, source_text, requirement_type,"
        " standard_document_id, superseded_at) SELECT 'a-old', clause, page, requirement_text, source_text,"
        " requirement_type, standard_document_id, '2026-11-16' FROM standard_requirements WHERE id = 'r-coat'"
    )
    con.execute("UPDATE standard_requirements SET id = 'z-new' WHERE id = 'r-coat'")
    _label(con, "z-new")
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in cur.execute(
            "SELECT * FROM standard_requirements WHERE id IN ('a-old', 'z-new')"
        )
    ]
    doc = it.build_items(
        con, "doc_never_reviewed", KIND, skills=[], cache={}, requirement_rows=rows
    )
    assert _rules(doc) == {"z-new"}
    assert (
        doc["rules_left_out"]["superseded"] == 1
        and "stored_repeat" not in doc["rules_left_out"]
    )


def test_a_persons_later_refusal_of_the_version_reaches_the_carried_successor(book):
    """R92: the successor keeps the label's rule-book version link, so a refusal made AFTER the carry stops both."""
    book.execute(
        "INSERT INTO standard_requirements VALUES ('old-bridged', 'd-book', 'Stems shall be sealed.',"
        " 'Stems shall be sealed.', '2026-11-16', ?, 'ch-plain', 1)",
        (RUN,),
    )
    book.execute(
        "INSERT INTO standard_requirements VALUES ('new-bridged', 'd-book', 'Stems shall be sealed.',"
        " 'Stems shall be sealed.', NULL, NULL, 'ch-plain', 1)"
    )
    _label(book, "old-bridged", rule_version_id="v-bridged")
    _version(book, "v-bridged", 1, "Stems shall be sealed.")
    standards.carry_labels(book, "d-book", RUN)
    assert (
        rule_labels.usable_tier(book, requirement_id="new-bridged").tier
        == rule_labels.AI_TIER
    )
    book.execute(
        "INSERT INTO rulebook_approval VALUES ('a9', 'v-bridged', 'reject', 'u1', 't', NULL, NULL)"
    )
    assert rule_labels.usable_tier(book, requirement_id="old-bridged").tier is None
    assert rule_labels.usable_tier(book, requirement_id="new-bridged").tier is None


def test_only_the_newest_rechunk_of_the_book_is_read(book):
    """R92: an older re-chunk's rows belong to an earlier re-extraction and are not read again."""
    book.execute(
        "INSERT INTO standard_requirements VALUES ('old-older-rechunk', 'd-book', 'Plugs shall be tight.',"
        " 'Plugs shall be tight.', '2026-01-01', 'xrun_rechunk_1', 'ch-plain', 1)"
    )
    book.execute(
        "INSERT INTO standard_requirements VALUES ('new-older-rechunk', 'd-book', 'Plugs shall be tight.',"
        " 'Plugs shall be tight.', NULL, NULL, 'ch-plain', 1)"
    )
    _label(book, "old-older-rechunk", rule_version_id=None)
    standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "new-rechunk") and not _has(book, "new-older-rechunk")


def _version(book, vid, page, quote, doc="d-book"):
    """A latest rule-book version quoting `quote` on `page` of `doc`: what `rule_labels.bridge_map` reads."""
    book.execute(
        "INSERT OR IGNORE INTO rulebook_version VALUES (?, ?, 1)", (vid, f"rule-{vid}")
    )
    book.execute(
        "INSERT INTO rulebook_provenance VALUES (?, ?, ?, ?)", (vid, doc, page, quote)
    )


def _old_new(book, text, old_page=1, new_page=1, olds=("o1",), versions=("v-old",)):
    for i, (o, v) in enumerate(zip(olds, versions, strict=True)):
        book.execute(
            "INSERT INTO standard_requirements VALUES (?, 'd-book', ?, ?, '2026-11-16', ?, 'ch-plain', ?)",
            (o, text, text if i == 0 else text + " ", RUN, old_page),
        )
        _label(book, o, rule_version_id=v)
    book.execute(
        "INSERT INTO standard_requirements VALUES ('n1', 'd-book', ?, ?, NULL, NULL, 'ch-plain', ?)",
        (text, text, new_page),
    )


def _link(book, ref):
    return rule_labels.label_for(book, requirement_id=ref)["rule_version_id"]


TEXT = "Caps shall be fitted."


def test_the_successor_takes_its_own_version_on_its_own_page(book):
    """R95: the link is the successor's OWN version (its text on its page), as the labeller links, not the old rule's."""
    _version(book, "v-old", 2, TEXT)  # the old rule's link quotes another page
    _version(book, "v-own", 1, TEXT)
    _old_new(book, TEXT)
    got = standards.carry_labels(book, "d-book", RUN)
    assert _link(book, "n1") == "v-own" and got["version_link_own"] >= 1


def test_a_later_refusal_of_the_successors_own_version_blocks_it(book):
    """R95 probe i: the successor's own version refused after the carry: the successor is no longer asked."""
    _version(book, "v-own", 1, TEXT)
    _old_new(
        book, TEXT, versions=(None,)
    )  # the old rule had no link at all (67 such on real data)
    standards.carry_labels(book, "d-book", RUN)
    assert (
        rule_labels.usable_tier(book, requirement_id="n1").tier == rule_labels.AI_TIER
    )
    book.execute(
        "INSERT INTO rulebook_approval VALUES ('a8', 'v-own', 'reject', 'u1', 't', NULL, NULL)"
    )
    assert rule_labels.usable_tier(book, requirement_id="n1").tier is None


def test_another_pages_version_never_reads_as_the_successors(book):
    """R93 fault A stays fixed: the old rule's version quotes another page; its later approval gives no person tier."""
    _version(book, "v-old", 2, TEXT)
    _old_new(book, TEXT)
    standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "n1") and _link(book, "n1") is None
    book.execute(
        "INSERT INTO rulebook_approval VALUES ('a7', 'v-old', 'approve', 'u1', 't', 'relief valve', 'owner')"
    )
    assert (
        rule_labels.usable_tier(
            book, requirement_id="n1", equipment_type="relief valve"
        ).tier
        == rule_labels.AI_TIER
    )


def test_another_books_version_on_the_same_page_never_reads_as_the_successors(book):
    """R95 probe j: the page is compared WITH its document."""
    _version(book, "v-other-book", 1, TEXT, doc="d-other")
    _old_new(book, TEXT, versions=("v-other-book",))
    standards.carry_labels(book, "d-book", RUN)
    assert _link(book, "n1") is None


def test_two_old_rules_with_their_own_links_give_the_successor_only_its_own(book):
    """R93 probes c/d: two old rules with different links; the successor takes its own version, or none."""
    _old_new(book, TEXT, olds=("o1", "o2"), versions=("v-x", "v-y"))
    standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "n1") and _link(book, "n1") is None


def test_a_successor_with_no_page_gets_no_link(book):
    """The page guard: a successor with no page takes no version, not even one stored with no page."""
    _version(book, "v-nopage", None, TEXT)
    _old_new(book, TEXT, new_page=None)
    standards.carry_labels(book, "d-book", RUN)
    assert _has(book, "n1") and _link(book, "n1") is None
