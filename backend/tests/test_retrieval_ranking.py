"""Ranking and answer-context fixes (retrieval audit R4, R5, R6, R9, R11, R12, L1).

One section per defect, each test named for the property it pins, so a
regression says WHICH one broke. Every test here is mutation-proven: the
entries M1285-M1299 and M1300 in scripts/mutations/ delete the feature and
this file must fail.

  1. ONE TOP-K. The chat searched with limit 3 while the gate claimed 5 and
     the benchmark reported recall@5.
  2. IDENTIFIERS ON THE RERANK SCALE. The identifier boost was <= 0.016 added
     to a -11..+10 field, so it never moved anything.
  3. OVERLAP-FREE EXPANSION. Joining neighbours repeated the chunk overlap.
  4. SOFT CARRIED IDENTIFIERS. A follow-up made identifiers from up to three
     turns back mandatory.
  5. LOCAL-LANE FIGURE CHECK. Only citation numbers were checked.
  6. PER-PROVIDER PACKING. Claude was packed like the 4B local model.
  7. RERANKER THREADS. Hard-set to 12 whatever the machine.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app import answer as answer_mod
from app import chat as chat_mod
from app import chat_stream, db, keyword, lexical, passages, reranker, search
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
SCOPE = frozenset({"d1"})


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


# ----------------------------------------------------------------- helpers


def _hit(i: int, text: str, *, section: str | None = None, rerank: float = 1.0) -> dict:
    return {
        "chunk_id": f"c{i}", "document_id": "d1", "filename": "spec.pdf",
        "section": section or f"{i}.1 Clause {i}", "page_start": i + 1, "page_end": i + 1,
        "text": text, "score": rerank, "rerank_score": rerank, "rrf": 0.02,
        "identifier_hits": [], "separation": None, "heading_declares": False,
        "text_source": "extracted",
    }


def _fake_search(monkeypatch, hits: list[dict], seen: dict | None = None):
    def fake(question, limit=10, candidates=None, document_id=None, rerank=True,
             dense=True, *, allowed_document_ids, progress_id=None, soft_identifiers=()):
        if seen is not None:
            seen.update(question=question, limit=limit, soft=tuple(soft_identifiers))
        return {"query": question, "mode": "hybrid", "reranked": True,
                "keyword_candidates": len(hits), "dense_candidates": 0,
                "total": len(hits), "seconds": 0.0, "timings": {},
                "shortlist_excluded": [], "document_census": {},
                "hits": [dict(h) for h in hits[:limit]]}
    monkeypatch.setattr(answer_mod.search_mod, "search", fake)


def _lexical_passes_on(monkeypatch, marker: str, seen_questions: list | None = None):
    """The lexical gate, faked: a passage passes when it carries `marker`."""
    def assess(question, text, document_id=None, *, allowed_document_ids):
        if seen_questions is not None:
            seen_questions.append(question)
        ok = marker in text
        return {"ok": ok, "reason": None if ok else "not covered",
                "coverage": 1.0 if ok else 0.0, "terms": [], "covered": [],
                "absent_from_corpus": []}
    monkeypatch.setattr(lexical, "assess", assess)
    monkeypatch.setattr(lexical, "distinguishing_uncovered_terms",
                        lambda *a, **k: [])
    monkeypatch.setattr(answer_mod, "_coverage", lambda *a, **k: None)


def _local_lane(monkeypatch):
    monkeypatch.setattr(answer_mod, "claude_lane", lambda: False)


FIVE = [
    "Vibration is monitored on rotating equipment.",
    "Pumps are installed on a common baseplate.",
    "Bearings are lubricated with mineral oil.",
    "Seal flush plans are listed in the annex.",
    "ANSWERHERE the vibration limit is 3.0 mm/s RMS at the bearing housing.",
]


# ====================================================== 1. one top-k (R5)


def test_the_answer_searches_at_least_the_shared_top_k_however_few_it_shows(monkeypatch):
    """`max(limit, 3)` meant a limit-3 chat search returned 3 hits and the gate,
    documented as examining 5, examined 3."""
    seen: dict = {}
    _fake_search(monkeypatch, [_hit(i, t) for i, t in enumerate(FIVE)], seen)
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    answer_mod.answer("what is the vibration limit", limit=3, allowed_document_ids=SCOPE)
    assert seen["limit"] >= settings.answer_top_k == 5


def test_the_gate_reaches_the_answer_at_rank_five_from_a_limit_three_chat(monkeypatch):
    """The documented case: the only passage that answers sits at rank 5. At
    limit 3 it used to be refused because the gate never saw it."""
    _fake_search(monkeypatch, [_hit(i, t) for i, t in enumerate(FIVE)])
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    result = answer_mod.answer("what is the vibration limit", limit=3,
                               allowed_document_ids=SCOPE)
    assert result["answer_type"] == "extract"
    assert result["passage"]["chunk_id"] == "c4"


def test_the_default_depth_is_the_configured_top_k(monkeypatch):
    """No caller-supplied limit: the answer considers exactly answer_top_k
    passages - the lead plus the rest as supporting evidence."""
    _fake_search(monkeypatch, [_hit(i, "ANSWERHERE " + t) for i, t in enumerate(FIVE * 2)])
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    monkeypatch.setattr(settings, "answer_top_k", 4)
    result = answer_mod.answer("what is the vibration limit", allowed_document_ids=SCOPE)
    shown = [result["passage"], *result["supporting"]]
    assert len(shown) == 4


def test_the_chat_and_the_api_default_to_the_shared_top_k():
    import inspect

    from app import schemas
    assert inspect.signature(chat_mod.ask).parameters["limit"].default is None
    assert schemas.AskRequest(question="x").limit is None


def test_the_benchmark_reports_recall_at_the_configured_top_k(monkeypatch):
    """The benchmark's k and the chat's k are one setting. Loaded with k=4, the
    tripwire must report recall@4 - a literal 5 would not notice."""
    monkeypatch.setattr(settings, "answer_top_k", 4)
    spec = importlib.util.spec_from_file_location(
        "eval_retrieval_k4", REPO / "scripts" / "eval_retrieval.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    assert 4 in ev.CUTOFFS
    m = ev.metrics([{"first_correct_rank": 4, "correct_ranks": [4], "latency_s": 0.1,
                     "top_rerank_score": None}])
    assert m["recall@4"] == 1.0


def test_tier_two_always_shows_the_model_the_passage_that_passed_the_gate(monkeypatch):
    """The gate passed at rank 5 but the prompt carried hits[:3]: the model was
    never shown the passage that made the question answerable."""
    _fake_search(monkeypatch, [_hit(i, t) for i, t in enumerate(FIVE)])
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    _local_lane(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: (
        prompts.append(prompt) or {"response": "The limit is 3.0 mm/s [S3]."}))
    answer_mod.answer("what is the vibration limit", tier="generated", limit=3,
                      allowed_document_ids=SCOPE)
    assert "ANSWERHERE" in prompts[0]
    assert prompts[0].count("[S") == 3  # still the local lane's three sources


# ================================== 2. identifiers on the rerank scale (R6)


def _cand(cid: str, text: str, rerank: float, section: str | None = None) -> search.Candidate:
    return search.Candidate(chunk_id=cid, document_id="d1", filename="f", section=section,
                            page_start=1, page_end=1, text=text, rrf=0.01,
                            rerank_score=rerank)


def _field(named_score: float, plain_score: float) -> list[search.Candidate]:
    """Two contenders plus a realistic tail, so the field has a spread."""
    return [
        _cand("plain", "Vibration should generally be kept low on rotating pumps.", plain_score),
        _cand("named", "Vibration limits per API 610 shall not exceed 3.0 mm/s.", named_score),
        *[_cand(f"t{i}", f"Unrelated clause about painting number {i}.", -8.0 - i)
          for i in range(5)],
    ]


def test_an_identifier_match_wins_a_near_tie_on_the_rerank_scale():
    """The case the old comment claimed and the old arithmetic could not do:
    a passage naming API 610 sits 0.1 below one that does not."""
    pool = _field(named_score=4.9, plain_score=5.0)
    search.apply_identifier_boost("what does API 610 say about vibration", pool)
    search.apply_identifier_rerank_boost(pool)
    named = next(c for c in pool if c.chunk_id == "named")
    plain = next(c for c in pool if c.chunk_id == "plain")
    assert named.score > plain.score
    # it reorders; it never makes a passage look more credible than it scored
    assert named.rerank_score == 4.9


def test_an_identifier_match_does_not_override_a_decisive_preference():
    """Within the noise band only - a categorical rule overriding a decisive
    score would be the same mistake in the other direction."""
    pool = _field(named_score=-2.0, plain_score=6.0)
    search.apply_identifier_boost("what does API 610 say about vibration", pool)
    search.apply_identifier_rerank_boost(pool)
    named = next(c for c in pool if c.chunk_id == "named")
    plain = next(c for c in pool if c.chunk_id == "plain")
    assert plain.score > named.score


#: Distinct vocabulary per filler, so near-duplicate removal (0.85 token
#: overlap) keeps every one of them in the field.
_WORDS = ("lettering", "handrail", "grating", "ladder", "cable", "tray", "lighting",
          "earthing", "insulation", "cladding", "scaffold", "signage", "drainage",
          "hatch", "davit", "winch", "crane", "hoist", "fender", "bollard")


def _filler(i: int) -> str:
    a, b, c = _WORDS[(3 * i) % 20], _WORDS[(3 * i + 1) % 20], _WORDS[(3 * i + 2) % 20]
    return f"Clause on {a} {b} and {c} arrangement {i}."


def _pipeline(monkeypatch, texts_scores: list[tuple[str, float]]):
    """search() end to end over a fake index: keyword side, hydration and the
    cross-encoder faked, every ranking rule real."""
    rows = {f"c{i}": {"id": f"c{i}", "document_id": "d1", "filename": "f",
                      "section": f"{i}.1", "page_start": i, "page_end": i, "text": t,
                      "retrievable": 1, "text_source": "extracted", "ocr_min_conf": None,
                      "ocr_alphabet_violations": 0, "ocr_alphabet_sample": None}
            for i, (t, _) in enumerate(texts_scores)}
    monkeypatch.setattr(search.keyword, "search", lambda q, limit=30, document_id=None, *,
                        allowed_document_ids, corrections=None:
                        [{"chunk_id": cid, "bm25": -1.0} for cid in rows])
    monkeypatch.setattr(search, "_hydrate", lambda ids: {i: rows[i] for i in ids})
    scored = {f"c{i}": s for i, (_, s) in enumerate(texts_scores)}
    monkeypatch.setattr(reranker, "rerank", lambda q, pairs, batch=None:
                        [(cid, scored[cid]) for cid, _ in pairs])


def test_search_ranks_the_identifier_match_first_in_a_near_tie(monkeypatch):
    fillers = [(_filler(i), -8.0 - i) for i in range(6)]
    _pipeline(monkeypatch, [("Vibration should be kept low on rotating pumps.", 5.0),
                            ("Vibration limits per API 610 are 3.0 mm/s.", 4.9), *fillers])
    result = search.search("what does API 610 say about vibration", limit=5,
                           dense=False, allowed_document_ids=SCOPE)
    assert result["hits"][0]["chunk_id"] == "c1"
    # the cross-encoder's own score is what the credibility floor reads
    assert result["hits"][0]["rerank_score"] == pytest.approx(4.9)


def test_an_exact_identifier_match_is_kept_in_the_final_top_k(monkeypatch):
    """Scored well below five passages that do not name the standard, the one
    that does is still inside what the caller receives."""
    others = [(_filler(i) + " Pump vibration.", 6.0 - i * 0.1) for i in range(6)]
    _pipeline(monkeypatch, [*others, ("Vibration limits per API 610 are 3.0 mm/s.", -3.0)])
    result = search.search("what does API 610 say about vibration", limit=5,
                           dense=False, allowed_document_ids=SCOPE)
    ids = [h["chunk_id"] for h in result["hits"]]
    assert "c6" in ids
    assert result["identifier_kept"]


def test_a_carried_identifier_is_not_guaranteed_a_slot():
    """Soft means soft: an identifier the reader did not type this turn gets
    the boost but not the guarantee."""
    c = _cand("x", "Vibration limits per API 610 are 3.0 mm/s.", 1.0)
    search.apply_identifier_boost("what is the tolerance there API 610", [c],
                                  soft_identifiers=["API 610"])
    assert not c.names_identifiers
    assert c.identifier_share > 0
    search.apply_identifier_boost("what does API 610 say", [c])
    assert c.names_identifiers


# ===================================================== 3. overlap-free (R11)


def _rows(texts: list[str]) -> list[dict]:
    return [{"id": f"r{i}", "ordinal": i, "page_start": 1, "page_end": 1,
             "section": "6.1", "parent_id": "p", "kind": "prose", "text": t,
             "text_source": "extracted", "ocr_min_conf": None,
             "ocr_alphabet_violations": 0, "ocr_alphabet_sample": None}
            for i, t in enumerate(texts)]


SHARED = "The coating shall be applied in three coats to 280 um total."


def test_expansion_writes_the_chunk_overlap_once(monkeypatch):
    """The chunker starts each chunk with the previous chunk's last sentences;
    joining them as stored showed the reader those sentences twice."""
    first = "Surface preparation shall be Sa 2.5 before priming. " + SHARED
    second = SHARED + " Holiday detection shall follow NACE SP0188."
    monkeypatch.setattr(passages, "_rows_for", lambda d: _rows([first, second]))
    out = passages.expand_passage("r1", "d1", budget=5000)
    assert out["text"].count(SHARED) == 1
    assert out["chunks_joined"] == 2
    start, end = out["match_span"]
    assert out["text"][start:end] == second  # the matched chunk is still exact


def test_the_budget_counts_the_overlap_once(monkeypatch):
    """A budget that just fits the deduplicated text must admit both chunks."""
    first = "Surface preparation shall be Sa 2.5 before priming. " + SHARED
    second = SHARED + " Holiday detection shall follow NACE SP0188."
    monkeypatch.setattr(passages, "_rows_for", lambda d: _rows([first, second]))
    deduped = len(first) + len(second) - len(SHARED)
    out = passages.expand_passage("r0", "d1", budget=deduped)
    assert out["chunks_joined"] == 2


def test_a_coincidental_short_repeat_is_not_treated_as_overlap():
    assert passages.boundary_overlap("the limit is 3.0", "3.0 mm/s applies") == 0
    assert passages.boundary_overlap("x" * 30 + " abc defghijklmnopqrstu",
                                     "abc defghijklmnopqrstuvw more") == 0  # ends mid-word


# ============================================ 4. soft carried identifiers (R4)


def test_only_carried_identifiers_are_soft():
    assert chat_mod.soft_identifiers(["API 610", "system 1", "tolerance", "5.3.2"]) == \
        ["API 610", "5.3.2"]


def test_a_carried_identifier_cannot_exclude_a_passage_from_the_keyword_side(monkeypatch):
    """keyword.search ANDs identifiers; a carried one must not."""
    corpus = {"a": "API 610 vibration tolerance 0.05 mm",
              "b": "shaft tolerance is 0.02 mm for all pumps"}

    def fake(question, limit=30, document_id=None, *, allowed_document_ids, corrections=None):
        need = [i.lower() for i in keyword.IDENTIFIER.findall(question)]
        return [{"chunk_id": k, "bm25": -1.0} for k, t in corpus.items()
                if all(n in t.lower() for n in need)]
    monkeypatch.setattr(search.keyword, "search", fake)
    hits = search._keyword_candidates("what is the tolerance API 610", 30, None, SCOPE, {},
                                      ("API 610",))
    assert [h["chunk_id"] for h in hits] == ["a", "b"]  # carried subject first, not only
    typed = search._keyword_candidates("what is the tolerance API 610", 30, None, SCOPE, {}, ())
    assert [h["chunk_id"] for h in typed] == ["a"]  # typed this turn: still required


def test_a_carried_identifier_never_reaches_the_lexical_gate(monkeypatch):
    """A carried identifier absent from the corpus must not produce "MR0175
    does not appear in the documents" for a question that never typed it."""
    asked: list[str] = []
    _fake_search(monkeypatch, [_hit(0, "ANSWERHERE tolerance is 0.02 mm")])
    _lexical_passes_on(monkeypatch, "ANSWERHERE", asked)
    answer_mod.answer("what is the tolerance MR0175", soft_identifiers=("MR0175",),
                      allowed_document_ids=SCOPE)
    assert asked and all("MR0175" not in q for q in asked[:1])


