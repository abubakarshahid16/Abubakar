"""Embedding throughput benchmark. Pick the model file by measurement, not by name."""
import os
import sqlite3
import time

import psutil

from app.embedder import Embedder, EmbedderConfig
from app.rates import Timer, rate

PROC = psutil.Process(os.getpid())


def rss_mb() -> float:
    return PROC.memory_info().rss / (1024 * 1024)


def load_chunks(limit: int) -> list[str]:
    c = sqlite3.connect("file:data/rag_intelligence.sqlite?mode=ro", uri=True)
    rows = c.execute(
        "SELECT text FROM chunks WHERE retrievable=1 ORDER BY document_id, ordinal LIMIT ?",
        (limit,),
    ).fetchall()
    return [r[0] for r in rows]


def bench(texts, model_file, threads, batch_size, warmup=8):
    Embedder.reset()
    base = rss_mb()
    emb = Embedder.instance(EmbedderConfig(model_file=model_file, intra_op_threads=threads))
    emb.embed_passages(texts[:warmup], batch_size=batch_size)   # warm the model
    warm = rss_mb()

    peak = warm
    t = Timer()
    step = 200
    for i in range(0, len(texts), step):
        emb.embed_passages(texts[i:i + step], batch_size=batch_size)
        peak = max(peak, rss_mb())
    elapsed = t.seconds()
    return {
        "chunks": len(texts),
        "seconds": elapsed,
        "chunks_per_sec": rate(len(texts), elapsed),
        "warm_rss_mb": round(warm, 1),
        "peak_rss_mb": round(peak, 1),
        "model_rss_mb": round(warm - base, 1),
    }


if __name__ == "__main__":
    SAMPLE = 400
    texts = load_chunks(SAMPLE)
    print(f"benchmark sample: {len(texts)} real retrievable chunks")
    print(f"{'model':32} {'thr':>4} {'batch':>6} {'sec':>7} {'chunks/s':>9} {'peakRSS':>9}")
    print("-" * 82)

    results = []
    for model_file in ("model_qint8_avx512_vnni.onnx", "model_O4.onnx"):
        for threads in (4, 10, 12):
            r = bench(texts, model_file, threads, batch_size=32)
            results.append((model_file, threads, 32, r))
            print(f"{model_file:32} {threads:>4} {32:>6} {r['seconds']:>7.2f} "
                  f"{(r['chunks_per_sec'] or 0):>9.1f} {r['peak_rss_mb']:>8.0f}M")

    best = max(results, key=lambda x: x[3]["chunks_per_sec"] or 0)
    print(f"\nFASTEST: {best[0]}  threads={best[1]}  "
          f"{best[3]['chunks_per_sec']:.1f} chunks/s  peak {best[3]['peak_rss_mb']:.0f} MB")

    print(f"\nBATCH SIZE SWEEP on the winner ({best[0]}, threads={best[1]})")
    print(f"{'batch':>6} {'sec':>7} {'chunks/s':>9} {'peakRSS':>9}")
    for bs in (16, 32, 48):
        r = bench(texts, best[0], best[1], batch_size=bs)
        print(f"{bs:>6} {r['seconds']:>7.2f} {(r['chunks_per_sec'] or 0):>9.1f} {r['peak_rss_mb']:>8.0f}M")
