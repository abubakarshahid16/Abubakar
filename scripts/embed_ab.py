"""Interleaved A/B embedding benchmark.

This laptop throttles, so sequential configs are not comparable - the same
config measured 7.6 then 4.4 chunks/s. Every config is therefore run in
alternating rounds and the BEST round is reported, which is the closest thing
to an unthrottled measurement.
"""
import os
import sqlite3
import sys

import numpy as np
import psutil

from app.embedder import Embedder, EmbedderConfig
from app.rates import Timer, rate

PROC = psutil.Process(os.getpid())
N = 600
ROUNDS = 3


def rss_mb() -> float:
    return PROC.memory_info().rss / (1024 * 1024)


def load(n: int) -> list[str]:
    c = sqlite3.connect("file:data/rag_intelligence.sqlite?mode=ro", uri=True)
    return [r[0] for r in c.execute(
        "SELECT text FROM chunks WHERE retrievable=1 ORDER BY document_id, ordinal LIMIT ?", (n,))]


def run_one(emb, texts, batch_size, bucketed):
    t = Timer()
    emb.embed_passages(texts, batch_size=batch_size, bucketed=bucketed)
    return t.seconds()


def main():
    texts = load(N)
    print(f"sample: {len(texts)} real retrievable chunks, {ROUNDS} interleaved rounds, best reported\n")

    configs = []
    for threads in (4, 10, 12):
        configs.append((f"bucketed thr={threads} bs=32", threads, 32, True))
    configs.append(("NAIVE    thr=12 bs=32", 12, 32, False))
    for bs in (64, 128):
        configs.append((f"bucketed thr=12 bs={bs}", 12, bs, True))

    best: dict[str, float] = {}
    peak: dict[str, float] = {}
    sessions: dict[int, Embedder] = {}

    for r in range(ROUNDS):
        for label, threads, bs, bucketed in configs:
            if threads not in sessions:
                Embedder.reset()
                sessions.clear()
                sessions[threads] = Embedder.instance(
                    EmbedderConfig(model_file="model_qint8_avx512_vnni.onnx",
                                   intra_op_threads=threads))
                sessions[threads].embed_passages(texts[:16], batch_size=bs)
            emb = sessions[threads]
            secs = run_one(emb, texts, bs, bucketed)
            best[label] = min(best.get(label, 1e9), secs)
            peak[label] = max(peak.get(label, 0), rss_mb())
            print(f"  round {r+1}  {label:26} {secs:7.2f}s  "
                  f"{(rate(len(texts), secs) or 0):6.1f} chunks/s", flush=True)
        print(flush=True)

    print("=" * 70)
    print("BEST OF ALL ROUNDS")
    print("=" * 70)
    print(f"{'config':28} {'sec':>8} {'chunks/s':>10} {'peakRSS':>9}")
    baseline = None
    for label, *_ in configs:
        cps = rate(len(texts), best[label]) or 0
        if label.startswith("NAIVE"):
            baseline = cps
        print(f"{label:28} {best[label]:>8.2f} {cps:>10.1f} {peak[label]:>8.0f}M")

    if baseline:
        buck = rate(len(texts), best["bucketed thr=12 bs=32"]) or 0
        print(f"\n  length bucketing speedup at thr=12 bs=32: {buck / baseline:.2f}x "
              f"({baseline:.1f} -> {buck:.1f} chunks/s)")


if __name__ == "__main__":
    sys.exit(main())