def test_the_chat_passes_carried_identifiers_to_retrieval_as_soft(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(chat_mod.answer_mod, "answer",
                        lambda q, **kw: seen.update(kw) or {"answer_type": "extract",
                                                           "passages": []})
    monkeypatch.setattr("app.answerability.assess",
                        lambda *a, **k: {"verdict": "supported"})
    chat_mod._document_answer("conv", "what is the tolerance API 610",
                              {"soft_identifiers": ["API 610"]}, tier="extract",
                              document_id=None, selected_document=None, limit=None,
                              allowed_document_ids=SCOPE, progress_id=None, model=None,
                              history="")
    assert seen["soft_identifiers"] == ("API 610",)


# ==================================== 5. the local lane's figure check (R9)


PASSAGE = [{"text": "Vibration shall not exceed 3.0 mm/s RMS per clause 5.3.2 of API 610."}]


def test_a_rounded_figure_is_not_treated_as_unsupported():
    """"17.2 barg" for a passage stating "17.24 barg" is accurate, not
    invented - an ordinary rounding must not trigger the strip."""
    passage = [{"text": "Design pressure is 17.24 barg per clause 5.3.2."}]
    text = "The design pressure is 17.2 barg [S1]."
    clean, removed = answer_mod.ground_numbers(text, passage)
    assert clean == text
    assert removed == []


def test_a_genuinely_different_figure_is_still_removed():
    """A figure well outside rounding distance of anything in the passage is
    still stripped - the tolerance must not swallow a real miss."""
    passage = [{"text": "Design pressure is 17.24 barg per clause 5.3.2."}]
    text = "The design pressure is 20.0 barg [S1]."
    clean, removed = answer_mod.ground_numbers(text, passage)
    assert "20.0" not in clean
    assert removed and removed[0]["value"] == "20.0"


def test_a_figure_its_cited_passage_does_not_contain_is_removed():
    text = ("Yes.\n- The limit is 4.5 mm/s [S1].\n- The limit is 3.0 mm/s RMS [S1].\n"
            "1. See clause 5.3.2 of API 610 [S1].")
    clean, removed = answer_mod.ground_numbers(text, PASSAGE)
    assert "4.5" not in clean
    assert "3.0 mm/s RMS [S1]" in clean
    assert "clause 5.3.2" in clean  # a reference numeral is a name, not a figure
    assert "1. See" in clean        # a list marker is not a figure either
    assert [r["value"] for r in removed] == ["4.5"]


def test_the_local_answer_does_not_show_an_invented_figure(monkeypatch):
    _fake_search(monkeypatch, [_hit(0, "ANSWERHERE " + PASSAGE[0]["text"])])
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    _local_lane(monkeypatch)
    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: {
        "response": "Yes. The limit is 3.0 mm/s [S1]. It rises to 7.5 mm/s at start-up [S1]."})
    result = answer_mod.answer("what is the vibration limit", tier="generated",
                               allowed_document_ids=SCOPE)
    assert result["answer_type"] == "generated"
    assert "7.5" not in result["answer"] and "3.0 mm/s [S1]" in result["answer"]
    assert result["numbers_unsupported"] == ["7.5"]
    assert result["claims_removed"] == 1
    assert result["notices"]


