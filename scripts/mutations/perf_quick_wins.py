"""Mutations for the performance quick wins (perf audit 2026-09-27), M1330-M1349.

ONE FILE FOR ONE CHANGE, NOT ONE PER MUTATED MODULE. The work touched db.py,
deliverables.py, review.py, comparison.py, acronyms.py, main.py, warmup.py and
model_transport.py, and several of those files' registry modules are being
edited by other branches at the same time; keeping these entries together
keeps the merge to one new file. Every entry targets
`tests/test_perf_quick_wins.py`.

Four further tests in that file were proven by hand-run mutations that have
no id here because the assigned range was used up (embedder batch/threads/
arena defaults and the CI benchmark step) - see the branch's report.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_perf_quick_wins.py"

MUTATIONS: tuple[Mutation, ...] = (
    # ---------------------------------------------------------- schema memo
    Mutation(
        id="M1330", phase=1330,
        description="never skip an ensure_schema: every call re-runs ~150 "
                    "schema statements, per finding and per request",
        path=APP / "db.py",
        anchor="        if _schema_memo.get(key) == _schema_version(conn):\n            return None",
        replacement="        if False:\n            return None",
        target=_T, keyword="one_statement",
    ),
    Mutation(
        id="M1331", phase=1330,
        description="memoise on 'ran once' instead of the schema version, so a "
                    "dropped table or index is never recreated",
        path=APP / "db.py",
        anchor="        key = (name, str(settings.db_path))\n"
               "        if _schema_memo.get(key) == _schema_version(conn):",
        replacement="        key = (name, str(settings.db_path))\n"
                    "        if key in _schema_memo:",
        target=_T, keyword="dropped_table",
    ),
    Mutation(
        id="M1332", phase=1330,
        description="memoise the deliverables owner sync with the DDL, so a new "
                    "item's owner never becomes a stakeholder",
        path=APP / "deliverables.py",
        anchor="    _ensure_tables()\n    with connect() as conn:",
        replacement="    _ensure_tables()\n    return\n    with connect() as conn:",
        target=_T, keyword="owner_still_becomes",
    ),
    Mutation(
        id="M1333", phase=1330,
        description="never set PRAGMA synchronous: back to FULL, one fsync per commit",
        path=APP / "db.py",
        anchor='        conn.execute(f"PRAGMA synchronous = {sqlite_synchronous()}")\n',
        replacement="        sqlite_synchronous()\n",
        target=_T, keyword="synchronous_normal_by_default or synchronous_full",
    ),
    Mutation(
        id="M1334", phase=1330,
        description="interpolate any SQLITE_SYNCHRONOUS value into the PRAGMA",
        path=APP / "db.py",
        anchor="    if mode not in SYNCHRONOUS_MODES:",
        replacement="    if False:",
        target=_T, keyword="unknown_synchronous",
    ),
    Mutation(
        id="M1335", phase=1330,
        description="drop the (review_run_id, requirement_id) index: the "
                    "duplicate gate scans every earlier finding of the run",
        path=APP / "review.py",
        anchor='        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_run_requirement "\n'
               '                     "ON review_findings(review_run_id, requirement_id)")',
        replacement="        pass",
        target=_T, keyword="own_index",
    ),
    # --------------------------------------------------- findings persistence
    Mutation(
        id="M1336", phase=1330,
        description="commit every finding on its own (one fsync each)",
        path=APP / "comparison.py",
        anchor='            "approval_status": "pending"}, None, row["created_at"])\n',
        replacement='            "approval_status": "pending"}, None, row["created_at"])\n'
                    "        conn.commit()\n",
        target=_T, keyword="one_commit",
    ),
    Mutation(
        id="M1337", phase=1330,
        description="delete the run's findings BEFORE computing the new ones, so "
                    "a re-run that fails half way leaves the run empty",
        path=APP / "comparison.py",
        anchor="    # A RE-RUN REPLACES THIS RUN'S UNCONFIRMED FINDINGS - in the same\n",
        replacement=(
            "    if replace:\n"
            "        with connect() as _early:\n"
            '            _early.execute("DELETE FROM review_findings WHERE review_run_id = ?"\n'
            '                           " AND confirmed_by IS NULL", (review_run_id,))\n'
            "    # A RE-RUN REPLACES THIS RUN'S UNCONFIRMED FINDINGS - in the same\n"),
        target=_T, keyword="fails_half_way",
    ),
    Mutation(
        id="M1338", phase=1330,
        description="the duplicate gate ignores findings prepared but not yet "
                    "written, so one batch can hold two findings for one pair",
        path=APP / "comparison.py",
        anchor='            and (requirement.get("id"), fact_id) in pending):',
        replacement="            and False):",
        target=_T, keyword="not_yet_written",
    ),
    # -------------------------------------------------------------- acronyms
    Mutation(
        id="M1339", phase=1330,
        description="look back fewer words than the pattern allows, so long "
                    "expansions are cut or missed",
        path=APP / "acronyms.py",
        anchor="_MAX_WORDS = 7\n",
        replacement="_MAX_WORDS = 2\n",
        target=_T, keyword="matches_the_regex_exactly",
    ),
    Mutation(
        id="M1340", phase=1330,
        description="search from the previous match instead of the words before "
                    "the bracket - correct results, the scan the fix removed",
        path=APP / "acronyms.py",
        anchor="        m = _PARENTHETICAL.search(text, i, hit.end())",
        replacement="        m = _PARENTHETICAL.search(text, floor, hit.end())",
        target=_T, keyword="only_ever_sees",
    ),
    Mutation(
        id="M1341", phase=1330,
        description="no per-document cache: every new scope re-harvests every document",
        path=APP / "acronyms.py",
        anchor="        cached = _doc_cache.get(key)\n",
        replacement="        cached = None\n",
        target=_T, keyword="harvest_each_document_once",
    ),
    Mutation(
        id="M1342", phase=1330,
        description="drop the scope from the per-document signatures: documents "
                    "the caller cannot read supply expansions",
        path=APP / "acronyms.py",
        anchor='    where += " AND c.document_id IN (%s)" % ",".join("?" * len(allowed_document_ids))\n'
               "    params.extend(sorted(allowed_document_ids))\n",
        replacement="",
        target=_T, keyword="outside_the_scope",
        tags=("access",),
    ),
    Mutation(
        id="M1343", phase=1330,
        description="a constant document signature: a re-chunked or excluded "
                    "chunk keeps serving its old expansions",
        path=APP / "acronyms.py",
        anchor="    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}",
        replacement="    return {r[0]: () for r in rows}",
        target=_T, keyword="rechunked",
    ),
    Mutation(
        id="M1344", phase=1330,
        description="an unbounded per-document cache",
        path=APP / "acronyms.py",
        anchor="            _doc_cache.popitem(last=False)",
        replacement="            break",
        target=_T, keyword="bounded",
    ),
    # --------------------------------------------------------------- warm-up
    Mutation(
        id="M1345", phase=1330,
        description="the lifespan never starts the warm-up (the old dead call)",
        path=APP / "main.py",
        anchor="    warmup_mod.start()\n    yield\n",
        replacement="    yield\n",
        target=_T, keyword="really_harvests",
    ),
    Mutation(
        id="M1346", phase=1330,
        description="run the warm-up in the starting thread, blocking the server start",
        path=APP / "warmup.py",
        anchor="    thread.start()\n",
        replacement="    thread.run()\n",
        target=_T, keyword="never_blocks",
    ),
    Mutation(
        id="M1347", phase=1330,
        description="swallow a failing warm-up step without logging it",
        path=APP / "warmup.py",
        anchor='                log.exception("startup warm-up step %r failed", name)\n',
        replacement="                pass\n",
        target=_T, keyword="never_swallowed",
    ),
    Mutation(
        id="M1348", phase=1330,
        description="the warm-up runs a schema check - DDL on the live database "
                    "from a background thread",
        path=APP / "warmup.py",
        anchor="    acronyms.harvest(allowed_document_ids=every_document_id())",
        replacement="    from . import keyword\n    keyword.ensure_schema.uncached()\n"
                    "    acronyms.harvest(allowed_document_ids=every_document_id())",
        target=_T, keyword="never_writes",
    ),
    # ---------------------------------------------------------------- Ollama
    Mutation(
        id="M1349", phase=1330,
        description="send each caller's own runner options and keep_alive, so "
                    "features evict each other's Ollama runner",
        path=APP / "model_transport.py",
        anchor="    return with_runner_options(body) if _path_of(path) in RUNNER_PATHS else body",
        replacement="    return body",
        target=_T, keyword="same_runner or larger_context or streamed",
    ),
)
