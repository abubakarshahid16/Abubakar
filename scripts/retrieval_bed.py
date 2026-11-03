"""#1606: the measurement bed for search index v2. Baseline first, then changes.

Measures the search that exists today on a COPY of the database and says how
good it is: recall@5, recall@20, MRR and citation precision, each with its
denominator. `scripts/eval_retrieval.py` stays the 30-case tripwire over a sheet
that is not on every machine; this builds its own hundreds of cases and scores
each change against the same set.

THE GOLD SET (`build-gold`). Built from what the database already holds, because
no engineer's answer key exists yet (#747 is open) and `eval/bench/truth.json`
names wrong rows, not right passages. Owner's recipe: question = rule text,
target = standard page.

    rule_text              a stored rule's text, searched over the whole library
    table_cell             the same for a rule read from a table
    compiled_field         a compiled rule's field and "applies to" wording, not
                           the sentence: the nearest thing here to what an
                           engineer types
    compiled_field_scoped  the same, searching only the rule's own document

A CASE EXISTS ONLY WHEN CODE FINDS ITS QUOTE, in a retrievable chunk or at least
on the stated page. Every other location holding the same quote also counts as
correct: a clause repeated elsewhere is not a wrong answer. What was dropped is
counted by reason. These labels are machine-read and code-checked; NO ENGINEER
HAS CONFIRMED THEM, and `rule_text` queries are close to the text they find, so
they flatter the result. Read the families apart.

SCORING (`score`). A hit is correct when its document matches and its page range
overlaps an expected page.

    recall@k            cases with a correct hit in the first k / all cases
    MRR                 mean of 1/rank of the first correct hit; a miss adds 0
    citation precision  cases whose FIRST hit is correct AND holds the quote
                        (case and whitespace folded) / cases with a first hit
                        and a quote that fits one chunk. The first hit is the
                        passage an answer would quote; a right page without the
                        words is not a right citation.
    page precision@5    correct hits / hits returned, first five, pooled. One
                        target per case caps it well below 1: read it to compare
                        runs, never as a grade.

Search hands back only `limit` passages, after the shortlist, relevance floor
and document cap, so recall@20 on the reranked path can be cut by those rules
before rank 20. A miss says which: `filtered:<reason>`, `possibly_beyond_limit`,
`never_a_candidate`.

THE EMBEDDING COMPARISON (`embed`, `score --candidate`). Off unless the setting
RETRIEVAL_BED_EMBEDDER names an engine:

    stored                the vectors already in the copy, exported. A control:
                          it must score exactly what the plain run scores, which
                          proves the swap itself changes nothing.
    ollama:<model>        a model ALREADY on this machine, through
                          `model_transport` (loopback only). A missing model is
                          refused; nothing is ever pulled.

Candidate vectors live in their own folder beside the copy and replace only
`search.dense_search`, in this process, for this run. Nothing under `backend/app`
changes and no database table is written, so with the setting off the search is
byte-identical.

PRIVACY (CLAUDE.md rules 1 and 3). The gold set holds document text: it may not
be written inside this repository, and the code in git holds only invented
fixtures. Results and stdout hold ids and counts, never text or file names. Every
socket off this machine is refused for the run. No Claude, no network.

    python scripts/retrieval_bed.py build-gold --db COPY --out GOLD.json \\
        [--compiled-db OTHER_COPY ...] [--seed N] [--per-document N]
    python scripts/retrieval_bed.py score --db COPY --gold GOLD.json --out RUN.json \\
        [--mode full|no_rerank|keyword|dense] [--compare EARLIER.json]
    RETRIEVAL_BED_EMBEDDER=stored python scripts/retrieval_bed.py embed --db COPY --out DIR
    RETRIEVAL_BED_EMBEDDER=stored python scripts/retrieval_bed.py score ... --candidate DIR

Not a gate yet: `--compare` prints a drop and exits 0. See #1606.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import random
import socket
import sqlite3
import statistics
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import live_guard, model_transport, states  # noqa: E402
from app import search as search_mod  # noqa: E402
from app.config import settings  # noqa: E402

GOLD_FORMAT = "retrieval-gold/1"
RUN_FORMAT = "retrieval-run/1"
SETTING = "RETRIEVAL_BED_EMBEDDER"
LIMIT = 20
CUTOFFS = (5, 20)
MODES = {
    "full": {"rerank": True, "dense": True},
    "no_rerank": {"rerank": False, "dense": True},
    "keyword": {"rerank": False, "dense": False},
    "dense": {"rerank": False, "dense": True},
}
#: Shorter than this, a text is a phrase many clauses share, not a target.
MIN_TEXT_CHARS = 20
TABLE_TYPES = {"table_value", "table_row"}
#: What the model card asks for at query time; a passage takes no instruction.
QUERY_TEMPLATES = {
    "qwen3-embedding": "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery: {q}",
}
EMBED_BATCH = 32
BREAKDOWNS = ("family", "chunk_kind", "document_role", "verbatim", "target_has_vector")
COMPARED = ("recall@5", "recall@20", "mrr", "citation_precision")


class Refused(Exception):
    """A safeguard said no; the message names no document."""


def fold(text: str | None) -> str:
    """Case and every space gone: stored text wraps lines where a quote does not."""
    return "".join((text or "").split()).casefold()


# ------------------------------------------------------------------ safeguards


def assert_outside_repo(path: Path) -> None:
    """The gold set and the run files are built from client documents."""
    resolved = Path(path).expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise Refused(f"refusing to write inside the repository: {resolved}")


def assert_copy(path: Path) -> None:
    if live_guard.is_live_shaped(path):
        raise Refused("refusing the live database; make a copy and pass that")
    if not Path(path).exists():
        raise Refused(f"no database at {path}")


def is_loopback(host: str) -> bool:
    return host in ("localhost", "::1") or str(host).startswith("127.")


_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(address[0]):
        raise Refused(f"refusing a socket off this machine: {address[0]}")
    return _real_connect(self, address)


def offline_guard(remove: bool = False) -> None:
    socket.socket.connect = _real_connect if remove else _guarded_connect


def embedder_setting() -> tuple[str, str | None] | None:
    """The setting. Off (None) unless it names an engine."""
    value = (os.environ.get(SETTING) or "").strip()
    if value in ("", "off"):
        return None
    if value == "stored":
        return ("stored", None)
    if value.startswith("ollama:") and value[len("ollama:") :]:
        return ("ollama", value[len("ollama:") :])
    raise Refused(f"{SETTING} must be off, stored or ollama:<model>")


# ------------------------------------------------------------------- gold set


def corpus_id(conn: sqlite3.Connection) -> str:
    """Which chunks a run searched. Targets are document and page, so a run on a
    re-chunked library still scores against the same gold; this says it differs."""
    digest = hashlib.sha256()
    for row in conn.execute(
        "SELECT id, content_hash FROM chunks WHERE retrievable = 1 ORDER BY id"
    ):
        digest.update(f"{row['id']}:{row['content_hash']}\n".encode())
    return digest.hexdigest()


class _Library:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.chunks = {
            r["id"]: {
                "id": r["id"],
                "document_id": r["document_id"],
                "start": r["page_start"],
                "end": r["page_end"],
                "kind": r["kind"],
                "folded": fold(r["text"]),
            }
            for r in conn.execute(
                "SELECT id, document_id, page_start, page_end, kind, text "
                "FROM chunks WHERE retrievable = 1"
            )
        }
        self.roles = dict(
            conn.execute(
                "SELECT document_id, document_role FROM document_classification"
            ).fetchall()
        )
        self.conn = conn

    def holding(self, folded_quote: str) -> list[dict]:
        return [c for c in self.chunks.values() if folded_quote in c["folded"]]

    def on_page(self, document_id: str, page: int | None, folded_quote: str) -> bool:
        row = self.conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (document_id, page),
        ).fetchone()
        return bool(row) and folded_quote in fold(row["text"])


def _expected(document_id: str, page: int | None, holders: list[dict]) -> list[dict]:
    """The stated page, plus any other place the same quote stands."""
    pages: dict[str, set[int]] = collections.defaultdict(set)
    if page is not None:
        pages[document_id].add(page)
    for chunk in holders:
        span = range(chunk["start"], chunk["end"] + 1)
        if not (chunk["document_id"] == document_id and page in span):
            pages[chunk["document_id"]].update(span)
    return [{"document_id": d, "pages": sorted(pages[d])} for d in sorted(pages)]


def _new_case(
    lib: _Library,
    source_id,
    family,
    document_id,
    page,
    query,
    quote,
    kind_of_chunk,
    dropped: collections.Counter,
) -> dict | None:
    folded_quote, folded_query = fold(quote), fold(query)
    if len(folded_query) < MIN_TEXT_CHARS // 2 or len(folded_quote) < MIN_TEXT_CHARS:
        dropped["text_too_short"] += 1
        return None
    holders = lib.holding(folded_quote)
    if not holders and not lib.on_page(document_id, page, folded_quote):
        dropped["quote_not_found"] += 1
        return None
    return {
        "id": f"{family}:{source_id}",
        "source_id": source_id,
        "source_document": document_id,
        "family": family,
        "query": query,
        "quote": quote,
        "scope_document_id": None,
        "chunk_kind": kind_of_chunk,
        "document_role": lib.roles.get(document_id),
        "verbatim": folded_query in folded_quote,
        "quote_in_chunk": bool(holders),
        "target_chunks": sorted(c["id"] for c in holders),
        "expected": _expected(document_id, page, holders),
    }


def _rule_cases(lib: _Library, conn, rng, per_document: int, dropped) -> list[dict]:
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id, standard_document_id, page, requirement_text, source_text, "
            "requirement_type, chunk_id FROM standard_requirements "
            "WHERE superseded_at IS NULL ORDER BY id"
        )
    ]
    rng.shuffle(rows)
    taken: collections.Counter = collections.Counter()
    seen: set[str] = set()
    cases = []
    for row in rows:
        chunk = lib.chunks.get(row["chunk_id"])
        table = row["requirement_type"] in TABLE_TYPES or bool(
            chunk and chunk["kind"] == "table"
        )
        family = "table_cell" if table else "rule_text"
        key = (row["standard_document_id"], family)
        if taken[key] >= per_document:
            continue
        if chunk is None:
            dropped["chunk_not_retrievable"] += 1
            continue
        query = (row["requirement_text"] or "").strip()
        if fold(query) in seen:
            dropped["same_question_again"] += 1
            continue
        case = _new_case(
            lib,
            row["id"],
            family,
            row["standard_document_id"],
            row["page"],
            query,
            row["source_text"] or query,
            chunk["kind"],
            dropped,
        )
        if case:
            taken[key] += 1
            seen.add(fold(query))
            cases.append(case)
    return cases


def _compiled_cases(lib: _Library, rows: list[dict], dropped) -> list[dict]:
    cases = []
    seen: set[tuple] = set()
    for row in sorted(rows, key=lambda r: str(r["id"])):
        key = (row["standard_document_id"], fold(row["quote"]))
        if key in seen:
            continue
        seen.add(key)
        field = (row.get("field") or "").strip()
        if not field:
            dropped["compiled_no_field"] += 1
            continue
        query = " ".join(
            x.strip() for x in (field, row.get("applies_to") or "") if x.strip()
        )
        case = _new_case(
            lib,
            row["id"],
            "compiled_field",
            row["standard_document_id"],
            row["page"],
            query,
            row["quote"],
            None,
            dropped,
        )
        if not case:
            continue
        kinds = {lib.chunks[c]["kind"] for c in case["target_chunks"]}
        case["chunk_kind"] = "table" if "table" in kinds else "prose"
        cases.append(case)
        cases.append(
            {
                **case,
                "id": f"compiled_field_scoped:{row['id']}",
                "family": "compiled_field_scoped",
                "scope_document_id": row["standard_document_id"],
            }
        )
    return cases


def build_gold(
    conn: sqlite3.Connection, *, seed: int, per_document: int, compiled_rows: list[dict]
) -> dict:
    conn.row_factory = sqlite3.Row
    dropped: collections.Counter = collections.Counter()
    lib = _Library(conn)
    cases = _rule_cases(lib, conn, random.Random(seed), per_document, dropped)
    cases += _compiled_cases(lib, compiled_rows, dropped)
    return {
        "format": GOLD_FORMAT,
        "note": "Machine-read, code-checked, not confirmed by an engineer. Holds document text: never in git.",
        "seed": seed,
        "per_document": per_document,
        "corpus_id": corpus_id(conn),
        "counts": dict(collections.Counter(c["family"] for c in cases)),
        "dropped": dict(dropped),
        "cases": cases,
    }


def read_compiled_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        assert_copy(path)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows += [
            dict(r)
            for r in conn.execute(
                "SELECT id, standard_document_id, page, field, applies_to, condition_text, quote "
                "FROM compiled_rules WHERE quote IS NOT NULL"
            )
        ]
        conn.close()
    return rows


# -------------------------------------------------------------------- scoring


def _correct(hit: dict, expected: list[dict]) -> bool:
    start, end = hit.get("page_start"), hit.get("page_end")
    if start is None or end is None:
        return False
    return any(
        e["document_id"] == hit.get("document_id")
        and any(start <= p <= end for p in e["pages"])
        for e in expected
    )


def _miss_cause(case: dict, result: dict) -> str:
    targets = set(case.get("target_chunks") or [])
    reasons = sorted(
        {
            e.get("reason")
            for e in result.get("shortlist_excluded") or []
            if e.get("chunk_id") in targets
        }
    )
    if reasons:
        return "filtered:" + "+".join(str(r) for r in reasons)
    if (result.get("total") or 0) > len(result.get("hits") or []):
        return "possibly_beyond_limit"
    return "never_a_candidate"


def score_case(
    case: dict,
    result: dict,
    *,
    latency: float | None = None,
    has_vector: bool | None = None,
) -> dict:
    """One case's row. Ids and ranks only: the run file holds no document text."""
    hits = result.get("hits") or []
    correct = [
        i for i, hit in enumerate(hits, start=1) if _correct(hit, case["expected"])
    ]
    top1_quote = None
    if hits and case.get("quote_in_chunk"):
        top1_quote = _correct(hits[0], case["expected"]) and fold(
            case["quote"]
        ) in fold(hits[0].get("text"))
    return {
        "id": case["id"],
        "family": case["family"],
        "chunk_kind": case.get("chunk_kind"),
        "document_role": case.get("document_role"),
        "verbatim": case.get("verbatim"),
        "target_has_vector": has_vector,
        "first_rank": correct[0] if correct else None,
        "correct_ranks": correct,
        "hits_returned": len(hits),
        "correct_in_first_5": sum(1 for r in correct if r <= 5),
        "returned_in_first_5": min(len(hits), 5),
        "top1_quote": top1_quote,
        "miss_cause": None if correct else _miss_cause(case, result),
        "latency_s": None if latency is None else round(latency, 4),
    }