def test_a_streamed_local_sentence_with_an_invented_figure_is_never_shown():
    turn = chat_stream.Turn(id="t", owner=None, conversation_id="c")
    turn.prepare(passages=PASSAGE, verify=False, general=False)
    turn.text("The limit is 9.9 mm/s [S1]. The limit is 3.0 mm/s [S1]. ")
    turn.flush()
    assert all("9.9" not in s for s in turn.shown)
    assert any("3.0" in s for s in turn.shown)


# ================================================ 6. per-provider packing (R12)


def test_claude_is_packed_by_its_own_budget_and_the_local_model_by_its_own(monkeypatch):
    hits = [_hit(i, "ANSWERHERE " + t) for i, t in enumerate(FIVE)]
    _fake_search(monkeypatch, hits)
    _lexical_passes_on(monkeypatch, "ANSWERHERE")
    prompts: list[str] = []
    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: (
        prompts.append(prompt) or {"response": "INSUFFICIENT EVIDENCE"}))

    monkeypatch.setattr(answer_mod, "claude_lane", lambda: False)
    answer_mod.answer("what is the vibration limit", tier="generated", allowed_document_ids=SCOPE)
    monkeypatch.setattr(answer_mod, "claude_lane", lambda: True)
    answer_mod.answer("what is the vibration limit", tier="generated", allowed_document_ids=SCOPE)

    local, claude = prompts
    assert local.count("[S") == settings.generated_context_passages == 3
    assert claude.count("[S") == settings.claude_context_passages == 5
    lane = answer_mod.context_budget_for_lane()
    assert lane["tokens"] == settings.claude_context_tokens
    assert lane["chars"] == settings.claude_context_chars


