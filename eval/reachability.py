"""Reachability: can any query actually reach each retrievable chunk?

COVERAGE AND REACHABILITY ARE DIFFERENT PROPERTIES and only the second supports
the claim the product makes. Coverage says the text is in the index. It says
nothing about whether a question brings it back. A chunk that is indexed and
unreachable is invisible in every way a user can observe, and it is counted as
success by every other measurement in this repository.

    python eval/reachability.py             # the whole corpus
    python eval/reachability.py --limit 300 # a sample, for a quick read

METHOD, stated because a reachability number with an unstated method is worth
nothing:

  For each retrievable chunk, a query is built FROM THAT CHUNK'S OWN most
  distinctive terms - the rarest words it contains, measured by document
  frequency across the corpus. That is the friendliest possible question: it
  uses the chunk's own vocabulary, with no synonym problem and no phrasing
  variation. A chunk that cannot be retrieved by its own rarest words cannot be
  retrieved by anything.

  So this measures a CEILING, not real-world performance. Real questions are
  harder. A chunk that fails here is definitively unreachable; a chunk that
  passes here may still be unreachable in practice.

  Retrieval runs through the real search path with RERANKING OFF, deliberately.
  Reachability is a REACH question - can any query surface this chunk as a
  candidate at all - and reranking is a SCORING stage that reorders candidates
  already found. A chunk that never becomes a candidate cannot be rescued by
  scoring, and one that is a candidate but ranked away is a different defect
  needing the opposite fix. Keeping them apart is the whole point of measuring
  this separately. It is also what makes a full-corpus sweep affordable: with
  the cross-encoder in the loop the sweep runs at ~19 chunks/minute (about four
  hours); without it, minutes.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import search  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.quality import is_word  # noqa: E402

_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']+")
#: How many of the chunk's rarest words to build the query from. Few enough to
#: be a plausible question, many enough that the chunk is identifiable.
QUERY_TERMS = 6


def document_frequency(texts: list[str]) -> Counter:
    df: Counter = Counter()
    for t in texts:
        df.update({w.lower() for w in _TOKEN.findall(t) if is_word(w)})
    return df


def distinctive_query(text: str, df: Counter, total: int) -> str:
    """The chunk's own rarest words - the friendliest possible query for it."""
    words = {w.lower() for w in _TOKEN.findall(text) if is_word(w)}
    if not words:
        return ""
    # Rarest first. idf, so a word in one chunk beats a word in a thousand.
    ranked = sorted(words, key=lambda w: (df.get(w, 1), w))
    return " ".join(ranked[:QUERY_TERMS])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="sample this many chunks instead of all")
    ap.add_argument("--seed", type=int, default=20260905)
    args = ap.parse_args()

    init_db()
    conn = connect()
    rows = conn.execute(
        """SELECT c.id, c.text, c.page_start, c.kind, c.text_source, d.filename
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE c.retrievable = 1"""
    ).fetchall()
    print(f"retrievable chunks: {len(rows)}")

    corpus_scope = search.every_document_id()   # no user; stated explicitly
    df = document_frequency([r["text"] for r in rows])
    total = len(rows)

    target = list(rows)
    if args.limit and args.limit < len(rows):
        random.seed(args.seed)
        target = random.sample(target, args.limit)
        print(f"sampling {len(target)} (seed {args.seed})")

    unreachable, no_query, reached = [], [], 0
    for i, r in enumerate(target, 1):
        q = distinctive_query(r["text"], df, total)
        if not q:
            # No word-like token at all - nothing to ask with. Unreachable by
            # construction, and worth counting separately from a chunk that
            # had a query and still lost.
            no_query.append(r)
            continue
        hits = search.search(q, limit=10, rerank=False,
                             allowed_document_ids=corpus_scope)
        ids = {h["chunk_id"] for h in hits["hits"]}
        if r["id"] in ids:
            reached += 1
        else:
            unreachable.append((r, q))
        if i % 250 == 0:
            print(f"  {i}/{len(target)} …", flush=True)

    n = len(target)
    print()
    print(f"REACHED           {reached:>5} / {n}  ({100 * reached / n:.1f}%)")
    print(f"UNREACHABLE       {len(unreachable):>5} / {n}  ({100 * len(unreachable) / n:.1f}%)")
    print(f"  no query possible {len(no_query):>3}  (no word-like token in the chunk)")
    print()

    if unreachable:
        by_kind: Counter = Counter(r["kind"] for r, _ in unreachable)
        by_doc: Counter = Counter(r["filename"][:38] for r, _ in unreachable)
        by_src: Counter = Counter(r["text_source"] for r, _ in unreachable)
        print("UNREACHABLE by kind:", dict(by_kind))
        print("UNREACHABLE by text_source:", dict(by_src))
        print("UNREACHABLE by document:")
        for k, v in by_doc.most_common():
            print(f"    {k:40} {v}")
        print("\nsample of what cannot be reached:")
        random.seed(args.seed)
        for r, q in random.sample(unreachable, min(6, len(unreachable))):
            print(f"  --- {r['filename'][:34]} p{r['page_start']} kind={r['kind']}")
            print(f"      query: {q}")
            print(f"      text : {' '.join(r['text'].split())[:150]}")
    if no_query:
        print("\nsample with NO possible query:")
        for r in no_query[:4]:
            print(f"  {r['filename'][:34]} p{r['page_start']}: "
                  f"{' '.join(r['text'].split())[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