def _ratio(hit, of) -> dict:
    return {"hit": hit, "of": of, "value": (hit / of) if of else None}


def metrics(rows: list[dict]) -> dict:
    """Every number keeps its denominator; nothing scored is None, never 0."""
    n = len(rows)
    out: dict = {"cases": n}
    for k in CUTOFFS:
        out[f"recall@{k}"] = _ratio(
            sum(
                1 for r in rows if r["first_rank"] is not None and r["first_rank"] <= k
            ),
            n,
        )
    reciprocal = sum(1.0 / r["first_rank"] for r in rows if r["first_rank"] is not None)
    out["mrr"] = {"sum": reciprocal, "of": n, "value": (reciprocal / n) if n else None}
    judged = [r for r in rows if r["top1_quote"] is not None]
    out["citation_precision"] = _ratio(
        sum(1 for r in judged if r["top1_quote"]), len(judged)
    )
    out["page_precision@5"] = _ratio(
        sum(r["correct_in_first_5"] for r in rows),
        sum(r["returned_in_first_5"] for r in rows),
    )
    out["hits_returned_mean"] = (
        round(sum(r["hits_returned"] for r in rows) / n, 2) if n else None
    )
    out["miss_causes"] = dict(
        collections.Counter(r["miss_cause"] for r in rows if r["miss_cause"])
    )
    times = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    out["latency_p50_ms"] = round(statistics.median(times) * 1000, 1) if times else None
    return out


