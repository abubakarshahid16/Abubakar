"""#515 (R29 #833): three graph queries - which standards apply, is this the
latest revision, what else is affected.

Every step of an answer is an edge of the graph with a citation that
resolves, or (for a revision) the stored record that one document supersedes
another, re-read at the time of asking. A question the graph cannot answer
gets a named state, never an empty list that reads as "none".

Invented standards only; no model, no socket.
"""
from __future__ import annotations

from app import db, okf, standards
from tests.test_513_okf import ALL, NOW, _build, library  # noqa: F401 - autouse fixture

PUMP = "Centrifugal pump"
STD = okf.concept_id("standard", "doc_std")
REV_A, REV_B, REV_C = (okf.concept_id("standard", d) for d in ("doc_rev_a", "doc_rev_b", "doc_rev_c"))


def _world(ids=("doc_std",), allowed=ALL):
    concepts = _build(ids, allowed)["concepts"]
    return concepts, okf.graph(concepts)


def _resolves(edges) -> bool:
    return bool(edges) and all(okf.resolve(edge["cite"]) is None for edge in edges)


# ------------------------------------------------------------- which apply
def test_the_standard_that_applies_is_reached_by_three_cited_steps():
    _concepts, built = _world()
    out = okf.applicable(built, PUMP)
    assert out["state"] == okf.ANSWERED and [s["standard"] for s in out["standards"]] == [STD]
    (path,) = out["standards"][0]["paths"]
    assert [edge["rel"] for edge in path] == [okf.APPLIES_TO, okf.IN_CLAUSE, okf.PART_OF]
    assert path[0]["from"] == path[1]["from"] and path[1]["to"] == path[2]["from"] and path[2]["to"] == STD
    assert _resolves(path)                                    # THE ACCEPTANCE CRITERION: each step resolves
    assert okf.applicable(built, "  centrifugal   PUMP ")["state"] == okf.ANSWERED


def test_an_equipment_type_the_graph_does_not_hold_is_not_no_standard_applies():
    _concepts, built = _world()
    out = okf.applicable(built, "Heat exchanger")
    assert out == {"state": okf.EQUIPMENT_UNKNOWN, "standards": [], "requirements_reaching_no_standard": 0}


def test_a_requirement_with_no_cited_way_to_a_standard_is_counted_not_trusted():
    """The requirement applies to the type, but its clause was never
    recorded: no edge leads to a standard, so none is named."""
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET clause = NULL WHERE equipment_type = ?", (PUMP,))
    _concepts, built = _world()
    out = okf.applicable(built, PUMP)
    assert out == {"state": okf.NO_CITED_PATH, "standards": [], "requirements_reaching_no_standard": 1}


def test_a_step_whose_citation_went_stale_is_not_walked():
    concepts = _build()["concepts"]
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE id = 'c1'")
    assert okf.applicable(okf.graph(concepts), PUMP)["state"] == okf.NO_CITED_PATH


# ------------------------------------------------------ what else is affected
def test_what_a_standard_affects_its_clauses_their_requirements_and_the_equipment_type():
    _concepts, built = _world()
    out = okf.impact(built, STD)
    assert out["state"] == okf.ANSWERED
    assert sorted(a["kind"] for a in out["affected"]) == ["clause", "clause", "equipment_type", "requirement", "requirement"]
    for affected in out["affected"]:
        assert _resolves(affected["path"])
        assert affected["path"][0]["to"] == STD               # a path starts at the concept asked about
        ends = (affected["path"][-1]["from"], affected["path"][-1]["to"])
        assert affected["concept"] in ends
    pump = next(a for a in out["affected"] if a["kind"] == "equipment_type")
    assert [edge["rel"] for edge in pump["path"]] == [okf.PART_OF, okf.IN_CLAUSE, okf.APPLIES_TO]


def test_what_a_clause_and_a_requirement_affect():
    concepts, built = _world()
    clause = okf.concept_id("clause", "doc_std", "5.3.3")
    out = okf.impact(built, clause)
    assert sorted(a["kind"] for a in out["affected"]) == ["equipment_type", "requirement"]
    assert STD not in [a["concept"] for a in out["affected"]]            # a change does not flow up to the standard
    requirement = next(a["concept"] for a in out["affected"] if a["kind"] == "requirement")
    assert [a["kind"] for a in okf.impact(built, requirement)["affected"]] == ["equipment_type"]
    plain = next(c["id"] for c in concepts if c["kind"] == "requirement" and c["id"] != requirement)
    assert okf.impact(built, plain) == {"state": okf.NOTHING_AFFECTED, "affected": []}


