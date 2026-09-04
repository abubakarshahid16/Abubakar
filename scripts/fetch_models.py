"""Stage the two local models.

Model weights never enter Git (see .gitignore), so a fresh machine - or a CI
runner - has to fetch them. This is the one script that reaches the network,
and it downloads MODELS only. No client document, chunk, question or answer
ever leaves the machine; that rule is unaffected by this.

    python scripts/fetch_models.py            # both, skipping what is present
    python scripts/fetch_models.py --force    # re-download

Exits non-zero if anything the application requires is still missing
afterwards, so CI fails loudly rather than running a suite that silently
skips half its assertions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "models"

#: (destination, repo, [files]) - only the files the application actually
#: opens. The full snapshot carries several unused ONNX variants and the
#: fp32 weights, which together are most of a gigabyte.
TARGETS = [
    (
        "e5-small",
        "intfloat/multilingual-e5-small",
        [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "sentencepiece.bpe.model",
        ],
    ),
    (
        "e5-small/onnx",
        "intfloat/multilingual-e5-small",
        ["onnx/model_qint8_avx512_vnni.onnx"],
    ),
    (
        "reranker",
        "Xenova/ms-marco-MiniLM-L-6-v2",
        [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
        ],
    ),
    (
        "reranker/onnx",
        "Xenova/ms-marco-MiniLM-L-6-v2",
        ["onnx/model_quantized.onnx"],
    ),
]

#: What must exist for the application to work. Checked after downloading, so
#: a partial fetch is a failure rather than a surprise at runtime.
REQUIRED = [
    "e5-small/tokenizer.json",
    "e5-small/onnx/model_qint8_avx512_vnni.onnx",
    "reranker/tokenizer.json",
    "reranker/onnx/model_quantized.onnx",
]


def fetch(force: bool) -> None:
    from huggingface_hub import hf_hub_download

    for dest, repo, files in TARGETS:
        # The repo layout is mirrored under backend/models/<dir>. The
        # destination root comes from the target entry rather than being
        # inferred from the repo name, because the application opens these by
        # path and a guess that drifts is a runtime error.
        root = MODELS / dest.split("/")[0]
        for filename in files:
            target = root / filename
            if target.exists() and not force:
                print(f"  present  {target.relative_to(MODELS)}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"  fetching {repo}/{filename}")
            path = hf_hub_download(repo_id=repo, filename=filename)
            target.write_bytes(Path(path).read_bytes())


def verify() -> list[str]:
    return [rel for rel in REQUIRED if not (MODELS / rel).exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download everything")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="check what is staged without downloading",
    )
    args = ap.parse_args()

    MODELS.mkdir(parents=True, exist_ok=True)
    if not args.verify_only:
        fetch(args.force)

    missing = verify()
    if missing:
        print("\nMISSING after fetch:")
        for rel in missing:
            print(f"  {rel}")
        print(
            "\nThe application cannot run without these. A test suite run "
            "against a partial staging silently skips its assertions rather "
            "than failing, which is worse than not running it."
        )
        return 1

    total = sum(f.stat().st_size for f in MODELS.rglob("*") if f.is_file())
    print(f"\nall required model files present ({total / 1e6:.0f} MB staged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
