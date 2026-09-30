"""Mutations of the dense-search vector store (owner decision 2026-09-27:
sqlite-vec, with the exact numpy matrix as fallback) - `vector_store.py`,
`vectorcache.py`, the generation triggers in `db.py`, and the stale-vector
re-embed path in `ingest.py`. Each must turn `tests/test_vector_store.py`
red. Needs the staged models only for M1278 (a real re-embed)."""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_VS = APP / "vector_store.py"
_VC = APP / "vectorcache.py"
_T = "tests/test_vector_store.py"
PHASE = 97

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1265", phase=PHASE,
        description="numpy backend: scope mask removed - every row is in scope",
        path=_VC,
        anchor="    mask = allowed[m.doc_index]\n",
        replacement="    mask = np.ones(len(m.ids), dtype=bool)\n",
        target=_T, keyword="outside_the_scope", tags=("access",),
    ),
    Mutation(
        id="M1266", phase=PHASE,
        description="sqlite-vec narrow path: partition-key IN filter dropped - top-k taken before the scope",
        path=_VS,
        anchor=('            rows = idx.execute(\n'
                '                base + " AND document_id IN (SELECT value FROM json_each(?))",\n'
                '                (q, k, json.dumps(sorted(in_scope)))).fetchall()\n'),
        replacement="            rows = idx.execute(base, (q, k)).fetchall()\n",
        target=_T, keyword="scoped_recall or before_top_k", tags=("access",),
    ),
    Mutation(
        id="M1267", phase=PHASE,
        description="sqlite-vec wide path: k not widened by the out-of-scope rows - recall lost",
        path=_VS,
        anchor="            rows = idx.execute(base, (q, k + n_out)).fetchall()\n",
        replacement="            rows = idx.execute(base, (q, k)).fetchall()\n",
        target=_T, keyword="scoped_recall",
    ),
    Mutation(
        id="M1268", phase=PHASE,
        description="sqlite-vec: the scope check on the way out removed - the wide path leaks",
        path=_VS,
        anchor="    ranked = sorted((r for r in rows if r[1] in scope), key=lambda r: (r[2], r[0]))\n",
        replacement="    ranked = sorted((r for r in rows), key=lambda r: (r[2], r[0]))\n",
        target=_T, keyword="outside_the_scope", tags=("access",),
    ),
    Mutation(
        id="M1269", phase=PHASE,
        description="sqlite-vec index: model tag not checked - stale vectors are searched",
        path=_VS,
        anchor="                         if r[2] == tag and r[1] is not None\n",
        replacement="                         if r[1] is not None\n",
        target=_T, keyword="stale",
    ),
    Mutation(
        id="M1270", phase=PHASE,
        description="numpy backend: model tag not checked - stale vectors are searched",
        path=_VC,
        anchor="           WHERE c.retrievable = 1 AND v.model = ? AND length(v.vector) = ?\n",
        replacement="           WHERE c.retrievable = 1 AND (v.model = ? OR 1) AND length(v.vector) = ?\n",
        target=_T, keyword="stale",
    ),
    Mutation(
        id="M1271", phase=PHASE,
        description="backend chosen as sqlite-vec even when the extension failed to load",
        path=_VS,
        anchor='    if ok:\n        return "sqlite_vec", None\n',
        replacement='    if True:\n        return "sqlite_vec", None\n',
        target=_T, keyword="falls_back",
    ),
    Mutation(
        id="M1272", phase=PHASE,
        description="fallback to numpy is silent - never logged",
        path=_VS,
        anchor='    _say_once(why or "unknown")\n    return "numpy", why\n',
        replacement='    return "numpy", why\n',
        target=_T, keyword="falls_back",
    ),
    Mutation(
        id="M1273", phase=PHASE,
        description="sqlite-vec scores returned as distance, not cosine",
        path=_VS,
        anchor='    return [{"chunk_id": r[0], "cosine": 1.0 - float(r[2])} for r in ranked[:k]]\n',
        replacement='    return [{"chunk_id": r[0], "cosine": float(r[2])} for r in ranked[:k]]\n',
        target=_T, keyword="match_exact_numpy or scoped_recall",
    ),
    Mutation(
        id="M1274", phase=PHASE,
        description="generation triggers never created - writes do not reach the index",
        path=APP / "db.py",
        anchor="    for statement in VECTOR_GENERATION_SQL:\n",
        replacement="    for statement in VECTOR_GENERATION_SQL[:3]:\n",
        target=_T, keyword="every_relevant_write",
    ),
    Mutation(
        id="M1275", phase=PHASE,
        description="the index re-syncs on every query - the per-query scan is back",
        path=_VS,
        anchor="    if token is None or _synced.get(_memo_key()) != token:\n",
        replacement="    if True:\n",
        target=_T, keyword="scans_nothing",
    ),
    Mutation(
        id="M1276", phase=PHASE,
        description="no generation token - numpy matrix rebuilt from chunks on every query",
        path=_VC,
        anchor="    return None if row is None else int(row[0])\n",
        replacement="    return None\n",
        target=_T, keyword="scans_nothing",
    ),
    Mutation(
        id="M1277", phase=PHASE,
        description="the vec0 index put inside the live database",
        path=_VS,
        anchor='    return settings.data_dir / "vector_index.sqlite"\n',
        replacement="    return settings.db_path\n",
        target=_T, keyword="outside_the_live",
    ),
    Mutation(
        id="M1278", phase=PHASE,
        description="embed_pending ignores stale vectors - they are never re-embedded",
        path=APP / "ingest.py",
        # Re-anchored 2026-09-30: the predicate moved to ingest._NOT_CURRENT,
        # shared by embed_pending and its gate (M1463).
        anchor='                " AND (v.chunk_id IS NULL OR v.model IS NOT ?)")\n',
        replacement='                " AND (v.chunk_id IS NULL OR ? IS NULL)")\n',
        target=_T, keyword="re_embeds",
    ),
    Mutation(
        id="M1279", phase=PHASE,
        description="embedded_count counts stale vectors as embedded",
        path=APP / "ingest.py",
        anchor=('               WHERE v.document_id = ? AND v.model = ?""",\n'
                '            (doc_id, embedding_tag()),\n'
                '        ).fetchone()[0]\n'),
        replacement=('               WHERE v.document_id = ? AND (v.model = ? OR 1)""",\n'
                     '            (doc_id, embedding_tag()),\n'
                     '        ).fetchone()[0]\n'),
        target=_T, keyword="counts_only_current",
    ),
    Mutation(
        id="M1280", phase=PHASE,
        description="System Health: corpus-wide vector counts shown to every caller",
        path=APP / "metrics.py",
        anchor='        "vector_store": _vector_store_status(host),\n',
        replacement='        "vector_store": _vector_store_status(True),\n',
        target=_T, keyword="system_health",
    ),
    Mutation(
        id="M1281", phase=PHASE,
        description="document_id widens the scope instead of narrowing it",
        path=_VS,
        anchor="        scope = scope & {document_id}   # a filter only ever NARROWS (rule 5)\n",
        replacement="        scope = scope | {document_id}\n",
        target=_T, keyword="only_narrows", tags=("access",),
    ),
    Mutation(
        id="M1282", phase=PHASE,
        description="numpy backend: top-k not ordered by score",
        path=_VC,
        anchor="    top = top[np.lexsort((top, -scores[top]))]\n",
        replacement="",
        target=_T, keyword="match_exact_numpy",
    ),
    Mutation(
        id="M1283", phase=PHASE,
        description="System Health tile: a numpy fallback is shown without its reason",
        path=FRONTEND_SRC / "views" / "DashboardTechnicalDetails.tsx",
        anchor='                metrics.vector_store.fallback_reason ?? "exact search",\n',
        replacement='                "exact search",\n',
        target="src/views/DashboardTechnicalDetails.vector.test.tsx",
        runner="vitest",
    ),
    Mutation(
        id="M1284", phase=PHASE,
        description="index kept after a tag change - vectors of the old input format still searched",
        path=_VS,
        anchor='    return f"{index_path()}|{embedding_tag()}"\n',
        replacement="    return str(index_path())\n",
        target=_T, keyword="tag_change",
    ),
)
