"""Mutations of the context notes (CHUNKER_VERSION 8): the heading chain in
backend/app/chunker.py, and its readers in keyword.py, search.py, ingest.py
and embedder.py. Target: backend/tests/test_context_notes.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_context_notes.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1400", phase=1400,
             description="the chain keeps only the current heading: a numbered "
                         "clause forgets the titled heading above it",
             path=APP / "chunker.py",
             anchor="            chain[:] = [(n, text) for n, text in chain\n"
                    "                        if n and own != n and own.startswith(n + \".\")]",
             replacement="            chain.clear()",
             target=_T, keyword="knows_the_titled_heading_above_it",
             tags=("retrieval",)),
    Mutation(id="M1401", phase=1401,
             description="the keyword index ignores the chain and indexes the bare section",
             path=APP / "keyword.py",
             anchor='index_text(r["context"] or r["section"] or "")',
             replacement='index_text(r["section"] or "")',
             target=_T, keyword="keyword_index_finds_a_clause_by_the_heading_above_it",
             tags=("retrieval",)),
    Mutation(id="M1402", phase=1402,
             description="the embedder ignores the chain",
             path=APP / "ingest.py",
             anchor='    chain = row["context"] if "context" in row.keys() else None',
             replacement="    chain = None",
             target=_T, keyword="stored_vector_is_computed_from_the_chain",
             tags=("retrieval",)),
    Mutation(id="M1403", phase=1403,
             description="heading-v1 vectors go stale on deployment: dense search "
                         "is dark for every document until it is re-processed",
             path=APP / "embedder.py",
             anchor='LEGACY_PASSAGE_INPUT_VERSIONS: tuple[str, ...] = ("heading-v1",)',
             replacement="LEGACY_PASSAGE_INPUT_VERSIONS: tuple[str, ...] = ()",
             target=_T, keyword="stays_searchable_after_deployment",
             tags=("reliability",)),
    Mutation(id="M1404", phase=1404,
             description="a section two different chains set keeps the last chain "
                         "(a wrong context) instead of none",
             path=APP / "chunker.py",
             anchor="        if key in paths and paths[key] != path:",
             replacement="        if False:",
             target=_T, keyword="two_different_chains_set_gets_no_context",
             tags=("honesty",)),
    Mutation(id="M1405", phase=1405,
             description="the reranker reads the bare section, not the chain",
             path=APP / "search.py",
             anchor="        heading = self.context or self.section",
             replacement="        heading = self.section",
             target=_T, keyword="reranker_reads_the_chain_not_just_the_number",
             tags=("retrieval",)),
    Mutation(id="M1406", phase=1406,
             description="a heading keeps every earlier heading as its parent, not "
                         "only those it is numbered under: 4.4 filed under 8",
             path=APP / "chunker.py",
             anchor="                        if n and own != n and own.startswith(n + \".\")]",
             replacement="                        if n and own != n]",
             target=_T, keyword="never_filed_under_a_heading_it_is_not_numbered_under "
                                "or same_depth_replaces",
             tags=("honesty",)),
)
