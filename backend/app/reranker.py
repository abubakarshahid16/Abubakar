"""Cross-encoder reranking, local and CPU-only.

A bi-encoder scores the question and the passage separately and compares two
vectors, so it never sees them together. A cross-encoder reads the pair and
scores the relationship directly, which is why it fixes orderings that RRF
cannot - and why it is what makes the no-LLM Tier 1 answer trustworthy enough
to be the default.

ms-marco-MiniLM-L-6-v2, int8 quantised, 22 MB. It reranks a shortlist of ~30
candidates rather than the corpus, so the cost is bounded regardless of how
many documents exist.

Reranking is an ENHANCEMENT, never a dependency: if the model is missing or
fails to load, retrieval falls back to the RRF ordering rather than failing.
"""

from __future__ import annotations

import threading

import numpy as np

from .config import settings

MODEL_DIR_NAME = "reranker"
MODEL_FILE = "model_quantized.onnx"

#: Cross-encoders are trained on short pairs; longer input is truncated by the
#: tokenizer anyway, and a shorter window keeps CPU cost predictable. Measured
#: on this CPU: 320 tokens costs ~34ms per candidate, 256 costs ~25ms. The
#: identifier boost is computed on the FULL chunk text, so truncating here
#: cannot lose an identifier that appears late in a passage.
MAX_TOKENS = settings.rerank_max_tokens

_lock = threading.Lock()
_session = None
_tokenizer = None
_unavailable_reason: str | None = None


def model_dir():
    return settings.embed_model_dir.parent / MODEL_DIR_NAME


def available() -> bool:
    return (model_dir() / "onnx" / MODEL_FILE).exists()


def unavailable_reason() -> str | None:
    return _unavailable_reason


#: Upper bound on the DERIVED default. 12 is what the owner's 12-thread laptop
#: was measured at (docs/benchmarks.md), so that machine keeps exactly the
#: setting it was tuned with; a bigger box gains little from more threads on a
#: 16-pair batch and would starve the embedder and Ollama running beside it.
MAX_DEFAULT_THREADS = 12


def _usable_cpus() -> int:
    """CPUs this process may actually run on.

    `os.cpu_count()` counts the machine; a container or an affinity mask can
    grant fewer (this sandbox: 2 of them). `sched_getaffinity` is the count
    that matters where the platform has it (Linux); elsewhere (Windows, the
    owner's laptop) it is `os.cpu_count()`.
    """
    import os

    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def thread_count() -> int:
    """The reranker session's intra-op threads: `rerank_threads` when set,
    else one per usable CPU, capped at MAX_DEFAULT_THREADS.

    Hard-set to 12 before, which oversubscribed any machine with fewer cores:
    a 16-passage rerank took 8,979 ms at 12 threads against 946 ms at 2 on a
    2-vCPU box (retrieval audit L1). Threads change scheduling, not
    arithmetic, so scores do not depend on this value.
    """
    configured = int(settings.rerank_threads or 0)
    if configured > 0:
        return configured
    return min(_usable_cpus(), MAX_DEFAULT_THREADS)


def _load():
    """Load once, and remember a failure rather than retrying on every query."""
    global _session, _tokenizer, _unavailable_reason
    if _session is not None or _unavailable_reason is not None:
        return _session, _tokenizer

    with _lock:
        if _session is not None or _unavailable_reason is not None:
            return _session, _tokenizer
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            path = model_dir() / "onnx" / MODEL_FILE
            if not path.exists():
                _unavailable_reason = f"reranker model not staged at {path}"
                return None, None

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = thread_count()
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # The arena reserves per-thread blocks sized for the worst-case
            # padded batch and never releases them - 829 MB for a 22 MB model.
            # See settings.onnx_cpu_arena for the measurement. Scores are
            # bit-identical either way.
            opts.enable_cpu_mem_arena = settings.onnx_cpu_arena_rerank

            session = ort.InferenceSession(
                str(path), sess_options=opts, providers=["CPUExecutionProvider"]
            )
            tok = Tokenizer.from_file(str(model_dir() / "tokenizer.json"))
            tok.enable_truncation(max_length=settings.rerank_max_tokens)
            tok.enable_padding(pad_id=0, pad_token="[PAD]")

            _session, _tokenizer = session, tok
        except Exception as exc:  # noqa: BLE001 - never let this break retrieval
            _unavailable_reason = f"{type(exc).__name__}: {exc}"
            return None, None
    return _session, _tokenizer


def reset() -> None:
    global _session, _tokenizer, _unavailable_reason
    with _lock:
        _session = _tokenizer = None
        _unavailable_reason = None


def rerank(
    question: str,
    passages: list[tuple[str, str]],
    batch: int | None = None,
) -> list[tuple[str, float]]:
    """Score (chunk_id, text) pairs against the question.

    Returns [] when the model is unavailable, so the caller keeps its existing
    order rather than losing results.
    """
    if not passages:
        return []
    batch = batch or settings.rerank_batch
    session, tok = _load()
    if session is None or tok is None:
        return []

    names = {i.name for i in session.get_inputs()}
    out: list[tuple[str, float]] = []

    for start in range(0, len(passages), batch):
        window = passages[start:start + batch]
        encodings = tok.encode_batch([(question, text) for _, text in window])
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        feeds: dict[str, np.ndarray] = {
            "input_ids": input_ids,
            "attention_mask": attention,
        }
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.array(
                [e.type_ids for e in encodings], dtype=np.int64
            )

        logits = session.run(None, feeds)[0]
        scores = logits[:, 0] if logits.ndim == 2 and logits.shape[1] == 1 else logits.reshape(-1)
        for (chunk_id, _), score in zip(window, scores):
            out.append((chunk_id, float(score)))

    return out
