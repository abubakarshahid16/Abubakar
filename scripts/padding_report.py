"""How much of every forward pass is padding?"""
import sqlite3
import statistics as st

import onnxruntime as ort

from app.config import settings
from app.embedder import PASSAGE_PREFIX, Embedder

emb = Embedder.instance()
tok = emb.tokenizer

c = sqlite3.connect("file:data/rag_intelligence.sqlite?mode=ro", uri=True)
texts = [r[0] for r in c.execute(
    "SELECT text FROM chunks WHERE retrievable=1 ORDER BY document_id, ordinal")]
print(f"retrievable chunks: {len(texts)}")

# --- are the ONNX sequence axes actually dynamic? ---
sess = emb.session
print("\nONNX SEQUENCE AXES")
for i in sess.get_inputs():
    print(f"  {i.name:16} {i.shape}   dynamic={not isinstance(i.shape[1], int)}")
print(f"  graph_optimization_level = ORT_ENABLE_ALL "
      f"(set in SessionOptions; ort {ort.__version__})")

# --- real token lengths, with the prefix, as fed to the model ---
lens = [len(e.ids) for e in tok.encode_batch([PASSAGE_PREFIX + t for t in texts[:4000]])]
# encode_batch pads to the batch max, so measure without padding:
tok.no_padding()
raw = [len(tok.encode(PASSAGE_PREFIX + t).ids) for t in texts[:4000]]
tok.enable_padding(pad_id=1, pad_token="<pad>")

raw_sorted = sorted(raw)
print("\nACTUAL TOKEN LENGTHS (prefix + chunk + specials)")
print(f"  min={raw_sorted[0]}  p25={raw_sorted[len(raw)//4]}  median={int(st.median(raw))}  "
      f"p75={raw_sorted[3*len(raw)//4]}  p95={raw_sorted[int(len(raw)*0.95)]}  max={raw_sorted[-1]}")

BATCH = 32


def padding_waste(order: list[int], label: str) -> None:
    real = 0
    padded = 0
    batch_maxes = []
    for start in range(0, len(order), BATCH):
        batch = order[start:start + BATCH]
        bmax = max(raw[i] for i in batch)
        batch_maxes.append(bmax)
        real += sum(raw[i] for i in batch)
        padded += bmax * len(batch)
    waste = 100 * (padded - real) / padded
    print(f"\n  {label}")
    print(f"    real tokens        : {real:,}")
    print(f"    tokens actually fed: {padded:,}   (padded to each batch max)")
    print(f"    WASTED ON PADDING  : {waste:.1f}%")
    print(f"    batch max: mean={st.mean(batch_maxes):.0f} median={st.median(batch_maxes):.0f} "
          f"max={max(batch_maxes)}")


print("\nPADDING WASTE AT BATCH SIZE 32")
padding_waste(list(range(len(raw))), "current: document order")
padding_waste(sorted(range(len(raw)), key=lambda i: raw[i]), "length-bucketed: sorted by token count")

# what a fixed-length export would have cost, for comparison
fixed = settings.chunk_max_tokens + 5
print(f"\n  for reference, if the export were FIXED at {fixed} tokens:")
print(f"    wasted on padding  : {100 * (fixed * len(raw) - sum(raw)) / (fixed * len(raw)):.1f}%")
