"""Mutations for the ranking / answer-context fixes (retrieval audit R4, R5,
R6, R9, R11, R12, L1), ids M1285-M1299. They span several modules (search,
answer, chat, chat_stream, passages, reranker, the benchmark script) but prove
one test file, `tests/test_retrieval_ranking.py`, so they live together here
rather than being scattered across files other work edits concurrently.
None needs a staged model except M1290 (reranker session)."""

from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_retrieval_ranking.py"
_PHASE = 97

MUTATIONS: tuple[Mutation, ...] = (
    # ---- 1. one top-k ----------------------------------------------------
    Mutation(
        id="M1285", phase=_PHASE,
        description="R5: the answer searches max(limit, 3) again - a limit-3 chat "
                    "gate sees 3 hits while it claims the top-k",
        path=APP / "answer.py",
        anchor="        question, limit=max(limit, gate_candidates()), document_id=document_id,\n",
        replacement="        question, limit=max(limit, 3), document_id=document_id,\n",
        target=_T, keyword="shared_top_k_however_few or rank_five_from_a_limit_three",
    ),
    Mutation(
        id="M1286", phase=_PHASE,
        description="R5: the answer's default depth is a literal 3, not answer_top_k",
        path=APP / "answer.py",
        anchor="    if limit is None:\n        limit = gate_candidates()\n    token = _PREFERENCE.set(model)\n",
        replacement="    if limit is None:\n        limit = 3\n    token = _PREFERENCE.set(model)\n",
        target=_T, keyword="default_depth_is_the_configured_top_k",
    ),
    Mutation(
        id="M1287", phase=_PHASE,
        description="R5: the benchmark reports a literal recall@5 whatever k the chat uses",
        path=REPO / "scripts" / "eval_retrieval.py",
        anchor="CUTOFFS = tuple(sorted({max(1, min(settings.answer_top_k, LIMIT)), LIMIT}))\n",
        replacement="CUTOFFS = (5, 10)\n",
        target=_T, keyword="benchmark_reports_recall_at_the_configured_top_k",
    ),
    Mutation(
        id="M1288", phase=_PHASE,
        description="R5: Tier 2 sends hits[:n] and drops the passage that passed the gate",
        path=APP / "answer.py",
        anchor="            chosen = chosen[:-1] + [lead]\n",
        replacement="            pass\n",
        target=_T, keyword="passage_that_passed_the_gate",
    ),
    # ---- 2. identifiers on the rerank scale -------------------------------
    Mutation(
        id="M1289", phase=_PHASE,
        description="R6: the identifier boost is numerically dead on the rerank scale again",
        path=APP / "search.py",
        anchor="            IDENTIFIER_RERANK_SHARE * width * c.identifier_share\n",
        replacement="            0.0 * width * c.identifier_share\n",
        target=_T, keyword="wins_a_near_tie or identifier_match_first_in_a_near_tie",
        tags=("honesty",),
    ),
    Mutation(
        id="M1291", phase=_PHASE,
        description="R6: no guarantee that an exact identifier match reaches the final top k",
        path=APP / "search.py",
        anchor="    if k < 1 or len(candidates) <= k:\n        return None\n",
        replacement="    if True:\n        return None\n",
        target=_T, keyword="kept_in_the_final_top_k",
    ),
    Mutation(
        id="M1292", phase=_PHASE,
        description="R4: a carried (soft) identifier is treated as one the reader typed",
        path=APP / "search.py",
        anchor="    required = [i.lower() for i in find_identifiers(question) if i.lower() not in soft]\n",
        replacement="    required = [i.lower() for i in find_identifiers(question)]\n",
        target=_T, keyword="carried_identifier_is_not_guaranteed",
    ),
    # ---- 4. soft carried identifiers --------------------------------------
    Mutation(
        id="M1293", phase=_PHASE,
        description="R4: the keyword side requires carried identifiers (AND) again",
        path=APP / "search.py",
        anchor="    if not soft:\n        return strict\n",
        replacement="    if True:\n        return strict\n",
        target=_T, keyword="cannot_exclude_a_passage_from_the_keyword_side",
    ),
    Mutation(
        id="M1294", phase=_PHASE,
        description="R4: the lexical gate is handed carried identifiers and can refuse on them",
        path=APP / "answer.py",
        anchor="    gate_question = (search_mod.without_terms(question, soft_identifiers)\n"
               "                     if soft_identifiers else question) or question\n",
        replacement="    gate_question = question\n",
        target=_T, keyword="never_reaches_the_lexical_gate",
    ),
    Mutation(
        id="M1295", phase=_PHASE,
        description="R4: the chat stops passing carried identifiers to retrieval as soft",
        path=APP / "chat.py",
        anchor='        soft_identifiers=tuple((understood or {}).get("soft_identifiers") or ()),\n',
        replacement="",
        target=_T, keyword="chat_passes_carried_identifiers",
    ),
    # ---- 3. overlap-free expansion ----------------------------------------
    Mutation(
        id="M1296", phase=_PHASE,
        description="R11: expansion joins neighbours with their overlap repeated",
        path=APP / "passages.py",
        anchor="    if len(previous) < MIN_OVERLAP_CHARS or len(following) < MIN_OVERLAP_CHARS:\n"
               "        return 0\n",
        replacement="    if True:\n        return 0\n",
        target=_T, keyword="overlap_once",
    ),
    # ---- 5. the local lane's figure check ---------------------------------
    Mutation(
        id="M1297", phase=_PHASE,
        description="R9: the local-lane answer shows a figure its cited passage lacks",
        path=APP / "answer.py",
        anchor="    numbers_removed: list[dict] = []\n    if not claude_lane():\n"
               "        text, numbers_removed = ground_numbers(text, passages)\n",
        replacement="    numbers_removed: list[dict] = []\n    if False:\n"
                    "        text, numbers_removed = ground_numbers(text, passages)\n",
        target=_T, keyword="local_answer_does_not_show_an_invented_figure",
        tags=("honesty",),
    ),
    Mutation(
        id="M1298", phase=_PHASE,
        description="R9: a streamed local sentence is shown before the figure check",
        path=APP / "chat_stream.py",
        anchor="            clean, _removed = answer_mod.ground_numbers(clean, self.passages or [])\n",
        replacement="",
        target=_T, keyword="streamed_local_sentence",
        tags=("honesty",),
    ),
    # ---- 6. per-provider packing ------------------------------------------
    Mutation(
        id="M1299", phase=_PHASE,
        description="R12: the Claude lane is packed like the local 4B model again",
        path=APP / "answer.py",
        anchor='    if claude_lane():\n        return {"lane": "claude",',
        replacement='    if False:\n        return {"lane": "claude",',
        target=_T, keyword="packed_by_its_own_budget",
    ),
    # ---- 7. reranker threads ----------------------------------------------
    Mutation(
        id="M1290", phase=_PHASE,
        description="L1: the reranker session is hard-set to num_thread (12) again",
        path=APP / "reranker.py",
        anchor="            opts.intra_op_num_threads = thread_count()\n",
        replacement="            opts.intra_op_num_threads = settings.num_thread\n",
        target=_T, keyword="session_is_created_with_the_derived_thread_count",
    ),
    # ---- follow-up: rounding tolerance in the local-lane figure check ------
    Mutation(
        id="M1360", phase=_PHASE,
        description="R9 follow-up: an ordinary rounding (17.2 for 17.24) is treated as "
                    "an unsupported figure and its sentence is wrongly stripped",
        path=APP / "answer.py",
        anchor="                unsupported = {v for v in claimed - spans if not _is_rounding_of(v, spans)}\n",
        replacement="                unsupported = claimed - spans\n",
        target=_T, keyword="a_rounded_figure_is_not_treated_as_unsupported",
    ),
)