# ================================================= 7. reranker threads (L1)


def test_reranker_threads_default_to_the_usable_cpus_capped(monkeypatch):
    monkeypatch.setattr(settings, "rerank_threads", 0)
    monkeypatch.setattr(reranker, "_usable_cpus", lambda: 2)
    assert reranker.thread_count() == 2
    monkeypatch.setattr(reranker, "_usable_cpus", lambda: 64)
    assert reranker.thread_count() == reranker.MAX_DEFAULT_THREADS == 12
    monkeypatch.setattr(settings, "rerank_threads", 3)
    assert reranker.thread_count() == 3


def test_the_reranker_session_is_created_with_the_derived_thread_count(monkeypatch):
    if not reranker.available():
        pytest.skip("reranker model not staged")
    import onnxruntime as ort

    captured: dict = {}
    real = ort.InferenceSession

    def spy(path, sess_options=None, providers=None):
        captured["threads"] = sess_options.intra_op_num_threads
        return real(path, sess_options=sess_options, providers=providers)
    monkeypatch.setattr(ort, "InferenceSession", spy)
    monkeypatch.setattr(settings, "rerank_threads", 0)
    monkeypatch.setattr(reranker, "_usable_cpus", lambda: 2)
    reranker.reset()
    try:
        reranker._load()
    finally:
        reranker.reset()
    assert captured["threads"] == 2


def test_the_thread_count_does_not_change_a_single_score(monkeypatch):
    """Threads change scheduling, not arithmetic - measured bit-identical, so
    deriving the count per machine cannot move a ranking. (Length-sorted small
    batches were measured too and moved scores by up to 0.43 - int8 dynamic
    quantization is per batch - so the one-batch rerank is kept.)"""
    if not reranker.available():
        pytest.skip("reranker model not staged")
    pairs = [(f"p{i}", ("vibration limit API 610 pump bearing " * (i + 1)).strip())
             for i in range(4)]
    out = {}
    for threads in (1, 2):
        monkeypatch.setattr(settings, "rerank_threads", threads)
        reranker.reset()
        out[threads] = reranker.rerank("vibration limit for the pump", pairs)
    reranker.reset()
    assert out[1] == out[2]
