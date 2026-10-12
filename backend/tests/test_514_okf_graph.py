"""#514 (R29 #833): the reference graph is built only from stored facts, and
every edge is cited.

A node per OKF concept; an edge per link whose target is a node and whose
citation resolves AT THE TIME THE GRAPH IS BUILT. A link that fails is not an
edge and is counted under its reason. Nothing is inferred.

Invented standard only; no model, no socket.
"""
from __future__ import annotations

from app import db, okf
from tests.test_513_okf import NOISE, _build, library  # noqa: F401 - autouse fixture


def _graph():
    return okf.graph(_build()["concepts"])


def test_a_node_per_concept_and_an_edge_per_cited_link():
    built = _graph()
    assert built["report"]["nodes"] == 6 and built["report"]["edges"] == 5
    assert built["report"]["nodes_by_kind"] == {"standard": 1, "clause": 2, "requirement": 2, "equipment_type": 1}
    assert built["report"]["edges_by_relation"] == {"part_of": 2, "in_clause": 2, "applies_to": 1}
    assert built["report"]["links_refused"] == {}
    assert set(built["nodes"]) == {c["id"] for c in _build()["concepts"]}


def test_every_edge_carries_a_citation_that_resolves_now():
    """THE ACCEPTANCE CRITERION of #514."""
    for edge in _graph()["edges"]:
        assert okf.resolve(edge["cite"]) is None
        assert edge["from"].startswith("okf:") and edge["to"].startswith("okf:")


def test_a_link_whose_citation_has_gone_stale_is_not_an_edge():
    """The files were written; then the page was re-read and the chunk is
    gone. The graph is built against what is stored NOW."""
    concepts = _build()["concepts"]
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE id = 'c2'")
    built = okf.graph(concepts)
    assert built["report"]["edges"] == 3 and built["report"]["links_refused"] == {okf.CHUNK_MISSING: 2}
    assert all(edge["cite"]["chunk_id"] == "c1" for edge in built["edges"])


def test_a_link_to_a_concept_that_is_not_there_is_not_an_edge_and_nothing_is_inferred():
    concepts = [c for c in _build()["concepts"] if c["kind"] != "standard"]
    built = okf.graph(concepts)
    assert built["report"]["links_refused"] == {okf.TARGET_MISSING: 2}        # the two part_of links
    assert not [e for e in built["edges"] if e["rel"] == okf.PART_OF]
    # the two clauses belong to one standard, but with no cited link between them they are not connected
    clauses = [c["id"] for c in concepts if c["kind"] == "clause"]
    assert not [e for e in built["edges"] if e["from"] in clauses and e["to"] in clauses]


def test_a_concept_that_is_not_ok_gives_no_edge_even_if_a_file_claims_links():
    concepts = _build()["concepts"]
    requirement = next(c for c in concepts if c["kind"] == "requirement")
    requirement["state"] = okf.CITATION_UNRESOLVED                            # a doctored or stale file
    built = okf.graph(concepts)
    assert built["report"]["links_refused"][okf.NOT_OK] == len(requirement["links"])
    assert not [e for e in built["edges"] if e["from"] == requirement["id"]]


def test_walking_the_graph_a_step_is_an_edge_with_its_citation():
    built = _graph()
    standard = okf.concept_id("standard", "doc_std")
    clauses = okf.neighbours(built, standard, relation=okf.PART_OF, incoming=True)
    assert sorted(e["from"] for e in clauses) == [okf.concept_id("clause", "doc_std", "5.3.3"),
                                                  okf.concept_id("clause", "doc_std", "6.1")]
    requirements = okf.neighbours(built, clauses[0]["from"], relation=okf.IN_CLAUSE, incoming=True)
    assert len(requirements) == 1 and requirements[0]["cite"]["chunk_id"] in ("c1", "c2")
    out = okf.neighbours(built, requirements[0]["from"])
    assert {e["rel"] for e in out} <= {okf.IN_CLAUSE, okf.APPLIES_TO} and all(e["cite"] for e in out)
    assert okf.neighbours(built, "okf:clause:nowhere") == []


def test_the_graph_is_the_same_from_the_files_as_from_the_build():
    built = _build()
    okf.write(built["concepts"])
    loaded = okf.load()
    assert loaded["unreadable"] == [] and loaded["concepts"] == built["concepts"]
    assert okf.graph(loaded["concepts"]) == okf.graph(built["concepts"])


def test_a_file_that_is_not_okf_is_named_and_a_missing_folder_is_empty(tmp_path):
    okf.write(_build()["concepts"])
    (okf.root() / "clause" / "broken.md").write_text("no frontmatter", encoding="utf-8")
    (okf.root() / "clause" / "other.md").write_text('---\nkind: "sentence"\nid: "x"\n---\n', encoding="utf-8")
    loaded = okf.load()
    assert loaded["unreadable"] == ["clause/broken.md", "clause/other.md"] and len(loaded["concepts"]) == 6
    assert okf.load(tmp_path / "nothing-here") == {"concepts": [], "unreadable": []}


def test_the_graph_report_holds_counts_only():
    text = str(_graph()["report"])
    assert "noise" not in text.lower() and NOISE not in text and "doc_std" not in text