def test_the_walk_ends_at_an_equipment_type_and_does_not_spread_through_it():
    """Two standards have a requirement for the same type. A change to one
    standard does not 'affect' the other standard's requirement."""
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET text = 'The casing shall be steel.' WHERE id = 'cx'")
    standards.create_requirement(standard_document_id="doc_other", chunk_id="cx", clause="4.2", page=1,
                                 requirement_text="The casing shall be steel.", source_text="The casing shall be steel.",
                                 structured={"requirement_type": "material"})
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET equipment_type = ? WHERE clause = '4.2'", (PUMP,))
    _concepts, built = _world(("doc_std", "doc_other"))
    assert len(okf.applicable(built, PUMP)["standards"]) == 2
    touched = okf.impact(built, STD)["affected"]
    # doc_std's two requirements and no third: a requirement id does not name its standard, so count them
    assert sorted(a["kind"] for a in touched) == ["clause", "clause", "equipment_type", "requirement", "requirement"]
    assert all(edge["cite"]["document_id"] == "doc_std" for a in touched for edge in a["path"])
    assert len(okf.impact(built, okf.concept_id("equipment_type", PUMP))["affected"]) == 2     # asked directly: both


def test_a_concept_that_is_not_in_the_graph_is_named():
    _concepts, built = _world()
    assert okf.impact(built, "okf:clause:doc_std:9.9") == {"state": okf.CONCEPT_MISSING, "affected": []}


# ------------------------------------------------------------ latest revision
def _revisions(*rows):
    """Invented revisions of one numbered standard: (document id, revision,
    superseded by)."""
    with db.connect() as conn:
        for doc, revision, replaced_by in rows:
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                         "uploaded_at) VALUES (?,?,?,1,'x','ready',1,?)", (doc, f"{doc}.pdf", f"sha-{doc}", NOW))
            conn.execute("INSERT INTO document_classification (document_id, suggested_by, document_number,"
                         " revision, superseded_by) VALUES (?, 'test', 'STD-100', ?, ?)",
                         (doc, revision, replaced_by))
    ids = tuple(row[0] for row in rows)
    return _world(ids, frozenset(ids))


def _latest(world, standard):
    concepts, built = world
    return okf.latest_revision(built, concepts, standard)


def test_a_superseded_revision_names_what_replaced_it():
    world = _revisions(("doc_rev_a", "A", "doc_rev_b"), ("doc_rev_b", "B", None))
    out = _latest(world, REV_A)
    assert out["state"] == okf.SUPERSEDED and out["superseded_by"] == "doc_rev_b"
    assert out["superseding_standard_in_the_graph"] is True
    assert out["basis"]["document_id"] == "doc_rev_a" and "library holds" in out["basis"]["boundary"]


def test_the_latest_of_the_revisions_held_rests_on_the_record_not_on_the_label():
    world = _revisions(("doc_rev_a", "A", "doc_rev_b"), ("doc_rev_b", "B", "doc_rev_c"), ("doc_rev_c", "C", None))
    out = _latest(world, REV_C)
    assert out["state"] == okf.LATEST_HELD and out["replaces"] == [REV_A, REV_B]       # A through B: the record is followed
    assert _latest(world, REV_B)["state"] == okf.SUPERSEDED


def test_two_revisions_with_no_record_between_them_are_not_ordered_by_their_labels():
    """Revision 'B' looks later than 'A'. Nobody recorded that it replaces
    it, so the answer is that the order is not recorded - for both."""
    world = _revisions(("doc_rev_a", "A", None), ("doc_rev_b", "B", None))
    assert _latest(world, REV_B) == {"state": okf.ORDER_NOT_RECORDED, "also_held": [REV_A],
                                     "basis": _latest(world, REV_B)["basis"]}
    assert _latest(world, REV_A)["state"] == okf.ORDER_NOT_RECORDED


def test_a_revision_replaced_by_a_document_outside_the_graph_does_not_make_this_one_latest():
    world = _revisions(("doc_rev_a", "A", "doc_elsewhere"), ("doc_rev_b", "B", None))
    assert _latest(world, REV_B)["state"] == okf.ORDER_NOT_RECORDED
    out = _latest(world, REV_A)
    assert out["state"] == okf.SUPERSEDED and out["superseding_standard_in_the_graph"] is False


def test_the_only_revision_held_is_said_to_be_the_only_one_held_never_the_latest():
    world = _revisions(("doc_rev_a", "A", None))
    assert _latest(world, REV_A)["state"] == okf.ONLY_ONE_HELD


def test_the_record_is_read_at_the_time_of_asking():
    world = _revisions(("doc_rev_a", "A", None))
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET superseded_by = 'doc_new' WHERE document_id = 'doc_rev_a'")
    assert _latest(world, REV_A)["state"] == okf.SUPERSEDED


def test_no_number_and_not_in_the_graph_are_named():
    world = _world()                                           # doc_std has no classification record
    assert _latest(world, STD)["state"] == okf.NO_NUMBER
    assert _latest(world, "okf:standard:doc_nowhere") == {"state": okf.CONCEPT_MISSING}
