"""Step 4 - local ONNX int8 e5-small embeddings.

Three things about e5 fail silently and poison retrieval with no error
anywhere, so they are stated explicitly here and asserted by tests:

1. POOLING IS MEAN POOLING over the last hidden state, masked by the
   attention mask. NOT the CLS token. The ONNX export emits
   `last_hidden_state` only, so pooling is ours to do; taking token 0 would
   load fine, embed fine, and retrieve badly.
2. PREFIXES: passages get "passage: ", queries get "query: ". e5 was trained
   with them; swapping or omitting them degrades quality quietly.
3. NORMALISATION to unit length happens once, at write time, so cosine
   similarity is a plain dot product everywhere downstream.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .config import settings

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

# e5-small's hard limit. The chunker's 480-token ceiling plus the prefix and
# the two special tokens stays under this.
MODEL_MAX_TOKENS = 512
EMBEDDING_DIM = 384

#: B6B E1: WHAT A PASSAGE VECTOR IS COMPUTED FROM - the chunk's clause heading,
#: then its body. The keyword index and the reranker already read "heading +
#: body" (search.Candidate.searchable_text); the embedder read the body alone,
#: so the 28% of chunks that are one short line ("Loads from the extreme case
#: shall also be established.") were embedded without the heading that says
#: what they are about ("4.7 Anchor Line Loads").
#: Recorded on every stored vector (chunk_vectors.model) so a vector computed
#: from the body alone is identifiable. The STORED chunk text - what a
#: citation quotes - is unchanged; only the model's input is.
#:
#: "context-v1" (2026-09-30, CHUNKER_VERSION 8): the heading is the chunk's
#: heading CHAIN (`chunks.context`) when it has one - "4 Piping > 4.2 Pipes
#: larger than 2 inch > 4.2.1" rather than "4.2.1" - else its section, as in
#: heading-v1. See `LEGACY_PASSAGE_INPUT_VERSIONS` for why heading-v1 vectors
#: stay searchable until they are re-embedded.
PASSAGE_INPUT_VERSION = "context-v1"

#: Input formats whose vectors are STILL SEARCHABLE. heading-v1 and
#: context-v1 differ only in how much heading the SAME model read, so a
#: heading-v1 vector's cosine against today's query is as meaningful as it
#: was yesterday. Treating it as stale would switch dense search off for
#: every document the moment this code is deployed, until each one is
#: re-processed. So it is searched as before, and `embed_pending` upgrades it
#: whenever its document is processed. A different MODEL is never legacy:
#: its vectors live in another space and stay stale.
LEGACY_PASSAGE_INPUT_VERSIONS: tuple[str, ...] = ("heading-v1",)


@dataclass(frozen=True)
class EmbedderConfig:
    """How the embedder runs. The defaults are READ FROM SETTINGS.

    They were literals - 12 threads, batch 32 - while `settings.embed_batch_size`
    (16) sat in config.py unread, so neither could be set from `.env` and the
    documented value was not the running one (perf audit item 5). Read at
    construction, so `Embedder.instance(EmbedderConfig())` rebuilds the session
    when a setting changes rather than keeping the old one.
    """

    model_file: str = "model_qint8_avx512_vnni.onnx"
    intra_op_threads: int = field(default_factory=lambda: settings.embed_intra_op_threads())
    batch_size: int = field(default_factory=lambda: settings.embed_batch_size)
    # Group similar-length texts into a batch so padding is not paid for.
    length_bucketed: bool = True
    #: ONNX Runtime's CPU arena for THIS session (settings.onnx_cpu_arena_embed).
    #: Part of the config so a changed setting is a changed config, and the
    #: resident session is rebuilt rather than silently kept.
    cpu_arena: bool = field(default_factory=lambda: settings.onnx_cpu_arena_embed)


def embedding_tag(model_file: str | None = None) -> str:
    """WHAT A STORED VECTOR WAS COMPUTED BY: the model file and the passage
    input format, written to `chunk_vectors.model` on every vector.

    THE ONE HOME of this string. Ingestion writes it and the vector store
    reads it back: a vector whose tag differs from the current one was made by
    another model or from another input format, so its cosine against a query
    embedded today is meaningless. The store leaves such a vector out of dense
    search, counts it as STALE in System Health, and `embed_pending` re-embeds
    it. Before this function the tag was written and never read (P2-11).

    The format is unchanged from what ingestion already wrote, so vectors made
    by the current build stay current - no re-embed is forced by this change.
    """
    return f"{model_file or EmbedderConfig().model_file}+{PASSAGE_INPUT_VERSION}"


def searchable_tags(model_file: str | None = None) -> tuple[str, ...]:
    """Every `chunk_vectors.model` tag dense search may use: today's, then
    the legacy input formats of the SAME model. `embedding_tag()` alone still
    decides what is written and what `embed_pending` upgrades."""
    model = model_file or EmbedderConfig().model_file
    return (embedding_tag(model),
            *(f"{model}+{v}" for v in LEGACY_PASSAGE_INPUT_VERSIONS))


def mean_pool(last_hidden_state: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean over real tokens only, padding excluded.

    This is what e5 requires. Using last_hidden_state[:, 0] (CLS) instead
    produces embeddings that look completely normal and retrieve badly.
    """
    mask = attention_mask.astype(np.float32)[..., None]      # (B, T, 1)
    summed = (last_hidden_state * mask).sum(axis=1)          # (B, D)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)           # (B, 1)
    return summed / counts


