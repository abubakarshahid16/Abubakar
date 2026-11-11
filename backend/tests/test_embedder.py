import numpy as np
import pytest

from app.chunker import count_tokens
from app.embedder import (
    EMBEDDING_DIM,
    MODEL_MAX_TOKENS,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    Embedder,
    cosine,
    l2_normalise,
    mean_pool,
)
from app.config import settings


# ------------------------------------------------------------- pure maths


def test_mean_pool_masks_padding_and_is_not_cls():
    """e5 requires mean pooling over real tokens. CLS would load fine and
    retrieve badly, with no error anywhere."""
    # 1 item, 3 timesteps, 2 dims. The third token is padding.
    hidden = np.array([[[1.0, 0.0], [3.0, 4.0], [99.0, 99.0]]], dtype=np.float32)
    mask = np.array([[1, 1, 0]], dtype=np.int64)

    pooled = mean_pool(hidden, mask)
    # mean of the two real tokens - padding excluded
    assert pooled.tolist() == [[2.0, 2.0]]
    # and definitively NOT the CLS token
    assert pooled.tolist() != [hidden[0, 0].tolist()]


def test_mean_pool_handles_an_all_padding_row_without_dividing_by_zero():
    hidden = np.zeros((1, 3, 2), dtype=np.float32)
    mask = np.zeros((1, 3), dtype=np.int64)
    pooled = mean_pool(hidden, mask)
    assert np.isfinite(pooled).all()


def test_l2_normalise_gives_unit_vectors():
    v = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    n = l2_normalise(v)
    assert np.allclose(n[0], [0.6, 0.8], atol=1e-6)   # float32, not exact
    assert np.isfinite(n).all()          # the zero row must not become NaN


# ---------------------------------------------------------------- prefixes


def test_prefix_constants_are_the_right_way_round():
    assert PASSAGE_PREFIX == "passage: "
    assert QUERY_PREFIX == "query: "


def test_prefix_fits_inside_the_chunk_ceiling():
    """A max-size chunk plus 'passage: ' plus special tokens must stay under 512."""
    prefix_tokens = count_tokens(PASSAGE_PREFIX)
    # 2 special tokens (<s> </s>) are added by the tokenizer
    assert settings.chunk_max_tokens + prefix_tokens + 2 <= MODEL_MAX_TOKENS


# --------------------------------------------------------- live model tests

pytestmark_model = pytest.mark.skipif(
    not (settings.embed_model_dir / "onnx" / "model_qint8_avx512_vnni.onnx").exists(),
    reason="embedding model not staged",
)


@pytestmark_model
def test_embeddings_are_unit_length_and_the_right_shape():
    emb = Embedder.instance()
    v = emb.embed_passages(["hydrostatic test pressure", "bearing vibration limit"])
    assert v.shape == (2, EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


@pytestmark_model
def test_paraphrases_score_above_unrelated_text():
    """If this fails the pipeline is wrong - pooling or prefixes."""
    emb = Embedder.instance()
    a, b, c = emb.embed_passages([
        "the maximum test pressure shall not exceed 150 psi",
        "test pressure must stay below 150 psi",
        "the cost per bit of memory has fallen dramatically",
    ])
    ab, ac, bc = cosine(a, b), cosine(a, c), cosine(b, c)
    assert ab > 0.85, f"paraphrases only scored {ab:.4f}"
    assert ab > ac and ab > bc, f"A-B {ab:.4f} is not clearly above A-C {ac:.4f} / B-C {bc:.4f}"


@pytestmark_model
def test_query_and_passage_paths_use_different_prefixes():
    """Swapping the prefixes degrades e5 silently, so the two paths must differ."""
    emb = Embedder.instance()
    text = "vibration limits per API 610 shall not exceed 3.0 mm/s RMS"
    as_query = emb.embed_queries([text])[0]
    as_passage = emb.embed_passages([text])[0]
    assert not np.allclose(as_query, as_passage, atol=1e-4)


@pytestmark_model
def test_empty_input_returns_an_empty_matrix_not_an_error():
    emb = Embedder.instance()
    v = emb.embed_passages([])
    assert v.shape == (0, EMBEDDING_DIM)


@pytestmark_model
def test_batching_barely_changes_the_result():
    """Padding is masked out, so batching must not meaningfully move a vector.

    The fp32 export is bit-identical across batchings, which proves the mask
    is applied correctly. The int8 export picks quantisation scales from the
    actual batch contents, so identical text in different batches lands
    within cosine ~0.995 rather than exactly equal. That noise floor sits far
    below the ~0.78 similarity of unrelated text, so it does not affect
    retrieval - but it means a re-embedded chunk is not bit-reproducible.
    """
    emb = Embedder.instance()
    texts = [f"pump P-{100 + i}A inspection interval and vibration limit" for i in range(5)]
    one = emb.embed_passages(texts, batch_size=32)
    split = emb.embed_passages(texts, batch_size=2)
    sims = [cosine(one[i], split[i]) for i in range(len(texts))]
    assert min(sims) > 0.99, f"batching moved a vector too far: {min(sims):.4f}"


@pytestmark_model
def test_length_bucketing_preserves_input_order():
    """Bucketing sorts internally; results must come back in the caller's order."""
    emb = Embedder.instance()
    texts = [
        "short one",
        " ".join(["a much longer passage about vibration limits"] * 40),
        "another short",
        " ".join(["intermediate length text on inspection intervals"] * 12),
    ]
    naive = emb.embed_passages(texts, batch_size=2, bucketed=False)
    bucketed = emb.embed_passages(texts, batch_size=2, bucketed=True)
    for i in range(len(texts)):
        assert cosine(naive[i], bucketed[i]) > 0.99, f"row {i} came back in the wrong order"


@pytestmark_model
def test_only_one_model_copy_is_kept_resident():
    """16 GB does not allow two copies of the model."""
    a = Embedder.instance()
    b = Embedder.instance()
    assert a is b