def summarise(rows: list[dict]) -> dict:
    by: dict = {}
    for label in BREAKDOWNS:
        groups: dict = collections.defaultdict(list)
        for row in rows:
            groups[str(row.get(label))].append(row)
        by[label] = {name: metrics(group) for name, group in sorted(groups.items())}
    return {"all": metrics(rows), "by": by}


def _cell(entry: dict) -> str:
    if entry["value"] is None:
        return f"-/{entry['of']}"
    if "hit" in entry:
        return f"{entry['value']:.3f} ({entry['hit']}/{entry['of']})"
    return f"{entry['value']:.3f} (/{entry['of']})"


def report_lines(summary: dict) -> list[str]:
    """What stdout gets. Labels and counts: `document_role` and family are ours."""
    lines = []

    def add(name: str, m: dict) -> None:
        lines.append(
            f"{name:<34} n={m['cases']:<5} "
            + "  ".join(
                f"{key}={_cell(m[key])}" for key in (*COMPARED, "page_precision@5")
            )
        )
        lines.append(
            f"{'':<34} hits returned mean={m['hits_returned_mean']}  "
            f"latency p50 ms={m['latency_p50_ms']}  misses={m['miss_causes']}"
        )

    add("ALL", summary["all"])
    for label, groups in summary["by"].items():
        for name, m in groups.items():
            add(f"{label}={name}", m)
    return lines