def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)


class Embedder:
    """One warm model copy. Thread-safe for a single ingestion worker."""

    _instance: Embedder | None = None
    _lock = threading.Lock()

    def __init__(self, config: EmbedderConfig | None = None) -> None:
        self.config = config or EmbedderConfig()
        model_dir: Path = settings.embed_model_dir
        model_path = model_dir / "onnx" / self.config.model_file
        if not model_path.exists():
            raise FileNotFoundError(f"embedding model not staged at {model_path}")

        tok_path = model_dir / "tokenizer.json"
        self.tokenizer = Tokenizer.from_file(str(tok_path))
        self.tokenizer.enable_truncation(max_length=MODEL_MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.config.intra_op_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_cpu_mem_arena = self.config.cpu_arena
        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    @classmethod
    def instance(cls, config: EmbedderConfig | None = None) -> Embedder:
        """Keep exactly one model copy resident - 16 GB does not allow two."""
        with cls._lock:
            if cls._instance is None or (config and config != cls._instance.config):
                cls._instance = Embedder(config)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------ core

    def _forward(self, texts: list[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        last_hidden_state = self.session.run(["last_hidden_state"], feeds)[0]
        pooled = mean_pool(last_hidden_state.astype(np.float32), attention_mask)
        return l2_normalise(pooled)

    def _token_lengths(self, texts: list[str]) -> list[int]:
        self.tokenizer.no_padding()
        try:
            return [len(e.ids) for e in self.tokenizer.encode_batch(texts)]
        finally:
            self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")

    def _embed(
        self,
        texts: list[str],
        prefix: str,
        batch_size: int | None = None,
        bucketed: bool | None = None,
    ) -> np.ndarray:
        """Embed texts, optionally grouping similar lengths into a batch.

        Padding is charged at full compute cost. In document order a batch of
        32 almost always contains one near-maximum chunk, so every batch pads
        to ~484 tokens against a median of 302 - about a third of all compute
        spent on zeros. Sorting by length before batching drops that to under
        1%. Results are returned in the caller's original order.
        """
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        bs = batch_size or self.config.batch_size
        use_buckets = self.config.length_bucketed if bucketed is None else bucketed
        prefixed = [prefix + t for t in texts]

        if not use_buckets:
            out = [self._forward(prefixed[i:i + bs]) for i in range(0, len(prefixed), bs)]
            return np.vstack(out).astype(np.float32)

        lengths = self._token_lengths(prefixed)
        order = sorted(range(len(prefixed)), key=lambda i: lengths[i])
        vectors = np.zeros((len(prefixed), EMBEDDING_DIM), dtype=np.float32)
        for start in range(0, len(order), bs):
            idx = order[start:start + bs]
            batch_vectors = self._forward([prefixed[i] for i in idx])
            vectors[idx] = batch_vectors
        return vectors

    def passage_input(self, heading: str | None, body: str) -> str:
        """The text a chunk is embedded from: its heading, a newline, its body.

        THE BODY IS NEVER CUT FOR THE HEADING. The tokenizer truncates at
        MODEL_MAX_TOKENS from the END, so a heading that pushed the input over
        the limit would silently drop the body's last sentences - the evidence.
        When heading + body would not fit, the body alone is embedded, exactly
        as before E1. (Measured: 0 of 842 real chunks reach that case - bodies
        are capped at chunk_max_tokens=480, headings run to about 30 tokens -
        but the margin is a measurement, not a guarantee.)
        """
        heading = (heading or "").strip()
        if not heading:
            return body
        candidate = heading + "\n" + body
        if self.tokenizer.encode(PASSAGE_PREFIX + candidate).overflowing:
            return body
        return candidate

    def embed_passages(
        self, texts: list[str], batch_size: int | None = None, bucketed: bool | None = None
    ) -> np.ndarray:
        """Chunks being indexed. Always the 'passage: ' prefix."""
        return self._embed(texts, PASSAGE_PREFIX, batch_size, bucketed)

    def embed_queries(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """User questions. Always the 'query: ' prefix.

        A query is a single short text, so bucketing buys nothing here.
        """
        return self._embed(texts, QUERY_PREFIX, batch_size, bucketed=False)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Vectors are unit length by construction, so this is a dot product."""
    return float(np.dot(a, b))
