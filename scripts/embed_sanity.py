"""Prove the embeddings are semantically meaningful before anything is built on them."""
import sqlite3

import numpy as np

from app.embedder import EMBEDDING_DIM, Embedder, EmbedderConfig, cosine

A = "the maximum test pressure shall not exceed 150 psi"
B = "test pressure must stay below 150 psi"
C = "the cost per bit of memory has fallen dramatically"

emb = Embedder.instance(EmbedderConfig(model_file="model_qint8_avx512_vnni.onnx",
                                       intra_op_threads=12))

print("pooling      : MEAN over last_hidden_state, masked by attention_mask (NOT CLS)")
print("prefixes     : passages 'passage: ', queries 'query: '")
print("normalisation: L2 to unit length at write time")
print()

vecs = emb.embed_passages([A, B, C])
print(f"shape        : {vecs.shape}   (expect (3, {EMBEDDING_DIM}))")
norms = np.linalg.norm(vecs, axis=1)
print(f"norms        : {np.round(norms, 6).tolist()}   (expect all 1.0)")
assert np.allclose(norms, 1.0, atol=1e-5), "vectors are not unit length"
print()

print("COSINE SIMILARITY MATRIX")
labels = ["A", "B", "C"]
print("        " + "".join(f"{l:>8}" for l in labels))
for i, li in enumerate(labels):
    row = "".join(f"{cosine(vecs[i], vecs[j]):>8.4f}" for j in range(3))
    print(f"   {li}    {row}")
print()
ab, ac, bc = cosine(vecs[0], vecs[1]), cosine(vecs[0], vecs[2]), cosine(vecs[1], vecs[2])
print(f"  A-B (paraphrases)  = {ab:.4f}   expect > 0.85")
print(f"  A-C (unrelated)    = {ac:.4f}")
print(f"  B-C (unrelated)    = {bc:.4f}")
margin = ab - max(ac, bc)
print(f"  margin A-B over the unrelated pairs = {margin:.4f}")

ok = ab > 0.85 and ab > ac and ab > bc
print(f"\n  VERDICT: {'PASS' if ok else 'FAIL - pipeline is wrong, stop'}")

# ------------------------------------------------ real chunk, real paraphrase
print()
print("REAL CHUNK RETRIEVAL CHECK")
c = sqlite3.connect("file:data/rag_intelligence.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
row = c.execute("""SELECT page_start, section, text FROM chunks
                   WHERE document_id='doc_b02fb622b193' AND retrievable=1
                   AND text LIKE '%hard-disk drive%' LIMIT 1""").fetchone()
if row is None:
    row = c.execute("""SELECT page_start, section, text FROM chunks
                       WHERE document_id='doc_b02fb622b193' AND retrievable=1
                       AND token_count BETWEEN 250 AND 320 ORDER BY ordinal LIMIT 1""").fetchone()

chunk_vec = emb.embed_passages([row["text"]])[0]
query = "how much did the first hard disk drive weigh and how much data did it store"
distractor = "what is the procedure for hydrostatic pressure testing of a vessel"
qv, dv = emb.embed_queries([query, distractor])

print(f"  chunk    : book1 p{row['page_start']}  section={row['section']!r}")
print(f"  text     : {row['text'][:150]}...")
print(f"  query    : {query!r}")
print(f"  score    : {cosine(qv, chunk_vec):.4f}")
print(f"  distractor query score : {cosine(dv, chunk_vec):.4f}")
print(f"  VERDICT  : {'PASS' if cosine(qv, chunk_vec) > cosine(dv, chunk_vec) else 'FAIL'}")

# ------------------------------------------------------------ prefix effect
print()
print("PREFIX CHECK - swapping the prefixes should measurably change the score")
q_as_passage = emb.embed_passages([query])[0]
print(f"  query embedded with 'query: '   vs chunk : {cosine(qv, chunk_vec):.4f}")
print(f"  query embedded with 'passage: ' vs chunk : {cosine(q_as_passage, chunk_vec):.4f}")