def compare(earlier: dict, current: dict) -> dict:
    """Against an earlier run of the SAME gold; a different set is incomparable,
    not a regression. Any real fall in a measured number is listed."""
    if earlier.get("gold_sha256") != current.get("gold_sha256"):
        return {
            "comparable": False,
            "why": "different gold set",
            "deltas": {},
            "drops": [],
        }
    deltas, drops = {}, []
    for key in COMPARED:
        before = earlier["summary"]["all"][key]["value"]
        now = current["summary"]["all"][key]["value"]
        if before is None or now is None:
            continue
        deltas[key] = {"before": before, "now": now, "delta": now - before}
        if now < before - 1e-9:
            drops.append(key)
    return {"comparable": True, "deltas": deltas, "drops": drops}


# ------------------------------------------------------- the candidate embedder


class OllamaEmbedder:
    """A model already on this machine, through the one loopback transport.
    Nothing here pulls: Ollama's embed call does not download, and a missing
    model is refused before anything is sent."""

    def __init__(self, model: str, transport=model_transport) -> None:
        self.model = model
        self.transport = transport

    def check_installed(self) -> None:
        tags = self.transport.get_json("/api/tags", timeout=10.0) or {}
        names = {m.get("name") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise Refused(
                f"embedding model {self.model} is not on this machine; nothing was downloaded"
            )

    def embed(self, texts: list[str]) -> np.ndarray:
        reply = self.transport.post_json(
            "/api/embed",
            {"model": self.model, "input": texts, "truncate": True},
            timeout=600.0,
        )
        vectors = np.asarray(reply["embeddings"], dtype=np.float32)
        return vectors / np.clip(
            np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None
        )

    def query_vector(self, question: str) -> np.ndarray:
        template = next(
            (t for name, t in QUERY_TEMPLATES.items() if name in self.model), "{q}"
        )
        return self.embed([template.replace("{q}", question)])[0]

    def unload(self) -> None:
        self.transport.post_json(
            "/api/embed",
            {"model": self.model, "input": [], "keep_alive": 0},
            timeout=60.0,
        )


class CandidateStore:
    """One matrix of candidate vectors, searched exactly. The access scope is
    applied before top-k, as `vector_store.search` does (CLAUDE.md rule 5)."""

    def __init__(
        self,
        vectors: np.ndarray,
        chunks: list[dict],
        query_vector: Callable[[str], np.ndarray],
    ) -> None:
        self.vectors = vectors
        self.chunks = chunks
        self.query_vector = query_vector
        self.document_ids = np.array([c["document_id"] for c in chunks])

    def dense(
        self,
        question: str,
        limit: int = 30,
        document_id: str | None = None,
        *,
        allowed_document_ids: frozenset[str],
    ) -> list[dict]:
        scope = states.searchable_scope(frozenset(allowed_document_ids))
        if document_id is not None:
            scope = scope & {document_id}
        if not scope or limit <= 0:
            return []
        in_scope = np.nonzero(np.isin(self.document_ids, list(scope)))[0]
        if not in_scope.size:
            return []
        scores = self.vectors[in_scope] @ self.query_vector(question)
        order = np.lexsort((in_scope, -scores))[:limit]
        return [
            {
                "chunk_id": self.chunks[in_scope[i]]["chunk_id"],
                "cosine": float(scores[i]),
            }
            for i in order
        ]


def _write_candidate(
    out: Path, vectors: np.ndarray, chunks: list[dict], embedder: str, corpus: str
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "vectors.npy", vectors.astype(np.float32))
    (out / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    (out / "meta.json").write_text(
        json.dumps(
            {
                "embedder": embedder,
                "vectors": len(chunks),
                "dim": int(vectors.shape[1]),
                "corpus_id": corpus,
                "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            },
            indent=1,
        ),
        encoding="utf-8",
    )


def _export_stored(conn: sqlite3.Connection) -> tuple[np.ndarray, list[dict]]:
    from app.embedder import EMBEDDING_DIM, searchable_tags

    marks = ",".join("?" * len(searchable_tags()))
    rows = conn.execute(
        "SELECT v.chunk_id, v.document_id, v.vector FROM chunk_vectors v "
        "JOIN chunks c ON c.id = v.chunk_id "
        f"WHERE c.retrievable = 1 AND v.model IN ({marks}) ORDER BY v.chunk_id",
        searchable_tags(),
    ).fetchall()
    matrix = np.frombuffer(
        b"".join(r["vector"] for r in rows), dtype=np.float32
    ).reshape(-1, EMBEDDING_DIM)
    return matrix, [
        {"chunk_id": r["chunk_id"], "document_id": r["document_id"]} for r in rows
    ]


def _embed_all(
    conn: sqlite3.Connection, embedder: OllamaEmbedder
) -> tuple[np.ndarray, list[dict]]:
    rows = conn.execute(
        "SELECT id, document_id, section, context, text FROM chunks WHERE retrievable = 1 ORDER BY id"
    ).fetchall()
    parts = []
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        # The same input ingestion embeds from: the heading chain, then the body.
        parts.append(
            embedder.embed(
                [
                    (
                        (r["context"] or r["section"] or "").strip() + "\n" + r["text"]
                    ).strip()
                    for r in batch
                ]
            )
        )
        if start % (EMBED_BATCH * 50) == 0:
            print(
                f"embedded {start + len(batch)} of {len(rows)} chunks",
                file=sys.stderr,
                flush=True,
            )
    return np.vstack(parts), [
        {"chunk_id": r["id"], "document_id": r["document_id"]} for r in rows
    ]


def load_candidate(
    folder: Path, engine: tuple[str, str | None]
) -> tuple[CandidateStore, dict, OllamaEmbedder | None]:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    named = engine[0] if engine[1] is None else f"{engine[0]}:{engine[1]}"
    if meta["embedder"] != named:
        raise Refused(
            f"candidate folder was built by {meta['embedder']}, the setting says {named}"
        )
    chunks = json.loads((folder / "chunks.json").read_text(encoding="utf-8"))
    vectors = np.load(folder / "vectors.npy", mmap_mode="r")
    if engine[0] == "stored":
        from app.embedder import Embedder, EmbedderConfig

        return (
            CandidateStore(
                vectors,
                chunks,
                lambda q: Embedder.instance(EmbedderConfig()).embed_queries([q])[0],
            ),
            meta,
            None,
        )
    embedder = OllamaEmbedder(engine[1])
    embedder.check_installed()
    return CandidateStore(vectors, chunks, embedder.query_vector), meta, embedder


# ------------------------------------------------------------------------ runs


@contextmanager
def _swapped(name: str, replacement):
    original = getattr(search_mod, name)
    setattr(search_mod, name, replacement)
    try:
        yield
    finally:
        setattr(search_mod, name, original)


@contextmanager
def _no_change():
    yield


def _no_keyword(*_args, **_kwargs) -> list[dict]:
    return []


def run_cases(
    cases: list[dict],
    *,
    search: Callable,
    mode: str,
    allowed: frozenset[str],
    dense_chunks: set[str] | None,
    candidate: CandidateStore | None = None,
) -> list[dict]:
    """Search each case once at LIMIT and score that one ranking. The pipeline
    is changed only for a candidate or the dense-only mode, and put back."""
    swap_dense = (
        _swapped("dense_search", candidate.dense) if candidate else _no_change()
    )
    drop_keyword = (
        _swapped("_keyword_candidates", _no_keyword)
        if mode == "dense"
        else _no_change()
    )
    rows = []
    with swap_dense, drop_keyword:
        for number, case in enumerate(cases, start=1):
            started = time.perf_counter()
            result = search(
                case["query"],
                limit=LIMIT,
                document_id=case.get("scope_document_id"),
                allowed_document_ids=allowed,
                **MODES[mode],
            )
            has_vector = (
                None
                if dense_chunks is None
                else any(c in dense_chunks for c in case.get("target_chunks") or [])
            )
            rows.append(
                score_case(
                    case,
                    result,
                    latency=time.perf_counter() - started,
                    has_vector=has_vector,
                )
            )
            if number % 100 == 0:
                print(f"{number} of {len(cases)} cases", file=sys.stderr, flush=True)
    return rows


def _open_copy(path: Path) -> sqlite3.Connection:
    """Point the whole app at the copy, before anything connects."""
    settings.db_path = Path(path).resolve()
    settings.data_dir = Path(path).resolve().parent
    from app.db import connect

    conn = connect()
    conn.row_factory = sqlite3.Row
    return conn


def _dense_chunks(conn: sqlite3.Connection, candidate: list[dict] | None) -> set[str]:
    if candidate is not None:
        return {c["chunk_id"] for c in candidate}
    from app.embedder import searchable_tags

    marks = ",".join("?" * len(searchable_tags()))
    return {
        r[0]
        for r in conn.execute(
            f"SELECT chunk_id FROM chunk_vectors WHERE model IN ({marks})",
            searchable_tags(),
        )
    }


def _corpus_block(conn: sqlite3.Connection, dense: set[str]) -> dict:
    retrievable = {
        r[0] for r in conn.execute("SELECT id FROM chunks WHERE retrievable = 1")
    }
    return {
        "retrievable_chunks": len(retrievable),
        "with_searchable_vector": len(retrievable & dense),
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "corpus_id": corpus_id(conn),
    }


def cmd_build_gold(args) -> int:
    out = Path(args.out).expanduser()
    assert_outside_repo(out)
    assert_copy(Path(args.db))
    compiled = read_compiled_rows([Path(p) for p in args.compiled_db or []])
    conn = sqlite3.connect(f"file:{Path(args.db).resolve()}?mode=ro", uri=True)
    gold = build_gold(
        conn, seed=args.seed, per_document=args.per_document, compiled_rows=compiled
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=0), encoding="utf-8")
    print(
        json.dumps({k: gold[k] for k in ("seed", "per_document", "counts", "dropped")})
    )
    print(
        f"cases {len(gold['cases'])}; sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}"
    )
    return 0


def cmd_embed(args) -> int:
    engine = embedder_setting()
    if engine is None:
        raise Refused(f"the embedding comparison is off; set {SETTING}")
    out = Path(args.out).expanduser()
    assert_outside_repo(out)
    assert_copy(Path(args.db))
    from app import heavy_lock

    conn = _open_copy(Path(args.db))
    if engine[0] == "stored":
        vectors, chunks = _export_stored(conn)
        _write_candidate(out, vectors, chunks, "stored", corpus_id(conn))
    else:
        embedder = OllamaEmbedder(engine[1])
        embedder.check_installed()
        with heavy_lock.held("ai_batch", owner="retrieval_bed embed"):
            try:
                vectors, chunks = _embed_all(conn, embedder)
            finally:
                embedder.unload()
        _write_candidate(out, vectors, chunks, f"ollama:{engine[1]}", corpus_id(conn))
    print(f"wrote {len(chunks)} vectors of {vectors.shape[1]} dimensions")
    return 0


def cmd_score(args) -> int:
    engine = embedder_setting()
    if args.candidate and engine is None:
        raise Refused(f"the embedding comparison is off; set {SETTING}")
    out = Path(args.out).expanduser()
    assert_outside_repo(out)
    assert_copy(Path(args.db))
    gold_path = Path(args.gold).expanduser()
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if gold.get("format") != GOLD_FORMAT:
        raise Refused("not a gold file this script wrote")
    conn = _open_copy(Path(args.db))
    from app.db import init_db

    init_db()
    candidate, meta, loaded = None, None, None
    if args.candidate:
        candidate, meta, loaded = load_candidate(
            Path(args.candidate).expanduser(), engine
        )
    dense = _dense_chunks(conn, candidate.chunks if candidate else None)
    cases = gold["cases"]
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    try:
        rows = run_cases(
            cases,
            search=search_mod.search,
            mode=args.mode,
            allowed=search_mod.every_document_id(),
            dense_chunks=dense,
            candidate=candidate,
        )
    finally:
        if loaded:
            loaded.unload()
    summary = summarise(rows)
    run = {
        "format": RUN_FORMAT,
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "mode": args.mode,
        "candidate": meta,
        "corpus": _corpus_block(conn, dense),
        "gold_corpus_id": gold.get("corpus_id"),
        "settings": {
            name: getattr(settings, name)
            for name in ("search_candidates", "rerank_candidates", "answer_top_k")
        },
        "summary": summary,
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=0), encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("mode", "corpus", "settings")}, default=str))
    print("\n".join(report_lines(summary)))
    if args.compare:
        earlier = json.loads(
            Path(args.compare).expanduser().read_text(encoding="utf-8")
        )
        print(json.dumps(compare(earlier, run), indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-gold")
    build.add_argument("--db", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--compiled-db", action="append")
    build.add_argument("--seed", type=int, default=20261102)
    build.add_argument("--per-document", type=int, default=1)
    build.set_defaults(run=cmd_build_gold)
    score = sub.add_parser("score")
    score.add_argument("--db", required=True)
    score.add_argument("--gold", required=True)
    score.add_argument("--out", required=True)
    score.add_argument("--mode", choices=sorted(MODES), default="full")
    score.add_argument("--candidate")
    score.add_argument("--compare")
    score.add_argument("--limit-cases", type=int)
    score.set_defaults(run=cmd_score)
    embed = sub.add_parser("embed")
    embed.add_argument("--db", required=True)
    embed.add_argument("--out", required=True)
    embed.set_defaults(run=cmd_embed)
    args = parser.parse_args(argv)
    offline_guard()
    try:
        return args.run(args)
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    finally:
        offline_guard(remove=True)


if __name__ == "__main__":
    sys.exit(main())
