"""#1606: the search-index measurement bed (`scripts/retrieval_bed.py`).

Invented text only; no model, no real database. The rules pinned here are the
ones a wrong number would hide behind: every metric keeps its denominator, a
gold case exists only when code finds its quote, nothing the bed writes holds
document text, and with the setting off the search pipeline is untouched.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sqlite3
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "retrieval_bed_under_test", REPO / "scripts" / "retrieval_bed.py"
)
bed = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bed)

ZEBRA = "The zebra gate shall open within 12 seconds of the signal."
MOON = "Moon valves shall be painted blue before the first shipment."
LAMP = "Every lamp post shall stand at least 3 metres from the canal."


def _library() -> sqlite3.Connection:
    """Two invented documents, one of them holding the same clause twice."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE document_classification (document_id TEXT, document_role TEXT);
        CREATE TABLE chunks (id TEXT, document_id TEXT, page_start INT, page_end INT,
            section TEXT, context TEXT, kind TEXT, text TEXT, retrievable INT, content_hash TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INT, text TEXT);
        CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, page INT,
            requirement_text TEXT, source_text TEXT, requirement_type TEXT, chunk_id TEXT,
            superseded_at TEXT);
    """)
    conn.executemany(
        "INSERT INTO documents VALUES (?,?)", [("d1", "a.pdf"), ("d2", "b.pdf")]
    )
    conn.execute("INSERT INTO document_classification VALUES ('d1','COMPANY_STANDARD')")
    conn.executemany(
        "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("c1", "d1", 3, 3, "1", None, "prose", ZEBRA, 1, "h1"),
            ("c2", "d1", 8, 9, "2", None, "prose", MOON, 1, "h2"),
            ("c3", "d2", 5, 5, "1", None, "prose", ZEBRA, 1, "h3"),
            ("c4", "d2", 6, 6, "2", None, "table", LAMP, 1, "h4"),
            (
                "c5",
                "d2",
                7,
                7,
                "3",
                None,
                "prose",
                "Hidden text kept out of search.",
                0,
                "h5",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO pages VALUES (?,?,?)",
        [
            ("d1", 3, ZEBRA),
            ("d1", 8, MOON),
            ("d2", 5, ZEBRA),
            ("d2", 6, LAMP),
        ],
    )
    conn.executemany(
        "INSERT INTO standard_requirements VALUES (?,?,?,?,?,?,?,?)",
        [
            ("r1", "d1", 3, "Zebra gate opening time", ZEBRA, "statement", "c1", None),
            ("r2", "d1", 8, MOON, MOON, "statement", "c2", None),
            ("r3", "d2", 6, "Lamp post distance", LAMP, "table_value", "c4", None),
            (
                "r4",
                "d1",
                8,
                "A superseded row about moons",
                MOON,
                "statement",
                "c2",
                "2026-01-01",
            ),
            (
                "r5",
                "d1",
                3,
                "A rule whose quote is nowhere",
                "Words found on no page at all here.",
                "statement",
                "c1",
                None,
            ),
            (
                "r6",
                "d2",
                7,
                "A rule in a chunk search may not use",
                "Hidden text kept out of search.",
                "statement",
                "c5",
                None,
            ),
        ],
    )
    return conn


def _case(**over) -> dict:
    case = {
        "id": "x",
        "family": "rule_text",
        "query": "q",
        "quote": ZEBRA,
        "scope_document_id": None,
        "chunk_kind": "prose",
        "document_role": "COMPANY_STANDARD",
        "verbatim": False,
        "quote_in_chunk": True,
        "target_chunks": ["c1"],
        "expected": [{"document_id": "d1", "pages": [3]}],
    }
    return {**case, **over}


def _hit(doc="d1", start=3, end=3, text=ZEBRA, chunk="c1") -> dict:
    return {
        "chunk_id": chunk,
        "document_id": doc,
        "page_start": start,
        "page_end": end,
        "text": text,
    }


def _result(*hits, total=None, excluded=()) -> dict:
    return {
        "hits": list(hits),
        "total": len(hits) if total is None else total,
        "shortlist_excluded": list(excluded),
    }


# ------------------------------------------------------------------ gold set


def test_a_case_exists_only_when_code_finds_its_quote():
    gold = bed.build_gold(_library(), seed=1, per_document=5, compiled_rows=[])
    ids = {c["source_id"] for c in gold["cases"]}
    assert ids == {"r1", "r2", "r3"}
    assert gold["dropped"]["quote_not_found"] == 1  # r5: on no page
    assert gold["dropped"]["chunk_not_retrievable"] == 1  # r6: search may not use it
    # r4 is superseded: not a live rule, so never even a candidate
    assert "r4" not in ids


def test_the_same_clause_elsewhere_also_counts_as_a_correct_location():
    gold = bed.build_gold(_library(), seed=1, per_document=5, compiled_rows=[])
    zebra = next(c for c in gold["cases"] if c["source_id"] == "r1")
    assert {(e["document_id"], tuple(e["pages"])) for e in zebra["expected"]} == {
        ("d1", (3,)),
        ("d2", (5,)),
    }
    assert set(zebra["target_chunks"]) == {"c1", "c3"}


def test_families_and_labels_say_what_each_case_is():
    gold = bed.build_gold(_library(), seed=1, per_document=5, compiled_rows=[])
    by_id = {c["source_id"]: c for c in gold["cases"]}
    assert by_id["r1"]["family"] == "rule_text" and by_id["r1"]["verbatim"] is False
    assert by_id["r2"]["family"] == "rule_text" and by_id["r2"]["verbatim"] is True
    assert (
        by_id["r3"]["family"] == "table_cell" and by_id["r3"]["chunk_kind"] == "table"
    )
    assert by_id["r3"]["document_role"] is None


def test_a_quote_split_across_chunks_is_kept_but_cannot_score_citation_precision():
    conn = _library()
    conn.execute(
        "UPDATE pages SET text = ? WHERE document_id='d1' AND page_no=3",
        (ZEBRA + " It spans into another chunk here and more.",),
    )
    conn.execute(
        "INSERT INTO standard_requirements VALUES "
        "('r7','d1',3,'Zebra spanning rule',?, 'statement','c1',NULL)",
        (ZEBRA + " It spans into another chunk",),
    )
    gold = bed.build_gold(conn, seed=1, per_document=9, compiled_rows=[])
    case = next(c for c in gold["cases"] if c["source_id"] == "r7")
    assert case["quote_in_chunk"] is False
    assert case["expected"] == [{"document_id": "d1", "pages": [3]}]


def test_sampling_is_per_document_and_repeatable():
    one = bed.build_gold(_library(), seed=7, per_document=1, compiled_rows=[])
    assert sorted(
        c["expected"][0]["document_id"]
        for c in one["cases"]
        if c["family"] == "rule_text"
    ) in (["d1"], ["d1", "d2"])
    per_doc = {}
    for c in one["cases"]:
        per_doc[c["source_document"]] = per_doc.get(c["source_document"], 0) + 1
    assert max(per_doc.values()) == 1
    assert (
        one["cases"]
        == bed.build_gold(_library(), seed=7, per_document=1, compiled_rows=[])["cases"]
    )


def test_compiled_rules_become_field_questions_both_unscoped_and_scoped():
    rows = [
        {
            "id": "k1",
            "standard_document_id": "d1",
            "page": 8,
            "field": "valve paint colour",
            "applies_to": "moon valves",
            "condition_text": None,
            "quote": MOON,
        }
    ]
    gold = bed.build_gold(_library(), seed=1, per_document=5, compiled_rows=rows)
    field = [c for c in gold["cases"] if c["source_id"] == "k1"]
    assert {c["family"] for c in field} == {"compiled_field", "compiled_field_scoped"}
    scoped = next(c for c in field if c["family"] == "compiled_field_scoped")
    assert scoped["scope_document_id"] == "d1"
    assert (
        next(c for c in field if c["family"] == "compiled_field")["scope_document_id"]
        is None
    )
    assert (
        scoped["query"] == "valve paint colour moon valves"
        and scoped["verbatim"] is False
    )


def test_compiled_rule_with_no_field_or_a_quote_not_on_its_page_is_dropped_and_counted():
    rows = [
        {
            "id": "k2",
            "standard_document_id": "d1",
            "page": 8,
            "field": None,
            "applies_to": "x",
            "condition_text": None,
            "quote": MOON,
        },
        {
            "id": "k3",
            "standard_document_id": "d1",
            "page": 3,
            "field": "colour",
            "applies_to": "moon",
            "condition_text": None,
            "quote": "Words on no page of this library.",
        },
    ]
    gold = bed.build_gold(_library(), seed=1, per_document=5, compiled_rows=rows)
    assert not [c for c in gold["cases"] if c["source_id"] in ("k2", "k3")]
    assert gold["dropped"]["compiled_no_field"] == 1
    assert gold["dropped"]["quote_not_found"] >= 1


# ------------------------------------------------------------------- scoring


def test_a_hit_is_correct_only_on_the_right_document_and_page():
    row = bed.score_case(
        _case(),
        _result(
            _hit(doc="d2", start=3, end=3, chunk="w1"),  # same page, wrong document
            _hit(start=9, end=9, chunk="w2"),  # right document, wrong page
            _hit(start=2, end=4, chunk="c1"),  # a range covering the page
        ),
    )
    assert row["first_rank"] == 3 and row["correct_ranks"] == [3]


def test_recall_and_mrr_carry_their_denominators():
    rows = [
        bed.score_case(_case(id="a"), _result(_hit())),  # rank 1
        bed.score_case(
            _case(id="b"),
            _result(*[_hit(start=9, chunk=f"w{i}") for i in range(5)], _hit()),
        ),  # 6
        bed.score_case(_case(id="c"), _result(_hit(start=9, chunk="w"))),  # miss
    ]
    m = bed.metrics(rows)
    assert m["cases"] == 3
    assert m["recall@5"] == {"hit": 1, "of": 3, "value": pytest.approx(1 / 3)}
    assert m["recall@20"] == {"hit": 2, "of": 3, "value": pytest.approx(2 / 3)}
    assert m["mrr"]["of"] == 3 and m["mrr"]["value"] == pytest.approx((1 + 1 / 6) / 3)


def test_citation_precision_needs_the_quote_in_the_first_hit_not_just_the_page():
    on_page_no_quote = bed.score_case(
        _case(id="a"), _result(_hit(text="Other words on that page."))
    )
    quoted = bed.score_case(
        _case(id="b"), _result(_hit(text=ZEBRA.upper().replace(" ", "  ")))
    )
    assert (
        on_page_no_quote["first_rank"] == 1 and on_page_no_quote["top1_quote"] is False
    )
    assert quoted["top1_quote"] is True
    m = bed.metrics([on_page_no_quote, quoted])
    assert m["citation_precision"] == {"hit": 1, "of": 2, "value": 0.5}


def test_citation_precision_leaves_out_what_it_cannot_judge_and_says_how_many():
    no_hits = bed.score_case(_case(id="a"), _result())
    split_quote = bed.score_case(_case(id="b", quote_in_chunk=False), _result(_hit()))
    assert no_hits["top1_quote"] is None and split_quote["top1_quote"] is None
    m = bed.metrics(
        [no_hits, split_quote, bed.score_case(_case(id="c"), _result(_hit()))]
    )
    assert m["citation_precision"] == {"hit": 1, "of": 1, "value": 1.0}
    assert m["cases"] == 3


def test_page_precision_is_pooled_over_the_hits_returned():
    row = bed.score_case(_case(), _result(_hit(), _hit(start=9, chunk="w")))
    assert bed.metrics([row])["page_precision@5"] == {"hit": 1, "of": 2, "value": 0.5}


def test_nothing_scored_is_none_never_zero():
    m = bed.metrics([])
    assert m["cases"] == 0
    for key in (
        "recall@5",
        "recall@20",
        "mrr",
        "citation_precision",
        "page_precision@5",
    ):
        assert m[key]["value"] is None and m[key]["of"] == 0


def test_a_miss_says_where_the_target_went():
    filtered = bed.score_case(
        _case(),
        _result(
            _hit(start=9, chunk="w"),
            excluded=[{"chunk_id": "c1", "reason": "document_cap"}],
        ),
    )
    assert filtered["miss_cause"] == "filtered:document_cap"
    beyond = bed.score_case(_case(), _result(_hit(start=9, chunk="w"), total=50))
    assert beyond["miss_cause"] == "possibly_beyond_limit"
    never = bed.score_case(_case(), _result(_hit(start=9, chunk="w")))
    assert never["miss_cause"] == "never_a_candidate"
    assert bed.score_case(_case(), _result(_hit()))["miss_cause"] is None


def test_summary_breaks_down_by_each_label():
    rows = [
        bed.score_case(_case(id="a"), _result(_hit())),
        bed.score_case(
            _case(id="b", family="table_cell", chunk_kind="table"), _result()
        ),
    ]
    s = bed.summarise(rows)
    assert s["all"]["cases"] == 2
    assert s["by"]["family"]["table_cell"]["recall@5"]["value"] == 0.0
    assert s["by"]["chunk_kind"]["prose"]["recall@5"]["value"] == 1.0


def test_nothing_the_bed_reports_holds_document_text():
    case = _case(id="a", query=MOON, quote=MOON)
    gold = {"format": bed.GOLD_FORMAT, "cases": [case]}
    rows = [bed.score_case(case, _result(_hit(text=MOON, doc="d1")))]
    summary = bed.summarise(rows)
    written = json.dumps({"rows": rows, "summary": summary}) + "\n".join(
        bed.report_lines(summary)
    )
    for word in ("Moon", "valves", "a.pdf"):
        assert word not in written
    assert gold["cases"][0]["query"] == MOON  # the gold itself stays local, see below


def test_compare_reports_a_drop_only_on_the_same_gold():
    def run(sha, hit):
        return {
            "gold_sha256": sha,
            "summary": {
                "all": bed.metrics(
                    [
                        bed.score_case(
                            _case(),
                            _result(_hit() if hit else _hit(start=9, chunk="w")),
                        )
                    ]
                )
            },
        }

    same = bed.compare(run("s", True), run("s", False))
    assert same["comparable"] is True
    assert "recall@5" in same["drops"] and same["deltas"]["recall@5"]["delta"] == -1.0
    assert bed.compare(run("s", True), run("s", True))["drops"] == []
    other = bed.compare(run("s", True), run("t", False))
    assert other["comparable"] is False and other["drops"] == []


# ------------------------------------------------------------------ safeguards


def test_gold_and_results_may_not_be_written_inside_the_repository(tmp_path):
    with pytest.raises(bed.Refused):
        bed.assert_outside_repo(REPO / "gold" / "gold.json")
    with pytest.raises(bed.Refused):
        bed.assert_outside_repo(REPO / "backend" / "data" / "x.json")
    bed.assert_outside_repo(tmp_path / "gold.json")


def test_the_live_database_is_refused(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    with pytest.raises(bed.Refused):
        bed.assert_copy(live)
    with pytest.raises(bed.Refused):
        bed.assert_copy(tmp_path / "missing.sqlite")
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(b"")
    bed.assert_copy(copy)


def test_the_guard_refuses_any_address_off_this_machine():
    bed.offline_guard()
    try:
        with pytest.raises(bed.Refused):
            socket.socket().connect(("192.0.2.1", 80))
        assert (
            bed.is_loopback("127.0.0.1")
            and bed.is_loopback("localhost")
            and bed.is_loopback("::1")
        )
    finally:
        bed.offline_guard(remove=True)


# ------------------------------------------------------- the switch, default off


@pytest.mark.parametrize("value", ["", "off", None])
def test_the_embedder_setting_is_off_by_default(value, monkeypatch):
    if value is None:
        monkeypatch.delenv(bed.SETTING, raising=False)
    else:
        monkeypatch.setenv(bed.SETTING, value)
    assert bed.embedder_setting() is None


def test_a_setting_that_names_no_known_embedder_is_refused(monkeypatch):
    monkeypatch.setenv(bed.SETTING, "somewhere:else")
    with pytest.raises(bed.Refused):
        bed.embedder_setting()
    monkeypatch.setenv(bed.SETTING, "ollama:toy-embed")
    assert bed.embedder_setting() == ("ollama", "toy-embed")
    monkeypatch.setenv(bed.SETTING, "stored")
    assert bed.embedder_setting() == ("stored", None)


def test_with_the_setting_off_embed_and_candidate_scoring_refuse(monkeypatch, tmp_path):
    monkeypatch.delenv(bed.SETTING, raising=False)
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(b"")
    assert bed.main(["embed", "--db", str(copy), "--out", str(tmp_path / "v")]) == 2
    assert (
        bed.main(
            [
                "score",
                "--db",
                str(copy),
                "--gold",
                str(tmp_path / "g.json"),
                "--out",
                str(tmp_path / "o.json"),
                "--candidate",
                str(tmp_path / "v"),
            ]
        )
        == 2
    )


def test_scoring_without_a_candidate_leaves_the_pipeline_exactly_as_it_was(tmp_path):
    original_dense = bed.search_mod.dense_search
    original_keyword = bed.search_mod._keyword_candidates
    seen = {}

    def fake_search(question, **kwargs):
        seen.update(kwargs)
        assert bed.search_mod.dense_search is original_dense
        assert bed.search_mod._keyword_candidates is original_keyword
        return _result(_hit())

    rows = bed.run_cases(
        [_case()],
        search=fake_search,
        mode="full",
        allowed=frozenset({"d1"}),
        dense_chunks=None,
    )
    assert rows[0]["first_rank"] == 1
    assert (
        seen["rerank"] is True and seen["dense"] is True and seen["limit"] == bed.LIMIT
    )
    assert bed.search_mod.dense_search is original_dense


def test_the_keyword_side_is_removed_only_during_the_dense_mode_and_restored():
    original = bed.search_mod._keyword_candidates

    def fake_search(question, **kwargs):
        assert bed.search_mod._keyword_candidates("anything") == []
        return _result()

    bed.run_cases(
        [_case()],
        search=fake_search,
        mode="dense",
        allowed=frozenset({"d1"}),
        dense_chunks=None,
    )
    assert bed.search_mod._keyword_candidates is original


def test_the_candidate_replaces_the_dense_side_only_and_is_restored(
    tmp_path, monkeypatch
):
    original = bed.search_mod.dense_search
    monkeypatch.setattr(
        bed.states, "searchable_scope", lambda allowed: frozenset(allowed)
    )
    store = bed.CandidateStore(
        vectors=np.array([[1, 0], [0, 1], [0.6, 0.8]], dtype=np.float32),
        chunks=[
            {"chunk_id": "a", "document_id": "d1"},
            {"chunk_id": "b", "document_id": "d2"},
            {"chunk_id": "c", "document_id": "d3"},
        ],
        query_vector=lambda q: np.array([1, 0], dtype=np.float32),
    )
    assert [
        r["chunk_id"]
        for r in store.dense(
            "q", limit=2, allowed_document_ids=frozenset({"d1", "d2", "d3"})
        )
    ] == ["a", "c"]
    # the access scope and the document filter only ever narrow, before top-k
    assert [
        r["chunk_id"]
        for r in store.dense("q", limit=2, allowed_document_ids=frozenset({"d2"}))
    ] == ["b"]
    assert [
        r["chunk_id"]
        for r in store.dense(
            "q", limit=2, document_id="d3", allowed_document_ids=frozenset({"d1", "d3"})
        )
    ] == ["c"]
    assert (
        store.dense(
            "q", limit=2, document_id="d3", allowed_document_ids=frozenset({"d1"})
        )
        == []
    )

    def fake_search(question, **kwargs):
        assert bed.search_mod.dense_search == store.dense
        return _result(_hit())

    bed.run_cases(
        [_case()],
        search=fake_search,
        mode="full",
        allowed=frozenset({"d1"}),
        candidate=store,
        dense_chunks=None,
    )
    assert bed.search_mod.dense_search is original


def test_a_model_not_on_this_machine_is_refused_and_nothing_is_pulled():
    calls = []

    class Transport:
        def get_json(self, path, *, timeout):
            calls.append(path)
            return {"models": [{"name": "other-model:latest"}]}

        def post_json(self, path, body, *, timeout):
            calls.append(path)
            raise AssertionError(
                "nothing may be posted for a model that is not installed"
            )

    with pytest.raises(bed.Refused) as err:
        bed.OllamaEmbedder("toy-embed", transport=Transport()).check_installed()
    assert "toy-embed" in str(err.value)
    assert calls == ["/api/tags"]


def test_the_local_embedder_normalises_and_uses_the_query_instruction():
    sent = []

    class Transport:
        def get_json(self, path, *, timeout):
            return {"models": [{"name": "qwen3-embedding:0.6b"}]}

        def post_json(self, path, body, *, timeout):
            sent.append((path, body))
            return {"embeddings": [[3.0, 4.0] for _ in body["input"]]}

    emb = bed.OllamaEmbedder("qwen3-embedding:0.6b", transport=Transport())
    emb.check_installed()
    assert np.allclose(emb.embed(["a passage"])[0], [0.6, 0.8])
    assert sent[0][1]["input"] == ["a passage"]
    emb.query_vector("how long")
    assert sent[1][0] == "/api/embed"
    assert sent[1][1]["input"][0].startswith("Instruct: ")
    assert sent[1][1]["input"][0].endswith("Query: how long")
